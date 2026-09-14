from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "render_poster.py"
SPEC = importlib.util.spec_from_file_location("artifact_v4_renderer", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ArtifactV4Tests(unittest.TestCase):
    def test_palette_routing(self):
        palette = MODULE.choose_palette({"destination_name": "海岛环游"})
        self.assertEqual(palette["background"], "#062B3A")

    def test_missing_value_is_explicit(self):
        self.assertEqual(MODULE.value(""), MODULE.MISSING)
        self.assertEqual(MODULE.value(None), MODULE.MISSING)

    def test_sanitized_example_renders_expected_canvas(self):
        config = json.loads((SKILL_ROOT / "examples" / "example-input.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "poster.png"
            MODULE.render(config, output)
            with Image.open(output) as image:
                self.assertEqual(image.size, (1080, 2568))
                self.assertEqual(image.format, "PNG")


if __name__ == "__main__":
    unittest.main()
