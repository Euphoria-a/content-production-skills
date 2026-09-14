from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "build_cover.py"
SPEC = importlib.util.spec_from_file_location("travel_cover_builder", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class TravelCoverContractTests(unittest.TestCase):
    def test_chinese_episode_numbers(self):
        self.assertEqual(MODULE.chinese_number(1), "一")
        self.assertEqual(MODULE.chinese_number(10), "十")
        self.assertEqual(MODULE.chinese_number(21), "二十一")

    def test_episode_range_is_bounded(self):
        with self.assertRaises(MODULE.ConfigError):
            MODULE.chinese_number(100)

    def test_subtitle_structure_detection(self):
        self.assertEqual(MODULE.subtitle_format("山水与人文"), "connector:与")
        self.assertEqual(MODULE.subtitle_format("城市记忆"), "plain")

    def test_filename_validation(self):
        with self.assertRaises(MODULE.ConfigError):
            MODULE.validate_name("错误/名称", "series_name")

    def test_corrupted_text_detection(self):
        self.assertTrue(MODULE.contains_bad_text("损坏\ufffd文字"))
        self.assertFalse(MODULE.contains_bad_text("正常文字"))


if __name__ == "__main__":
    unittest.main()
