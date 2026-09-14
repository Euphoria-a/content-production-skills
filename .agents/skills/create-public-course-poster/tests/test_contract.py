from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "scripts" / "render_poster.py"
SPEC = importlib.util.spec_from_file_location("public_course_renderer", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class PublicCourseContractTests(unittest.TestCase):
    def load_example(self) -> dict[str, object]:
        return json.loads((SKILL_ROOT / "examples" / "data.example.json").read_text(encoding="utf-8"))

    def write_payload(self, payload: dict[str, object]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
        with handle:
            json.dump(payload, handle, ensure_ascii=False)
        return Path(handle.name)

    def test_example_contract_loads(self):
        path = self.write_payload(self.load_example())
        self.addCleanup(path.unlink, missing_ok=True)
        data = MODULE.load_data(path)
        self.assertEqual(data["location_scope"], "china")
        self.assertEqual(len(data["core_points"]), 2)

    def test_fixed_brand_fields_cannot_be_overridden(self):
        payload = self.load_example()
        payload["brand_text"] = "override"
        path = self.write_payload(payload)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaisesRegex(ValueError, "不得由 JSON 覆盖"):
            MODULE.load_data(path)

    def test_background_requires_person_free_source(self):
        payload = self.load_example()
        payload["background_sources"][0]["contains_person"] = True
        path = self.write_payload(payload)
        self.addCleanup(path.unlink, missing_ok=True)
        with self.assertRaisesRegex(ValueError, "不含人物"):
            MODULE.load_data(path)

    def test_core_points_are_normalized(self):
        self.assertEqual(MODULE.normalize_core_points("城市空间；地方记忆。"), ["城市空间", "地方记忆"])


if __name__ == "__main__":
    unittest.main()
