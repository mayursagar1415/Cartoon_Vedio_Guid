"""Option 4 ('sprite8') 8-pose cartoon studio walk cycle and unified-outline procedural leg renderer."""

from __future__ import annotations

import math
from typing import Tuple

from PIL import Image, ImageDraw

from flat_puppet.core.kinematics import ease, rotate_point_pil


def compute_walk_angles(cyc: float) -> Tuple[float, float, float]:
    """Foot-locked 3-bone walk pose for u in [0, 1) (used when leg_mode='vector').

    Returns (thigh_pil_deg, knee_rel_pil_deg, foot_world_pil_deg).
    """
    step_amp = 18.0
    if cyc < 0.55:
        u = cyc / 0.55
        thigh_ang = step_amp * (1.0 - 2.0 * u)
        toe_off = max(0.0, (u - 0.80) / 0.20)
        knee_ang = -8.0 * toe_off
        if u < 0.12:
            foot_world = 10.0 * (1.0 - u / 0.12)
        elif u > 0.78:
            foot_world = -14.0 * ease((u - 0.78) / 0.22)
        else:
            foot_world = 0.0
        return thigh_ang, knee_ang, foot_world

    v = (cyc - 0.55) / 0.45
    thigh_ang = -step_amp + 2.0 * step_amp * ease(v)
    knee_ang = -28.0 * math.sin(math.pi * v)
    foot_world = -14.0 + 24.0 * ease(v)
    return thigh_ang, knee_ang, foot_world


# Option 4: 8-Pose Studio Walk Strip (Contact, Down, Passing, High-Point, Toe-off, Swing x 3)
# Each entry: (cyc_pos, thigh_deg, knee_rel_deg, foot_world_deg, body_bob_px, dhoti_tilt_deg)
_SPRITE8_KEYFRAMES = [
    (0.000, +18.0,  -2.0, +12.0, -1.0, 0.0),   # 0: Contact (heel strike)
    (0.125, +10.0,  -3.0,   0.0, -4.0, 0.0),   # 1: Down (weight squash, foot flat on ground)
    (0.275,   0.0,   0.0,   0.0, +1.0, 0.0),   # 2: Passing (straight planted leg under hip)
    (0.450, -14.0,   0.0,   0.0, +0.5, 0.0),   # 3: High-Point (heel still anchored, body forward)
    (0.550, -18.0, -12.0, -18.0, -1.0, 0.0),   # 4: Toe-off (heel lifts to push off)
    (0.700,  -2.0, -30.0, -15.0, -3.5, 0.0),   # 5: Swing passing (knee folds cleanly backward)
    (0.840, +12.0, -16.0,  -2.0, +1.5, 0.0),   # 6: Swing reach (shin extends forward)
    (0.940, +17.0,  -4.0, +10.0, +0.5, 0.0),   # 7: Pre-contact (ready for heel strike)
]


def compute_sprite8_pose(cyc: float) -> Tuple[float, float, float, float, float]:
    """Option 4: Interpolate 8-pose cartoon walk cycle with weight bounce and heel-to-toe roll.

    Returns (thigh_deg, knee_rel_deg, foot_world_deg, body_bob_px, dhoti_tilt_deg).
    """
    u = cyc % 1.0
    kfs = _SPRITE8_KEYFRAMES
    n = len(kfs)
    for idx in range(n):
        u0 = kfs[idx][0]
        u1 = kfs[(idx + 1) % n][0] if idx + 1 < n else 1.0
        if u0 <= u <= u1:
            a = ease((u - u0) / max(u1 - u0, 1e-6))
            p0 = kfs[idx]
            p1 = kfs[(idx + 1) % n]
            return (
                p0[1] + (p1[1] - p0[1]) * a,
                p0[2] + (p1[2] - p0[2]) * a,
                p0[3] + (p1[3] - p0[3]) * a,
                p0[4] + (p1[4] - p0[4]) * a,
                p0[5] + (p1[5] - p0[5]) * a,
            )
    p0 = kfs[0]
    return p0[1], p0[2], p0[3], p0[4], p0[5]


