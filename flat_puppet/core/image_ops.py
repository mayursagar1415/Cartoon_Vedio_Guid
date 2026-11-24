"""Image keying, polygonal extraction, leg articulation splitting, and offline asset baking."""

from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BAKE_VERSION = 8


def remove_white(img: Image.Image) -> Image.Image:
    """Flood-fill exterior near-white background to transparent alpha with soft anti-aliased edge."""
    img = img.convert("RGB")
    w, h = img.size
    arr = np.asarray(img).astype(np.int16)
    white = (arr[:, :, 0] > 232) & (arr[:, :, 1] > 230) & (arr[:, :, 2] > 222)

    try:
        from scipy.ndimage import label  # type: ignore

        labeled, _ = label(white)
        border_labels = np.unique(
            np.concatenate([labeled[0, :], labeled[-1, :], labeled[:, 0], labeled[:, -1]])
        )
        border_labels = border_labels[border_labels > 0]
        vis = np.isin(labeled, border_labels)
    except ImportError:
        vis = np.zeros((h, w), dtype=bool)
        dq: deque[tuple[int, int]] = deque()

        for x in range(w):
            for y in (0, h - 1):
                if white[y, x] and not vis[y, x]:
                    vis[y, x] = True
                    dq.append((y, x))
        for y in range(h):
            for x in (0, w - 1):
                if white[y, x] and not vis[y, x]:
                    vis[y, x] = True
                    dq.append((y, x))

        while dq:
            y, x = dq.popleft()
            if y + 1 < h and white[y + 1, x] and not vis[y + 1, x]:
                vis[y + 1, x] = True
                dq.append((y + 1, x))
            if y - 1 >= 0 and white[y - 1, x] and not vis[y - 1, x]:
                vis[y - 1, x] = True
                dq.append((y - 1, x))
            if x + 1 < w and white[y, x + 1] and not vis[y, x + 1]:
                vis[y, x + 1] = True
                dq.append((y, x + 1))
            if x - 1 >= 0 and white[y, x - 1] and not vis[y, x - 1]:
                vis[y, x - 1] = True
                dq.append((y, x - 1))

    alpha = np.where(vis, 0, 255).astype(np.uint8)
    aimg = Image.fromarray(alpha).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(0.8))
    out = img.convert("RGBA")
    out.putalpha(aimg)
    return out


def clear_big_white_components(
    img: Image.Image,
    min_area: int = 1200,
    protect_box: Optional[Sequence[int]] = None,
) -> Image.Image:
    """Remove large interior white pockets (e.g. between arm and body) while protecting eyes/teeth."""
    arr = np.asarray(img).copy()
    rgb = arr[:, :, :3].astype(np.int16)
    white = (rgb[:, :, 0] > 232) & (rgb[:, :, 1] > 230) & (rgb[:, :, 2] > 222) & (arr[:, :, 3] > 0)
    h, w = white.shape
    seen = np.zeros((h, w), dtype=bool)
    ys, xs = np.nonzero(white)

    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        comp: list[tuple[int, int]] = []
        dq: deque[tuple[int, int]] = deque([(y0, x0)])
        seen[y0, x0] = True
        while dq:
            y, x = dq.popleft()
            comp.append((y, x))
            if y + 1 < h and white[y + 1, x] and not seen[y + 1, x]:
                seen[y + 1, x] = True
                dq.append((y + 1, x))
            if y - 1 >= 0 and white[y - 1, x] and not seen[y - 1, x]:
                seen[y - 1, x] = True
                dq.append((y - 1, x))
            if x + 1 < w and white[y, x + 1] and not seen[y, x + 1]:
                seen[y, x + 1] = True
                dq.append((y, x + 1))
            if x - 1 >= 0 and white[y, x - 1] and not seen[y, x - 1]:
                seen[y, x - 1] = True
                dq.append((y, x - 1))

        if len(comp) >= min_area:
            cy = sum(p[0] for p in comp) / len(comp)
            cx = sum(p[1] for p in comp) / len(comp)
            if protect_box and protect_box[0] <= cx <= protect_box[2] and protect_box[1] <= cy <= protect_box[3]:
                continue
            for py, px in comp:
                arr[py, px, 3] = 0
    return Image.fromarray(arr, "RGBA")


