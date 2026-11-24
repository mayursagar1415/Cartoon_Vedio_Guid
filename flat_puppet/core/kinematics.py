"""Procedural animation, 2-bone analytical IK solver, easing curves, and blinking."""

from __future__ import annotations

import math
import random
from typing import Iterable, List, Sequence, Tuple


def ease(u: float) -> float:
    """Smoothstep easing for u in [0, 1]."""
    u = max(0.0, min(1.0, u))
    return u * u * (3.0 - 2.0 * u)


def apply_easing(u: float, mode: str = "smoothstep") -> float:
    u = max(0.0, min(1.0, u))
    if mode == "linear":
        return u
    if mode == "ease_in_out":
        return 0.5 * (1.0 - math.cos(math.pi * u))
    if mode == "ease_in_out_cubic":
        return 4.0 * u * u * u if u < 0.5 else 1.0 - pow(-2.0 * u + 2.0, 3) / 2.0
    if mode == "ease_out":
        return 1.0 - (1.0 - u) ** 3
    return ease(u)


def rotate_point_pil(
    pt: Tuple[float, float],
    pivot: Tuple[float, float],
    angle_deg: float,
) -> Tuple[float, float]:
    """Compute new coordinates of `pt` after PIL Image.rotate(angle_deg, center=pivot)."""
    rad = math.radians(angle_deg)
    dx = pt[0] - pivot[0]
    dy = pt[1] - pivot[1]
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    return (
        pivot[0] + dx * cos_a + dy * sin_a,
        pivot[1] - dx * sin_a + dy * cos_a,
    )


def solve_2bone_ik(
    root: Tuple[float, float],
    mid_rest: Tuple[float, float],
    end_rest: Tuple[float, float],
    target: Tuple[float, float],
    bend_sign: int = 1,
) -> Tuple[float, float]:
    """Analytical 2-bone Inverse Kinematics solver using the Law of Cosines.

    Given rest pose (root -> mid_rest -> end_rest) and desired `target` position for the end effector,
    returns (upper_angle_pil_deg, lower_rel_angle_pil_deg) ready for PIL Image.rotate().
    `bend_sign`: +1 bends elbow/knee clockwise of the root->target line; -1 bends counter-clockwise.
    """
    v1x, v1y = mid_rest[0] - root[0], mid_rest[1] - root[1]
    v2x, v2y = end_rest[0] - mid_rest[0], end_rest[1] - mid_rest[1]
    l1 = max(math.hypot(v1x, v1y), 1e-3)
    l2 = max(math.hypot(v2x, v2y), 1e-3)

    rest_phi1 = math.atan2(v1y, v1x)
    rest_phi2 = math.atan2(v2y, v2x)

    dx = target[0] - root[0]
    dy = target[1] - root[1]
    raw_dist = math.hypot(dx, dy)
    min_d = abs(l1 - l2) + 1e-2
    max_d = (l1 + l2) - 1e-2
    dist = max(min_d, min(max_d, raw_dist))

    base_ang = math.atan2(dy, dx)
    cos_a = max(-1.0, min(1.0, (l1 * l1 + dist * dist - l2 * l2) / (2.0 * l1 * dist)))
    a = math.acos(cos_a)

    phi1 = base_ang + (1 if bend_sign >= 0 else -1) * a
    elbow_x = root[0] + l1 * math.cos(phi1)
    elbow_y = root[1] + l1 * math.sin(phi1)

    # Point lower bone from solved elbow toward target (or clamped reachable point along target ray)
    tx_clamped = root[0] + dist * math.cos(base_ang)
    ty_clamped = root[1] + dist * math.sin(base_ang)
    phi2 = math.atan2(ty_clamped - elbow_y, tx_clamped - elbow_x)

    # Convert screen-space angle delta (CW positive) to PIL rotate angle (CCW positive)
    def wrap_deg(rad: float) -> float:
        d = math.degrees(rad)
        while d > 180.0:
            d -= 360.0
        while d < -180.0:
            d += 360.0
        return d

    upper_pil = -wrap_deg(phi1 - rest_phi1)
    lower_total_pil = -wrap_deg(phi2 - rest_phi2)
    lower_rel_pil = lower_total_pil - upper_pil
    return upper_pil, lower_rel_pil


def articulated_leg_pose(
    u: float,
    step_amp: float = 15.0,
    knee_bend: float = 14.0,
    lift_amp: float = 11.0,
) -> Tuple[float, float, float]:
    """2-bone walk cycle fallback for one leg, u in [0, 1)."""
    if u < 0.55:
        thigh_ang = step_amp * (1.0 - 2.0 * (u / 0.55))
        toe_off = max(0.0, (u - 0.45) / 0.10)
        return thigh_ang, -6.0 * toe_off, 0.0

    v = (u - 0.55) / 0.45
    thigh_ang = -step_amp + 2.0 * step_amp * ease(v)
    knee_ang = -knee_bend * math.sin(math.pi * v)
    lift = lift_amp * math.sin(math.pi * v)
    return thigh_ang, knee_ang, lift


def gesture_angle(t: float, windows: Sequence[Tuple[float, float]], max_angle: float = 28.0) -> float:
    """Smooth arm raise during dialogue emphasis windows."""
    ang = 0.0
    for a, b in windows:
        if a <= t <= b and b > a:
            u = (t - a) / (b - a)
            val = max_angle * math.sin(math.pi * ease(min(u * 1.15, 1.0))) if u < 1.0 else 0.0
            ang = max(ang, val)
    return ang


def turn_transition_scale(t: float, switch_t: float, half_window: float = 0.14) -> float:
    """Horizontal squash scale around a side-to-front view switch for smooth turn illusion."""
    dt = abs(t - switch_t)
    if dt >= half_window:
        return 1.0
    u = ease(dt / half_window)
    return 0.38 + 0.62 * u


def procedural_blinks(
    duration: float,
    seed: int = 42,
    min_gap: float = 2.0,
    max_gap: float = 3.8,
    blink_dur: float = 0.12,
) -> List[Tuple[float, float]]:
    """Generate deterministic natural blink intervals across scene duration."""
    rng = random.Random(seed)
    blinks: List[Tuple[float, float]] = []
    t = rng.uniform(0.9, 1.8)
    while t + blink_dur < duration:
        blinks.append((round(t, 3), round(t + blink_dur, 3)))
        if rng.random() < 0.18 and t + 0.32 < duration:
            t2 = t + 0.20
            blinks.append((round(t2, 3), round(t2 + blink_dur, 3)))
            t = t2 + rng.uniform(min_gap, max_gap)
        else:
            t += rng.uniform(min_gap, max_gap)
    return blinks


def is_blinking(t: float, table: Iterable[Tuple[float, float]]) -> bool:
    return any(a <= t <= b for a, b in table)


def breathing_offset(t: float, freq: float = 0.3, amp: float = 1.0) -> float:
    return math.sin(t * 2.0 * math.pi * freq) * amp
