#!/usr/bin/env python3
"""创建和修改带版本记录的分层 SVG 视觉项目。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


def qname(local: str) -> str:
    return f"{{{SVG_NS}}}{local}"


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value.strip(), flags=re.UNICODE)
    return value.strip("-") or "视觉项目"


def versioned_path(directory: Path, stem: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}{suffix}"
    version = 2
    while candidate.exists():
        candidate = directory / f"{stem}-v{version}{suffix}"
        version += 1
    return candidate


def copy_asset(source: str | Path, assets_dir: Path, stem: str) -> Path:
    source = Path(source).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    suffix = source.suffix.lower() or ".png"
    target = versioned_path(assets_dir, slugify(stem), suffix)
    shutil.copy2(source, target)
    return target


def add_tspans(
    text_node: ET.Element,
    lines: Iterable[str],
    x: float,
    line_height: float,
) -> None:
    for index, line in enumerate(lines):
        tspan = ET.SubElement(text_node, qname("tspan"), {"x": str(x)})
        if index:
            tspan.set("dy", str(line_height))
        tspan.text = line


def wrap_text(text: str, max_chars: int) -> list[str]:
    explicit = text.replace("\r\n", "\n").split("\n")
    output: list[str] = []
    for paragraph in explicit:
        if not paragraph:
            output.append("")
            continue
        if " " in paragraph and len(paragraph) > max_chars:
            current = ""
            for word in paragraph.split():
                candidate = word if not current else f"{current} {word}"
                if len(candidate) <= max_chars:
                    current = candidate
                else:
                    if current:
                        output.append(current)
                    current = word
            if current:
                output.append(current)
        else:
            output.extend(
                paragraph[index : index + max_chars]
                for index in range(0, len(paragraph), max_chars)
            )
    return output or [""]


def fitted_max_chars(bounds_width: int, font_size: int, letter_spacing: float) -> int:
    """按中文全角字的保守宽度估算一行可容纳字符数。"""
    estimated_glyph_width = font_size * 0.85
    return max(1, int((bounds_width + letter_spacing) // (estimated_glyph_width + letter_spacing)))


def _group(
    root: ET.Element,
    layer_id: str,
    layer_type: str,
    bounds: tuple[int, int, int, int],
    **extra: str,
) -> ET.Element:
    attrs = {
        "id": layer_id,
        "data-layer-type": layer_type,
        "data-bounds": ",".join(map(str, bounds)),
    }
    attrs.update(extra)
    return ET.SubElement(root, qname("g"), attrs)


def _text_group(
    root: ET.Element,
    layer_id: str,
    bounds: tuple[int, int, int, int],
    text: str,
    x: int,
    y: int,
    font_size: int,
    fill: str,
    family: str,
    weight: str = "400",
    max_chars: int = 18,
    line_height: int | None = None,
    anchor: str = "start",
    letter_spacing: float | None = None,
    tabular_nums: bool = False,
    stroke: str | None = None,
    stroke_width: float = 0,
) -> ET.Element:
    line_height = line_height or int(font_size * 1.25)
    letter_spacing = (
        letter_spacing
        if letter_spacing is not None
        else round(font_size * 0.08, 2) if font_size >= 80 else 1
    )
    max_chars = min(max_chars, fitted_max_chars(bounds[2], font_size, letter_spacing))
    group = _group(
        root,
        layer_id,
        "text",
        bounds,
        **{
            "data-text-x": str(x),
            "data-text-y": str(y),
            "data-line-height": str(line_height),
            "data-max-chars": str(max_chars),
        },
    )
    text_attrs = {
        "x": str(x),
        "y": str(y),
        "fill": fill,
        "font-family": family,
        "font-size": str(font_size),
        "font-weight": weight,
        "text-anchor": anchor,
        "letter-spacing": str(letter_spacing),
    }
    if tabular_nums:
        text_attrs["style"] = "font-variant-numeric:tabular-nums;font-feature-settings:'tnum' 1"
    if stroke and stroke_width > 0:
        text_attrs["stroke"] = stroke
        text_attrs["stroke-width"] = str(stroke_width)
        text_attrs["paint-order"] = "stroke fill"
        text_attrs["stroke-linejoin"] = "round"
    text_node = ET.SubElement(
        group,
        qname("text"),
        text_attrs,
    )
    add_tspans(text_node, wrap_text(text, max_chars), x, line_height)
    return group


def asset_hashes(project_dir: Path) -> dict[str, str]:
    assets = project_dir / "assets"
    return {
        path.relative_to(project_dir).as_posix(): sha256(path)
        for path in sorted(assets.rglob("*"))
        if path.is_file()
    }


def _write_tree(tree: ET.ElementTree, path: Path) -> None:
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def create_project(
    project_dir: str | Path,
    title: str,
    subtitle: str,
    body: str,
    metadata_text: str,
    background: str | Path,
    subject: str | Path | None = None,
    width: int = 1536,
    height: int = 2048,
    provider: str | None = None,
    model: str | None = None,
    prompt_path: str | None = None,
) -> Path:
    project_dir = Path(project_dir).resolve()
    if (project_dir / "project.svg").exists():
        raise FileExistsError(f"项目已存在：{project_dir}")
    for folder in ("assets", "assets/_failed", "masks", "prompts", "history", "exports"):
        (project_dir / folder).mkdir(parents=True, exist_ok=True)

    bg_asset = copy_asset(background, project_dir / "assets", "background")
    subject_asset = (
        copy_asset(subject, project_dir / "assets", "subject") if subject else None
    )

    root = ET.Element(
        qname("svg"),
        {
            "width": str(width),
            "height": str(height),
            "viewBox": f"0 0 {width} {height}",
            "role": "img",
        },
    )
    defs = ET.SubElement(root, qname("defs"))
    gradient = ET.SubElement(
        defs, qname("linearGradient"), {"id": "bottom-fade", "x1": "0", "y1": "0", "x2": "0", "y2": "1"}
    )
    ET.SubElement(gradient, qname("stop"), {"offset": "0", "stop-color": "#061a2b", "stop-opacity": "0"})
    ET.SubElement(gradient, qname("stop"), {"offset": "1", "stop-color": "#061a2b", "stop-opacity": "0.85"})
    left_gradient = ET.SubElement(
        defs, qname("linearGradient"), {"id": "left-fade", "x1": "0", "y1": "0", "x2": "1", "y2": "0"}
    )
    ET.SubElement(left_gradient, qname("stop"), {"offset": "0", "stop-color": "#061a2b", "stop-opacity": "0.65"})
    ET.SubElement(left_gradient, qname("stop"), {"offset": "0.56", "stop-color": "#061a2b", "stop-opacity": "0.18"})
    ET.SubElement(left_gradient, qname("stop"), {"offset": "1", "stop-color": "#061a2b", "stop-opacity": "0"})
    subject_box = (
        int(width * 0.58),
        int(height * 0.27),
        int(width * 0.38),
        int(height * 0.64),
    )
    clip = ET.SubElement(defs, qname("clipPath"), {"id": "subject-clip"})
    ET.SubElement(
        clip,
        qname("rect"),
        {
            "x": str(subject_box[0]),
            "y": str(subject_box[1]),
            "width": str(subject_box[2]),
            "height": str(subject_box[3]),
            "rx": "40",
        },
    )

    background_group = _group(root, "background", "raster", (0, 0, width, height))
    ET.SubElement(
        background_group,
        qname("image"),
        {"href": bg_asset.relative_to(project_dir).as_posix(), "x": "0", "y": "0", "width": str(width), "height": str(height), "preserveAspectRatio": "xMidYMid slice"},
    )
    overlay = _group(root, "overlay", "shape", (0, 0, width, height))
    ET.SubElement(overlay, qname("rect"), {"x": "0", "y": "0", "width": str(width), "height": str(height), "fill": "url(#left-fade)"})
    ET.SubElement(overlay, qname("rect"), {"x": "0", "y": str(int(height * 0.48)), "width": str(width), "height": str(int(height * 0.52)), "fill": "url(#bottom-fade)"})
    ET.SubElement(overlay, qname("line"), {"x1": str(int(width * 0.06)), "y1": str(int(height * 0.09)), "x2": str(int(width * 0.94)), "y2": str(int(height * 0.09)), "stroke": "#d7b36a", "stroke-width": "3"})

    subject_group = _group(root, "subject", "raster", subject_box)
    if subject_asset:
        ET.SubElement(
            subject_group,
            qname("image"),
            {"href": subject_asset.relative_to(project_dir).as_posix(), "x": str(subject_box[0]), "y": str(subject_box[1]), "width": str(subject_box[2]), "height": str(subject_box[3]), "preserveAspectRatio": "xMidYMid slice", "clip-path": "url(#subject-clip)"},
        )

    title_size = round(width * 156 / 864)
    lead_size = round(width * 40 / 864)
    body_size = round(width * 28 / 864)
    metadata_size = round(width * 44 / 864)
    title_family = "Noto Serif SC, Source Han Serif SC, Microsoft YaHei, serif"
    body_family = "Noto Sans SC, Source Han Sans SC, Microsoft YaHei, sans-serif"
    _text_group(root, "title", (int(width * 0.06), int(height * 0.12), int(width * 0.82), int(height * 0.29)), title, int(width * 0.06), int(height * 0.21), title_size, "#f8f5e9", title_family, "700", 9, round(title_size * 1.05), stroke="#061a2b", stroke_width=2.5)
    _text_group(root, "subtitle", (int(width * 0.065), int(height * 0.40), int(width * 0.76), int(height * 0.10)), subtitle, int(width * 0.065), int(height * 0.45), lead_size, "#d7b36a", title_family, "600", 24, round(lead_size * 1.4), stroke="#061a2b", stroke_width=1.5)
    _text_group(root, "body", (int(width * 0.065), int(height * 0.55), int(width * 0.48), int(height * 0.28)), body, int(width * 0.065), int(height * 0.61), body_size, "#f5f7f8", body_family, "400", 22, round(body_size * 1.5), stroke="#061a2b", stroke_width=1.4)
    _text_group(root, "metadata", (int(width * 0.065), int(height * 0.84), int(width * 0.87), int(height * 0.12)), metadata_text, int(width * 0.065), int(height * 0.89), metadata_size, "#eef2f4", body_family, "500", 38, round(metadata_size * 1.35), tabular_nums=True, stroke="#061a2b", stroke_width=1.5)

    svg_path = project_dir / "project.svg"
    _write_tree(ET.ElementTree(root), svg_path)
    layers = [
        {"id": node.get("id"), "type": node.get("data-layer-type")}
        for node in root.findall(qname("g"))
    ]
    project_data: dict[str, Any] = {
        "schema_version": 1,
        "current_version": 1,
        "canvas": {"width": width, "height": height, "viewBox": [0, 0, width, height]},
        "svg": "project.svg",
        "provider": provider,
        "model": model,
        "prompt_path": prompt_path,
        "review_profile": "poster-review-v2",
        "design_tokens_ref": ".image-studio/design-tokens.json",
        "anti_text_retry_count": 0,
        "design_tokens": {
            "safe_margin_px": round(width * 40 / 864),
            "important_text_contrast_ratio": 4.5,
            "quiet_space_target": "30-40%",
            "gold_bright": "#d7b36a",
            "gold_deep": "#a37b3c",
            "overlay_alpha_tokens": [0.85, 0.65, 0.35, 0.18],
        },
        "layers": layers,
        "asset_hashes": asset_hashes(project_dir),
        "history": [
            {"version": 1, "at": datetime.now(timezone.utc).isoformat(), "action": "create", "target": "project"}
        ],
    }
    (project_dir / "project.json").write_text(
        json.dumps(project_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (project_dir / "text-only.md").write_text(
        "# 海报纯文字版\n\n"
        f"- 主标题：{title}\n"
        f"- 导语：{subtitle}\n"
        f"- 正文：{body}\n"
        f"- 时间地点及行动信息：{metadata_text}\n",
        encoding="utf-8",
    )
    return svg_path


def load_project(project_dir: str | Path) -> tuple[Path, ET.ElementTree, dict[str, Any]]:
    project_dir = Path(project_dir).resolve()
    tree = ET.parse(project_dir / "project.svg")
    data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
    return project_dir, tree, data


def find_layer(root: ET.Element, layer_id: str) -> ET.Element:
    for group in root.findall(qname("g")):
        if group.get("id") == layer_id:
            return group
    raise KeyError(f"未知图层：{layer_id}")


def snapshot(project_dir: Path, data: dict[str, Any]) -> Path:
    version = int(data.get("current_version", 1))
    snapshot_dir = project_dir / "history" / f"v{version:03d}"
    snapshot_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(project_dir / "project.svg", snapshot_dir / "project.svg")
    shutil.copy2(project_dir / "project.json", snapshot_dir / "project.json")
    return snapshot_dir


def _finish_change(
    project_dir: Path,
    tree: ET.ElementTree,
    data: dict[str, Any],
    action: str,
    target: str,
    before_hash: str | None,
    after_hash: str | None,
) -> None:
    data["current_version"] = int(data.get("current_version", 1)) + 1
    data["asset_hashes"] = asset_hashes(project_dir)
    data.setdefault("history", []).append(
        {
            "version": data["current_version"],
            "at": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "before_sha256": before_hash,
            "after_sha256": after_hash,
        }
    )
    _write_tree(tree, project_dir / "project.svg")
    (project_dir / "project.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def update_text(project_dir: str | Path, layer_id: str, text: str) -> None:
    project_dir, tree, data = load_project(project_dir)
    layer = find_layer(tree.getroot(), layer_id)
    if layer.get("data-layer-type") != "text":
        raise ValueError(f"目标不是文字图层：{layer_id}")
    before = sha256(project_dir / "project.svg")
    snapshot(project_dir, data)
    text_node = layer.find(qname("text"))
    if text_node is None:
        raise ValueError(f"图层缺少文字节点：{layer_id}")
    for child in list(text_node):
        text_node.remove(child)
    x = float(layer.get("data-text-x", text_node.get("x", "0")))
    line_height = float(layer.get("data-line-height", "48"))
    max_chars = int(layer.get("data-max-chars", "20"))
    add_tspans(text_node, wrap_text(text, max_chars), x, line_height)
    _write_tree(tree, project_dir / "project.svg")
    after = sha256(project_dir / "project.svg")
    _finish_change(project_dir, tree, data, "update-text", layer_id, before, after)


def replace_image(project_dir: str | Path, layer_id: str, source: str | Path) -> Path:
    project_dir, tree, data = load_project(project_dir)
    layer = find_layer(tree.getroot(), layer_id)
    if layer.get("data-layer-type") != "raster":
        raise ValueError(f"目标不是位图图层：{layer_id}")
    image_node = layer.find(qname("image"))
    if image_node is None:
        raise ValueError(f"图层缺少图片节点：{layer_id}")
    old_href = image_node.get("href") or image_node.get(f"{{{XLINK_NS}}}href")
    old_path = project_dir / str(old_href)
    before = sha256(old_path) if old_path.is_file() else None
    snapshot(project_dir, data)
    if old_path.is_file():
        failed_dir = project_dir / "assets" / "_failed"
        archived = versioned_path(
            failed_dir,
            f"{slugify(old_path.stem)}-{before[:12] if before else '无哈希'}",
            old_path.suffix,
        )
        shutil.copy2(old_path, archived)
    new_asset = copy_asset(source, project_dir / "assets", layer_id)
    image_node.set("href", new_asset.relative_to(project_dir).as_posix())
    after = sha256(new_asset)
    _finish_change(project_dir, tree, data, "replace-image", layer_id, before, after)
    return new_asset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分层 SVG 项目内部辅助程序")
    sub = parser.add_subparsers(dest="operation", required=True)
    create = sub.add_parser("create")
    create.add_argument("--project-dir", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--subtitle", default="")
    create.add_argument("--body", default="")
    create.add_argument("--metadata", default="")
    create.add_argument("--background", required=True)
    create.add_argument("--subject")
    create.add_argument("--width", type=int, default=1536)
    create.add_argument("--height", type=int, default=2048)
    text = sub.add_parser("update-text")
    text.add_argument("--project-dir", required=True)
    text.add_argument("--layer", required=True)
    text.add_argument("--text", required=True)
    image = sub.add_parser("replace-image")
    image.add_argument("--project-dir", required=True)
    image.add_argument("--layer", required=True)
    image.add_argument("--source", required=True)
    args = parser.parse_args(argv)
    if args.operation == "create":
        path = create_project(args.project_dir, args.title, args.subtitle, args.body, args.metadata, args.background, args.subject, args.width, args.height)
        print(path)
    elif args.operation == "update-text":
        update_text(args.project_dir, args.layer, args.text)
        print(Path(args.project_dir).resolve() / "project.svg")
    else:
        print(replace_image(args.project_dir, args.layer, args.source))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2)
