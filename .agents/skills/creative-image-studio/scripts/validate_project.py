#!/usr/bin/env python3
"""校验分层 SVG 结构、关联素材、项目元数据和位图导出。"""

from __future__ import annotations

import argparse
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"


def qname(local: str) -> str:
    return f"{{{SVG_NS}}}{local}"


def svg_number(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().lower().replace("px", "")
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def primary_font_family(value: str | None) -> str | None:
    if not value:
        return None
    family = value.split(",", 1)[0].strip().strip("'\"")
    return family or None


def estimated_text_width(value: str, font_size: float, letter_spacing: float) -> float:
    """用中西文近似字宽估算一行 SVG 文字的占用宽度。"""
    widths = []
    for char in value:
        if char.isspace():
            widths.append(font_size * 0.33)
        elif ord(char) < 128:
            widths.append(font_size * 0.58)
        else:
            widths.append(font_size * 0.85)
    return sum(widths) + max(0, len(widths) - 1) * letter_spacing


def validate(project_dir: str | Path, raster: str | Path | None = None) -> dict[str, Any]:
    project_dir = Path(project_dir).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    svg_path = project_dir / "project.svg"
    json_path = project_dir / "project.json"
    if not svg_path.is_file():
        return {"ok": False, "errors": ["缺少 project.svg"], "warnings": []}
    if not json_path.is_file():
        return {"ok": False, "errors": ["缺少 project.json"], "warnings": []}

    try:
        tree = ET.parse(svg_path)
    except ET.ParseError as exc:
        return {"ok": False, "errors": [f"SVG XML 无效：{exc}"], "warnings": []}
    try:
        metadata = json.loads(json_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"project.json 无效：{exc}"], "warnings": []}

    root = tree.getroot()
    try:
        width = int(float(str(root.get("width")).replace("px", "")))
        height = int(float(str(root.get("height")).replace("px", "")))
    except (TypeError, ValueError):
        width = height = 0
        errors.append("SVG 的 width 和 height 必须是数字")
    if width <= 0 or height <= 0:
        errors.append("SVG 尺寸必须大于零")
    view_box = str(root.get("viewBox", "")).split()
    if len(view_box) != 4:
        errors.append("SVG viewBox 必须包含四个值")
    else:
        try:
            if int(float(view_box[2])) != width or int(float(view_box[3])) != height:
                errors.append("SVG viewBox 尺寸与 width/height 不一致")
        except ValueError:
            errors.append("SVG viewBox 含非数字值")

    groups = root.findall(qname("g"))
    ids = [group.get("id") for group in groups]
    if any(not layer_id for layer_id in ids):
        errors.append("每个顶层图层组都必须有 id")
    if len(ids) != len(set(ids)):
        errors.append("图层 id 必须唯一")
    declared_ids = [item.get("id") for item in metadata.get("layers", [])]
    if set(ids) != set(declared_ids):
        errors.append("project.json 与 project.svg 的图层 id 不一致")

    if metadata.get("review_profile") == "poster-review-v2":
        if not metadata.get("design_tokens_ref"):
            errors.append("[CT1][P0] 缺少工作区设计令牌引用 design_tokens_ref")
        token_values = metadata.get("design_tokens", {}).get("overlay_alpha_tokens")
        if token_values != [0.85, 0.65, 0.35, 0.18]:
            errors.append("[CT3][P0] 遮罩透明度令牌必须为 0.85、0.65、0.35、0.18")

    layer_bounds: dict[str, tuple[float, float, float, float]] = {}
    for group in groups:
        bounds_text = group.get("data-bounds")
        if not bounds_text:
            errors.append(f"图层 {group.get('id')} 缺少 data-bounds")
            continue
        try:
            x, y, box_width, box_height = [float(value) for value in bounds_text.split(",")]
            values = (x, y, box_width, box_height)
            if not all(math.isfinite(value) for value in values):
                raise ValueError
            if x < 0 or y < 0 or box_width < 0 or box_height < 0 or x + box_width > width or y + box_height > height:
                errors.append(f"图层 {group.get('id')} 的边界超出画布：{bounds_text}")
            elif group.get("id"):
                layer_bounds[str(group.get("id"))] = values
        except (ValueError, TypeError):
            errors.append(f"图层 {group.get('id')} 的 data-bounds 无效：{bounds_text}")

    for image in root.iter(qname("image")):
        href = image.get("href") or image.get(f"{{{XLINK_NS}}}href")
        if not href:
            errors.append("图片元素缺少 href")
            continue
        linked = (project_dir / href).resolve()
        try:
            linked.relative_to(project_dir)
        except ValueError:
            errors.append(f"图片 href 逃逸出项目目录：{href}")
            continue
        if not linked.is_file():
            errors.append(f"关联素材不存在：{href}")

    for text in root.iter(qname("text")):
        content = "".join(text.itertext())
        if "\ufffd" in content:
            errors.append("SVG 文字包含替换字符 U+FFFD")
        if not content.strip():
            warnings.append("存在空的 SVG 文字节点")

    allowed_alpha = {0.0, 0.18, 0.35, 0.65, 0.85, 1.0}
    for stop in root.iter(qname("stop")):
        opacity = svg_number(stop.get("stop-opacity"))
        if opacity is not None and round(opacity, 2) not in allowed_alpha:
            errors.append(f"[CT3][P0] 渐变透明度 {opacity:g} 未使用设计令牌")

    safe_margin = width * 40 / 864 if width > 0 else 0
    font_families: set[str] = set()
    poster_warning_count = len(warnings)
    metadata_tokens = ("metadata", "date", "time", "location", "venue")
    for group in groups:
        if group.get("data-layer-type") != "text":
            continue
        layer_id = str(group.get("id", "unnamed"))
        text_node = group.find(qname("text"))
        if text_node is None:
            warnings.append(f"[{layer_id}] 文字图层没有 text 元素")
            continue

        bounds = layer_bounds.get(layer_id)
        if bounds and width > 0 and height > 0:
            x, y, box_width, box_height = bounds
            if (
                x < safe_margin
                or y < safe_margin
                or width - (x + box_width) < safe_margin
                or height - (y + box_height) < safe_margin
            ):
                warnings.append(
                    f"[P4] 文字图层 {layer_id} 进入按比例计算的 {safe_margin:.1f}px 画布安全区"
                )

        family = primary_font_family(text_node.get("font-family"))
        if family:
            font_families.add(family)
        font_size = svg_number(text_node.get("font-size"))
        if not font_size or font_size <= 0 or width <= 0:
            continue
        normalized_size = font_size * 864 / width

        if normalized_size >= 80:
            spacing = svg_number(text_node.get("letter-spacing"))
            ratio = (spacing or 0) / font_size
            if ratio < 0.05 or ratio > 0.12:
                warnings.append(
                    f"[T2] 大字号图层 {layer_id} 的字距为 {ratio:.1%}，目标为 5–12%"
                )

        lowered_id = layer_id.lower()
        if any(token in lowered_id for token in metadata_tokens) and normalized_size < 28:
            warnings.append(
                f"[A11y2] 信息图层 {layer_id} 折算到 864px 宽时为 {normalized_size:.1f}px，目标至少 28px"
            )
        content = "".join(text_node.itertext())
        style = text_node.get("style", "").lower()
        if any(token in lowered_id for token in metadata_tokens) and any(char.isdigit() for char in content):
            if "tabular" not in style and "tnum" not in style:
                warnings.append(f"[T7] 数字信息图层 {layer_id} 未声明等宽数字")

        spacing = svg_number(text_node.get("letter-spacing")) or 0
        tspans = text_node.findall(qname("tspan"))
        if bounds:
            _, bounds_y, bounds_width, bounds_height = bounds
            for tspan in tspans:
                line = "".join(tspan.itertext()).strip()
                actual = estimated_text_width(line, font_size, spacing)
                if actual > bounds_width + 0.5:
                    errors.append(
                        f"[R1/T5][P0] 图层 {layer_id} 的文字行估算宽度 {actual:.1f}px 超过排版框 {bounds_width:.1f}px"
                    )
                    break
            baseline_y = svg_number(text_node.get("y")) or bounds_y
            line_height = svg_number(group.get("data-line-height")) or font_size * 1.25
            last_bottom = baseline_y + max(0, len(tspans) - 1) * line_height + font_size * 0.2
            if last_bottom > bounds_y + bounds_height + 0.5:
                errors.append(f"[R1/T5][P0] 图层 {layer_id} 的文字高度超出排版框")

        if layer_id.lower() == "title" and len(tspans) >= 2:
            line_height = svg_number(group.get("data-line-height"))
            if line_height:
                leading_ratio = line_height / font_size
                if leading_ratio < 0.9 or leading_ratio > 1.2:
                    warnings.append(
                        f"[T3] 标题行高比例为 {leading_ratio:.2f}，目标为 0.9–1.2"
                    )
            line_widths = []
            spacing = svg_number(text_node.get("letter-spacing")) or 0
            for tspan in tspans:
                line = "".join(tspan.itertext()).strip()
                line_widths.append(len(line) * font_size + max(0, len(line) - 1) * spacing)
            if line_widths and max(line_widths) > 0:
                difference = (max(line_widths) - min(line_widths)) / max(line_widths)
                if difference > 0.10:
                    warnings.append(
                    f"[T5] 双行标题视觉宽度差为 {difference:.1%}，目标不超过 10%"
                    )

        if layer_id.lower() == "body":
            for tspan in tspans:
                line = "".join(tspan.itertext())
                if len("".join(line.split())) > 40:
                    warnings.append("[T8] 正文单行超过 40 个中文字符等价值")
                    break

    if len(font_families) > 3:
        warnings.append(
            f"[T1] 海报使用 {len(font_families)} 个主要字体家族，目标为两类正文/标题字体加一个有意使用的数字或品牌字体"
        )

    if raster:
        from PIL import Image, ImageStat

        raster_path = Path(raster)
        if not raster_path.is_file():
            errors.append(f"位图导出不存在：{raster_path}")
        else:
            with Image.open(raster_path) as image:
                if image.size != (width, height):
                    errors.append(f"位图尺寸 {image.size} 与画布 {(width, height)} 不一致")
                rgb = image.convert("RGB").resize((64, 64))
                extrema = ImageStat.Stat(rgb).extrema
                if max(high - low for low, high in extrema) < 4:
                    errors.append("位图导出疑似空白或接近单色")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": sorted(set(warnings)),
        "canvas": {"width": width, "height": height},
        "layers": ids,
        "poster_review": {
            "profile": metadata.get("review_profile", "poster-review-v2"),
            "safe_margin_px": round(safe_margin, 2),
            "font_families": sorted(font_families),
            "automated_warning_count": len(warnings) - poster_warning_count,
            "manual_review_required": ["S", "H", "T", "C", "A", "P", "W", "CT", "R", "A11y", "100%", "25%"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验 creative-image-studio 项目")
    parser.add_argument("project_dir")
    parser.add_argument("--raster")
    parser.add_argument("--json-out")
    args = parser.parse_args(argv)
    result = validate(args.project_dir, args.raster)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        Path(args.json_out).write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