def render_leg_vector(
    size: Tuple[int, int],
    hip: Tuple[float, float],
    knee: Tuple[float, float],
    ankle: Tuple[float, float],
    thigh_ang: float,
    knee_rel_ang: float,
    foot_world_ang: float,
    is_far: bool = False,
    skin_rgb: Tuple[int, int, int] = (228, 170, 124),
) -> Image.Image:
    """Unified-outline 2x-supersampled procedural cartoon leg matching bare-ankle proportions."""
    w, h = size
    scale = 2
    sw, sh = w * scale, h * scale
    canvas = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    new_knee = rotate_point_pil(knee, hip, thigh_ang)
    calf_ang = thigh_ang + knee_rel_ang
    dkx, dky = new_knee[0] - knee[0], new_knee[1] - knee[1]
    rot_ankle = rotate_point_pil(ankle, knee, calf_ang)
    new_ankle = (rot_ankle[0] + dkx, rot_ankle[1] + dky)

    heel_rel = (-10.0, 13.0)
    toe_rel = (36.0, 14.5)
    instep_rel = (14.0, 4.5)
    new_heel = rotate_point_pil((new_ankle[0] + heel_rel[0], new_ankle[1] + heel_rel[1]), new_ankle, foot_world_ang)
    new_toe = rotate_point_pil((new_ankle[0] + toe_rel[0], new_ankle[1] + toe_rel[1]), new_ankle, foot_world_ang)
    new_instep = rotate_point_pil((new_ankle[0] + instep_rel[0], new_ankle[1] + instep_rel[1]), new_ankle, foot_world_ang)

    def sc(pt: Tuple[float, float]) -> Tuple[float, float]:
        return (pt[0] * scale, pt[1] * scale)

    p_hip = sc(hip)
    p_knee = sc(new_knee)
    p_ankle = sc(new_ankle)
    p_heel = sc(new_heel)
    p_toe = sc(new_toe)
    p_instep = sc(new_instep)

    r_hip = 15.5 * scale
    r_knee = 10.6 * scale
    r_ankle = 6.6 * scale
    r_heel = 5.2 * scale
    r_toe = 3.6 * scale
    stroke = 2.1 * scale

    if is_far:
        fill_rgb = (
            max(0, int(round(skin_rgb[0] * 0.85))),
            max(0, int(round(skin_rgb[1] * 0.85))),
            max(0, int(round(skin_rgb[2] * 0.85))),
            255,
        )
    else:
        fill_rgb = (*skin_rgb, 255)
    ink_rgb = (14, 12, 10, 255)

    def _draw_segment(a: Tuple[float, float], b: Tuple[float, float], ra: float, rb: float, pad: float, col) -> None:
        dx, dy = b[0] - a[0], b[1] - a[1]
        d = max(math.hypot(dx, dy), 1e-4)
        nx, ny = -dy / d, dx / d
        rra, rrb = ra + pad, rb + pad
        draw.polygon(
            [
                (a[0] + nx * rra, a[1] + ny * rra),
                (b[0] + nx * rrb, b[1] + ny * rrb),
                (b[0] - nx * rrb, b[1] - ny * rrb),
                (a[0] - nx * rra, a[1] - ny * rra),
            ],
            fill=col,
        )
        draw.ellipse([a[0] - rra, a[1] - rra, a[0] + rra, a[1] + rra], fill=col)
        draw.ellipse([b[0] - rrb, b[1] - rrb, b[0] + rrb, b[1] + rrb], fill=col)

    def _draw_foot(pad: float, col) -> None:
        _draw_segment(p_ankle, p_heel, r_ankle, r_heel, pad, col)
        _draw_segment(p_heel, p_toe, r_heel, r_toe, pad, col)
        _draw_segment(p_ankle, p_instep, r_ankle * 0.85, r_toe * 1.15, pad, col)
        _draw_segment(p_instep, p_toe, r_toe * 1.15, r_toe, pad, col)

    # Pass 1: unified outer outline across Thigh + Calf + Foot
    _draw_segment(p_hip, p_knee, r_hip, r_knee, stroke, ink_rgb)
    _draw_segment(p_knee, p_ankle, r_knee, r_ankle, stroke, ink_rgb)
    _draw_foot(stroke, ink_rgb)

    # Pass 2: seamless inner fill across Thigh + Calf + Foot (zero internal seams)
    _draw_segment(p_hip, p_knee, r_hip, r_knee, 0.0, fill_rgb)
    _draw_segment(p_knee, p_ankle, r_knee, r_ankle, 0.0, fill_rgb)
    _draw_foot(0.0, fill_rgb)

    return canvas.resize((w, h), Image.Resampling.LANCZOS)