def load_char(
    root: Path,
    base_file: str,
    variant_files: Iterable[Tuple[str, str]] = (),
) -> dict:
    """Load base character and aligned variants, cropping all to the base alpha bounding box."""
    base_path = root / base_file
    if not base_path.is_file():
        raise FileNotFoundError(f"Character base image not found: {base_path}")
    with Image.open(base_path) as base_im:
        base_size = base_im.size
        base = remove_white(base_im)
    bbox = base.split()[3].point(lambda p: 255 if p > 20 else 0).getbbox()
    out: dict = {"base": base.crop(bbox), "bbox": bbox}
    for name, vf in variant_files:
        vp = root / vf
        if not vp.is_file():
            raise FileNotFoundError(f"Character variant '{name}' image not found: {vp}")
        with Image.open(vp) as v_im:
            if v_im.size != base_size:
                raise ValueError(
                    f"Variant '{name}' size {v_im.size} does not match base size {base_size} ({vf})"
                )
            v = remove_white(v_im)
        out[name] = v.crop(bbox)
    return out


def poly_part(img: Image.Image, poly: Sequence[Tuple[float, float]], feather: float = 0.6) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).polygon(list(poly), fill=255)
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    a = np.asarray(img.split()[3]).astype(np.int32)
    mm = np.asarray(m).astype(np.int32)
    out = img.copy()
    out.putalpha(Image.fromarray((a * mm // 255).astype(np.uint8)))
    return out


def rect_part(img: Image.Image, y_split: int, feather: float = 6) -> Image.Image:
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rectangle([0, 0, img.size[0], y_split], fill=255)
    if feather:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    a = np.asarray(img.split()[3]).astype(np.int32)
    mm = np.asarray(m).astype(np.int32)
    out = img.copy()
    out.putalpha(Image.fromarray((a * mm // 255).astype(np.uint8)))
    return out


def split_limb_at_joint(
    limb_img: Image.Image,
    joint_pivot: Tuple[float, float],
    overlap: int = 16,
    feather: float = 2.5,
    cap_radius: Optional[int] = None,
) -> Tuple[Image.Image, Image.Image, Image.Image]:
    """Split a limb image into (upper, lower, joint_cap) around `joint_pivot`.

    The `joint_cap` (gol tukda) sits over the joint pivot when bending to hide any seam or gap.
    """
    w, h = limb_img.size
    jx, jy = joint_pivot
    r = max(overlap, 14)

    upper_mask = Image.new("L", (w, h), 0)
    ud = ImageDraw.Draw(upper_mask)
    ud.rectangle([0, 0, w, int(jy)], fill=255)
    ud.ellipse([jx - r * 3.0, jy - r, jx + r * 3.0, jy + r], fill=255)
    if feather:
        upper_mask = upper_mask.filter(ImageFilter.GaussianBlur(feather))

    lower_mask = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(lower_mask)
    ld.rectangle([0, int(jy + 3), w, h], fill=255)
    ld.ellipse([jx - r * 2.2, jy - r, jx + r * 2.2, jy + r], fill=255)
    if feather:
        lower_mask = lower_mask.filter(ImageFilter.GaussianBlur(feather))

    cr = cap_radius or max(18, int(r * 1.4))
    cap_mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(cap_mask).ellipse([jx - cr, jy - cr, jx + cr, jy + cr], fill=255)
    cap_mask = cap_mask.filter(ImageFilter.GaussianBlur(max(1.5, feather)))

    base_alpha = np.asarray(limb_img.split()[3]).astype(np.int32)

    upper = limb_img.copy()
    upper.putalpha(Image.fromarray((base_alpha * np.asarray(upper_mask).astype(np.int32) // 255).astype(np.uint8)))

    lower = limb_img.copy()
    lower.putalpha(Image.fromarray((base_alpha * np.asarray(lower_mask).astype(np.int32) // 255).astype(np.uint8)))

    cap = limb_img.copy()
    cap.putalpha(Image.fromarray((base_alpha * np.asarray(cap_mask).astype(np.int32) // 255).astype(np.uint8)))
    return upper, lower, cap


def split_leg_with_knee(
    leg_img: Image.Image,
    knee_pivot: Tuple[float, float],
    overlap: int = 16,
    feather: float = 3.0,
) -> Tuple[Image.Image, Image.Image]:
    """Backwards-compatible wrapper returning (thigh, calf) from split_limb_at_joint."""
    thigh, calf, _ = split_limb_at_joint(leg_img, knee_pivot, overlap=overlap, feather=feather)
    return thigh, calf


def patch(
    dst: Image.Image,
    src: Image.Image,
    box: Sequence[int],
    feather: float = 14,
) -> Image.Image:
    x0, y0, x1, y1 = box
    m = Image.new("L", dst.size, 0)
    ImageDraw.Draw(m).ellipse([x0, y0, x1, y1], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(feather))
    out = dst.copy()
    out.paste(src, (0, 0), m)
    return out


def rot(layer: Image.Image, angle: float, pivot: Tuple[float, float]) -> Image.Image:
    return layer.rotate(angle, resample=Image.Resampling.BICUBIC, center=pivot)


def rot_safe(
    layer: Image.Image,
    angle: float,
    pivot: Tuple[float, float],
) -> Tuple[Image.Image, Tuple[int, int]]:
    """Rotate `layer` with expand=True (preventing edge clipping) and return (img, paste_offset)."""
    import math

    w, h = layer.size
    if abs(angle) < 1e-3:
        return layer, (0, 0)
    r = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    nw, nh = r.size
    rad = math.radians(angle)
    dx, dy = pivot[0] - w / 2.0, pivot[1] - h / 2.0
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    dxr = dx * cos_a + dy * sin_a
    dyr = -dx * sin_a + dy * cos_a
    new_pivot_x = nw / 2.0 + dxr
    new_pivot_y = nh / 2.0 + dyr
    return r, (round(pivot[0] - new_pivot_x), round(pivot[1] - new_pivot_y))


def darken(img: Image.Image, factor: float = 0.82) -> Image.Image:
    arr = np.asarray(img).copy()
    arr[:, :, :3] = (arr[:, :, :3].astype(np.float32) * factor).astype(np.uint8)
    return Image.fromarray(arr)


def scaled(img: Image.Image, height: int) -> Tuple[Image.Image, float]:
    s = height / img.size[1]
    return img.resize((max(1, int(img.size[0] * s)), height), Image.Resampling.LANCZOS), s


def subtract_alpha(base: Image.Image, part: Image.Image) -> Image.Image:
    a = np.asarray(base.split()[3]).astype(np.int32)
    pa = np.asarray(part.split()[3]).astype(np.int32)
    out = base.copy()
    out.putalpha(Image.fromarray(np.clip(a - pa, 0, 255).astype(np.uint8)))
    return out


class AssetBaker:
    """Manages fast pre-baked RGBA cutouts in assets_baked/ to skip runtime BFS white keying."""

    def __init__(self, root: Path, baked_dir: Optional[Path] = None) -> None:
        self.root = root
        self.baked_dir = baked_dir or (root / "assets_baked")
        self.manifest_path = self.baked_dir / "manifest.json"

    def _source_signature(self, rel_files: Sequence[str]) -> dict:
        sig = {"version": BAKE_VERSION, "files": {}}
        for rf in sorted(set(rel_files)):
            p = self.root / rf
            if p.is_file():
                st = p.stat()
                sig["files"][rf] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        return sig

    def is_fresh(self, rel_files: Sequence[str], required_outputs: Sequence[str]) -> bool:
        if not self.manifest_path.is_file():
            return False
        try:
            current = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if current != self._source_signature(rel_files):
            return False
        return all((self.baked_dir / out).is_file() for out in required_outputs)

    def save_image(self, rel_name: str, img: Image.Image) -> Path:
        self.baked_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.baked_dir / rel_name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, format="PNG", optimize=False)
        return out_path

    def load_image(self, rel_name: str) -> Image.Image:
        with Image.open(self.baked_dir / rel_name) as im:
            return im.convert("RGBA")

    def save_meta(self, rel_name: str, data: dict) -> Path:
        self.baked_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.baked_dir / rel_name
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return out_path

    def load_meta(self, rel_name: str) -> dict:
        return json.loads((self.baked_dir / rel_name).read_text(encoding="utf-8"))

    def commit_manifest(self, rel_files: Sequence[str]) -> None:
        self.baked_dir.mkdir(parents=True, exist_ok=True)
        sig = self._source_signature(rel_files)
        self.manifest_path.write_text(json.dumps(sig, indent=2), encoding="utf-8")
