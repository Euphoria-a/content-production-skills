from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "analyze_narration.py"
SPEC = importlib.util.spec_from_file_location("analyze_narration", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class NarrationAnalysisTests(unittest.TestCase):
    def test_effective_char_count_ignores_punctuation(self):
        self.assertEqual(MODULE.effective_char_count("山河，2026！"), 6)

    def test_duration_range_uses_speed(self):
        fast, slow = MODULE.estimate_minutes(640, 1.0)
        self.assertEqual((fast, slow), (4.0, 640 / 120))

    def test_missing_required_location_is_error(self):
        report = MODULE.analyze("我们从甲地出发。", locations=["甲地", "乙地"])
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["missing_locations"], ["乙地"])

    def test_mojibake_is_error(self):
        report = MODULE.analyze("这段文字包含锟斤拷。")
        self.assertGreater(report["error_count"], 0)

    def test_style_risks_are_warnings(self):
        report = MODULE.analyze("这里最美。真的必去。其实吧。")
        self.assertEqual(report["status"], "review")
        self.assertGreaterEqual(report["warning_count"], 3)

    def test_clean_copy_passes(self):
        report = MODULE.analyze("沿着河谷向前走，我们会看到聚落如何依水展开，也能理解道路为何选择这条方向。")
        self.assertEqual(report["status"], "passed")


if __name__ == "__main__":
    unittest.main()
