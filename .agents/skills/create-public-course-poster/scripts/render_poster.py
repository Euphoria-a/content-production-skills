#!/usr/bin/env python3
"""确定性合成“区域文化 / 世界文化”固定模板海报。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


SKILL_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = SKILL_ROOT / "assets" / "fonts"
LAYOUT_PATH = SKILL_ROOT / "references" / "layout.json"

FONT_FILES = {
    "youth": FONT_DIR / "文悦新青年体简体W8.otf",
    "serif": FONT_DIR / "NotoSerifCJKsc-Regular.otf",
    "serif_bold": FONT_DIR / "NotoSerifCJKsc-Bold.otf",
    "sans": FONT_DIR / "NotoSansCJKsc-Regular.otf",
    "sans_bold": FONT_DIR / "NotoSansCJKsc-Bold.otf",
}
FONT_ENV = {
    "youth": "PUBLIC_COURSE_FONT_YOUTH",
    "serif": "PUBLIC_COURSE_FONT_SERIF",
    "serif_bold": "PUBLIC_COURSE_FONT_SERIF_BOLD",
    "sans": "PUBLIC_COURSE_FONT_SANS",
    "sans_bold": "PUBLIC_COURSE_FONT_SANS_BOLD",
}
SYSTEM_FONT_CANDIDATES = {
    "youth": [],
    "serif": [Path(r"C:\Windows\Fonts\simsun.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc")],
    "serif_bold": [Path(r"C:\Windows\Fonts\simhei.ttf"), Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc")],
    "sans": [Path(r"C:\Windows\Fonts\msyh.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")],
    "sans_bold": [Path(r"C:\Windows\Fonts\msyhbd.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")],
}

COLORS = {
    "cream": (246, 241, 229, 255),
    "teal": (4, 51, 55, 255),
    "gold": (224, 177, 83, 255),
    "navy": (23, 58, 94, 255),
    "white": (245, 245, 238, 255),
}
TITLE_CANDIDATES = [COLORS["cream"], COLORS["teal"], COLORS["gold"], COLORS["navy"]]
PANEL_THEMES = {
    "dark_teal": {
        "fill": (3, 38, 41),
        "brand_fill": (4, 51, 55),
        "outline": COLORS["gold"],
        "heading": COLORS["gold"],
        "body": COLORS["white"],
        "brand_text": COLORS["cream"],
        "icon": COLORS["gold"],
    },
    "light_sand": {
        "fill": (244, 231, 198),
        "brand_fill": (244, 231, 198),
        "outline": (137, 96, 48, 255),
        "heading": COLORS["navy"],
        "body": COLORS["teal"],
        "brand_text": COLORS["teal"],
        "icon": (137, 96, 48, 255),
    },
}
BRANDS = {
    "china": "区域文化 · 网络公益课",
    "world": "世界文化 · 网络公益课",
}
REQUIRED_KEYS = {
    "location_scope",
    "title_lines",
    "subtitle",
    "guest_name",
    "guest_identity",
    "guest_intro",
    "core_points",
    "event_time",
    "course_location",
    "portrait_face_box",
    "background_sources",
}
FORBIDDEN_KEYS = {"brand", "brand_text", "font", "colors", "layout", "title_color"}
CORE_SPLIT = re.compile(r"[\n\r，,。；;！？!?]+")
EDGE_PUNCTUATION = "，,。；;！？!?、：:·|｜—- "


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="合成固定模板中文公益课海报，并生成审计文件。")
    parser.add_argument("--base", required=True, type=Path, help="1024×1536、无人无字的背景 PNG")
    parser.add_argument("--portrait", required=True, type=Path, help="1024×1536 的 RGBA 透明人物层 PNG")
    parser.add_argument("--data", required=True, type=Path, help="UTF-8 文案 JSON")
    parser.add_argument("--out", required=True, type=Path, help="最终 PNG 路径")
    parser.add_argument(
        "--debug-overlay",
        action="store_true",
        help="除内部调试图外，再在最终 PNG 同目录输出一份调试叠加图",
    )
    parser.add_argument("--layout", type=Path, default=None, help="自定义布局 JSON 路径（可选）")
    parser.add_argument("--title-color", type=str, default=None, help="主标题颜色 hex，如 #E0B153（可选）")
    parser.add_argument("--subtitle-color", type=str, default=None, help="副标题颜色 hex（可选）")
    parser.add_argument("--title-font", type=str, default="youth", help="标题字体：youth(新青年粗体)/serif_bold(宋体粗体)/sans_bold(黑体粗体)（可选）")
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pixel_sha256(path: Path) -> str:
    with Image.open(path) as image:
        normalized = image.convert("RGBA")
        digest = hashlib.sha256()
        digest.update(f"{normalized.width}x{normalized.height}:RGBA".encode("ascii"))
        digest.update(normalized.tobytes())
        return digest.hexdigest()


def load_layout(custom_path: Path | None = None) -> dict[str, object]:
    path = custom_path if custom_path is not None else LAYOUT_PATH
    if not path.is_file():
        raise FileNotFoundError(f"布局配置缺失：{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def select_font(kind: str) -> Path:
    candidates: list[Path] = []
    configured = os.environ.get(FONT_ENV[kind])
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(FONT_FILES[kind])
    if kind == "youth":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "Microsoft" / "Windows" / "Fonts" / "文悦新青年体 简体 (需授权) W8.otf")
    candidates.extend(SYSTEM_FONT_CANDIDATES[kind])
    for path in candidates:
        if path.is_file():
            return path
    checked = ", ".join(str(path) for path in candidates)
    if kind == "youth":
        raise FileNotFoundError(
            "缺少已授权的新青年体标题字体。请把字体放入 assets/fonts，"
            "或设置 PUBLIC_COURSE_FONT_YOUTH。为避免改变固定模板，脚本不会静默替换该字体。"
        )
    raise FileNotFoundError(f"缺少字体角色 {kind}。已检查：{checked}")


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(select_font(kind)), size=size)


def normalize_lines(value: object, field: str, minimum: int, maximum: int) -> list[str]:
    if isinstance(value, str):
        lines = [line.strip() for line in value.splitlines() if line.strip()]
    elif isinstance(value, list):
        lines = [str(line).strip() for line in value if str(line).strip()]
    else:
        raise TypeError(f"{field} 必须是字符串或字符串数组")
    if not minimum <= len(lines) <= maximum:
        raise ValueError(f"{field} 必须包含 {minimum} 至 {maximum} 行")
    return lines


def normalize_core_points(value: object) -> list[str]:
    source: Iterable[object]
    if isinstance(value, str):
        source = [value]
    elif isinstance(value, list):
        source = value
    else:
        raise TypeError("core_points 必须是字符串或字符串数组")

    points: list[str] = []
    for item in source:
        for fragment in CORE_SPLIT.split(str(item)):
            cleaned = fragment.strip(EDGE_PUNCTUATION)
            if cleaned:
                points.append(cleaned)
    if not 2 <= len(points) <= 3:
        raise ValueError("核心内容拆分后必须为 2 至 3 条；请先根据完整材料提炼，禁止脚本编造或删改事实")
    return points


def normalize_face_box(value: object) -> list[int]:
    if not isinstance(value, list) or len(value) != 4:
        raise TypeError("portrait_face_box 必须是 [左, 上, 右, 下] 四个整数")
    try:
        box = [int(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise TypeError("portrait_face_box 必须是 [左, 上, 右, 下] 四个整数") from exc
    left, top, right, bottom = box
    if not (0 <= left < right <= 1024 and 0 <= top < bottom <= 1536):
        raise ValueError("portrait_face_box 必须位于 1024×1536 画布内且宽高为正")
    return box


def normalize_sources(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError("background_sources 必须至少记录一项最终使用的背景素材")
    required = {"source", "element", "license", "usage", "contains_person"}
    text_fields = required - {"contains_person"}
    sources: list[dict[str, object]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"background_sources 第 {index} 项必须是对象")
        missing = sorted(required - item.keys())
        if missing:
            raise ValueError(f"background_sources 第 {index} 项缺少：{', '.join(missing)}")
        if not isinstance(item["contains_person"], bool):
            raise TypeError(f"background_sources 第 {index} 项的 contains_person 必须是 true 或 false")
        record: dict[str, object] = {
            str(key): str(content).strip() for key, content in item.items() if key != "contains_person"
        }
        record["contains_person"] = item["contains_person"]
        empty = sorted(key for key in text_fields if not record.get(key))
        if empty:
            raise ValueError(f"background_sources 第 {index} 项不能为空：{', '.join(empty)}")
        sources.append(record)
    if not any(record["contains_person"] is False for record in sources):
        raise ValueError(
            "背景素材至少需要一张不含人物的干净真实地点照片；"
            "禁止把含嘉宾照片作为唯一背景并用大面积生成式补洞擦除人物"
        )
    return sources


def load_data(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = sorted(REQUIRED_KEYS - payload.keys())
    if missing:
        raise ValueError(f"缺少必需字段：{', '.join(missing)}")
    forbidden = sorted(FORBIDDEN_KEYS & payload.keys())
    if forbidden:
        raise ValueError(f"以下固定模板字段不得由 JSON 覆盖：{', '.join(forbidden)}")

    scope = str(payload["location_scope"]).strip().lower()
    if scope not in BRANDS:
        raise ValueError("location_scope 只能是 china 或 world；地点归属不明确时请先询问用户")
    payload["location_scope"] = scope
    payload["title_lines"] = normalize_lines(payload["title_lines"], "title_lines", 1, 2)
    payload["guest_intro"] = normalize_lines(payload["guest_intro"], "guest_intro", 1, 2)
    payload["core_points"] = normalize_core_points(payload["core_points"])
    payload["portrait_face_box"] = normalize_face_box(payload["portrait_face_box"])
    payload["background_sources"] = normalize_sources(payload["background_sources"])
    panel_theme = str(payload.get("panel_theme", "dark_teal")).strip().lower()
    if panel_theme not in PANEL_THEMES:
        raise ValueError(f"panel_theme 只能是：{', '.join(PANEL_THEMES)}")
    payload["panel_theme"] = panel_theme

    for key in REQUIRED_KEYS - {"title_lines", "guest_intro", "core_points", "portrait_face_box", "background_sources"}:
        value = str(payload[key]).strip()
        if not value:
            raise ValueError(f"字段不能为空：{key}")
        payload[key] = value
    if len(str(payload["guest_name"])) > 6:
        raise ValueError("嘉宾姓名超过 6 个汉字，请缩短")
    return payload


def open_background(path: Path, canvas: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.size != canvas:
            raise ValueError(f"背景尺寸必须为 {canvas[0]}×{canvas[1]}，禁止自动裁切：当前为 {image.size}")
        return image.convert("RGBA")


def open_portrait(path: Path, canvas: tuple[int, int]) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        if image.size != canvas:
            raise ValueError(f"人物层尺寸必须为 {canvas[0]}×{canvas[1]}：当前为 {image.size}")
        if "A" not in image.getbands():
            raise ValueError("人物层必须是带透明通道的 RGBA PNG")
        return image.convert("RGBA")


def rec709_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def pixel_data(image: Image.Image):
    """兼容当前与旧版 Pillow 的只读像素迭代接口。"""
    if hasattr(image, "get_flattened_data"):
        return image.get_flattened_data()
    return image.getdata()


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("无法计算空像素区域")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def background_brightness(image: Image.Image) -> dict[str, float]:
    sample = image.convert("RGB").resize((256, 384), Image.Resampling.LANCZOS)
    values = [rec709_luminance(pixel) for pixel in pixel_data(sample)]
    return {
        "mean": round(statistics.fmean(values), 2),
        "quartile_25": round(percentile(values, 0.25), 2),
    }


def adjacent_seam_metrics(grayscale: Image.Image) -> dict[str, object]:
    width, height = grayscale.size
    row_difference = ImageChops.difference(
        grayscale.crop((0, 1, width, height)),
        grayscale.crop((0, 0, width, height - 1)),
    )
    row_pixels = list(pixel_data(row_difference))
    row_means = [
        statistics.fmean(row_pixels[index * width : (index + 1) * width])
        for index in range(height - 1)
    ]

    column_width = width - 1
    column_difference = ImageChops.difference(
        grayscale.crop((1, 0, width, height)),
        grayscale.crop((0, 0, width - 1, height)),
    )
    column_sums = [0] * column_width
    for index, value in enumerate(pixel_data(column_difference)):
        column_sums[index % column_width] += value
    column_means = [total / height for total in column_sums]

    maximum_row = max(row_means)
    maximum_column = max(column_means)
    return {
        "maximum_adjacent_row_difference": round(maximum_row, 2),
        "maximum_adjacent_row_y": row_means.index(maximum_row) + 1,
        "maximum_adjacent_column_difference": round(maximum_column, 2),
        "maximum_adjacent_column_x": column_means.index(maximum_column) + 1,
    }


def top_column_metrics(image: Image.Image, rules: dict[str, object]) -> list[dict[str, float]]:
    zone = [int(value) for value in rules["top_band"]]
    band = image.crop(tuple(zone)).convert("L")
    target_width = 256
    target_height = max(1, round(band.height * target_width / band.width))
    band = band.resize((target_width, target_height), Image.Resampling.LANCZOS)
    edges = band.filter(ImageFilter.FIND_EDGES)
    count = int(rules["top_column_count"])
    results: list[dict[str, float]] = []
    inset = 2
    for index in range(count):
        left = round(index * target_width / count)
        right = round((index + 1) * target_width / count)
        box = (left + inset, inset, right - inset, target_height - inset)
        luminance = band.crop(box)
        edge = edges.crop(box)
        results.append(
            {
                "column": index + 1,
                "luminance_stddev": round(statistics.pstdev(pixel_data(luminance)), 2),
                "edge_mean": round(statistics.fmean(pixel_data(edge)), 2),
            }
        )
    return results


def background_density(image: Image.Image, rules: dict[str, object]) -> dict[str, object]:
    zone = [int(value) for value in rules["upper_zone"]]
    upper = image.crop(tuple(zone)).convert("L")
    target_width = 256
    target_height = max(1, round(upper.height * target_width / upper.width))
    upper = upper.resize((target_width, target_height), Image.Resampling.LANCZOS)
    luminances = list(pixel_data(upper))
    inset = 3
    edges = upper.filter(ImageFilter.FIND_EDGES).crop(
        (inset, inset, upper.width - inset, upper.height - inset)
    )
    result: dict[str, object] = {
        "upper_luminance_stddev": round(statistics.pstdev(luminances), 2),
        "upper_edge_mean": round(statistics.fmean(pixel_data(edges)), 2),
        "top_columns": top_column_metrics(image, rules),
    }
    result.update(adjacent_seam_metrics(image.crop(tuple(zone)).convert("L")))
    return result


def validate_background_density(metrics: dict[str, object], rules: dict[str, object]) -> None:
    stddev = float(metrics["upper_luminance_stddev"])
    edge_mean = float(metrics["upper_edge_mean"])
    minimum_stddev = float(rules["minimum_luminance_stddev"])
    minimum_edge = float(rules["minimum_edge_mean"])
    if stddev < minimum_stddev or edge_mean < minimum_edge:
        raise ValueError(
            "海报上半部过于空旷："
            f"亮度层次 {stddev}（至少 {minimum_stddev}），结构细节 {edge_mean}（至少 {minimum_edge}）。"
            "请把真实地点素材或低对比地标向上移动到 y=80–650，并保持标题可读"
        )
    minimum_column_stddev = float(rules["minimum_top_column_luminance_stddev"])
    minimum_column_edge = float(rules["minimum_top_column_edge_mean"])
    weak_columns = [
        item
        for item in metrics["top_columns"]
        if float(item["luminance_stddev"]) < minimum_column_stddev
        or float(item["edge_mean"]) < minimum_column_edge
    ]
    if weak_columns:
        details = "；".join(
            f"第{item['column']}栏层次{item['luminance_stddev']}、结构{item['edge_mean']}"
            for item in weak_columns
        )
        raise ValueError(
            "海报顶部素材分布不均："
            f"{details}。每栏层次至少 {minimum_column_stddev}、结构至少 {minimum_column_edge}；"
            "请把真实地点素材向上并横向铺开，禁止用纯色、模糊矩形或简单渐变占位"
        )
    maximum_row = float(metrics["maximum_adjacent_row_difference"])
    maximum_column = float(metrics["maximum_adjacent_column_difference"])
    row_limit = float(rules["maximum_upper_adjacent_row_difference"])
    column_limit = float(rules["maximum_upper_adjacent_column_difference"])
    if maximum_row > row_limit or maximum_column > column_limit:
        raise ValueError(
            "背景检测到贯穿式拼贴硬接缝："
            f"横向最大突变 {maximum_row}（y={metrics['maximum_adjacent_row_y']}，上限 {row_limit}），"
            f"纵向最大突变 {maximum_column}（x={metrics['maximum_adjacent_column_x']}，上限 {column_limit}）。"
            "请移除矩形补丁、拉丝、复制块和硬边蒙版，改用自然遮挡或重新选择干净实景素材"
        )


def subtitle_background_metrics(
    image: Image.Image,
    zone: list[int],
    rules: dict[str, object],
) -> dict[str, float]:
    x1, y1, x2, y2 = [int(value) for value in zone]
    grayscale = image.convert("L")
    center = grayscale.crop((x1, y1, x2, y2))
    center_values = list(pixel_data(center))
    threshold = int(rules["dark_band_luminance"])
    dark_fraction = sum(value < threshold for value in center_values) / len(center_values)
    neighbor_height = min(32, y1, image.height - y2)
    upper = grayscale.crop((x1, y1 - neighbor_height, x2, y1))
    lower = grayscale.crop((x1, y2, x2, y2 + neighbor_height))
    center_mean = statistics.fmean(center_values)
    neighbor_mean = statistics.fmean([*pixel_data(upper), *pixel_data(lower)])
    return {
        "mean_luminance": round(center_mean, 2),
        "dark_fraction": round(dark_fraction, 4),
        "neighbor_mean_luminance": round(neighbor_mean, 2),
        "neighbor_drop": round(neighbor_mean - center_mean, 2),
    }


def validate_subtitle_background(
    metrics: dict[str, float],
    rules: dict[str, object],
    preset: str,
) -> None:
    dark_fraction = metrics["dark_fraction"]
    neighbor_drop = metrics["neighbor_drop"]
    if (
        dark_fraction > float(rules["maximum_dark_fraction"])
        and neighbor_drop > float(rules["maximum_neighbor_drop"])
    ):
        raise ValueError(
            f"副标题预设区域 {preset} 检测到横向深色底带："
            f"暗像素占比 {dark_fraction:.1%}，比上下邻区暗 {neighbor_drop:.1f}。"
            "副标题必须直接叠加在自然背景上，禁止黑色、深青色或半透明长条底板"
        )


def validate_background_brightness(metrics: dict[str, float], rules: dict[str, float]) -> None:
    mean = metrics["mean"]
    quartile = metrics["quartile_25"]
    if not rules["mean_min"] <= mean <= rules["mean_max"]:
        raise ValueError(
            f"背景平均亮度为 {mean}，必须位于 {rules['mean_min']}–{rules['mean_max']}；请调整为自然明亮效果"
        )
    if quartile < rules["quartile_min"]:
        raise ValueError(
            f"背景 25% 分位亮度为 {quartile}，不得低于 {rules['quartile_min']}；暗部过重，请提亮"
        )


def validate_portrait(
    image: Image.Image,
    rules: dict[str, object],
    face_box: list[int],
) -> dict[str, object]:
    alpha = image.getchannel("A")
    threshold = alpha.point(lambda value: 255 if value >= 16 else 0)
    bbox = threshold.getbbox()
    if bbox is None:
        raise ValueError("人物层没有可见人物像素")
    if alpha.getextrema() == (255, 255):
        raise ValueError("人物层完全不透明，必须移除照片背景")
    alpha_values = list(pixel_data(alpha))
    visible_count = sum(value > 0 for value in alpha_values)
    solid_visible_count = sum(value >= 16 for value in alpha_values)
    faint_count = sum(0 < value < 16 for value in alpha_values)
    transition_count = sum(16 <= value < 250 for value in alpha_values)
    coverage = solid_visible_count / (image.width * image.height)
    faint_fraction = faint_count / visible_count
    transition_fraction = transition_count / solid_visible_count
    if faint_fraction > float(rules["maximum_faint_alpha_fraction"]):
        raise ValueError(
            f"人物微弱透明残留占非零像素 {faint_fraction:.1%}，"
            f"不得超过 {float(rules['maximum_faint_alpha_fraction']):.0%}；"
            "疑似残留照片背景，请重新清理透明蒙版"
        )
    if transition_fraction > float(rules["maximum_transition_alpha_fraction"]):
        raise ValueError(
            f"人物半透明过渡占可见像素 {transition_fraction:.1%}，"
            f"不得超过 {float(rules['maximum_transition_alpha_fraction']):.0%}；"
            "疑似肩膀或衣物过度羽化，请重新抠图并保持实体边缘清晰"
        )
    color_mismatch_fraction = portrait_edge_color_mismatch_fraction(image)
    if color_mismatch_fraction > float(rules["maximum_edge_color_mismatch_fraction"]):
        raise ValueError(
            f"人物半透明边缘中有 {color_mismatch_fraction:.1%} 与内侧前景颜色严重不一致，"
            f"不得超过 {float(rules['maximum_edge_color_mismatch_fraction']):.0%}；"
            "疑似残留白边、天空蓝边、草木绿边、砖瓦红边或普通 RGBA 缩放串色，请在原分辨率精修并做边缘去色污染"
        )
    safe_margin = int(rules["safe_margin"])
    if bbox[0] < safe_margin:
        raise ValueError(
            f"人物左侧安全边距仅 {bbox[0]}px，至少需要 {safe_margin}px；禁止裁掉头发、手臂、衣袖或随身物品"
        )
    rightmost_x = bbox[2] - 1
    if rightmost_x > int(rules["right_limit"]):
        raise ValueError(f"人物最右可见像素为 x={rightmost_x}，不得超过 x={rules['right_limit']}；禁止进入嘉宾卡区域")
    if bool(rules["must_touch_bottom"]) and bbox[3] != image.height:
        raise ValueError(f"人物必须触底 y={image.height}，当前最下像素为 y={bbox[3]}")
    if not int(rules["top_min"]) <= bbox[1] <= int(rules["top_max"]):
        raise ValueError(
            f"人物头顶/最上像素为 y={bbox[1]}，必须位于 {rules['top_min']}–{rules['top_max']}"
        )
    if coverage > float(rules["maximum_coverage"]):
        raise ValueError(
            f"人物不透明面积占画布 {coverage:.1%}，不得超过 {float(rules['maximum_coverage']):.0%}"
        )
    face_center = [round((face_box[0] + face_box[2]) / 2), round((face_box[1] + face_box[3]) / 2)]
    target_x, target_y = [int(value) for value in rules["face_center"]]
    tolerance = int(rules["face_center_tolerance"])
    if abs(face_center[0] - target_x) > tolerance or abs(face_center[1] - target_y) > tolerance:
        raise ValueError(
            f"脸部中心为 ({face_center[0]},{face_center[1]})，必须接近 ({target_x},{target_y})，允许误差 ±{tolerance}px"
        )
    face_height = face_box[3] - face_box[1]
    height_min, height_max = [int(value) for value in rules["face_height"]]
    if not height_min <= face_height <= height_max:
        raise ValueError(f"脸框高度为 {face_height}px，必须位于 {height_min}–{height_max}px")
    return {
        "alpha_bbox": list(bbox),
        "coverage": round(coverage, 4),
        "faint_alpha_fraction": round(faint_fraction, 4),
        "transition_alpha_fraction": round(transition_fraction, 4),
        "edge_color_mismatch_fraction": round(color_mismatch_fraction, 4),
        "touches_bottom": bbox[3] == image.height,
        "left_safe_margin": bbox[0],
        "top_safe_margin": bbox[1],
        "right_safe_margin": image.width - bbox[2],
        "rightmost_x": rightmost_x,
        "face_box": face_box,
        "face_center": face_center,
        "face_height": face_height,
    }


def portrait_edge_color_mismatch_fraction(image: Image.Image) -> float:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    alpha_pixels = alpha.load()
    color_pixels = rgba.load()
    width, height = rgba.size
    mismatch_count = 0
    sample_count = 0
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            opacity = alpha_pixels[x, y]
            if not 16 <= opacity < 250:
                continue
            if max(
                alpha_pixels[x - 1, y],
                alpha_pixels[x + 1, y],
                alpha_pixels[x, y - 1],
                alpha_pixels[x, y + 1],
            ) < 250:
                continue
            neighbors = []
            for neighbor_y in range(max(0, y - 3), min(height, y + 4)):
                for neighbor_x in range(max(0, x - 3), min(width, x + 4)):
                    if alpha_pixels[neighbor_x, neighbor_y] >= 250:
                        neighbors.append(color_pixels[neighbor_x, neighbor_y][:3])
            if len(neighbors) < 3:
                continue
            reference = tuple(statistics.median(color[index] for color in neighbors) for index in range(3))
            current = color_pixels[x, y][:3]
            color_distance = math.sqrt(sum((current[index] - reference[index]) ** 2 for index in range(3)))
            reference_luminance = rec709_luminance(reference)
            current_luminance = rec709_luminance(current)
            sample_count += 1
            if color_distance > 50 or abs(current_luminance - reference_luminance) > 35:
                mismatch_count += 1
    return mismatch_count / sample_count if sample_count else 0.0


def portrait_proof(image: Image.Image) -> Image.Image:
    panel_size = image.size
    portrait = image
    white = Image.new("RGBA", panel_size, (246, 246, 242, 255))
    teal = Image.new("RGBA", panel_size, COLORS["teal"])
    checker = Image.new("RGBA", panel_size, (210, 210, 210, 255))
    checker_draw = ImageDraw.Draw(checker)
    tile = 32
    for y in range(0, panel_size[1], tile):
        for x in range(0, panel_size[0], tile):
            if (x // tile + y // tile) % 2:
                checker_draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(150, 150, 150, 255))
    proof = Image.new("RGB", (panel_size[0] * 3, panel_size[1]), (255, 255, 255))
    for index, background in enumerate((white, checker, teal)):
        background.alpha_composite(portrait)
        proof.paste(background.convert("RGB"), (index * panel_size[0], 0))
    return proof


def portrait_edge_proof(image: Image.Image) -> Image.Image:
    alpha = image.getchannel("A")
    visible = alpha.point(lambda value: 255 if value >= 16 else 0).getbbox()
    if visible is None:
        raise ValueError("无法为没有可见像素的人物层生成边缘校样")
    left = max(0, visible[0] - 20)
    right = min(image.width, visible[2] + 20)
    height = visible[3] - visible[1]
    ranges = (
        (visible[1], min(visible[3], round(visible[1] + height * 0.38))),
        (round(visible[1] + height * 0.25), min(visible[3], round(visible[1] + height * 0.72))),
        (round(visible[1] + height * 0.55), visible[3]),
    )
    scale = 4
    gap = 24
    crops = []
    for top, bottom in ranges:
        crop = image.crop((left, top, right, bottom))
        checker = Image.new("RGBA", crop.size, (232, 232, 232, 255))
        checker_draw = ImageDraw.Draw(checker)
        tile = 12
        for y in range(0, crop.height, tile):
            for x in range(0, crop.width, tile):
                if (x // tile + y // tile) % 2:
                    checker_draw.rectangle((x, y, x + tile - 1, y + tile - 1), fill=(95, 95, 95, 255))
        checker.alpha_composite(crop)
        crops.append(checker.convert("RGB").resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST))
    proof_width = max(crop.width for crop in crops)
    proof_height = sum(crop.height for crop in crops) + gap * (len(crops) - 1)
    proof = Image.new("RGB", (proof_width, proof_height), (20, 20, 20))
    y = 0
    for crop in crops:
        proof.paste(crop, ((proof_width - crop.width) // 2, y))
        y += crop.height + gap
    return proof


def srgb_channel(value: int) -> float:
    normalized = value / 255.0
    return normalized / 12.92 if normalized <= 0.04045 else ((normalized + 0.055) / 1.055) ** 2.4


def relative_luminance(color: tuple[int, int, int, int]) -> float:
    r, g, b, _ = color
    return 0.2126 * srgb_channel(r) + 0.7152 * srgb_channel(g) + 0.0722 * srgb_channel(b)


def contrast_ratio(first: float, second: float) -> float:
    lighter = max(first, second)
    darker = min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def crop_relative_luminances(image: Image.Image, zone: list[int]) -> list[float]:
    crop = image.crop(tuple(zone)).convert("RGB")
    target_width = min(216, crop.width)
    target_height = max(1, round(crop.height * target_width / crop.width))
    crop = crop.resize((target_width, target_height), Image.Resampling.LANCZOS)
    return [relative_luminance((*pixel, 255)) for pixel in pixel_data(crop)]


def candidate_scores(image: Image.Image, zone: list[int]) -> list[tuple[float, tuple[int, int, int, int]]]:
    background_values = crop_relative_luminances(image, zone)
    results = []
    for candidate in TITLE_CANDIDATES:
        foreground = relative_luminance(candidate)
        ratios = [contrast_ratio(foreground, value) for value in background_values]
        results.append((percentile(ratios, 0.10), candidate))
    return sorted(results, key=lambda item: item[0], reverse=True)


def apply_feathered_adjustment(
    image: Image.Image,
    zone: list[int],
    mode: str,
    strength: float,
) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    padding_x, padding_y = 28, 22
    box = (
        max(0, zone[0] - padding_x),
        max(0, zone[1] - padding_y),
        min(image.width, zone[2] + padding_x),
        min(image.height, zone[3] + padding_y),
    )
    mask_draw.rounded_rectangle(box, radius=28, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=34))
    mask = mask.point(lambda value: round(value * strength))
    overlay_color = COLORS["teal"] if mode == "darken" else COLORS["cream"]
    overlay = Image.new("RGBA", image.size, overlay_color)
    return Image.composite(overlay, image, mask)


def ensure_contrast(
    image: Image.Image,
    zone: list[int],
    minimum: float,
    allow_adjustment: bool = True,
) -> tuple[Image.Image, tuple[int, int, int, int], float, dict[str, object]]:
    best_score, best_color = candidate_scores(image, zone)[0]
    if best_score >= minimum:
        return image, best_color, best_score, {"mode": "none", "strength": 0.0}

    if not allow_adjustment:
        raise ValueError(
            f"副标题四色均无法达到 {minimum}:1 对比度；禁止添加横向明暗底板，请重新规划副标题区域背景"
        )

    for strength in (0.15, 0.25, 0.35, 0.45):
        passing: list[tuple[float, tuple[int, int, int, int], str, Image.Image]] = []
        for mode in ("darken", "lighten"):
            adjusted = apply_feathered_adjustment(image, zone, mode, strength)
            score, color = candidate_scores(adjusted, zone)[0]
            if score >= minimum:
                passing.append((score, color, mode, adjusted))
        if passing:
            score, color, mode, adjusted = max(passing, key=lambda item: item[0])
            return adjusted, color, score, {"mode": mode, "strength": strength}
    raise ValueError(f"四色与局部明暗调整后仍无法达到 {minimum}:1 对比度；请更换或重新规划背景")


def color_hex(color: tuple[int, int, int, int]) -> str:
    return "#" + "".join(f"{value:02X}" for value in color[:3])


def text_width(value: str, face: ImageFont.FreeTypeFont, tracking: int = 0) -> float:
    if not value:
        return 0.0
    return sum(face.getlength(character) for character in value) + tracking * (len(value) - 1)


def require_width(value: str, face: ImageFont.FreeTypeFont, maximum: int, field: str, tracking: int = 0) -> None:
    width = text_width(value, face, tracking)
    if width > maximum:
        raise ValueError(f"{field} 超出固定宽度：{value}（{width:.1f}px > {maximum}px）；请压缩文案，禁止缩字号")


def optimize_title_lines(data: dict[str, object], layout: dict[str, object]) -> dict[str, object]:
    title_cfg = dict(layout["title"])
    original = list(data["title_lines"])
    optimized = original
    merged = False
    if len(original) == 2:
        candidate = "".join(original)
        title_face = font("youth", int(title_cfg["font_size"]))
        if text_width(candidate, title_face, int(title_cfg["tracking"])) <= int(title_cfg["max_width"]):
            optimized = [candidate]
            merged = True
    data["title_lines"] = optimized
    return {
        "input_line_count": len(original),
        "output_line_count": len(optimized),
        "merged_to_one_line": merged,
    }


def title_and_subtitle_geometry(
    data: dict[str, object],
    layout: dict[str, object],
) -> dict[str, object]:
    line_count = len(data["title_lines"])
    key = str(line_count)
    title_cfg = dict(layout["title"])
    subtitle_cfg = dict(layout["subtitle"])
    title_positions = title_cfg["one_line_y"] if line_count == 1 else title_cfg["two_line_y"]
    last_line = str(data["title_lines"][-1])
    title_face = font("youth", int(title_cfg["font_size"]))
    bbox = title_face.getbbox(last_line)
    title_bottom = int(title_positions[-1]) + (bbox[3] - bbox[1])
    subtitle = str(data["subtitle"])
    subtitle_face = font("youth", int(subtitle_cfg["font_size"]))
    subtitle_bbox = subtitle_face.getbbox(subtitle)
    subtitle_visual_height = subtitle_bbox[3] - subtitle_bbox[1]
    subtitle_center = int(subtitle_cfg["center_y_by_title_line_count"][key])
    subtitle_visual_top = round(subtitle_center - subtitle_visual_height / 2)
    gap = subtitle_visual_top - title_bottom
    minimum_gap = int(subtitle_cfg["minimum_title_gap"])
    if gap < minimum_gap:
        raise ValueError(f"主标题与副标题文字仅间隔 {gap}px，至少需要 {minimum_gap}px")
    return {
        "title_line_count": line_count,
        "title_zone": list(title_cfg["zone_by_line_count"][key]),
        "subtitle_zone": list(subtitle_cfg["zone_by_title_line_count"][key]),
        "subtitle_center_y": subtitle_center,
        "subtitle_visual_top": subtitle_visual_top,
        "title_subtitle_gap": gap,
    }


def draw_tracked_top(
    draw: ImageDraw.ImageDraw,
    value: str,
    center_x: int,
    visual_top: int,
    face: ImageFont.FreeTypeFont,
    tracking: int,
    fill: tuple[int, int, int, int],
) -> None:
    width = text_width(value, face, tracking)
    bbox = face.getbbox(value)
    x = center_x - width / 2
    y = visual_top - bbox[1]
    for character in value:
        draw.text((round(x), round(y)), character, font=face, fill=fill)
        x += face.getlength(character) + tracking


def draw_tracked_center(
    draw: ImageDraw.ImageDraw,
    value: str,
    center: tuple[int, int],
    face: ImageFont.FreeTypeFont,
    tracking: int,
    fill: tuple[int, int, int, int],
) -> None:
    bbox = face.getbbox(value)
    visual_height = bbox[3] - bbox[1]
    draw_tracked_top(draw, value, center[0], round(center[1] - visual_height / 2), face, tracking, fill)


def draw_plain_top(
    draw: ImageDraw.ImageDraw,
    value: str,
    xy: tuple[int, int],
    face: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    maximum: int,
    field: str,
) -> None:
    require_width(value, face, maximum, field)
    bbox = face.getbbox(value)
    draw.text((xy[0], xy[1] - bbox[1]), value, font=face, fill=fill)


def panel_palette(data: dict[str, object]) -> dict[str, tuple[int, ...]]:
    return PANEL_THEMES[str(data["panel_theme"])]


def draw_card(
    draw: ImageDraw.ImageDraw,
    box: list[int],
    opacity: int,
    palette: dict[str, tuple[int, ...]],
) -> None:
    fill = tuple(palette["fill"][:3]) + (opacity,)
    draw.rounded_rectangle(tuple(box), radius=16, fill=fill, outline=palette["outline"], width=2)


def draw_brand(draw: ImageDraw.ImageDraw, data: dict[str, object], layout: dict[str, object]) -> None:
    box = list(layout["brand_box"])
    opacity = int(layout["panel_opacity"])
    palette = panel_palette(data)
    fill = tuple(palette["brand_fill"][:3]) + (opacity,)
    draw.rounded_rectangle(tuple(box), radius=5, fill=fill, outline=palette["outline"], width=2)
    brand = BRANDS[str(data["location_scope"])]
    face = font("serif_bold", int(layout["brand_font_size"]))
    require_width(brand, face, box[2] - box[0] - 44, "品牌文字")
    draw.text(
        ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
        brand,
        font=face,
        fill=palette["brand_text"],
        anchor="mm",
    )


def draw_titles(
    draw: ImageDraw.ImageDraw,
    data: dict[str, object],
    layout: dict[str, object],
    title_color: tuple[int, int, int, int],
    subtitle_color: tuple[int, int, int, int],
    title_font_kind: str = "youth",
) -> None:
    title_cfg = dict(layout["title"])
    title_face = font(title_font_kind, int(title_cfg["font_size"]))
    lines = list(data["title_lines"])
    for line in lines:
        require_width(line, title_face, int(title_cfg["max_width"]), "主标题", int(title_cfg["tracking"]))
    positions = title_cfg["one_line_y"] if len(lines) == 1 else title_cfg["two_line_y"]
    for line, visual_top in zip(lines, positions):
        draw_tracked_top(
            draw,
            line,
            512,
            int(visual_top),
            title_face,
            int(title_cfg["tracking"]),
            title_color,
        )

    subtitle_cfg = dict(layout["subtitle"])
    subtitle_face = font(title_font_kind, int(subtitle_cfg["font_size"]))
    subtitle = str(data["subtitle"])
    require_width(subtitle, subtitle_face, int(subtitle_cfg["max_width"]), "副标题", int(subtitle_cfg["tracking"]))
    preset_key = str(len(lines))
    draw_tracked_center(
        draw,
        subtitle,
        (512, int(subtitle_cfg["center_y_by_title_line_count"][preset_key])),
        subtitle_face,
        int(subtitle_cfg["tracking"]),
        subtitle_color,
    )


def draw_info_card(draw: ImageDraw.ImageDraw, data: dict[str, object], layout: dict[str, object]) -> None:
    cfg = dict(layout["info_card"])
    opacity = int(layout["panel_opacity"])
    palette = panel_palette(data)
    draw_card(draw, list(cfg["box"]), opacity, palette)
    left = int(cfg["inner_left"])
    maximum = int(cfg["inner_right"]) - left
    heading_face = font("sans_bold", int(cfg["heading_size"]))
    body_face = font("sans", int(cfg["body_size"]))

    guest_heading = f"分享嘉宾｜{data['guest_name']}"
    draw_plain_top(draw, guest_heading, (left, int(cfg["guest_heading_y"])), heading_face, palette["heading"], maximum, "分享嘉宾标题")
    guest_lines = [str(data["guest_identity"]), *list(data["guest_intro"])]
    guest_positions = list(cfg["guest_body_y"][str(len(guest_lines))])
    for value, y in zip(guest_lines, guest_positions):
        draw_plain_top(draw, value, (left, int(y)), body_face, palette["body"], maximum, "嘉宾正文")

    divider_y = int(cfg["divider_y"])
    draw.line((left, divider_y, int(cfg["inner_right"]), divider_y), fill=palette["outline"], width=1)
    draw_plain_top(draw, "核心内容", (left, int(cfg["core_heading_y"])), heading_face, palette["heading"], maximum, "核心内容标题")
    core_points = list(data["core_points"])
    core_positions = list(cfg["core_body_y"][str(len(core_points))])
    for value, y in zip(core_points, core_positions):
        draw_plain_top(draw, value, (left, int(y)), body_face, palette["body"], maximum, "核心内容正文")


def draw_clock(draw: ImageDraw.ImageDraw, center: tuple[int, int], color: tuple[int, ...]) -> None:
    x, y = center
    draw.ellipse((x - 14, y - 14, x + 14, y + 14), outline=color, width=2)
    draw.line((x, y, x, y - 8), fill=color, width=2)
    draw.line((x, y, x + 7, y + 4), fill=color, width=2)


def draw_pin(draw: ImageDraw.ImageDraw, center: tuple[int, int], color: tuple[int, ...]) -> None:
    x, y = center
    draw.ellipse((x - 10, y - 14, x + 10, y + 6), outline=color, width=2)
    draw.polygon([(x - 7, y + 3), (x + 7, y + 3), (x, y + 14)], fill=color)
    draw.ellipse((x - 3, y - 7, x + 3, y - 1), fill=color)


def draw_label_value(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    center_y: int,
    cfg: dict[str, object],
    palette: dict[str, tuple[int, ...]],
) -> None:
    face_label = font("sans_bold", int(cfg["font_size"]))
    face_value = font("sans", int(cfg["font_size"]))
    label_x = int(cfg["label_x"])
    right = int(cfg["right"])
    label_bbox = face_label.getbbox(label)
    label_y = center_y - (label_bbox[1] + label_bbox[3]) / 2
    draw.text((label_x, label_y), label, font=face_label, fill=palette["heading"])
    value_x = round(label_x + face_label.getlength(label) + 8)
    require_width(value, face_value, right - value_x, label.rstrip("｜"))
    value_bbox = face_value.getbbox(value)
    value_y = center_y - (value_bbox[1] + value_bbox[3]) / 2
    draw.text((value_x, value_y), value, font=face_value, fill=palette["body"])


def draw_time_card(draw: ImageDraw.ImageDraw, data: dict[str, object], layout: dict[str, object]) -> None:
    cfg = dict(layout["time_card"])
    palette = panel_palette(data)
    draw_card(draw, list(cfg["box"]), int(layout["panel_opacity"]), palette)
    time_center_y = int(cfg["time_center_y"])
    location_center_y = int(cfg["location_center_y"])
    draw_clock(draw, (int(cfg["icon_x"]), time_center_y), palette["icon"])
    draw_pin(draw, (int(cfg["icon_x"]), location_center_y), palette["icon"])
    draw_label_value(draw, "课程时间｜", str(data["event_time"]), time_center_y, cfg, palette)
    draw_label_value(draw, "课程地点｜", str(data["course_location"]), location_center_y, cfg, palette)


def draw_debug_overlay(
    image: Image.Image,
    layout: dict[str, object],
    portrait_metrics: dict[str, object],
    geometry: dict[str, object],
) -> Image.Image:
    debug = image.copy()
    draw = ImageDraw.Draw(debug, "RGBA")
    debug_font = font("sans_bold", 20)
    rectangles = [
        (layout["brand_box"], "品牌", (255, 70, 70, 255)),
        (geometry["title_zone"], "主标题区", (50, 220, 255, 255)),
        (geometry["subtitle_zone"], "副标题区", (100, 255, 130, 255)),
        (layout["info_card"]["box"], "嘉宾卡", (255, 200, 50, 255)),
        (layout["time_card"]["box"], "时间地点卡", (255, 150, 50, 255)),
        (portrait_metrics["alpha_bbox"], "人物透明边界", (255, 60, 210, 255)),
        (portrait_metrics["face_box"], "脸框测量", (170, 40, 255, 255)),
    ]
    for box, label, color in rectangles:
        draw.rectangle(tuple(box), outline=color, width=3)
        draw.rectangle((box[0], box[1], box[0] + 150, box[1] + 28), fill=(0, 0, 0, 170))
        draw.text((box[0] + 5, box[1] + 3), label, font=debug_font, fill=color)
    face_x, face_y = layout["portrait"]["face_center"]
    tolerance = int(layout["portrait"]["face_center_tolerance"])
    draw.ellipse((face_x - tolerance, face_y - tolerance, face_x + tolerance, face_y + tolerance), outline=(255, 0, 255, 255), width=3)
    time_cfg = layout["time_card"]
    for center_y in (int(time_cfg["time_center_y"]), int(time_cfg["location_center_y"])):
        draw.line(
            (int(time_cfg["box"][0]), center_y, int(time_cfg["box"][2]), center_y),
            fill=(80, 255, 255, 190),
            width=1,
        )
    return debug


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def hex_to_rgba(hex_str: str) -> tuple[int, int, int, int]:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) != 6:
        raise ValueError(f"颜色 hex 必须是 6 位：{hex_str}")
    return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16), 255)


def render(
    base_path: Path,
    portrait_path: Path,
    data_path: Path,
    out_path: Path,
    export_debug: bool,
    layout_path: Path | None = None,
    title_color_hex: str | None = None,
    subtitle_color_hex: str | None = None,
    title_font_kind: str = "youth",
) -> None:
    layout = load_layout(layout_path)
    canvas = tuple(layout["canvas"])
    data = load_data(data_path)
    title_optimization = optimize_title_lines(data, layout)
    title_geometry = title_and_subtitle_geometry(data, layout)
    base = open_background(base_path, canvas)
    portrait = open_portrait(portrait_path, canvas)

    brightness = background_brightness(base)
    validate_background_brightness(brightness, dict(layout["background_brightness"]))
    density = background_density(base, dict(layout["background_density"]))
    validate_background_density(density, dict(layout["background_density"]))
    subtitle_cfg = dict(layout["subtitle"])
    subtitle_background: dict[str, dict[str, float]] = {}
    for preset, zone in subtitle_cfg["zone_by_title_line_count"].items():
        metrics = subtitle_background_metrics(base, list(zone), subtitle_cfg)
        validate_subtitle_background(metrics, subtitle_cfg, str(preset))
        subtitle_background[str(preset)] = metrics
    portrait_metrics = validate_portrait(portrait, dict(layout["portrait"]), list(data["portrait_face_box"]))

    title_cfg = dict(layout["title"])
    if title_color_hex is not None:
        title_color = hex_to_rgba(title_color_hex)
        title_contrast = 0.0
        title_adjustment = {"mode": "none", "strength": 0.0}
    else:
        base, title_color, title_contrast, title_adjustment = ensure_contrast(
            base, list(title_geometry["title_zone"]), float(title_cfg["minimum_contrast"])
        )
    if subtitle_color_hex is not None:
        subtitle_color = hex_to_rgba(subtitle_color_hex)
        subtitle_contrast = 0.0
        subtitle_adjustment = {"mode": "none", "strength": 0.0}
    else:
        base, subtitle_color, subtitle_contrast, subtitle_adjustment = ensure_contrast(
            base,
            list(title_geometry["subtitle_zone"]),
            float(subtitle_cfg["minimum_contrast"]),
            bool(subtitle_cfg["allow_background_adjustment"]),
        )

    base.alpha_composite(portrait)
    draw = ImageDraw.Draw(base, "RGBA")
    draw_brand(draw, data, layout)
    draw_titles(draw, data, layout, title_color, subtitle_color, title_font_kind)
    draw_info_card(draw, data, layout)
    draw_time_card(draw, data, layout)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    base.convert("RGB").save(out_path, format="PNG", optimize=True)

    work_dir = out_path.parent / f"{out_path.stem}_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "canvas": list(canvas),
        "location_scope": data["location_scope"],
        "brand": BRANDS[str(data["location_scope"])],
        "font": {
            "title_and_subtitle": select_font("youth").name,
            "title_size": title_cfg["font_size"],
            "title_tracking": title_cfg["tracking"],
            "subtitle_size": subtitle_cfg["font_size"],
            "subtitle_tracking": subtitle_cfg["tracking"],
        },
        "selected_colors": {
            "title": color_hex(title_color),
            "subtitle": color_hex(subtitle_color),
            "panel_theme": data["panel_theme"],
        },
        "contrast": {
            "title": round(title_contrast, 3),
            "subtitle": round(subtitle_contrast, 3),
            "title_adjustment": title_adjustment,
            "subtitle_adjustment": subtitle_adjustment,
        },
        "title_optimization": title_optimization,
        "title_geometry": title_geometry,
        "layout": layout,
    }
    audit = {
        "automatic_status": "passed",
        "output": str(out_path.resolve()),
        "canvas": list(canvas),
        "background_brightness": brightness,
        "background_density": density,
        "subtitle_background": subtitle_background,
        "portrait": portrait_metrics,
        "time_card_alignment": {
            "time_center_y": layout["time_card"]["time_center_y"],
            "location_center_y": layout["time_card"]["location_center_y"],
            "icon_label_value_share_center": True,
        },
        "content": {
            "title_line_count": len(data["title_lines"]),
            "guest_body_line_count": 1 + len(data["guest_intro"]),
            "core_line_count": len(data["core_points"]),
            "background_source_count": len(data["background_sources"]),
        },
        "provenance": {
            "renderer": {
                "path": str(Path(__file__).resolve()),
                "sha256": sha256_file(Path(__file__).resolve()),
            },
            "layout": {
                "path": str(LAYOUT_PATH.resolve()),
                "sha256": sha256_file(LAYOUT_PATH.resolve()),
            },
            "inputs": {
                "base": {"path": str(base_path.resolve()), "sha256": sha256_file(base_path.resolve())},
                "portrait": {"path": str(portrait_path.resolve()), "sha256": sha256_file(portrait_path.resolve())},
                "data": {"path": str(data_path.resolve()), "sha256": sha256_file(data_path.resolve())},
            },
            "output_pixel_sha256": pixel_sha256(out_path),
        },
        "manual_checks_required": [
            "人物层与原照片并排核对：全身照新增裁切只允许位于画布底边且只涉及超出的下半身或衣服下摆，左、右、上方没有新增裁切",
            "portrait-proof.png 在白色、棋盘格和深青底上按100%核对整个人物；portrait-edge-proof.png 按400%核对头发、耳侧、肩线、袖线和手指，无浅色/深色/彩色描边、锯齿、虚化或背景残片",
            "调试图中的脸框测量紧贴可见脸部，且人物与原照片身份一致",
            "人物、服装、道具和背景无品牌、活动文字、Logo或水印",
            "背景无水平/垂直硬接缝、矩形补丁、拉丝、复制/镜像块、重复地标和透视断裂；重要地标未被人物、标题或卡片遮挡",
            "背景史实、地点和素材许可已经核对",
            "四角无伪文字，姓名、履历、日期、时间和地点逐字正确",
        ],
    }
    write_json(work_dir / "layout-manifest.json", manifest)
    write_json(work_dir / "audit-report.json", audit)
    write_json(work_dir / "background-sources.json", {"sources": data["background_sources"]})
    portrait_proof(portrait).save(work_dir / "portrait-proof.png", format="PNG", optimize=True)
    portrait_edge_proof(portrait).save(work_dir / "portrait-edge-proof.png", format="PNG", optimize=True)
    debug = draw_debug_overlay(base, layout, portrait_metrics, title_geometry)
    debug.convert("RGB").save(work_dir / "debug-overlay.png", format="PNG", optimize=True)
    if export_debug:
        debug.convert("RGB").save(out_path.with_name(f"{out_path.stem}_debug.png"), format="PNG", optimize=True)

    with Image.open(out_path) as check:
        if check.size != canvas:
            raise RuntimeError(f"最终输出尺寸错误：{check.size}")
    print(f"已生成固定模板海报：{out_path.resolve()}")
    print(f"内部审计目录：{work_dir.resolve()}")


def main() -> None:
    args = parse_args()
    render(
        args.base,
        args.portrait,
        args.data,
        args.out,
        args.debug_overlay,
        layout_path=args.layout,
        title_color_hex=args.title_color,
        subtitle_color_hex=args.subtitle_color,
        title_font_kind=args.title_font,
    )


if __name__ == "__main__":
    main()
