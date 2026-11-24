"""Data-driven scene compositor with virtual camera, Action Library playback, and 2-bone IK limbs."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image

from flat_puppet.core.actions import ActionLibrary
from flat_puppet.core.audio import AudioAnalyzer
from flat_puppet.core.config import load_and_validate_scene
from flat_puppet.core.image_ops import rot_safe
from flat_puppet.core.kinematics import (
    breathing_offset,
    ease,
    is_blinking,
    procedural_blinks,
    rotate_point_pil,
    solve_2bone_ik,
    turn_transition_scale,
)
from flat_puppet.core.leg_modes import (
    CapsuleLegRig,
    compute_sprite8_pose,
    compute_walk_angles,
    render_leg_mesh,
    render_leg_vector,
)
from flat_puppet.core.puppet import ScaledAssets


def load_scene_config(scene_path: Path, root: Optional[Path] = None) -> dict:
    if root is not None:
        return load_and_validate_scene(root, scene_path)
    import json

    return json.loads(scene_path.read_text(encoding="utf-8"))


class SceneCompositor:
    """Renders individual frames for a scene JSON definition."""

    def __init__(
        self,
        root: Path,
        config_dir: Path,
        scene_path: Path,
        leg_mode_override: Optional[str] = None,
    ) -> None:
        self.root = root
        self.config_dir = config_dir
        self.scene = load_and_validate_scene(root, scene_path)
        self.leg_mode: str = leg_mode_override or self.scene["characters"]["gopal"].get("leg_mode", "mesh")

        self.fps: int = int(self.scene.get("fps", 25))
        self.width: int = int(self.scene.get("width", 1280))
        self.height: int = int(self.scene.get("height", 720))
        self.duration: float = float(self.scene.get("duration", 10.7))
        self.nframes: int = int(self.duration * self.fps)
        self.ground_y: int = int(self.scene.get("ground_y", 692))

        bg_path = root / self.scene["background"]
        with Image.open(bg_path) as bg_im:
            self.bg = bg_im.convert("RGB").resize((self.width, self.height), Image.Resampling.LANCZOS)

        self.assets = ScaledAssets(root, config_dir, self.scene)
        self.actions = ActionLibrary(config_dir / "actions")
        self._rot_cache: Dict[Tuple[int, float, Tuple[float, float]], Tuple[Image.Image, Tuple[int, int]]] = {}
        self.capsule_leg_n = CapsuleLegRig(
            self.assets.side_parts["legN_full"],
            self.assets.legn_hip,
            self.assets.legn_knee,
            self.assets.legn_ankle,
            is_far=False,
        )
        self.capsule_leg_f = CapsuleLegRig(
            self.assets.side_parts["legF_full"],
            self.assets.legf_hip,
            self.assets.legf_knee,
            self.assets.legf_ankle,
            is_far=True,
        )

        audio_cfg = self.scene.get("audio", {})
        voice_rel = audio_cfg.get("voice")
        voice_path = (root / voice_rel) if voice_rel else None
        rhubarb_rel = audio_cfg.get("rhubarb_json")
        rhubarb_path = (root / rhubarb_rel) if rhubarb_rel else None
        self.audio = AudioAnalyzer(
            audio_path=voice_path,
            start_time=float(audio_cfg.get("voice_start", 4.4)),
            fps=self.fps,
            cache_dir=root / ".cache",
            rhubarb_json=rhubarb_path,
            gain_ref=audio_cfg.get("gain_ref", "auto"),
        )

        # Precompute mouth level track with hysteresis so parallel workers agree identically
        self._mouth_track: List[int] = []
        prev_lvl: Optional[int] = None
        for i in range(self.nframes + 2):
            lvl = self.audio.mouth_level(i / self.fps, prev_level=prev_lvl)
            self._mouth_track.append(lvl)
            prev_lvl = lvl

        chars = self.scene["characters"]
        tara_blinks = chars["tara"].get("blinks")
        self.blinks_tara: List[Tuple[float, float]] = (
            [tuple(b) for b in tara_blinks]
            if tara_blinks
            else procedural_blinks(self.duration, seed=101)
        )
        gopal_blinks = chars["gopal"].get("blinks")
        self.blinks_gopal: List[Tuple[float, float]] = (
            [tuple(b) for b in gopal_blinks]
            if gopal_blinks
            else procedural_blinks(self.duration, seed=202)
        )

    def _rot_cached(
        self,
        layer: Image.Image,
        angle: float,
        pivot: Tuple[float, float],
    ) -> Tuple[Image.Image, Tuple[int, int]]:
        q_ang = round(angle, 1)
        key = (id(layer), q_ang, pivot)
        cached = self._rot_cache.get(key)
        if cached is None:
            cached = rot_safe(layer, q_ang, pivot)
            if len(self._rot_cache) > 512:
                self._rot_cache.clear()
            self._rot_cache[key] = cached
        return cached

    def _paste_2bone_limb(
        self,
        frame: Image.Image,
        upper_img: Image.Image,
        lower_img: Image.Image,
        cap_img: Image.Image,
        root_pivot: Tuple[float, float],
        joint_pivot: Tuple[float, float],
        upper_ang: float,
        lower_rel_ang: float,
        pos_x: int,
        pos_y: int,
    ) -> None:
        """Composite a 2-bone hierarchical limb with expand=True safe rotation and joint cap."""
        upper_r, (ux_off, uy_off) = self._rot_cached(upper_img, upper_ang, root_pivot)
        new_joint = rotate_point_pil(joint_pivot, root_pivot, upper_ang)
        lower_r, (lx_off, ly_off) = self._rot_cached(lower_img, upper_ang + lower_rel_ang, joint_pivot)
        cap_r, (cx_off, cy_off) = self._rot_cached(cap_img, upper_ang + 0.5 * lower_rel_ang, joint_pivot)

        dx = new_joint[0] - joint_pivot[0]
        dy = new_joint[1] - joint_pivot[1]
        jx = int(round(pos_x + dx))
        jy = int(round(pos_y + dy))

        frame.paste(lower_r, (jx + lx_off, jy + ly_off), lower_r)
        frame.paste(cap_r, (jx + cx_off, jy + cy_off), cap_r)
        frame.paste(upper_r, (pos_x + ux_off, pos_y + uy_off), upper_r)

    def _apply_turn_squash(self, layer: Image.Image, scale_x: float) -> Tuple[Image.Image, int]:
        if scale_x >= 0.999:
            return layer, 0
        w, h = layer.size
        new_w = max(4, int(round(w * scale_x)))
        squashed = layer.resize((new_w, h), Image.Resampling.BILINEAR)
        x_shift = (w - new_w) // 2
        return squashed, x_shift

    def _apply_camera(self, frame: Image.Image, t: float) -> Image.Image:
        cam = self.scene.get("camera", {})
        if not cam.get("enabled", False):
            return frame

        zoom_start = float(cam.get("zoom_start", 1.0))
        zoom_end = float(cam.get("zoom_end", 1.03))
        z_t0 = float(cam.get("zoom_t_start", 4.2))
        z_t1 = float(cam.get("zoom_t_end", self.duration))

        if t <= z_t0:
            zoom = zoom_start
        elif t >= z_t1:
            zoom = zoom_end
        else:
            u = ease((t - z_t0) / max(z_t1 - z_t0, 0.001))
            zoom = zoom_start + (zoom_end - zoom_start) * u

        if abs(zoom - 1.0) < 1e-4:
            return frame

        focus_x = float(cam.get("focus_x", 0.5)) * self.width
        focus_y = float(cam.get("focus_y", 0.52)) * self.height
        crop_w = self.width / zoom
        crop_h = self.height / zoom

        left = max(0.0, min(self.width - crop_w, focus_x - crop_w / 2.0))
        top = max(0.0, min(self.height - crop_h, focus_y - crop_h / 2.0))
        return frame.crop((left, top, left + crop_w, top + crop_h)).resize(
            (self.width, self.height), Image.Resampling.BICUBIC
        )

    def render_frame(self, i: int) -> Image.Image:
        t = i / self.fps
        frame = self.bg.copy()
        chars = self.scene["characters"]

        # 1. Gulli (standing bird with oscillating tail)
        gulli_cfg = chars["gulli"]
        gx_gulli = int(gulli_cfg["x"])
        gy_gulli = self.ground_y - int(gulli_cfg["height"])
        tail_r, (tx_off, ty_off) = self._rot_cached(
            self.assets.gulli_tail,
            7.0 * math.sin(t * 2.0 * math.pi * 0.9),
            self.assets.tail_pivot,
        )
        frame.paste(self.assets.gulli_body, (gx_gulli, gy_gulli), self.assets.gulli_body)
        frame.paste(tail_r, (gx_gulli + tx_off, gy_gulli + ty_off), tail_r)

        # 2. Tara (standing character with subtle breathing + blinks)
        tara_cfg = chars["tara"]
        tara_x = int(tara_cfg["x"])
        tara_y = self.ground_y - int(tara_cfg["height"])
        tara_img = self.assets.tara_blink if is_blinking(t, self.blinks_tara) else self.assets.tara_base
        tara_dy = breathing_offset(t, freq=0.3, amp=1.0)
        frame.paste(tara_img, (tara_x, int(tara_y + tara_dy)), tara_img)

        # 3. Gopal (Action Library walk with hip-pinned 2-bone legs & elbow -> turn -> 2-bone IK dialogue)
        gopal_cfg = chars["gopal"]
        walk_dur = float(gopal_cfg.get("walk_duration", 4.2))
        side_h = int(gopal_cfg["side_height"])
        front_h = int(gopal_cfg["front_height"])
        turn_scale = turn_transition_scale(t, walk_dur, half_window=float(gopal_cfg.get("turn_half_window", 0.14)))

        if t < walk_dur:
            walk_clip = self.actions.get(gopal_cfg.get("walk_action", "walk_cycle"))
            walk_speed = float(gopal_cfg.get("walk_cycles_per_sec", 0.8))
            x_start = float(gopal_cfg.get("walk_x_start", -60))
            x_end = float(gopal_cfg.get("walk_x_end", 330))
            x = x_start + (x_end - x_start) * (t / walk_dur)

            cyc = (t * walk_speed) % 1.0
            cyc_opp = (cyc + 0.5) % 1.0

            dhoti_tilt = 0.0
            if self.leg_mode == "cut":
                ang_n = walk_clip.eval_normalized("leg_near_thigh", cyc)
                knee_n = walk_clip.eval_normalized("leg_near_knee", cyc)
                ang_f = walk_clip.eval_normalized("leg_near_thigh", cyc_opp)
                knee_f = walk_clip.eval_normalized("leg_near_knee", cyc_opp)
                foot_n = foot_f = 0.0
                bob = walk_clip.eval_normalized("body_bob", cyc)
            elif self.leg_mode == "sprite8":
                ang_n, knee_n, foot_n, bob, dhoti_tilt = compute_sprite8_pose(cyc)
                ang_f, knee_f, foot_f, _, _ = compute_sprite8_pose(cyc_opp)
            else:
                ang_n, knee_n, foot_n = compute_walk_angles(cyc)
                ang_f, knee_f, foot_f = compute_walk_angles(cyc_opp)
                bob = walk_clip.eval_normalized("body_bob", cyc)

            sh_ang = walk_clip.eval_normalized("arm_swing_shoulder", cyc)
            el_ang = walk_clip.eval_normalized("arm_swing_elbow", cyc)

            # Hip remains pinned at `y` under the dhoti; foot clearance comes naturally from knee bend + bob
            y = int(self.ground_y - side_h + bob)
            arm_x_off = int(self.assets.arm_side_off[0])
            arm_y_off = int(self.assets.arm_side_off[1])

            def _draw_legs(target_canvas: Image.Image, px: int, py: int) -> None:
                if self.leg_mode == "mesh":
                    leg_f_img, (fx_off, fy_off) = render_leg_mesh(
                        self.assets.side_parts["legF_full"],
                        self.assets.legf_hip,
                        self.assets.legf_knee,
                        self.assets.legf_ankle,
                        ang_f,
                        knee_f,
                        foot_f,
                    )
                    leg_n_img, (nx_off, ny_off) = render_leg_mesh(
                        self.assets.side_parts["legN_full"],
                        self.assets.legn_hip,
                        self.assets.legn_knee,
                        self.assets.legn_ankle,
                        ang_n,
                        knee_n,
                        foot_n,
                    )
                    target_canvas.paste(leg_f_img, (px + fx_off, py + fy_off), leg_f_img)
                    target_canvas.paste(leg_n_img, (px + nx_off, py + ny_off), leg_n_img)
                elif self.leg_mode == "capsule":
                    self.capsule_leg_f.render(target_canvas, self._rot_cached, px, py, ang_f, knee_f, foot_f)
                    self.capsule_leg_n.render(target_canvas, self._rot_cached, px, py, ang_n, knee_n, foot_n)
                elif self.leg_mode in ("vector", "sprite8"):
                    vec_size = self.assets.side_parts["torso"].size
                    # Align far ankle height with near ankle so both feet touch the exact ground plane
                    far_ankle_aligned = (self.assets.legf_ankle[0], self.assets.legn_ankle[1])
                    vec_f = render_leg_vector(
                        vec_size,
                        self.assets.legf_hip,
                        self.assets.legf_knee,
                        far_ankle_aligned,
                        ang_f,
                        knee_f,
                        foot_f,
                        is_far=True,
                    )
                    vec_n = render_leg_vector(
                        vec_size,
                        self.assets.legn_hip,
                        self.assets.legn_knee,
                        self.assets.legn_ankle,
                        ang_n,
                        knee_n,
                        foot_n,
                        is_far=False,
                    )
                    target_canvas.paste(vec_f, (px, py), vec_f)
                    target_canvas.paste(vec_n, (px, py), vec_n)
                else:
                    self._paste_2bone_limb(
                        target_canvas,
                        self.assets.side_parts["legF_thigh"],
                        self.assets.side_parts["legF_calf"],
                        self.assets.side_parts["legF_cap"],
                        self.assets.legf_hip,
                        self.assets.legf_knee,
                        ang_f,
                        knee_f,
                        px,
                        py,
                    )
                    self._paste_2bone_limb(
                        target_canvas,
                        self.assets.side_parts["legN_thigh"],
                        self.assets.side_parts["legN_calf"],
                        self.assets.side_parts["legN_cap"],
                        self.assets.legn_hip,
                        self.assets.legn_knee,
                        ang_n,
                        knee_n,
                        px,
                        py,
                    )

            torso_img = self.assets.side_parts["torso"]
            torso_ox, torso_oy = 0, 0
            if abs(dhoti_tilt) > 0.05:
                hip_mid = (
                    (self.assets.legn_hip[0] + self.assets.legf_hip[0]) * 0.5,
                    self.assets.legn_hip[1] * 0.7,
                )
                torso_img, (torso_ox, torso_oy) = self._rot_cached(torso_img, dhoti_tilt, hip_mid)

            if turn_scale < 0.999:
                local = Image.new("RGBA", self.assets.side_parts["torso"].size, (0, 0, 0, 0))
                local.paste(self.assets.side_parts["under"], (0, 0), self.assets.side_parts["under"])
                _draw_legs(local, 0, 0)
                local.paste(torso_img, (torso_ox, torso_oy), torso_img)
                self._paste_2bone_limb(
                    local,
                    self.assets.side_parts["arm_upper"],
                    self.assets.side_parts["arm_lower"],
                    self.assets.side_parts["arm_cap"],
                    self.assets.sh_pivot,
                    self.assets.side_elbow_pivot,
                    sh_ang,
                    el_ang,
                    arm_x_off,
                    arm_y_off,
                )
                squashed, x_shift = self._apply_turn_squash(local, turn_scale)
                frame.paste(squashed, (int(x) + x_shift, y), squashed)
            else:
                frame.paste(self.assets.side_parts["under"], (int(x), y), self.assets.side_parts["under"])
                _draw_legs(frame, int(x), y)
                frame.paste(torso_img, (int(x) + torso_ox, y + torso_oy), torso_img)
                self._paste_2bone_limb(
                    frame,
                    self.assets.side_parts["arm_upper"],
                    self.assets.side_parts["arm_lower"],
                    self.assets.side_parts["arm_cap"],
                    self.assets.sh_pivot,
                    self.assets.side_elbow_pivot,
                    sh_ang,
                    el_ang,
                    int(x + arm_x_off),
                    int(y + arm_y_off),
                )
        else:
            m_lvl = self._mouth_track[min(i, len(self._mouth_track) - 1)]
            b_flag = 1 if is_blinking(t, self.blinks_gopal) else 0
            head_s, arm_upper_s, arm_lower_s, arm_cap_s = self.assets.front_states[(m_lvl, b_flag)]

            gx = int(gopal_cfg.get("talk_x", 350))
            gy = self.ground_y - front_h + breathing_offset(t, freq=0.3, amp=1.2)
            o = self.audio.envelope(t)

            gestures = [tuple(w) for w in gopal_cfg.get("gesture_windows", [[5.5, 6.7], [8.1, 9.3]])]
            gesture_clip = self.actions.get(gopal_cfg.get("gesture_action", "speak_gesture"))
            hand_dx, hand_dy = 0.0, 0.0
            for a, b in gestures:
                if a <= t <= b and b > a:
                    u = (t - a) / (b - a)
                    hand_dx = gesture_clip.eval_normalized("hand_ik_dx", u)
                    hand_dy = gesture_clip.eval_normalized("hand_ik_dy", u)
                    break

            hand_dy -= o * 4.0

            target = (
                self.assets.front_wrist_pivot[0] + hand_dx,
                self.assets.front_wrist_pivot[1] + hand_dy,
            )
            sh_ang, el_rel_ang = solve_2bone_ik(
                self.assets.arm_pivot,
                self.assets.front_elbow_pivot,
                self.assets.front_wrist_pivot,
                target,
                bend_sign=1,
            )

            head_r, (hx_off, hy_off) = self._rot_cached(
                head_s,
                1.0 * math.sin(t * 2.0 * math.pi * 0.24) - 1.8 * o,
                self.assets.head_pivot,
            )

            if turn_scale < 0.999:
                local = Image.new("RGBA", self.assets.front_base.size, (0, 0, 0, 0))
                local.paste(self.assets.front_base, (0, 0), self.assets.front_base)
                self._paste_2bone_limb(
                    local,
                    arm_upper_s,
                    arm_lower_s,
                    arm_cap_s,
                    self.assets.arm_pivot,
                    self.assets.front_elbow_pivot,
                    sh_ang,
                    el_rel_ang,
                    int(self.assets.arm_off[0]),
                    int(self.assets.arm_off[1] + o * 3),
                )
                local.paste(
                    self.assets.front_stub,
                    (int(self.assets.arm_off[0]), int(self.assets.arm_off[1])),
                    self.assets.front_stub,
                )
                local.paste(
                    head_r,
                    (int(self.assets.head_off[0]) + hx_off, int(self.assets.head_off[1] + o * 4) + hy_off),
                    head_r,
                )
                squashed, x_shift = self._apply_turn_squash(local, turn_scale)
                frame.paste(squashed, (gx + x_shift, int(gy)), squashed)
            else:
                frame.paste(self.assets.front_base, (gx, int(gy)), self.assets.front_base)
                self._paste_2bone_limb(
                    frame,
                    arm_upper_s,
                    arm_lower_s,
                    arm_cap_s,
                    self.assets.arm_pivot,
                    self.assets.front_elbow_pivot,
                    sh_ang,
                    el_rel_ang,
                    int(gx + self.assets.arm_off[0]),
                    int(gy + self.assets.arm_off[1] + o * 3),
                )
                frame.paste(
                    self.assets.front_stub,
                    (int(gx + self.assets.arm_off[0]), int(gy + self.assets.arm_off[1])),
                    self.assets.front_stub,
                )
                frame.paste(
                    head_r,
                    (int(gx + self.assets.head_off[0]) + hx_off, int(gy + self.assets.head_off[1] + o * 4) + hy_off),
                    head_r,
                )

        return self._apply_camera(frame, t)
