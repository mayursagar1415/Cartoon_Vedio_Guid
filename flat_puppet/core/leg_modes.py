"""Alternative leg animation & rendering modes for side-by-side comparison.

Modes:
  - 'mesh'    (Option 1): 3-bone NumPy Linear Blend Skinning on uncut leg PNG (zero cut seams).
  - 'capsule' (Option 2): Closed-outline 3-part capsule rig (Thigh + Calf + Foot + joint balls).
  - 'vector'  (Option 3): Supersampled procedural cartoon legs (skin fill + unified outer stroke).
  - 'sprite8' (Option 4): 8-keyframe heel-to-toe roll with dhoti sway and weight squash.
  - 'cut'     (Baseline): Original 2-bone split raster leg.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np
from PIL import Image, ImageDraw

from flat_puppet.core.kinematics import ease, rotate_point_pil


def compute_walk_angles(cyc: float) -> Tuple[float, float, float]:
    """Foot-locked 3-bone walk pose for u in [0, 1).

    Returns (thigh_pil_deg, knee_rel_pil_deg, foot_world_pil_deg):
      - step_amp = 18.0 deg matches Gopal's ground travel (390 px / 6.72 steps) -> zero foot slide.
      - Stance (u < 0.55): foot stays flat on ground (0 deg), gently rolling up at push-off.
      - Swing  (u >= 0.55): knee bends naturally (-28 deg) and ankle relaxes before heel-strike.
    """
    step_amp = 18.0
    if cyc < 0.55:
        u = cyc / 0.55
        thigh_ang = step_amp * (1.0 - 2.0 * u)
        # Keep knee straight until toe-off
        toe_off = max(0.0, (u - 0.80) / 0.20)
        knee_ang = -8.0 * toe_off
        # Foot stays planted flat (0 deg) through mid-stance, then heel lifts slightly at push-off
        if u < 0.12:
            # Heel strike settling flat
            foot_world = 10.0 * (1.0 - u / 0.12)
        elif u > 0.78:
            # Push-off: heel lifts (clockwise = negative PIL angle)
            foot_world = -14.0 * ease((u - 0.78) / 0.22)
        else:
            foot_world = 0.0
        return thigh_ang, knee_ang, foot_world

    v = (cyc - 0.55) / 0.45
    thigh_ang = -step_amp + 2.0 * step_amp * ease(v)
    knee_ang = -28.0 * math.sin(math.pi * v)
    # Foot trails backward during early swing, then points toes slightly up for heel-strike
    foot_world = -14.0 + 24.0 * ease(v)
    return thigh_ang, knee_ang, foot_world


def _bilinear_sample_rgba(arr: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """Vectorized bilinear RGBA sampling from source image array."""
    h, w, _ = arr.shape
    valid = (sx >= 0.0) & (sx <= w - 1.001) & (sy >= 0.0) & (sy <= h - 1.001)
    sx_c = np.clip(sx, 0.0, w - 1.001)
    sy_c = np.clip(sy, 0.0, h - 1.001)

    x0 = np.floor(sx_c).astype(np.int32)
    y0 = np.floor(sy_c).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = (sx_c - x0)[..., None]
    fy = (sy_c - y0)[..., None]

    c00 = arr[y0, x0]
    c10 = arr[y0, x1]
    c01 = arr[y1, x0]
    c11 = arr[y1, x1]

    out = (
        c00 * (1.0 - fx) * (1.0 - fy)
        + c10 * fx * (1.0 - fy)
        + c01 * (1.0 - fx) * fy
        + c11 * fx * fy
    )
    out[~valid] = 0.0
    return np.clip(out, 0, 255).astype(np.uint8)


def render_leg_mesh(
    leg_full: Image.Image,
    hip: Tuple[float, float],
    knee: Tuple[float, float],
    ankle: Tuple[float, float],
    thigh_ang: float,
    knee_rel_ang: float,
    foot_world_ang: float,
) -> Tuple[Image.Image, Tuple[int, int]]:
    """Option 1: Smooth 3-bone Linear Blend Skinning on the uncut leg PNG (zero cut seams).

    Deforms a local tight crop around the leg cleanly and returns (warped_rgba, paste_offset).
    """
    arr_full = np.asarray(leg_full)
    ys_nz, xs_nz = np.nonzero(arr_full[:, :, 3] > 5)
    if len(xs_nz) == 0:
        return leg_full, (0, 0)

    pad = 45
    x0 = max(0, int(xs_nz.min()) - pad)
    y0 = max(0, int(ys_nz.min()) - 10)
    x1 = min(leg_full.width, int(xs_nz.max()) + pad)
    y1 = min(leg_full.height, int(ys_nz.max()) + pad)

    crop_arr = arr_full[y0:y1, x0:x1].astype(np.float32)
    ch, cw, _ = crop_arr.shape

    hx, hy = hip[0] - x0, hip[1] - y0
    kx, ky = knee[0] - x0, knee[1] - y0
    ax, ay = ankle[0] - x0, ankle[1] - y0

    # Forward kinematics joint positions in cropped space
    new_knee = rotate_point_pil((kx, ky), (hx, hy), thigh_ang)
    calf_ang = thigh_ang + knee_rel_ang
    dkx, dky = new_knee[0] - kx, new_knee[1] - ky
    # Rotate ankle around knee by calf_ang, then translate by knee delta
    rot_ankle = rotate_point_pil((ax, ay), (kx, ky), calf_ang)
    new_ankle = (rot_ankle[0] + dkx, rot_ankle[1] + dky)
    dax, day = new_ankle[0] - ax, new_ankle[1] - ay

    # Destination grid
    yy, xx = np.mgrid[0:ch, 0:cw].astype(np.float32)

    # Compute smooth bone blend weights based on height relative to deformed knee & ankle
    def smoothstep_arr(edge0: float, edge1: float, val: np.ndarray) -> np.ndarray:
        t = np.clip((val - edge0) / max(edge1 - edge0, 1e-4), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    blend_k = 10.0  # smooth skinning zone around knee (+/- 10 px)
    blend_a = 6.0   # smooth skinning zone around ankle (+/- 6 px)
    w_below_knee = smoothstep_arr(new_knee[1] - blend_k, new_knee[1] + blend_k, yy)
    w_below_ankle = smoothstep_arr(new_ankle[1] - blend_a, new_ankle[1] + blend_a, yy)

    w_foot = w_below_ankle
    w_calf = w_below_knee * (1.0 - w_below_ankle)
    w_thigh = 1.0 - w_below_knee

    # Inverse transform for Thigh (inverse rotate by -thigh_ang around hip)
    rad1 = math.radians(-thigh_ang)
    c1, s1 = math.cos(rad1), math.sin(rad1)
    dx1, dy1 = xx - hx, yy - hy
    sx1 = hx + dx1 * c1 + dy1 * s1
    sy1 = hy - dx1 * s1 + dy1 * c1

    # Inverse transform for Calf (translate back to original knee, inverse rotate by -calf_ang)
    rad2 = math.radians(-calf_ang)
    c2, s2 = math.cos(rad2), math.sin(rad2)
    dx2, dy2 = xx - new_knee[0], yy - new_knee[1]
    sx2 = kx + dx2 * c2 + dy2 * s2
    sy2 = ky - dx2 * s2 + dy2 * c2

    # Inverse transform for Foot (translate back to original ankle, inverse rotate by -foot_world_ang)
    rad3 = math.radians(-foot_world_ang)
    c3, s3 = math.cos(rad3), math.sin(rad3)
    dx3, dy3 = xx - new_ankle[0], yy - new_ankle[1]
    sx3 = ax + dx3 * c3 + dy3 * s3
    sy3 = ay - dx3 * s3 + dy3 * c3

    sx = w_thigh * sx1 + w_calf * sx2 + w_foot * sx3
    sy = w_thigh * sy1 + w_calf * sy2 + w_foot * sy3

    warped = _bilinear_sample_rgba(crop_arr, sx, sy)
    return Image.fromarray(warped, "RGBA"), (x0, y0)


def _draw_tapered_capsule(
    size: Tuple[int, int],
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    r0: float,
    r1: float,
    fill_rgb: Tuple[int, int, int],
    outline_rgb: Tuple[int, int, int] = (14, 12, 10),
    stroke: float = 2.6,
    scale: int = 2,
) -> Image.Image:
    """Draw a 2x-supersampled closed-outline tapered capsule between p0 and p1."""
    w, h = size
    sw, sh = w * scale, h * scale
    canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    x0, y0 = p0[0] * scale, p0[1] * scale
    x1, y1 = p1[0] * scale, p1[1] * scale
    sr0, sr1 = r0 * scale, r1 * scale
    st = stroke * scale

    dx, dy = x1 - x0, y1 - y0
    dist = max(math.hypot(dx, dy), 1e-4)
    nx, ny = -dy / dist, dx / dist

    def _draw_body(pad: float, color: Tuple[int, int, int, int]) -> None:
        rr0 = sr0 + pad
        rr1 = sr1 + pad
        poly = [
            (x0 + nx * rr0, y0 + ny * rr0),
            (x1 + nx * rr1, y1 + ny * rr1),
            (x1 - nx * rr1, y1 - ny * rr1),
            (x0 - nx * rr0, y0 - ny * rr0),
        ]
        draw.polygon(poly, fill=color)
        draw.ellipse([x0 - rr0, y0 - rr0, x0 + rr0, y0 + rr0], fill=color)
        draw.ellipse([x1 - rr1, y1 - rr1, x1 + rr1, y1 + rr1], fill=color)

    _draw_body(st, (*outline_rgb, 255))
    _draw_body(0.0, (*fill_rgb, 255))
    return canvas.resize((w, h), Image.Resampling.LANCZOS)


def extract_closed_foot(
    leg_full: Image.Image,
    ankle: Tuple[float, float],
    fill_rgb: Tuple[int, int, int],
    outline_rgb: Tuple[int, int, int] = (14, 12, 10),
) -> Image.Image:
    """Extract Gopal's drawn foot below ankle with a clean rounded ankle-ball cap."""
    w, h = leg_full.size
    ax, ay = ankle
    arr = np.asarray(leg_full).copy()
    yy, _ = np.mgrid[0:h, 0:w]
    # Keep foot pixels below ankle
    arr[yy < ay - 2, 3] = 0
    foot_img = Image.fromarray(arr, "RGBA")

    # Add rounded closed ankle cap on top so ankle bends cleanly without open edge
    cap = _draw_tapered_capsule(
        (w, h),
        (ax, ay),
        (ax, ay + 6),
        r0=10.5,
        r1=10.0,
        fill_rgb=fill_rgb,
        outline_rgb=outline_rgb,
        stroke=2.2,
    )
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(cap, (0, 0), cap)
    out.paste(foot_img, (0, 0), foot_img)
    return out


