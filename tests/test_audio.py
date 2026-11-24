"""Tests for audio envelope extraction, adaptive gain, and lip-sync hysteresis."""

import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from flat_puppet.core.audio import AudioAnalyzer


def _write_sine_wav(path: Path, freq: float, duration: float, amp: float, sr: int = 22050) -> None:
    n = int(sr * duration)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            val = int(max(-1.0, min(1.0, amp * math.sin(2.0 * math.pi * freq * i / sr))) * 32767)
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))


class TestAudioAnalyzer(unittest.TestCase):
    def test_quiet_take_drives_mouth_with_adaptive_gain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wav_path = Path(td) / "quiet.wav"
            _write_sine_wav(wav_path, freq=220.0, duration=1.5, amp=0.06)
            analyzer = AudioAnalyzer(wav_path, start_time=0.5, fps=25, gain_ref="auto")
            self.assertEqual(analyzer.mouth_level(0.1), 0)
            self.assertGreater(analyzer.envelope(1.0), 0.5)
            self.assertGreaterEqual(analyzer.mouth_level(1.0), 1)

    def test_missing_audio_returns_silence_without_crashing(self) -> None:
        analyzer = AudioAnalyzer(Path("nonexistent_audio.wav"), start_time=0.0, fps=25)
        self.assertEqual(analyzer.envelope(1.0), 0.0)
        self.assertEqual(analyzer.mouth_level(1.0), 0)
