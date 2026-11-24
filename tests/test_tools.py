"""Tests for asset-prep helpers, voice/subtitle automation, and multi-shot story compiler."""

import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from flat_puppet.core.config import load_and_validate_scene
from flat_puppet.tools.puppet_prep import save_probe_grid
from flat_puppet.tools.story_compiler import compile_story_to_scenes, stride_matched_walk_cps
from flat_puppet.tools.voice_and_subs import wav_duration, write_ass_file, write_parrot_chirp_wav


ROOT = Path(__file__).resolve().parent.parent


class TestToolsAndStoryCompiler(unittest.TestCase):
    def test_stride_matched_walk_speed_bounds(self) -> None:
        cps = stride_matched_walk_cps(-55, 315, 3.35)
        self.assertGreaterEqual(cps, 0.70)
        self.assertLessEqual(cps, 0.90)
        self.assertEqual(stride_matched_walk_cps(0, 1000, 1.0), 1.05)

    def test_probe_grid_and_chirp_and_ass_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            src = p / "dummy.png"
            Image.new("RGB", (200, 200), (255, 255, 255)).save(src)
            probe_out = save_probe_grid(src, p / "probe.png", step_px=50)
            self.assertTrue(probe_out.is_file())

            chirp = p / "chirp.wav"
            dur = write_parrot_chirp_wav(chirp)
            self.assertAlmostEqual(dur, 0.32, places=2)
            self.assertAlmostEqual(wav_duration(chirp), 0.32, places=2)

            ass_p = write_ass_file([(1.0, 3.2, "Bansi", "नमस्ते!")], p / "sub.ass", {"Bansi": "&H0066E0FF"})
            txt = ass_p.read_text(encoding="utf-8")
            self.assertIn("Dialogue: 0,0:00:01.00,0:00:03.20,Bansi", txt)

    def test_mitthu_story_compiles_with_cached_tts(self) -> None:
        story_path = ROOT / "configs" / "stories" / "mitthu_ka_hissa.json"
        self.assertTrue(story_path.is_file())
        story_data = json.loads(story_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "compiled"
            # Seed cached TTS WAVs matching story hash keys so this test stays 100% offline & fast
            import hashlib
            tts_cache = work / "tts_cache"
            tts_cache.mkdir(parents=True, exist_ok=True)
            cast = story_data["cast"]
            for line in story_data["shots"][0]["lines"]:
                sp = cast["hero"] if line["speaker"] == "hero" else cast["partner"]
                k = f"{sp['tts_voice']}|{sp['tts_rate']}|{sp['tts_pitch']}|{line['text']}".encode("utf-8")
                h = hashlib.sha1(k).hexdigest()[:12]
                write_parrot_chirp_wav(tts_cache / f"{h}.wav")

            _, scenes = compile_story_to_scenes(ROOT, story_path, work_dir=work)
            self.assertEqual(len(scenes), 1)
            validated = load_and_validate_scene(ROOT, scenes[0])
            self.assertGreater(validated["duration"], 4.0)
            self.assertEqual(validated["characters"]["gopal"]["leg_mode"], "sprite8")