class CapsuleLegRig:
    """Option 2: Pre-built closed-outline 3-part capsule rig (Thigh + Calf + Foot) like Ramu sheet."""

    def __init__(
        self,
        leg_full: Image.Image,
        hip: Tuple[float, float],
        knee: Tuple[float, float],
        ankle: Tuple[float, float],
        is_far: bool = False,
    ) -> None:
        self.hip = hip
        self.knee = knee
        self.ankle = ankle
        fill = (194, 144, 105) if is_far else (228, 170, 124)
        size = leg_full.size
        self.thigh = _draw_tapered_capsule(size, hip, knee, r0=17.5, r1=12.5, fill_rgb=fill)
        self.calf = _draw_tapered_capsule(size, knee, ankle, r0=12.0, r1=9.5, fill_rgb=fill)
        self.foot = extract_closed_foot(leg_full, ankle, fill_rgb=fill)

    def render(
        self,
        canvas: Image.Image,
        rot_fn,
        pos_x: int,
        pos_y: int,
        thigh_ang: float,
        knee_rel_ang: float,
        foot_world_ang: float,
    ) -> None:
        thigh_r, (tx, ty) = rot_fn(self.thigh, thigh_ang, self.hip)
        new_knee = rotate_point_pil(self.knee, self.hip, thigh_ang)

        calf_ang = thigh_ang + knee_rel_ang
        calf_r, (cx, cy) = rot_fn(self.calf, calf_ang, self.knee)
        dkx = new_knee[0] - self.knee[0]
        dky = new_knee[1] - self.knee[1]

        rot_ankle = rotate_point_pil(self.ankle, self.knee, calf_ang)
        new_ankle = (rot_ankle[0] + dkx, rot_ankle[1] + dky)
        dax = new_ankle[0] - self.ankle[0]
        day = new_ankle[1] - self.ankle[1]

        foot_r, (fx, fy) = rot_fn(self.foot, foot_world_ang, self.ankle)

        canvas.paste(foot_r, (int(round(pos_x + dax)) + fx, int(round(pos_y + day)) + fy), foot_r)
        canvas.paste(calf_r, (int(round(pos_x + dkx)) + cx, int(round(pos_y + dky)) + cy), calf_r)
        canvas.paste(thigh_r, (pos_x + tx, pos_y + ty), thigh_r)
