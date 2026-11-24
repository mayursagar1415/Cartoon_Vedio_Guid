"""Tests for scene config validation and ASS subtitle timing sync."""

from pathlib import Path
import tempfile
import unittest

from flat_puppet.core.config import load_and_validate_scene, parse_ass_time
from flat_puppet.utils.ffmpeg import _format_ass_time, _shift_ass_timestamps


ROOT = Path(__file__).resolve().parent.parent


class TestConfigValidation(unittest.TestCase):
    def test_demo_scene_loads_and_validates(self) -> None:
        cfg = load_and_validate_scene(ROOT, ROOT / "configs" / "scenes" / "demo_courtyard.json")
        self.assertEqual(cfg["fps"], 25)
        self.assertGreater(cfg["duration"], 0)

    def test_missing_asset_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            bad_scene = p / "bad.json"
            bad_scene.write_text('{"background": "missing_bg.webp", "duration": 5, "fps": 25}', encoding="utf-8")
            with self.assertRaises(FileNotFoundError) as ctx:
                load_and_validate_scene(p, bad_scene)
            self.assertIn("background", str(ctx.exception))

    def test_ass_timestamp_shift(self) -> None:
        sample = "Dialogue: 0,0:00:04.40,0:00:07.50,Default,,0,0,0,,Test\n"
        shifted = _shift_ass_timestamps(sample, -1.4)
        self.assertIn("0:00:03.00,0:00:06.10", shifted)
        self.assertAlmostEqual(parse_ass_time("0:00:04.40"), 4.4)
        self.assertEqual(_format_ass_time(4.4), "0:00:04.40")
