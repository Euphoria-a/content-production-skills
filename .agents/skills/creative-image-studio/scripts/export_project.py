#!/usr/bin/env python3
"""内部交付包导出器：生成 PNG、JPG、25% 预览图和项目元数据副本。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

from render_svg import convert_jpg, render
from validate_project import validate


def export_project(project_dir: str | Path, stem: str = "海报") -> dict[str, str]:
    project_dir = Path(project_dir).resolve()
    svg_path = project_dir / "project.svg"
    json_path = project_dir / "project.json"
    exports = project_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)

    png_path, engine = render(svg_path, exports / f"{stem}.png")
    jpg_path = convert_jpg(png_path, exports / f"{stem}.jpg")
    preview_path = png_path.with_name(f"{png_path.stem}-25pct.png")
    with Image.open(png_path) as source:
        preview_size = (max(1, source.width // 4), max(1, source.height // 4))
        source.resize(preview_size, Image.Resampling.LANCZOS).save(preview_path)

    metadata_copy = exports / f"{png_path.stem}-project.json"
    shutil.copy2(json_path, metadata_copy)
    text_source = project_dir / "text-only.md"
    text_copy = exports / f"{png_path.stem}-text-only.md"
    if text_source.is_file():
        shutil.copy2(text_source, text_copy)

    result = validate(project_dir, png_path)
    validation_path = exports / f"{png_path.stem}-validation.json"
    validation_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not result["ok"]:
        raise RuntimeError(f"导出后校验未通过，详见：{validation_path}")

    outputs = {
        "png": str(png_path),
        "jpg": str(jpg_path),
        "preview_25pct": str(preview_path),
        "project_json": str(metadata_copy),
        "validation": str(validation_path),
        "renderer": engine,
    }
    if text_source.is_file():
        outputs["text_only"] = str(text_copy)
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="creative-image-studio 内部交付包导出器")
    parser.add_argument("project_dir", help="项目目录")
    parser.add_argument("--stem", default="海报", help="导出文件名主体")
    args = parser.parse_args(argv)
    print(json.dumps(export_project(args.project_dir, args.stem), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2)
