"""Audio envelope extraction with hysteresis smoothing and optional Rhubarb viseme cues."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple
import wave

import numpy as np

from flat_puppet.utils.ffmpeg import convert_to_wav

RHUBARB_TO_LEVEL = {
    "X": 0,  # silence / rest
    "A": 0,  # closed M/B/P
    "B": 1,  # slightly open consonants
    "C": 2,  # open vowels
    "D": 2,  # wide open vowels
    "E": 1,  # rounded mid vowels
    "F": 1,  # puckered O/U
    "G": 1,  # F/V
    "H": 1,  # L
}


class AudioAnalyzer:
    """Computes lip-sync amplitude envelopes and mouth openness levels cleanly without import side-effects."""

    def __init__(
        self,
        audio_path: Optional[Path],
        start_time: float = 0.0,
        fps: int = 25,
        cache_dir: Optional[Path] = None,
        rhubarb_json: Optional[Path] = None,
        gain_ref: float | str = "auto",
    ) -> None:
        self.start_time = start_time
        self.fps = fps
        self.sr = 22050
        self.gain_ref = gain_ref
        self.pcm = np.zeros(0, dtype=np.float32)
        self.duration = 0.0
        self.cues: List[Tuple[float, float, int]] = []
        self._smoothed_env: np.ndarray = np.zeros(0, dtype=np.float32)

        if rhubarb_json and rhubarb_json.is_file():
            self._load_rhubarb(rhubarb_json)

        if audio_path and audio_path.is_file():
            wav_path = audio_path
            if audio_path.suffix.lower() != ".wav":
                target_dir = cache_dir or audio_path.parent / ".cache"
                wav_path = convert_to_wav(audio_path, target_dir / f"{audio_path.stem}.wav", sample_rate=self.sr)
            self._load_wav(wav_path)

    def _load_rhubarb(self, json_path: Path) -> None:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for cue in data.get("mouthCues", []):
            lvl = RHUBARB_TO_LEVEL.get(cue.get("value", "X"), 0)
            self.cues.append((float(cue["start"]), float(cue["end"]), lvl))

    def _load_wav(self, wav_path: Path) -> None:
        with wave.open(str(wav_path), "rb") as wf:
            self.sr = wf.getframerate()
            na = wf.getnframes()
            raw = wf.readframes(na)
            channels = wf.getnchannels()
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        self.pcm = samples
        self.duration = len(samples) / max(self.sr, 1)
        self._precompute_smoothed_envelope()

    def _precompute_smoothed_envelope(self) -> None:
        """Compute per-frame RMS envelope with attack/release smoothing to prevent mouth chatter."""
        if len(self.pcm) == 0:
            self._smoothed_env = np.zeros(0, dtype=np.float32)
            return

        total_frames = int(np.ceil(self.duration * self.fps)) + 2
        spf = self.sr / self.fps
        raw_env = np.zeros(total_frames, dtype=np.float32)

        for i in range(total_frames):
            vals = []
            for k in (i - 1, i, i + 1):
                a = int(k * spf)
                b = min(int((k + 1) * spf), len(self.pcm))
                if b > a and a >= 0:
                    vals.append(float(np.sqrt(np.mean(self.pcm[a:b] ** 2))))
            raw_env[i] = max(vals) if vals else 0.0

        if self.gain_ref == "auto":
            active = raw_env[raw_env > 0.005]
            ref = float(np.percentile(active, 90)) if len(active) else 0.24
            ref = max(0.08, ref)
        else:
            ref = max(1e-4, float(self.gain_ref))
        raw_env = np.minimum(raw_env / ref, 1.0)

        # Asymmetric attack/release smoothing (fast open, smooth close)
        smoothed = np.zeros_like(raw_env)
        prev = 0.0
        for i, val in enumerate(raw_env):
            alpha = 0.72 if val >= prev else 0.42
            prev = alpha * val + (1.0 - alpha) * prev
            smoothed[i] = prev
        self._smoothed_env = smoothed

    def envelope(self, t: float) -> float:
        lt = t - self.start_time
        if lt < 0 or lt > self.duration or len(self._smoothed_env) == 0:
            return 0.0
        idx = min(int(lt * self.fps), len(self._smoothed_env) - 1)
        return float(self._smoothed_env[idx])

    def mouth_level(self, t: float, prev_level: Optional[int] = None) -> int:
        lt = t - self.start_time
        if self.cues and 0 <= lt <= self.duration:
            for s, e, lvl in self.cues:
                if s <= lt <= e:
                    return lvl

        o = self.envelope(t)
        # Hysteresis thresholds prevent jittery rapid toggling around boundary values
        if prev_level is not None:
            if prev_level == 0:
                return 0 if o < 0.17 else (1 if o < 0.52 else 2)
            if prev_level == 1:
                return 0 if o < 0.11 else (1 if o < 0.52 else 2)
            return 0 if o < 0.11 else (1 if o < 0.43 else 2)

        return 0 if o < 0.14 else (1 if o < 0.48 else 2)
