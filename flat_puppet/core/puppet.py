"""Data-driven puppet baking, joint-splitting (with circular caps), loading, and scaling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from flat_puppet.core.image_ops import (
    AssetBaker,
    clear_big_white_components,
    darken,
    load_char,
    patch,
    poly_part,
    rect_part,
    remove_white,
    scaled,
    split_limb_at_joint,
    subtract_alpha,
)


def _collect_source_files(puppets_cfg: dict) -> list[str]:
    files: list[str] = []
    for char_cfg in puppets_cfg.values():
        for view in char_cfg.get("views", {}).values():
            for key in ("base_file", "orig_file", "eyes_file"):
                if key in view:
                    files.append(view[key])
            for vf in view.get("variants", {}).values():
                files.append(vf)
    return files


def _is_hero_puppet(cfg: dict) -> bool:
    views = cfg.get("views", {})
    return "side" in views and "front" in views


def _is_companion_puppet(cfg: dict) -> bool:
    views = cfg.get("views", {})
    return "side" in views and "tail_poly_rel" in views["side"] and "front" not in views


def _required_outputs_for_puppet(name: str, cfg: dict) -> list[str]:
    if _is_hero_puppet(cfg):
        outs = [
            f"{name}/side_torso.png",
            f"{name}/side_under.png",
            f"{name}/side_arm_upper.png",
            f"{name}/side_arm_lower.png",
            f"{name}/side_arm_cap.png",
            f"{name}/side_legN_full.png",
            f"{name}/side_legF_full.png",
            f"{name}/side_legN_thigh.png",
            f"{name}/side_legN_calf.png",
            f"{name}/side_legN_cap.png",
            f"{name}/side_legF_thigh.png",
            f"{name}/side_legF_calf.png",
            f"{name}/side_legF_cap.png",
            f"{name}/side_meta.json",
            f"{name}/front_base.png",
            f"{name}/front_stub.png",
            f"{name}/front_meta.json",
        ]
        for m in (0, 1, 2):
            for b in (0, 1):
                outs.extend([
                    f"{name}/front_head_m{m}_b{b}.png",
                    f"{name}/front_arm_upper_m{m}_b{b}.png",
                    f"{name}/front_arm_lower_m{m}_b{b}.png",
                    f"{name}/front_arm_cap_m{m}_b{b}.png",
                ])
        return outs
    if _is_companion_puppet(cfg):
        return [f"{name}/body.png", f"{name}/tail.png", f"{name}/meta.json"]
    # Standing front character (listener or second speaker)
    outs = [f"{name}/base.png", f"{name}/eyes.png", f"{name}/meta.json"]
    variants = cfg.get("views", {}).get("front", {}).get("variants", {})
    for vk in ("half", "open"):
        if vk in variants:
            outs.append(f"{name}/mouth_{vk}.png")
    return outs


def _bake_hero_puppet(baker: AssetBaker, root: Path, name: str, hero_cfg: dict) -> None:
    side_cfg = hero_cfg["views"]["side"]
    side_base_c = load_char(root, side_cfg["base_file"])
    sb2 = side_base_c["bbox"]

    def s2(pt):
        return (pt[0] - sb2[0], pt[1] - sb2[1])

    base_img = side_base_c["base"]
    leg_n_full = poly_part(base_img, [s2(p) for p in side_cfg["polygons"]["leg_near"]])
    leg_f_full = darken(poly_part(base_img, [s2(p) for p in side_cfg["polygons"]["leg_far"]]), 0.85)

    knee_n = s2(side_cfg["pivots"]["knee_near"])
    knee_f = s2(side_cfg["pivots"]["knee_far"])
    leg_n_thigh, leg_n_calf, leg_n_cap = split_limb_at_joint(leg_n_full, knee_n, overlap=16, feather=2.5, cap_radius=54)
    leg_f_thigh, leg_f_calf, leg_f_cap = split_limb_at_joint(leg_f_full, knee_f, overlap=16, feather=2.5, cap_radius=48)

    # Dhoti back-flap between legs
    up = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    ImageDraw.Draw(up).polygon([s2(p) for p in side_cfg["polygons"]["under_flap"]], fill=(233, 230, 222, 255))
    ua = np.asarray(up.split()[3]).astype(np.float32)
    fy0 = max(0, min(base_img.height, s2((0, 1785))[1]))
    fy1 = max(fy0, min(base_img.height, s2((0, 1845))[1]))
    if fy1 > fy0:
        ua[fy0:fy1] *= (1.0 - (np.arange(fy0, fy1) - fy0) / (fy1 - fy0))[:, None]
    up.putalpha(Image.fromarray(ua.astype(np.uint8)))
    side_under = up.filter(ImageFilter.GaussianBlur(1.0))

    hem_cut_y = int(side_cfg.get("hem_cut_y", 1732))
    side_torso = subtract_alpha(subtract_alpha(base_img, leg_n_full), leg_f_full)
    side_torso = rect_part(side_torso, int(s2((0, hem_cut_y))[1]), feather=2.5)

    side_orig_c = load_char(root, side_cfg["orig_file"])
    sb = side_orig_c["bbox"]

    def s_orig(pt):
        return (pt[0] - sb[0], pt[1] - sb[1])

    side_arm_full = poly_part(side_orig_c["base"], [s_orig(p) for p in side_cfg["polygons"]["arm"]])
    sa_arr = np.asarray(side_arm_full).copy()
    hand_y0 = max(0, min(sa_arr.shape[0], int(s_orig(side_cfg["pivots"]["wrist"])[1])))
    rgb_h = sa_arr[hand_y0:, :, :3].astype(np.int16)
    dhoti_leak = (rgb_h[:, :, 0] > 202) & (rgb_h[:, :, 1] > 200) & (rgb_h[:, :, 2] > 192)
    sa_arr[hand_y0:, :, 3] = np.where(dhoti_leak, 0, sa_arr[hand_y0:, :, 3])
    side_arm_full = Image.fromarray(sa_arr, "RGBA")

    side_elbow = s_orig(side_cfg["pivots"]["elbow"])
    side_arm_upper, side_arm_lower, side_arm_cap = split_limb_at_joint(
        side_arm_full, side_elbow, overlap=18, feather=2.5, cap_radius=76
    )

    baker.save_image(f"{name}/side_torso.png", side_torso)
    baker.save_image(f"{name}/side_under.png", side_under)
    baker.save_image(f"{name}/side_arm_upper.png", side_arm_upper)
    baker.save_image(f"{name}/side_arm_lower.png", side_arm_lower)
    baker.save_image(f"{name}/side_arm_cap.png", side_arm_cap)
    baker.save_image(f"{name}/side_legN_full.png", leg_n_full)
    baker.save_image(f"{name}/side_legF_full.png", leg_f_full)
    baker.save_image(f"{name}/side_legN_thigh.png", leg_n_thigh)
    baker.save_image(f"{name}/side_legN_calf.png", leg_n_calf)
    baker.save_image(f"{name}/side_legN_cap.png", leg_n_cap)
    baker.save_image(f"{name}/side_legF_thigh.png", leg_f_thigh)
    baker.save_image(f"{name}/side_legF_calf.png", leg_f_calf)
    baker.save_image(f"{name}/side_legF_cap.png", leg_f_cap)
    baker.save_meta(
        f"{name}/side_meta.json",
        {
            "shoulder": s_orig(side_cfg["pivots"]["shoulder"]),
            "elbow": side_elbow,
            "wrist": s_orig(side_cfg["pivots"]["wrist"]),
            "hip_near": s2(side_cfg["pivots"]["hip_near"]),
            "hip_far": s2(side_cfg["pivots"]["hip_far"]),
            "knee_near": knee_n,
            "knee_far": knee_f,
            "ankle_near": s2(side_cfg["pivots"]["ankle_near"]),
            "ankle_far": s2(side_cfg["pivots"]["ankle_far"]),
            "arm_offset": [sb[0] - sb2[0], sb[1] - sb2[1]],
        },
    )

    # Front view (pre-composited head + 2-bone elbow-split arm for all mouth/blink states)
    front_cfg = hero_cfg["views"]["front"]
    front_base_c = load_char(root, front_cfg["base_file"])
    front_base_img = front_base_c["base"]
    cut = Image.new("L", front_base_img.size, 255)
    ImageDraw.Draw(cut).rectangle([0, 0, front_base_img.size[0], front_cfg["neck_cut_y"]], fill=0)
    cut = cut.filter(ImageFilter.GaussianBlur(4))
    ba = np.asarray(front_base_img.split()[3]).astype(np.int32)
    cm = np.asarray(cut).astype(np.int32)
    front_base_img.putalpha(Image.fromarray((ba * cm // 255).astype(np.uint8)))

    variants = list(front_cfg["variants"].items())
    front = load_char(root, front_cfg["orig_file"], variants)
    fb = front["bbox"]

    def f_pt(pt):
        return (pt[0] - fb[0], pt[1] - fb[1])

    front_img = front["base"]
    head_p = f_pt(front_cfg["pivots"]["head"])
    arm_p = f_pt(front_cfg["pivots"]["arm"])
    front_elbow_p = f_pt(front_cfg["pivots"]["elbow"])
    front_wrist_p = f_pt(front_cfg["pivots"]["wrist"])
    mouth_box = (*f_pt(front_cfg["boxes"]["mouth"][:2]), *f_pt(front_cfg["boxes"]["mouth"][2:]))
    eye_box = (*f_pt(front_cfg["boxes"]["eyes"][:2]), *f_pt(front_cfg["boxes"]["eyes"][2:]))
    arm_poly = [f_pt(p) for p in front_cfg["polygons"]["arm"]]
    stub_poly = [f_pt(p) for p in front_cfg["polygons"]["sleeve_stub"]]
    front_stub = poly_part(front_img, stub_poly)
    front_cap_r = int(front_cfg.get("cap_radius", 40))

    baker.save_image(f"{name}/front_base.png", front_base_img)
    baker.save_image(f"{name}/front_stub.png", front_stub)
    for m in (0, 1, 2):
        for b in (0, 1):
            img = front_img
            if m == 1:
                img = patch(img, front["half"], mouth_box)
            elif m == 2:
                img = patch(img, front["open"], mouth_box)
            if b:
                img = patch(img, front["eyes"], eye_box)
            baker.save_image(f"{name}/front_head_m{m}_b{b}.png", rect_part(img, int(head_p[1])))
            arm_full = poly_part(img, arm_poly)
            arm_upper, arm_lower, arm_cap = split_limb_at_joint(
                arm_full, front_elbow_p, overlap=14, feather=2.5, cap_radius=front_cap_r
            )
            baker.save_image(f"{name}/front_arm_upper_m{m}_b{b}.png", arm_upper)
            baker.save_image(f"{name}/front_arm_lower_m{m}_b{b}.png", arm_lower)
            baker.save_image(f"{name}/front_arm_cap_m{m}_b{b}.png", arm_cap)

    baker.save_meta(
        f"{name}/front_meta.json",
        {
            "head_pivot": list(head_p),
            "arm_pivot": list(arm_p),
            "elbow_pivot": list(front_elbow_p),
            "wrist_pivot": list(front_wrist_p),
            "orig_height": front_img.size[1],
            "head_offset": front_cfg["offsets"]["head"],
            "arm_offset": front_cfg["offsets"]["arm"],
        },
    )


def _bake_standing_puppet(baker: AssetBaker, root: Path, name: str, char_cfg: dict) -> None:
    front_cfg = char_cfg["views"]["front"]
    full = clear_big_white_components(
        remove_white(Image.open(root / front_cfg["base_file"])),
        protect_box=front_cfg.get("protect_box"),
    )
    alpha_ch = full.split()[3]
    tb = alpha_ch.point(lambda p: 255 if p > 20 else 0).getbbox()

    def t_pt(pt):
        return (pt[0] - tb[0], pt[1] - tb[1])

    eyes_full = remove_white(Image.open(root / front_cfg["eyes_file"]))
    eyes_full.putalpha(alpha_ch)
    eye_box = (*t_pt(front_cfg["boxes"]["eyes"][:2]), *t_pt(front_cfg["boxes"]["eyes"][2:]))
    baker.save_image(f"{name}/base.png", full.crop(tb))
    baker.save_image(f"{name}/eyes.png", eyes_full.crop(tb))

    meta: dict = {"eye_box": list(eye_box)}
    variants = front_cfg.get("variants", {})
    if "mouth" in front_cfg["boxes"]:
        meta["mouth_box"] = [*t_pt(front_cfg["boxes"]["mouth"][:2]), *t_pt(front_cfg["boxes"]["mouth"][2:])]
    for vk in ("half", "open"):
        if vk in variants:
            m_im = remove_white(Image.open(root / variants[vk]))
            m_im.putalpha(alpha_ch)
            baker.save_image(f"{name}/mouth_{vk}.png", m_im.crop(tb))

    baker.save_meta(f"{name}/meta.json", meta)


def _bake_companion_puppet(baker: AssetBaker, root: Path, name: str, char_cfg: dict) -> None:
    side_cfg = char_cfg["views"]["side"]
    c = load_char(root, side_cfg["base_file"])
    cb = c["bbox"]
    with Image.open(root / side_cfg["base_file"]) as orig:
        gw, gh = orig.size

    def c_pt(pt):
        return (pt[0] - cb[0], pt[1] - cb[1])

    tail_poly = [c_pt((int(rx * gw), int(ry * gh))) for rx, ry in side_cfg["tail_poly_rel"]]
    tail_p = c_pt((int(side_cfg["tail_pivot_rel"][0] * gw), int(side_cfg["tail_pivot_rel"][1] * gh)))
    tail = poly_part(c["base"], tail_poly)
    body = subtract_alpha(c["base"], tail)
    baker.save_image(f"{name}/body.png", body)
    baker.save_image(f"{name}/tail.png", tail)
    baker.save_meta(f"{name}/meta.json", {"tail_pivot": list(tail_p)})


def bake_all_puppets(root: Path, config_dir: Path, force: bool = False) -> AssetBaker:
    """Bake raw character drawings into transparent, joint-split RGBA assets in assets_baked/."""
    baker = AssetBaker(root)
    puppets_cfg = _load_puppet_configs(config_dir)
    source_files = _collect_source_files(puppets_cfg)

    required_outputs: list[str] = []
    for name, cfg in puppets_cfg.items():
        required_outputs.extend(_required_outputs_for_puppet(name, cfg))

    if not force and baker.is_fresh(source_files, required_outputs):
        return baker

    for name, cfg in puppets_cfg.items():
        if _is_hero_puppet(cfg):
            _bake_hero_puppet(baker, root, name, cfg)
        elif _is_companion_puppet(cfg):
            _bake_companion_puppet(baker, root, name, cfg)
        else:
            _bake_standing_puppet(baker, root, name, cfg)

    baker.commit_manifest(source_files)
    return baker


def _load_puppet_configs(config_dir: Path) -> Dict[str, dict]:
    puppets_dir = config_dir / "puppets"
    configs: Dict[str, dict] = {}
    for p in sorted(puppets_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        configs[data["name"]] = data
    return configs


class ScaledAssets:
    """Holds pre-scaled RGBA parts ready for fast worker-level compositing."""

    def __init__(self, root: Path, config_dir: Path, scene_cfg: dict) -> None:
        baker = bake_all_puppets(root, config_dir, force=False)
        chars_cfg = scene_cfg["characters"]

        # Standing character / listener (tara slot -> e.g. 'tara' or 'kavya')
        tara_cfg = chars_cfg["tara"]
        tara_name = tara_cfg.get("puppet", "tara")
        tara_h = tara_cfg["height"]
        tara_meta = baker.load_meta(f"{tara_name}/meta.json")
        self.tara_base, tara_s = scaled(baker.load_image(f"{tara_name}/base.png"), tara_h)
        self.tara_eyes_full, _ = scaled(baker.load_image(f"{tara_name}/eyes.png"), tara_h)
        t_eye_box = tuple(int(v * tara_s) for v in tara_meta["eye_box"])
        self.tara_blink = patch(self.tara_base, self.tara_eyes_full, t_eye_box)

        self.tara_states: Dict[Tuple[int, int], Image.Image] = {
            (0, 0): self.tara_base,
            (0, 1): self.tara_blink,
        }
        if "mouth_box" in tara_meta:
            t_mouth_box = tuple(int(v * tara_s) for v in tara_meta["mouth_box"])
            for lvl, vk in ((1, "half"), (2, "open")):
                rel_p = f"{tara_name}/mouth_{vk}.png"
                if (baker.baked_dir / rel_p).is_file():
                    m_full, _ = scaled(baker.load_image(rel_p), tara_h)
                    m_img = patch(self.tara_base, m_full, t_mouth_box, feather=6)
                    self.tara_states[(lvl, 0)] = m_img
                    self.tara_states[(lvl, 1)] = patch(m_img, self.tara_eyes_full, t_eye_box)
                else:
                    self.tara_states[(lvl, 0)] = self.tara_base
                    self.tara_states[(lvl, 1)] = self.tara_blink
        else:
            for lvl in (1, 2):
                self.tara_states[(lvl, 0)] = self.tara_base
                self.tara_states[(lvl, 1)] = self.tara_blink

        # Companion creature (gulli slot -> e.g. 'gulli' or 'mitthu')
        gulli_cfg = chars_cfg["gulli"]
        gulli_name = gulli_cfg.get("puppet", "gulli")
        gulli_h = gulli_cfg["height"]
        gulli_meta = baker.load_meta(f"{gulli_name}/meta.json")
        self.gulli_body, gs = scaled(baker.load_image(f"{gulli_name}/body.png"), gulli_h)
        self.gulli_tail, _ = scaled(baker.load_image(f"{gulli_name}/tail.png"), gulli_h)
        self.tail_pivot: Tuple[float, float] = (
            gulli_meta["tail_pivot"][0] * gs,
            gulli_meta["tail_pivot"][1] * gs,
        )

        # Hero character (gopal slot -> e.g. 'gopal' or 'bansi')
        hero_cfg = chars_cfg["gopal"]
        hero_name = hero_cfg.get("puppet", "gopal")
        side_h = hero_cfg["side_height"]
        side_meta = baker.load_meta(f"{hero_name}/side_meta.json")
        self.side_parts: Dict[str, Image.Image] = {}
        ss = 1.0
        for name, file_key in [
            ("arm_upper", f"{hero_name}/side_arm_upper.png"),
            ("arm_lower", f"{hero_name}/side_arm_lower.png"),
            ("arm_cap", f"{hero_name}/side_arm_cap.png"),
            ("legN_full", f"{hero_name}/side_legN_full.png"),
            ("legF_full", f"{hero_name}/side_legF_full.png"),
            ("legN_thigh", f"{hero_name}/side_legN_thigh.png"),
            ("legN_calf", f"{hero_name}/side_legN_calf.png"),
            ("legN_cap", f"{hero_name}/side_legN_cap.png"),
            ("legF_thigh", f"{hero_name}/side_legF_thigh.png"),
            ("legF_calf", f"{hero_name}/side_legF_calf.png"),
            ("legF_cap", f"{hero_name}/side_legF_cap.png"),
            ("torso", f"{hero_name}/side_torso.png"),
            ("under", f"{hero_name}/side_under.png"),
        ]:
            self.side_parts[name], ss = scaled(baker.load_image(file_key), side_h)

        self.sh_pivot = (side_meta["shoulder"][0] * ss, side_meta["shoulder"][1] * ss)
        self.side_elbow_pivot = (side_meta["elbow"][0] * ss, side_meta["elbow"][1] * ss)
        self.legn_hip = (side_meta["hip_near"][0] * ss, side_meta["hip_near"][1] * ss)
        self.legf_hip = (side_meta["hip_far"][0] * ss, side_meta["hip_far"][1] * ss)
        self.legn_knee = (side_meta["knee_near"][0] * ss, side_meta["knee_near"][1] * ss)
        self.legf_knee = (side_meta["knee_far"][0] * ss, side_meta["knee_far"][1] * ss)
        self.legn_ankle = (side_meta["ankle_near"][0] * ss, side_meta["ankle_near"][1] * ss)
        self.legf_ankle = (side_meta["ankle_far"][0] * ss, side_meta["ankle_far"][1] * ss)
        self.arm_side_off = (side_meta["arm_offset"][0] * ss, side_meta["arm_offset"][1] * ss)

        front_h = hero_cfg["front_height"]
        front_meta = baker.load_meta(f"{hero_name}/front_meta.json")
        self.front_base, _ = scaled(baker.load_image(f"{hero_name}/front_base.png"), front_h)
        self.front_stub, _ = scaled(baker.load_image(f"{hero_name}/front_stub.png"), front_h)
        front_s = front_h / front_meta["orig_height"]
        self.head_pivot = (front_meta["head_pivot"][0] * front_s, front_meta["head_pivot"][1] * front_s)
        self.arm_pivot = (front_meta["arm_pivot"][0] * front_s, front_meta["arm_pivot"][1] * front_s)
        self.front_elbow_pivot = (front_meta["elbow_pivot"][0] * front_s, front_meta["elbow_pivot"][1] * front_s)
        self.front_wrist_pivot = (front_meta["wrist_pivot"][0] * front_s, front_meta["wrist_pivot"][1] * front_s)
        self.head_off = tuple(front_meta["head_offset"])
        self.arm_off = tuple(front_meta["arm_offset"])

        self.front_states: Dict[Tuple[int, int], Tuple[Image.Image, Image.Image, Image.Image, Image.Image]] = {}
        for m in (0, 1, 2):
            for b in (0, 1):
                hs, _ = scaled(baker.load_image(f"{hero_name}/front_head_m{m}_b{b}.png"), front_h)
                au, _ = scaled(baker.load_image(f"{hero_name}/front_arm_upper_m{m}_b{b}.png"), front_h)
                al, _ = scaled(baker.load_image(f"{hero_name}/front_arm_lower_m{m}_b{b}.png"), front_h)
                ac, _ = scaled(baker.load_image(f"{hero_name}/front_arm_cap_m{m}_b{b}.png"), front_h)
                self.front_states[(m, b)] = (hs, au, al, ac)
