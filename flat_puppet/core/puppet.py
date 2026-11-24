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


def bake_all_puppets(root: Path, config_dir: Path, force: bool = False) -> AssetBaker:
    """Bake raw character drawings into transparent, joint-split RGBA assets in assets_baked/."""
    baker = AssetBaker(root)
    puppets_cfg = _load_puppet_configs(config_dir)
    source_files = _collect_source_files(puppets_cfg)

    required_outputs = [
        "gopal/side_torso.png",
        "gopal/side_under.png",
        "gopal/side_arm_upper.png",
        "gopal/side_arm_lower.png",
        "gopal/side_arm_cap.png",
        "gopal/side_legN_thigh.png",
        "gopal/side_legN_calf.png",
        "gopal/side_legN_cap.png",
        "gopal/side_legF_thigh.png",
        "gopal/side_legF_calf.png",
        "gopal/side_legF_cap.png",
        "gopal/side_meta.json",
        "gopal/front_base.png",
        "gopal/front_stub.png",
        "gopal/front_meta.json",
        "tara/base.png",
        "tara/eyes.png",
        "tara/meta.json",
        "gulli/body.png",
        "gulli/tail.png",
        "gulli/meta.json",
    ]
    for m in (0, 1, 2):
        for b in (0, 1):
            required_outputs.append(f"gopal/front_head_m{m}_b{b}.png")
            required_outputs.append(f"gopal/front_arm_upper_m{m}_b{b}.png")
            required_outputs.append(f"gopal/front_arm_lower_m{m}_b{b}.png")
            required_outputs.append(f"gopal/front_arm_cap_m{m}_b{b}.png")

    if not force and baker.is_fresh(source_files, required_outputs):
        return baker

    # 1. Bake Gopal Side (2-bone legs + 2-bone arm with circular joint caps)
    gopal = puppets_cfg["gopal"]
    side_cfg = gopal["views"]["side"]
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
    fy0, fy1 = s2((0, 1785))[1], s2((0, 1845))[1]
    ua[fy0:fy1] *= (1.0 - (np.arange(fy0, fy1) - fy0) / max(fy1 - fy0, 1))[:, None]
    up.putalpha(Image.fromarray(ua.astype(np.uint8)))
    side_under = up.filter(ImageFilter.GaussianBlur(1.0))
    side_torso = subtract_alpha(subtract_alpha(base_img, leg_n_full), leg_f_full)

    side_orig_c = load_char(root, side_cfg["orig_file"])
    sb = side_orig_c["bbox"]

    def s_orig(pt):
        return (pt[0] - sb[0], pt[1] - sb[1])

    side_arm_full = poly_part(side_orig_c["base"], [s_orig(p) for p in side_cfg["polygons"]["arm"]])
    side_elbow = s_orig(side_cfg["pivots"]["elbow"])
    side_arm_upper, side_arm_lower, side_arm_cap = split_limb_at_joint(
        side_arm_full, side_elbow, overlap=18, feather=2.5, cap_radius=76
    )

    baker.save_image("gopal/side_torso.png", side_torso)
    baker.save_image("gopal/side_under.png", side_under)
    baker.save_image("gopal/side_arm_upper.png", side_arm_upper)
    baker.save_image("gopal/side_arm_lower.png", side_arm_lower)
    baker.save_image("gopal/side_arm_cap.png", side_arm_cap)
    baker.save_image("gopal/side_legN_thigh.png", leg_n_thigh)
    baker.save_image("gopal/side_legN_calf.png", leg_n_calf)
    baker.save_image("gopal/side_legN_cap.png", leg_n_cap)
    baker.save_image("gopal/side_legF_thigh.png", leg_f_thigh)
    baker.save_image("gopal/side_legF_calf.png", leg_f_calf)
    baker.save_image("gopal/side_legF_cap.png", leg_f_cap)
    baker.save_meta(
        "gopal/side_meta.json",
        {
            "shoulder": s_orig(side_cfg["pivots"]["shoulder"]),
            "elbow": side_elbow,
            "wrist": s_orig(side_cfg["pivots"]["wrist"]),
            "hip_near": s2(side_cfg["pivots"]["hip_near"]),
            "hip_far": s2(side_cfg["pivots"]["hip_far"]),
            "knee_near": knee_n,
            "knee_far": knee_f,
            "arm_offset": [sb[0] - sb2[0], sb[1] - sb2[1]],
        },
    )

    # 2. Bake Gopal Front (pre-composited head + 2-bone elbow-split arm for all mouth/blink states)
    front_cfg = gopal["views"]["front"]
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

    baker.save_image("gopal/front_base.png", front_base_img)
    baker.save_image("gopal/front_stub.png", front_stub)
    for m in (0, 1, 2):
        for b in (0, 1):
            img = front_img
            if m == 1:
                img = patch(img, front["half"], mouth_box)
            elif m == 2:
                img = patch(img, front["open"], mouth_box)
            if b:
                img = patch(img, front["eyes"], eye_box)
            baker.save_image(f"gopal/front_head_m{m}_b{b}.png", rect_part(img, int(head_p[1])))
            arm_full = poly_part(img, arm_poly)
            arm_upper, arm_lower, arm_cap = split_limb_at_joint(
                arm_full, front_elbow_p, overlap=14, feather=2.5, cap_radius=40
            )
            baker.save_image(f"gopal/front_arm_upper_m{m}_b{b}.png", arm_upper)
            baker.save_image(f"gopal/front_arm_lower_m{m}_b{b}.png", arm_lower)
            baker.save_image(f"gopal/front_arm_cap_m{m}_b{b}.png", arm_cap)

    baker.save_meta(
        "gopal/front_meta.json",
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

    # 3. Bake Tara
    tara_cfg = puppets_cfg["tara"]["views"]["front"]
    tara_full = clear_big_white_components(
        remove_white(Image.open(root / tara_cfg["base_file"])),
        protect_box=tara_cfg["protect_box"],
    )
    tara_eyes_full = remove_white(Image.open(root / tara_cfg["eyes_file"]))
    tara_eyes_full.putalpha(tara_full.split()[3])
    tb = tara_full.split()[3].point(lambda p: 255 if p > 20 else 0).getbbox()

    def t_pt(pt):
        return (pt[0] - tb[0], pt[1] - tb[1])

    eye_box_t = (*t_pt(tara_cfg["boxes"]["eyes"][:2]), *t_pt(tara_cfg["boxes"]["eyes"][2:]))
    baker.save_image("tara/base.png", tara_full.crop(tb))
    baker.save_image("tara/eyes.png", tara_eyes_full.crop(tb))
    baker.save_meta("tara/meta.json", {"eye_box": list(eye_box_t)})

    # 4. Bake Gulli
    gulli_cfg = puppets_cfg["gulli"]["views"]["side"]
    gulli_c = load_char(root, gulli_cfg["base_file"])
    gb = gulli_c["bbox"]
    gw, gh = Image.open(root / gulli_cfg["base_file"]).size

    def g_pt(pt):
        return (pt[0] - gb[0], pt[1] - gb[1])

    tail_poly = [g_pt((int(rx * gw), int(ry * gh))) for rx, ry in gulli_cfg["tail_poly_rel"]]
    tail_p = g_pt((int(gulli_cfg["tail_pivot_rel"][0] * gw), int(gulli_cfg["tail_pivot_rel"][1] * gh)))
    gulli_tail = poly_part(gulli_c["base"], tail_poly)
    gulli_body = subtract_alpha(gulli_c["base"], gulli_tail)
    baker.save_image("gulli/body.png", gulli_body)
    baker.save_image("gulli/tail.png", gulli_tail)
    baker.save_meta("gulli/meta.json", {"tail_pivot": list(tail_p)})

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

        # Tara
        tara_h = chars_cfg["tara"]["height"]
        tara_meta = baker.load_meta("tara/meta.json")
        self.tara_base, tara_s = scaled(baker.load_image("tara/base.png"), tara_h)
        self.tara_eyes_full, _ = scaled(baker.load_image("tara/eyes.png"), tara_h)
        t_eye_box = tuple(int(v * tara_s) for v in tara_meta["eye_box"])
        self.tara_blink = patch(self.tara_base, self.tara_eyes_full, t_eye_box)

        # Gulli
        gulli_h = chars_cfg["gulli"]["height"]
        gulli_meta = baker.load_meta("gulli/meta.json")
        self.gulli_body, gs = scaled(baker.load_image("gulli/body.png"), gulli_h)
        self.gulli_tail, _ = scaled(baker.load_image("gulli/tail.png"), gulli_h)
        self.tail_pivot: Tuple[float, float] = (
            gulli_meta["tail_pivot"][0] * gs,
            gulli_meta["tail_pivot"][1] * gs,
        )

        # Gopal Side (2-bone legs + 2-bone arm)
        side_h = chars_cfg["gopal"]["side_height"]
        side_meta = baker.load_meta("gopal/side_meta.json")
        self.side_parts: Dict[str, Image.Image] = {}
        ss = 1.0
        for name, file_key in [
            ("arm_upper", "gopal/side_arm_upper.png"),
            ("arm_lower", "gopal/side_arm_lower.png"),
            ("arm_cap", "gopal/side_arm_cap.png"),
            ("legN_thigh", "gopal/side_legN_thigh.png"),
            ("legN_calf", "gopal/side_legN_calf.png"),
            ("legN_cap", "gopal/side_legN_cap.png"),
            ("legF_thigh", "gopal/side_legF_thigh.png"),
            ("legF_calf", "gopal/side_legF_calf.png"),
            ("legF_cap", "gopal/side_legF_cap.png"),
            ("torso", "gopal/side_torso.png"),
            ("under", "gopal/side_under.png"),
        ]:
            self.side_parts[name], ss = scaled(baker.load_image(file_key), side_h)

        self.sh_pivot = (side_meta["shoulder"][0] * ss, side_meta["shoulder"][1] * ss)
        self.side_elbow_pivot = (side_meta["elbow"][0] * ss, side_meta["elbow"][1] * ss)
        self.legn_hip = (side_meta["hip_near"][0] * ss, side_meta["hip_near"][1] * ss)
        self.legf_hip = (side_meta["hip_far"][0] * ss, side_meta["hip_far"][1] * ss)
        self.legn_knee = (side_meta["knee_near"][0] * ss, side_meta["knee_near"][1] * ss)
        self.legf_knee = (side_meta["knee_far"][0] * ss, side_meta["knee_far"][1] * ss)
        self.arm_side_off = (side_meta["arm_offset"][0] * ss, side_meta["arm_offset"][1] * ss)

        # Gopal Front (2-bone IK arm + head)
        front_h = chars_cfg["gopal"]["front_height"]
        front_meta = baker.load_meta("gopal/front_meta.json")
        self.front_base, _ = scaled(baker.load_image("gopal/front_base.png"), front_h)
        self.front_stub, _ = scaled(baker.load_image("gopal/front_stub.png"), front_h)
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
                hs, _ = scaled(baker.load_image(f"gopal/front_head_m{m}_b{b}.png"), front_h)
                au, _ = scaled(baker.load_image(f"gopal/front_arm_upper_m{m}_b{b}.png"), front_h)
                al, _ = scaled(baker.load_image(f"gopal/front_arm_lower_m{m}_b{b}.png"), front_h)
                ac, _ = scaled(baker.load_image(f"gopal/front_arm_cap_m{m}_b{b}.png"), front_h)
                self.front_states[(m, b)] = (hs, au, al, ac)
