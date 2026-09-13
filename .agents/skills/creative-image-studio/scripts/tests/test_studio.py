from __future__ import annotations

import base64
import io
import json
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw


SCRIPT_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from provider_client import (  # noqa: E402
    OpenAIImageClient,
    ProviderChoiceRequired,
    ProviderError,
    composite_masked_edit,
    encode_multipart,
    normalize_mask,
    persist_response,
    select_provider,
)
from render_svg import versioned_output  # noqa: E402
from svg_project import asset_hashes, create_project, replace_image, update_text  # noqa: E402
from validate_project import qname, validate  # noqa: E402


def png_bytes(color=(20, 80, 140, 255), size=(64, 64)) -> bytes:
    image = Image.new("RGBA", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class MockHandler(BaseHTTPRequestHandler):
    image = png_bytes()
    last_authorization = None
    last_body = b""
    last_content_type = None
    last_path = None

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path == "/asset.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(self.image)
            return
        self.send_error(404)

    def do_POST(self):
        type(self).last_authorization = self.headers.get("Authorization")
        length = int(self.headers.get("Content-Length", "0"))
        type(self).last_body = self.rfile.read(length)
        type(self).last_content_type = self.headers.get("Content-Type")
        type(self).last_path = self.path
        if self.path.endswith("/images/generations"):
            payload = {"data": [{"b64_json": base64.b64encode(self.image).decode()}]}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path.endswith("/images/edits"):
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(self.image)))
            self.end_headers()
            self.wfile.write(self.image)
            return
        if self.path.endswith("/images/error"):
            raw = b'{"error":"credential top-secret rejected"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_error(404)


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def profile(self, **overrides):
        profile = {
            "enabled": True,
            "base_url": self.base_url,
            "api_key_env": "TEST_IMAGE_KEY",
            "models": {"generate": "test-gen", "edit": "test-edit"},
            "endpoints": {"generate": "/images/generations", "edit": "/images/edits"},
            "capabilities": {"generate": True, "edit": True, "mask": True},
            "mask_semantics": "transparent_edit",
        }
        profile.update(overrides)
        return profile

    def test_provider_selection_and_advisor_mode(self):
        config = {"default_provider": "a", "providers": {"a": self.profile()}}
        self.assertIsNone(select_provider(config, "generate", environ={}))
        selected = select_provider(config, "generate", environ={"TEST_IMAGE_KEY": "secret"})
        self.assertEqual(selected[0], "a")

    def test_multiple_provider_choice_required(self):
        config = {
            "providers": {"a": self.profile(), "b": self.profile()},
        }
        with self.assertRaises(ProviderChoiceRequired):
            select_provider(config, "generate", environ={"TEST_IMAGE_KEY": "secret"})

    def test_mask_capability_filters_provider(self):
        weak = self.profile()
        weak["capabilities"] = {"generate": True, "edit": True, "mask": False}
        config = {
            "default_provider": "weak",
            "providers": {"weak": weak, "strong": self.profile()},
        }
        selected = select_provider(
            config, ["edit", "mask"], environ={"TEST_IMAGE_KEY": "secret"}
        )
        self.assertEqual(selected[0], "strong")

    def test_http_errors_redact_api_key(self):
        profile = self.profile()
        profile["endpoints"]["generate"] = "/images/error"
        client = OpenAIImageClient(profile, {"TEST_IMAGE_KEY": "top-secret"})
        with self.assertRaises(ProviderError) as caught:
            client.generate("test")
        self.assertNotIn("top-secret", str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_multipart_contains_fields_and_file(self):
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "图像.png"
            image_path.write_bytes(png_bytes())
            body, mime = encode_multipart({"prompt": "只改天空", "n": 1}, [("image", image_path)])
            self.assertIn("multipart/form-data", mime)
            self.assertIn("只改天空".encode(), body)
            self.assertIn(png_bytes(), body)

    def test_mock_generate_edit_and_base64_persistence(self):
        client = OpenAIImageClient(self.profile(), {"TEST_IMAGE_KEY": "top-secret"})
        with tempfile.TemporaryDirectory() as temp:
            body, mime = client.generate("text-free Antarctic landscape")
            outputs = persist_response(body, mime, temp, "antarctic")
            self.assertEqual(len(outputs), 1)
            with Image.open(outputs[0]) as generated:
                self.assertEqual(generated.size, (64, 64))
            edit_body, edit_mime = client.edit("change only sky", [outputs[0]])
            edited = persist_response(edit_body, edit_mime, temp, "edited")
            self.assertEqual(len(edited), 1)
        self.assertEqual(MockHandler.last_authorization, "Bearer top-secret")

    def test_json_data_uri_edit_transport(self):
        profile = self.profile(
            endpoints={"generate": "/images/generations", "edit": "/images/generations"},
            capabilities={
                "generate": True,
                "edit": True,
                "mask": False,
                "reference_images": True,
            },
            edit_transport="json_data_uri",
            edit_image_field="extra_body.image",
            edit_size_from_input=True,
            edit_defaults={"extra_body": {"response_format": "b64_json"}},
        )
        client = OpenAIImageClient(profile, {"TEST_IMAGE_KEY": "top-secret"})
        with tempfile.TemporaryDirectory() as temp:
            image_path = Path(temp) / "input.png"
            second_path = Path(temp) / "reference.png"
            image_path.write_bytes(png_bytes(size=(80, 48)))
            second_path.write_bytes(png_bytes(color=(180, 80, 40, 255), size=(32, 32)))
            body, mime = client.edit(
                "只把天空改成晚霞，保持构图不变", [image_path, second_path]
            )
            outputs = persist_response(body, mime, temp, "json-edit")
            self.assertEqual(len(outputs), 1)

            mask_path = Path(temp) / "mask.png"
            mask_path.write_bytes(png_bytes())
            mask_profile = dict(profile)
            mask_profile["capabilities"] = dict(profile["capabilities"], mask=True)
            mask_client = OpenAIImageClient(
                mask_profile, {"TEST_IMAGE_KEY": "top-secret"}
            )
            with self.assertRaisesRegex(ProviderError, "不支持遮罩"):
                mask_client.edit("局部编辑", [image_path], mask_path)

        self.assertEqual(MockHandler.last_path, "/v1/images/generations")
        self.assertEqual(MockHandler.last_content_type, "application/json")
        payload = json.loads(MockHandler.last_body.decode("utf-8"))
        self.assertEqual(payload["model"], "test-edit")
        self.assertEqual(payload["size"], "80x48")
        self.assertEqual(payload["extra_body"]["response_format"], "b64_json")
        self.assertEqual(len(payload["extra_body"]["image"]), 2)
        self.assertTrue(payload["extra_body"]["image"][0].startswith("data:image/png;base64,"))
        self.assertNotIn("tags", payload)

    def test_url_response_persistence(self):
        payload = {"data": [{"url": f"http://127.0.0.1:{self.server.server_port}/asset.png"}]}
        with tempfile.TemporaryDirectory() as temp:
            outputs = persist_response(json.dumps(payload).encode(), "application/json", temp, "url-image")
            with Image.open(outputs[0]) as downloaded:
                self.assertEqual(downloaded.size, (64, 64))

    def test_render_output_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "poster.png"
            first.write_bytes(b"existing")
            self.assertEqual(versioned_output(first).name, "poster-v2.png")

    def test_mask_semantics_and_outside_pixel_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            original = temp / "original.png"
            edited = temp / "edited.png"
            mask = temp / "mask.png"
            Image.new("RGBA", (20, 20), "blue").save(original)
            Image.new("RGBA", (20, 20), "red").save(edited)
            mask_image = Image.new("L", (20, 20), 0)
            ImageDraw.Draw(mask_image).rectangle((5, 5, 14, 14), fill=255)
            mask_image.save(mask)
            normalized = normalize_mask(mask, temp / "transparent.png", "transparent_edit")
            with Image.open(normalized) as converted:
                self.assertEqual(converted.getpixel((10, 10))[3], 0)
            black_edit = normalize_mask(mask, temp / "black-edit.png", "black_edit")
            with Image.open(black_edit) as converted:
                self.assertEqual(converted.getpixel((10, 10)), 0)
            output = composite_masked_edit(original, edited, mask, temp / "composite.png")
            result = Image.open(output).convert("RGBA")
            self.assertEqual(result.getpixel((0, 0)), (0, 0, 255, 255))
            self.assertEqual(result.getpixel((10, 10)), (255, 0, 0, 255))

    def test_svg_text_and_image_changes_are_targeted(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            background = temp / "background.png"
            subject = temp / "subject.png"
            replacement = temp / "replacement.png"
            Image.new("RGB", (300, 400), (20, 80, 130)).save(background)
            Image.new("RGB", (160, 260), (220, 180, 120)).save(subject)
            Image.new("RGB", (160, 260), (150, 210, 170)).save(replacement)
            project = temp / "project"
            create_project(project, "南极纪行", "世界文化公益课", "冰川、生命与远方", "时间｜地点", background, subject)
            before = asset_hashes(project)
            update_text(project, "title", "南极新章")
            self.assertEqual(before, asset_hashes(project))
            replace_image(project, "subject", replacement)
            after = asset_hashes(project)
            self.assertEqual(before["assets/background.png"], after["assets/background.png"])
            self.assertTrue(any("assets/_failed/subject-" in path for path in after))
            result = validate(project)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["poster_review"]["profile"], "poster-review-v2")
            project_data = json.loads((project / "project.json").read_text(encoding="utf-8"))
            self.assertGreater(project_data["design_tokens"]["safe_margin_px"], 0)
            self.assertEqual(project_data["design_tokens_ref"], ".image-studio/design-tokens.json")
            self.assertTrue((project / "text-only.md").is_file())

    def test_poster_review_detects_objective_typography_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            background = temp / "background.png"
            Image.new("RGB", (300, 400), (20, 80, 130)).save(background)
            project = temp / "project"
            create_project(
                project,
                "南极纪行",
                "风光篇",
                "海报正文",
                "2026-08-08 09:00｜报告厅",
                background,
            )
            tree = ET.parse(project / "project.svg")
            root = tree.getroot()
            title = next(group for group in root.findall(qname("g")) if group.get("id") == "title")
            title.set("data-bounds", "0,0,900,300")
            title.find(qname("text")).set("letter-spacing", "1")
            metadata = next(
                group for group in root.findall(qname("g")) if group.get("id") == "metadata"
            )
            metadata_text = metadata.find(qname("text"))
            metadata_text.set("font-size", "20")
            metadata_text.attrib.pop("style", None)
            tree.write(project / "project.svg", encoding="utf-8", xml_declaration=True)

            result = validate(project)
            self.assertFalse(result["ok"], result)
            errors = "\n".join(result["errors"])
            self.assertIn("[R1/T5][P0]", errors)
            warnings = "\n".join(result["warnings"])
            for code in ("[P4]", "[T2]", "[A11y2]", "[T7]"):
                self.assertIn(code, warnings)

    def test_recipe_library_has_exactly_ninety_recipes(self):
        files = sorted(SKILL_DIR.glob("references/recipes-*.md"))
        files = [path for path in files if path.name != "recipes-index.md"]
        self.assertEqual(len(files), 18)
        recipe_rows = 0
        for path in files:
            rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| `")]
            self.assertEqual(len(rows), 5, path.name)
            recipe_rows += len(rows)
        self.assertEqual(recipe_rows, 90)


if __name__ == "__main__":
    unittest.main(verbosity=2)
