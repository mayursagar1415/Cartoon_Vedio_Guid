"""Reusable Action Library loader and keyframe curve evaluator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

from flat_puppet.core.kinematics import apply_easing


class ActionClip:
    """Evaluates a named keyframed action clip from configs/actions/*.json."""

    def __init__(self, data: dict) -> None:
        self.name: str = data["name"]
        self.duration: float = float(data.get("duration", 1.0))
        self.loop: bool = bool(data.get("loop", False))
        self.tracks: Dict[str, Tuple[str, List[Tuple[float, float]]]] = {}
        for track_name, track_cfg in data.get("tracks", {}).items():
            easing = track_cfg.get("easing", "smoothstep")
            kfs = sorted((float(u), float(val)) for u, val in track_cfg["keyframes"])
            self.tracks[track_name] = (easing, kfs)

    def eval_normalized(self, track_name: str, u: float, default: float = 0.0) -> float:
        """Evaluate track at normalized progress u in [0, 1]."""
        if track_name not in self.tracks:
            return default
        easing, kfs = self.tracks[track_name]
        if not kfs:
            return default
        if self.loop:
            u = u % 1.0
        else:
            u = max(0.0, min(1.0, u))

        if u <= kfs[0][0]:
            return kfs[0][1]
        if u >= kfs[-1][0]:
            return kfs[-1][1]

        for idx in range(len(kfs) - 1):
            u0, v0 = kfs[idx]
            u1, v1 = kfs[idx + 1]
            if u0 <= u <= u1:
                span = max(u1 - u0, 1e-6)
                alpha = apply_easing((u - u0) / span, easing)
                return v0 + (v1 - v0) * alpha
        return kfs[-1][1]

    def eval_time(self, track_name: str, local_t: float, default: float = 0.0) -> float:
        if self.duration <= 0:
            return default
        return self.eval_normalized(track_name, local_t / self.duration, default=default)


class ActionLibrary:
    """Registry of reusable actions stored in configs/actions/*.json."""

    def __init__(self, actions_dir: Path) -> None:
        self.clips: Dict[str, ActionClip] = {}
        if actions_dir.is_dir():
            for p in sorted(actions_dir.glob("*.json")):
                data = json.loads(p.read_text(encoding="utf-8"))
                clip = ActionClip(data)
                self.clips[clip.name] = clip

    def get(self, name: str) -> ActionClip:
        if name not in self.clips:
            raise KeyError(f"Action '{name}' not found in ActionLibrary.")
        return self.clips[name]

    def has(self, name: str) -> bool:
        return name in self.clips
