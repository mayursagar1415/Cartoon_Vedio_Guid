"""Scene configuration loader and strict validation."""

from __future__ import annotations

import json
from pathlib import Path
import re


_ASS_TIME_RE = re.compile(r"^Dialogue:\s*\d+,(\d+:\d{2}:\d{2}\.\d{2}),(\d+:\d{2}:\d{2}\.\d{2}),")


def parse_ass_time(ts: str) -> float:
    h, m, s = ts.split(":")
    return int(h) * 3600.0 + int(m) * 60.0 + float(s)


def load_and_validate_scene(root: Path, scene_path: Path) -> dict:
    """Load scene JSON and validate required assets, numeric bounds, and subtitle timing."""
    if not scene_path.is_file():
        raise FileNotFoundError(f"Scene config not found: {scene_path}")

    cfg = json.loads(scene_path.read_text(encoding="utf-8"))

    fps = int(cfg.get("fps", 25))
    width = int(cfg.get("width", 1280))
    height = int(cfg.get("height", 720))
    duration = float(cfg.get("duration", 10.7))
    if fps <= 0 or width <= 0 or height <= 0 or duration <= 0:
        raise ValueError(f"Invalid scene dimensions/timing: {width}x{height} @ {fps}fps, {duration}s")

    bg_rel = cfg.get("background")
    if not bg_rel or not (root / bg_rel).is_file():
        raise FileNotFoundError(f"Scene asset 'background' not found: {root / (bg_rel or '')}")

    audio = cfg.get("audio", {})
    voice_start = float(audio.get("voice_start", 0.0))
    if voice_start < 0 or voice_start > duration:
        raise ValueError(f"audio.voice_start ({voice_start}s) must be within [0, {duration}s]")

    for key in ("voice", "bgm", "subtitles"):
        rel = audio.get(key)
        if rel and not (root / rel).is_file():
            raise FileNotFoundError(f"Scene asset 'audio.{key}' not found: {root / rel}")

    ass_rel = audio.get("subtitles")
    if ass_rel:
        ass_path = root / ass_rel
        base_start = float(audio.get("subtitles_base_start", voice_start))
        shift = voice_start - base_start
        for line in ass_path.read_text(encoding="utf-8").splitlines():
            m = _ASS_TIME_RE.match(line)
            if m:
                end_t = parse_ass_time(m.group(2)) + shift
                if end_t > duration + 0.05:
                    raise ValueError(
                        f"Subtitle line ends at {end_t:.2f}s, exceeding scene duration {duration:.2f}s"
                    )

    return cfg
