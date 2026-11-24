"""Reusable character prep, coordinate probing, flood-fill recoloring, and 4x facial synthesis tools.

Stores all asset-creation techniques proven in Flat Puppet Studio so new characters can be prepped
deterministically with minimal manual trial-and-error:
  - Coordinate grid probe sheets (`save_probe_grid`) for exact pixel pivot/box measurement
  - Closed-ink garment flood-fill recoloring (`flood_enclosed`, `recolor_region`)
  - Arm-removed torso base reconstruction (`reconstruct_front_noarm`)
  - 4x supersampled closed eyelids (`synthesize_eyes_closed`) & half/open mouths (`synthesize_mouths`)
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from flat_puppet.core.image_ops import remove_white


def rgb_luma(rgb: np.ndarray) -> np.ndarray:
    """Compute perceptual luma array for (H, W, 3) RGB uint8/float image."""
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def save_probe_grid(
    src_path: Path,
    out_path: Path,
    step_px: int = 100,
    minor_step_px: Optional[int] = 50,
    normalized: bool = False,
    crop_box: Optional[Tuple[int, int, int, int]] = None,
) -> Path:
    """Save an image overlaid with crisp X (red) and Y (blue) coordinate lines for pivot picking."""
    im = Image.open(src_path).convert("RGB")
    w, h = im.size
    draw = ImageDraw.Draw(im)

    if normalized:
        for i in range(1, 10):
            x = int(w * i / 10)
            y = int(h * i / 10)
            draw.line([(x, 0), (x, h)], fill=(255, 0, 0), width=2)
            draw.text((x + 4, 8), f"0.{i}", fill=(255, 0, 0))
            draw.line([(0, y), (w, y)], fill=(0, 0, 255), width=2)
            draw.text((8, y + 4), f"0.{i}", fill=(0, 0, 255))
    else:
        if minor_step_px and minor_step_px > 0:
            for x in range(0, w, minor_step_px):
                if x % step_px != 0:
                    draw.line([(x, 0), (x, h)], fill=(255, 175, 175), width=1)
            for y in range(0, h, minor_step_px):
                if y % step_px != 0:
                    draw.line([(0, y), (w, y)], fill=(175, 175, 255), width=1)
        for x in range(0, w, step_px):
            draw.line([(x, 0), (x, h)], fill=(230, 0, 0), width=2)
            draw.text((x + 3, 6), str(x), fill=(220, 0, 0))
        for y in range(0, h, step_px):
            draw.line([(0, y), (w, y)], fill=(0, 0, 230), width=2)
            draw.text((6, y + 3), str(y), fill=(0, 0, 220))

    if crop_box:
        im = im.crop(crop_box)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path


def flood_enclosed(
    luma: np.ndarray,
    pass_mask: np.ndarray,
    seeds: Iterable[Tuple[int, int]],
    wall_luma: float = 90.0,
) -> np.ndarray:
    """Flood-fill closed interior pockets bounded by dark ink lines (`luma <= wall_luma`)."""
    h, w = luma.shape
    mask = np.zeros((h, w), dtype=bool)
    passable = pass_mask & (luma > wall_luma)
    dq: deque[tuple[int, int]] = deque()

    for sx, sy in seeds:
        if 0 <= sx < w and 0 <= sy < h and passable[sy, sx] and not mask[sy, sx]:
            mask[sy, sx] = True
            dq.append((sy, sx))

    while dq:
        y, x = dq.popleft()
        if y + 1 < h and passable[y + 1, x] and not mask[y + 1, x]:
            mask[y + 1, x] = True
            dq.append((y + 1, x))
        if y - 1 >= 0 and passable[y - 1, x] and not mask[y - 1, x]:
            mask[y - 1, x] = True
            dq.append((y - 1, x))
        if x + 1 < w and passable[y, x + 1] and not mask[y, x + 1]:
            mask[y, x + 1] = True
            dq.append((y, x + 1))
        if x - 1 >= 0 and passable[y, x - 1] and not mask[y, x - 1]:
            mask[y, x - 1] = True
            dq.append((y, x - 1))
    return mask


def recolor_region(
    rgb: np.ndarray,
    mask: np.ndarray,
    target_rgb: Tuple[int, int, int],
    ref_luma: float,
) -> np.ndarray:
    """Shift pixels in `mask` to `target_rgb` while preserving cel shading & anti-aliased dark outlines."""
    out = rgb.astype(np.float32).copy()
    luma = rgb_luma(out)
    scale = np.clip(luma / max(ref_luma, 1.0), 0.42, 1.15)[..., None]
    target = np.array(target_rgb, dtype=np.float32)[None, None, :] * scale
    ink_fade = np.clip((luma - 55.0) / 55.0, 0.0, 1.0)[..., None]
    blend = mask[..., None].astype(np.float32) * ink_fade
    out = out * (1.0 - blend) + np.clip(target, 0, 255) * blend
    return np.clip(out, 0, 255).astype(np.uint8)


def synthesize_eyes_closed(
    src_rgb: Image.Image,
    left_eye_box: Tuple[int, int, int, int],
    right_eye_box: Tuple[int, int, int, int],
    left_skin_pt: Tuple[int, int],
    right_skin_pt: Tuple[int, int],
    ink_rgb: Tuple[int, int, int] = (18, 14, 12),
    lid_width: float = 5.0,
    ss: int = 4,
) -> Image.Image:
    """Generate pixel-aligned closed-eye blink frame at 4x supersampling over open eye boxes."""
    w, h = src_rgb.size
    arr = np.asarray(src_rgb)
    skin_l = tuple(int(v) for v in arr[left_skin_pt[1], left_skin_pt[0]])
    skin_r = tuple(int(v) for v in arr[right_skin_pt[1], right_skin_pt[0]])

    big = src_rgb.resize((w * ss, h * ss), Image.Resampling.BICUBIC)
    draw = ImageDraw.Draw(big)

    for box, skin in ((left_eye_box, skin_l), (right_eye_box, skin_r)):
        x0, y0, x1, y1 = box
        draw.ellipse([x0 * ss, y0 * ss, x1 * ss, y1 * ss], fill=skin)
        ey_mid = (y0 + y1) / 2.0
        arc_top = ey_mid - (y1 - y0) * 0.18
        arc_bot = ey_mid + (y1 - y0) * 0.25
        draw.arc(
            [(x0 + 3) * ss, arc_top * ss, (x1 - 3) * ss, arc_bot * ss],
            start=10,
            end=170,
            fill=ink_rgb,
            width=int(lid_width * ss),
        )

    res = big.resize((w, h), Image.Resampling.LANCZOS)
    out = src_rgb.copy()
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([left_eye_box[0] - 1, left_eye_box[1] - 1, left_eye_box[2] + 1, left_eye_box[3] + 1], fill=255)
    md.ellipse([right_eye_box[0] - 1, right_eye_box[1] - 1, right_eye_box[2] + 1, right_eye_box[3] + 1], fill=255)
    out.paste(res, (0, 0), mask)
    return out


def synthesize_mouths(
    src_rgb: Image.Image,
    clear_box: Tuple[int, int, int, int],
    skin_sample_pt: Tuple[int, int],
    half_box: Tuple[int, int, int, int],
    open_box: Tuple[int, int, int, int],
    mustache_preserve_y: Optional[int] = None,
    chin_arc_box: Optional[Tuple[int, int, int, int]] = None,
    ink_rgb: Tuple[int, int, int] = (18, 14, 12),
    ss: int = 4,
) -> Tuple[Image.Image, Image.Image]:
    """Generate pixel-aligned `mouth_half` and `mouth_open` images with optional mustache lock."""
    w, h = src_rgb.size
    arr = np.asarray(src_rgb)
    mouth_skin = tuple(int(v) for v in arr[skin_sample_pt[1], skin_sample_pt[0]])
    cx0, cy0, cx1, cy1 = clear_box
    outputs: List[Image.Image] = []

    for mode, mbox in (("half", half_box), ("open", open_box)):
        mx0, my0, mx1, my1 = mbox
        big = src_rgb.resize((w * ss, h * ss), Image.Resampling.BICUBIC)
        dm = ImageDraw.Draw(big)
        dm.rounded_rectangle([cx0 * ss, cy0 * ss, cx1 * ss, cy1 * ss], radius=18 * ss, fill=mouth_skin)

        mw = mx1 - mx0
        mh = my1 - my0
        outline_w = int((3.8 if mode == "half" else 4.2) * ss)
        dm.chord([mx0 * ss, my0 * ss, mx1 * ss, my1 * ss], start=5, end=175, fill=(32, 11, 12), outline=ink_rgb, width=outline_w)
        # Warm tongue
        dm.chord(
            [(mx0 + mw * 0.2) * ss, (my0 + mh * 0.45) * ss, (mx1 - mw * 0.2) * ss, (my1 - 2) * ss],
            start=12,
            end=168,
            fill=(196, 82, 80),
        )
        # Upper teeth strip
        dm.chord(
            [(mx0 + mw * 0.1) * ss, (my0 + mh * 0.22) * ss, (mx1 - mw * 0.1) * ss, (my0 + mh * 0.52) * ss],
            start=0,
            end=180,
            fill=(249, 247, 243),
        )
        upper_lip_y = int((my0 + mh * 0.48) * ss)
        dm.line([(mx0 * ss, upper_lip_y), (mx1 * ss, upper_lip_y)], fill=ink_rgb, width=int(3.6 * ss))
        dm.chord([mx0 * ss, my0 * ss, mx1 * ss, my1 * ss], start=5, end=175, fill=None, outline=ink_rgb, width=outline_w)

        if chin_arc_box:
            ax0, ay0, ax1, ay1 = chin_arc_box
            dm.arc([ax0 * ss, ay0 * ss, ax1 * ss, ay1 * ss], start=15, end=165, fill=ink_rgb, width=int(2.8 * ss))

        res = big.resize((w, h), Image.Resampling.LANCZOS)
        if mustache_preserve_y is not None:
            r_arr = np.asarray(res).copy()
            yy, _ = np.mgrid[0:h, 0:w]
            dark_orig = (arr[:, :, 0] < 48) & (arr[:, :, 1] < 48) & (arr[:, :, 2] < 48) & (yy < mustache_preserve_y)
            r_arr[dark_orig] = arr[dark_orig]
            res = Image.fromarray(r_arr)

        out = src_rgb.copy()
        mm = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mm).rounded_rectangle([cx0 - 2, cy0 - 2, cx1 + 2, cy1 + 2], radius=18, fill=255)
        out.paste(res, (0, 0), mm)
        outputs.append(out)

    return outputs[0], outputs[1]


def reconstruct_front_noarm(
    src_rgb: Image.Image,
    erase_poly: Sequence[Tuple[int, int]],
    shoulder_fill_poly: Sequence[Tuple[int, int]],
    shoulder_ink_pts: Sequence[Tuple[int, int]],
    paste_mask_poly: Sequence[Tuple[int, int]],
    kurta_sample_pt: Tuple[int, int],
    ink_rgb: Tuple[int, int, int] = (18, 14, 12),
    ink_width: float = 5.2,
    ss: int = 4,
) -> Image.Image:
    """Remove extended speaking arm to solid white while keeping artist torso wall & shoulder continuous."""
    w, h = src_rgb.size
    arr = np.asarray(src_rgb)
    kurta_rgb = tuple(int(v) for v in arr[kurta_sample_pt[1], kurta_sample_pt[0]])

    big = src_rgb.resize((w * ss, h * ss), Image.Resampling.BICUBIC)
    d = ImageDraw.Draw(big)
    d.polygon([(x * ss, y * ss) for x, y in erase_poly], fill=(255, 255, 255))
    d.polygon([(x * ss, y * ss) for x, y in shoulder_fill_poly], fill=kurta_rgb)
    d.line([(x * ss, y * ss) for x, y in shoulder_ink_pts], fill=ink_rgb, width=int(ink_width * ss), joint="curve")
    res = big.resize((w, h), Image.Resampling.LANCZOS)

    out = src_rgb.copy()
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(list(paste_mask_poly), fill=255)
    out.paste(res, (0, 0), mask)
    return out


def recolor_bansi_side_from_gopal(root: Path, src_rel: str, dst_path: Path) -> Path:
    """Derive clean side view matching Bansi palette via closed-ink flood fill."""
    im = Image.open(root / src_rel).convert("RGB")
    arr = np.asarray(im).copy()
    h, w, _ = arr.shape
    yy, xx = np.mgrid[0:h, 0:w]
    fg = np.asarray(remove_white(im))[:, :, 3] > 20
    luma = rgb_luma(arr.astype(np.float32))

    neutral_fg = fg & ((arr[:, :, 0].astype(np.int16) - arr[:, :, 2].astype(np.int16)) < 28) & (luma > 105)
    turban_seeds = [(sx, sy) for sy in range(100, 465, 6) for sx in range(250, 790, 6) if neutral_fg[sy, sx]]
    turban_cloth = flood_enclosed(luma, fg, turban_seeds, wall_luma=90.0) & neutral_fg & (yy < 468)
    arr = recolor_region(arr, turban_cloth, target_rgb=(156, 40, 44), ref_luma=228.0)

    diag_y = 398.0 - 0.36 * (xx - 305.0)
    gold_band = turban_cloth & (np.abs(yy - diag_y) < 14.0) & (xx > 265) & (xx < 785)
    arr = recolor_region(arr, gold_band, target_rgb=(246, 174, 58), ref_luma=110.0)

    warm_cream = (
        fg
        & (yy >= 655)
        & (yy <= 1615)
        & ((arr[:, :, 0].astype(np.int16) - arr[:, :, 2].astype(np.int16)) >= 16)
        & (arr[:, :, 2] > 145)
    )
    kurta_seeds = [(sx, sy) for sy in range(660, 1590, 14) for sx in range(320, 600, 14) if warm_cream[sy, sx]]
    kurta_cloth = flood_enclosed(luma, fg, kurta_seeds, wall_luma=90.0) & warm_cream
    arr = recolor_region(arr, kurta_cloth, target_rgb=(241, 163, 63), ref_luma=228.0)

    skin_mask = (
        fg
        & ~turban_cloth
        & ~kurta_cloth
        & (arr[:, :, 0] > 165)
        & (arr[:, :, 0] < 248)
        & (arr[:, :, 1] > 105)
        & (arr[:, :, 1] < 195)
        & (arr[:, :, 2] > 65)
        & (arr[:, :, 2] < 155)
        & ((arr[:, :, 0].astype(np.int16) - arr[:, :, 2].astype(np.int16)) > 40)
    )
    arr = recolor_region(arr, skin_mask, target_rgb=(215, 141, 91), ref_luma=184.0)

    final_arr = np.where(fg[..., None], arr, 255).astype(np.uint8)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(final_arr).save(dst_path)
    return dst_path


def build_bansi_story_cutouts(root: Path) -> None:
    """Reproduce all Bansi & Kavya character variants cleanly inside `assets_story/`."""
    out = root / "assets_story"
    bansi_src = Image.open(out / "bansi_front.jpg").convert("RGB")

    reconstruct_front_noarm(
        bansi_src,
        erase_poly=[
            (456, 440), (560, 440), (695, 720), (695, 930), (519, 930),
            (513, 880), (502, 720), (490, 640), (485, 560), (481, 520), (479, 480),
        ],
        shoulder_fill_poly=[(444, 442), (454, 442), (478, 480), (480, 524), (458, 524)],
        shoulder_ink_pts=[(453, 442), (477, 478), (479, 526)],
        paste_mask_poly=[
            (448, 436), (565, 436), (695, 720), (695, 930), (520, 930),
            (514, 880), (503, 720), (491, 640), (486, 560), (481, 520), (452, 480),
        ],
        kurta_sample_pt=(472, 650),
    ).save(out / "bansi_front_noarm.png")

    synthesize_eyes_closed(
        bansi_src,
        left_eye_box=(331, 246, 399, 311),
        right_eye_box=(432, 243, 484, 309),
        left_skin_pt=(326, 260),
        right_skin_pt=(422, 285),
    ).save(out / "bansi_front_eyes_closed.png")

    bm_h, bm_o = synthesize_mouths(
        bansi_src,
        clear_box=(388, 360, 448, 383),
        skin_sample_pt=(420, 378),
        half_box=(392, 353, 444, 383),
        open_box=(390, 348, 446, 392),
        mustache_preserve_y=368,
    )
    bm_h.save(out / "bansi_front_mouth_half.png")
    bm_o.save(out / "bansi_front_mouth_open.png")

    recolor_bansi_side_from_gopal(
        root,
        "media-generation-flat-gopal-side-noarm-legsapar-0-cf2cd755-b4a2-4aa0-9936-a0ebc20681b1.webp",
        out / "bansi_side_noarm.png",
    )
    recolor_bansi_side_from_gopal(
        root,
        "media-generation-flat-gopal-side-0-0e877276-a234-4e2e-b4df-3e5d8a70550c.webp",
        out / "bansi_side.png",
    )

    # Recolor Tara into Kavya + synthesize speaking mouths
    for rel_src, dst_name in [
        ("media-generation-flat-tara-body-0-468797d4-f104-42b5-8a43-dd693fb4dadc.webp", "kavya_base.png"),
        ("media-generation-flat-tara-eyes-closed-0-da4a4ad5-fefc-4fd4-95b2-bbd2b1a9a806.webp", "kavya_eyes_closed.png"),
    ]:
        im = Image.open(root / rel_src).convert("RGB")
        arr = np.asarray(im).copy()
        h, w, _ = arr.shape
        yy, xx = np.mgrid[0:h, 0:w]
        fg = np.asarray(remove_white(im))[:, :, 3] > 20
        luma = rgb_luma(arr.astype(np.float32))
        cloth_chroma = fg & (yy >= 715) & (yy <= 1765) & (xx >= 235) & (xx <= 725) & (arr[:, :, 0] > 175) & (arr[:, :, 2] < 135)
        frock_seeds = [(440, 1200), (440, 900), (350, 820), (540, 840), (560, 1000), (560, 1450), (450, 1680), (310, 1550)]
        dress_body = flood_enclosed(luma, fg, frock_seeds, wall_luma=90.0) & cloth_chroma
        trim_zone = fg & (
            (((xx < 250) | (xx > 720)) & (yy > 1050) & (yy < 1365) & (arr[:, :, 0] > 165) & (arr[:, :, 1] < 130))
            | ((((yy >= 715) & (yy <= 785)) | ((yy >= 1620) & (yy <= 1755))) & (xx > 235) & (xx < 725) & (arr[:, :, 0] > 180) & (arr[:, :, 1] < 155) & (arr[:, :, 2] < 80))
        )
        orange_pass = fg & ((arr[:, :, 0].astype(np.int16) - arr[:, :, 1].astype(np.int16)) > 74) & (arr[:, :, 2] < 95)
        trim_mask = flood_enclosed(luma, orange_pass, [(int(x), int(y)) for x, y in list(zip(*np.nonzero(trim_zone)[::-1]))[::25]], wall_luma=90.0) & orange_pass
        cuffs = fg & (yy >= 925) & (yy <= 990) & ((xx < 350) | (xx > 590)) & orange_pass
        if np.any(cuffs):
            trim_mask |= flood_enclosed(luma, orange_pass, [(int(x), int(y)) for x, y in list(zip(*np.nonzero(cuffs)[::-1]))[::10]], wall_luma=90.0) & orange_pass
        main_teal = dress_body & ~trim_mask
        arr = recolor_region(arr, main_teal, target_rgb=(34, 156, 146), ref_luma=205.0)
        arr = recolor_region(arr, trim_mask, target_rgb=(218, 56, 108), ref_luma=135.0)
        Image.fromarray(np.where(fg[..., None], arr, 255).astype(np.uint8)).save(out / dst_name)

    k_base = Image.open(out / "kavya_base.png").convert("RGB")
    km_h, km_o = synthesize_mouths(
        k_base,
        clear_box=(334, 536, 476, 608),
        skin_sample_pt=(345, 560),
        half_box=(362, 540, 444, 592),
        open_box=(360, 532, 446, 604),
        chin_arc_box=(386, 597, 422, 610),
    )
    km_h.save(out / "kavya_mouth_half.png")
    km_o.save(out / "kavya_mouth_open.png")
