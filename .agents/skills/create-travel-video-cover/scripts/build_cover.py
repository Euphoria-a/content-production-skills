#!/usr/bin/env python3
"""Build a packaged travel-video cover series and its contact-sheet thumbnail."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - environment-dependent
    raise SystemExit("Pillow is required. Run this script with a Python environment that includes Pillow.") from exc


W, H = 1024, 1365
PHOTO_W, PHOTO_H = 1024, 576
PHOTO_Y = (H - PHOTO_H) // 2
TITLE_LINE_GAP = 54  # 10pt at the current 1024px-canvas type scale
BODY_LINE_GAP = 11   # 2pt at the current 1024px-canvas type scale
TITLE_YELLOW = (255, 215, 0, 255)
BODY_WHITE = (255, 255, 255, 255)
GRADIENT_COOL = (6, 10, 18)
HANG_PUNCT = set("，。！？、：；")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FONT_FILENAME = "文悦新青年体 简体 (需授权) W8.otf"
CONNECTORS = ("与", "和", "·", "：", "—")
CN_DIGITS = "零一二三四五六七八九"


class ConfigError(ValueError):
    """Raised when a series configuration violates the specification."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="UTF-8 series JSON config")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing images")
    return parser.parse_args()


def contains_bad_text(text: str) -> bool:
    if "\ufffd" in text:
        return True
    return any(unicodedata.category(ch) == "Cc" and ch not in "\t\n\r" for ch in text)


def resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def default_font_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("TRAVEL_VIDEO_COVER_FONT")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / "fonts" / FONT_FILENAME)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "Windows" / "Fonts" / FONT_FILENAME)
    return candidates


def resolve_font(value: str | None, base_dir: Path) -> Path:
    candidates = [resolve_path(value, base_dir)] if value else default_font_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise ConfigError(f"Required licensed font not found. Checked: {searched}")


def validate_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty string")
    name = value.strip()
    if INVALID_FILENAME.search(name) or name.endswith((" ", ".")):
        raise ConfigError(f"{label} contains characters that are invalid in a Windows filename: {name!r}")
    if contains_bad_text(name):
        raise ConfigError(f"{label} contains corrupted text")
    return name


def chinese_number(value: int) -> str:
    if not 1 <= value <= 99:
        raise ConfigError("episode must be between 1 and 99")
    if value < 10:
        return CN_DIGITS[value]
    tens, ones = divmod(value, 10)
    prefix = "十" if tens == 1 else CN_DIGITS[tens] + "十"
    return prefix if ones == 0 else prefix + CN_DIGITS[ones]


def subtitle_format(text: str) -> str:
    matches = [connector for connector in CONNECTORS if text.count(connector) == 1]
    if len(matches) == 1:
        connector = matches[0]
        left, right = text.split(connector)
        if left and right:
            return f"connector:{connector}"
    return "plain"


def count_chars(lines: Iterable[str]) -> int:
    return sum(len(line.strip()) for line in lines)


def validate_text(cfg: dict[str, Any], font_path: Path, series_name: str) -> list[str]:
    subtitle = cfg.get("subtitle")
    body = cfg.get("body")
    main_title = cfg.get("main_title", series_name)

    if main_title != series_name:
        raise ConfigError(f"main_title must stay {series_name!r} throughout the series")
    if not isinstance(subtitle, str) or not subtitle.strip():
        raise ConfigError("subtitle must be a non-empty string")
    subtitle = subtitle.strip()
    if not isinstance(body, list) or len(body) != 4 or not all(isinstance(line, str) for line in body):
        raise ConfigError("body must contain exactly four strings")

    all_text = [main_title, subtitle, *body]
    if any(contains_bad_text(text) for text in all_text):
        raise ConfigError("Text contains a replacement character or an abnormal control character")

    if any(not line.strip() for line in body):
        raise ConfigError("body lines must not be empty")
    for index, raw_line in enumerate(body, start=1):
        line = raw_line.strip()
        length = len(line)
        if length > 15:
            raise ConfigError(f"body line {index} has {length} characters including punctuation; maximum is 15")
        expected = "，" if index < 4 else "。"
        if not line.endswith(expected):
            raise ConfigError(f"body line {index} must end with {expected}")

    probe = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(probe)
    checks = [
        (main_title, 162, "main_title"),
        (subtitle, 135, "subtitle"),
        *[(line.strip(), 76, f"body line {idx}") for idx, line in enumerate(body, start=1)],
    ]
    for text, size, label in checks:
        font = ImageFont.truetype(str(font_path), size)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width > W - 32:
            raise ConfigError(f"{label} is {width}px wide and will not fit the 1024px canvas")
    return ["".join(line.strip() for line in body)]


def crop_16_9_without_upscale(path: Path) -> Image.Image:
    if not path.is_file():
        raise ConfigError(f"Background image not found: {path}")
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    src_w, src_h = image.size
    target_ratio = 16 / 9
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        crop_h = src_h
        crop_w = int(round(crop_h * target_ratio))
        left, top = (src_w - crop_w) // 2, 0
    else:
        crop_w = src_w
        crop_h = int(round(crop_w / target_ratio))
        left, top = 0, (src_h - crop_h) // 2
    if crop_w < PHOTO_W or crop_h < PHOTO_H:
        raise ConfigError(
            f"Background crop would be {crop_w}x{crop_h}; at least {PHOTO_W}x{PHOTO_H} is required. "
            "The central image must not be upsampled."
        )
    cropped = image.crop((left, top, left + crop_w, top + crop_h))
    return cropped.resize((PHOTO_W, PHOTO_H), Image.Resampling.LANCZOS)


def make_blur_fill(sharp: Image.Image) -> Image.Image:
    filled = ImageOps.fit(sharp, (W, H), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    return ImageEnhance.Brightness(filled.filter(ImageFilter.GaussianBlur(60))).enhance(0.82)


def gradient_overlay(height: int, max_alpha: int, reverse: bool, blur: int) -> Image.Image:
    strip = Image.new("RGBA", (1, H), (0, 0, 0, 0))
    pixels = strip.load()
    for y in range(H):
        if reverse:
            distance = H - 1 - y
            alpha = int(max_alpha * ((distance / height) ** 1.7)) if distance < height else 0
        else:
            alpha = int(max_alpha * ((1 - y / height) ** 1.6)) if y < height else 0
        pixels[0, y] = (*GRADIENT_COOL, alpha)
    return strip.resize((W, H)).filter(ImageFilter.GaussianBlur(blur))


def centered_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int = W) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return (width - (bbox[2] - bbox[0])) // 2 - bbox[0]


def draw_title(draw: ImageDraw.ImageDraw, font_path: Path, main_title: str, subtitle: str) -> None:
    main_font = ImageFont.truetype(str(font_path), 162)
    sub_font = ImageFont.truetype(str(font_path), 135)
    top_y = 58
    main_bbox = draw.textbbox((0, 0), main_title, font=main_font)
    main_h = main_bbox[3] - main_bbox[1]
    draw.text((centered_x(draw, main_title, main_font), top_y), main_title, font=main_font, fill=TITLE_YELLOW)
    sub_y = top_y + main_h + TITLE_LINE_GAP
    draw.text((centered_x(draw, subtitle, sub_font), sub_y), subtitle, font=sub_font, fill=TITLE_YELLOW)


def draw_body(draw: ImageDraw.ImageDraw, font_path: Path, lines: list[str]) -> None:
    font = ImageFont.truetype(str(font_path), 76)
    line_height = 76 + BODY_LINE_GAP
    y_start = H - 30 - (4 * line_height - BODY_LINE_GAP)
    for index, line in enumerate(lines):
        centered = line[:-1] if line[-1] in HANG_PUNCT else line
        x = centered_x(draw, centered, font)
        y = y_start + index * line_height
        draw.text((x, y), line, font=font, fill=BODY_WHITE)


def build_cover(
    cfg: dict[str, Any], base_dir: Path, output_dir: Path, font_path: Path, series_name: str
) -> tuple[int, str, Path, Path]:
    episode = cfg["episode"]
    subtitle = cfg["subtitle"].strip()
    sharp = crop_16_9_without_upscale(resolve_path(str(cfg.get("background", "")), base_dir))
    canvas = make_blur_fill(sharp).convert("RGBA")
    canvas.paste(sharp, (0, PHOTO_Y))
    canvas = Image.alpha_composite(canvas, gradient_overlay(320, 155, reverse=False, blur=28))
    canvas = Image.alpha_composite(canvas, gradient_overlay(490, 225, reverse=True, blur=34))
    draw = ImageDraw.Draw(canvas)
    draw_title(draw, font_path, series_name, subtitle)
    draw_body(draw, font_path, [line.strip() for line in cfg["body"]])

    stem = f"{series_name}第{chinese_number(episode)}集封面"
    png_path = output_dir / f"{stem}.png"
    jpg_path = output_dir / f"{stem}.jpg"
    rgb = canvas.convert("RGB")
    rgb.save(png_path, optimize=True)
    rgb.save(jpg_path, quality=95, subsampling=0, optimize=True)
    return episode, subtitle, png_path, jpg_path


def preview_columns(count: int) -> tuple[int, int]:
    if count == 1:
        return 1, 800
    if count <= 4:
        return 2, 1200
    return 4, 1600


def make_series_preview(
    items: list[tuple[int, str, Path, Path]], output_dir: Path, series_name: str, font_path: Path
) -> Path:
    columns, canvas_w = preview_columns(len(items))
    margin, gap, header_h, caption_h = 28, 28, 90, 48
    tile_w = (canvas_w - 2 * margin - (columns - 1) * gap) // columns
    tile_h = round(tile_w * H / W)
    rows = math.ceil(len(items) / columns)
    canvas_h = header_h + margin + rows * (tile_h + caption_h) + (rows - 1) * gap + margin
    preview = Image.new("RGB", (canvas_w, canvas_h), (246, 245, 240))
    draw = ImageDraw.Draw(preview)
    draw.rectangle((0, 0, canvas_w, header_h), fill=(27, 36, 51))
    header_font = ImageFont.truetype(str(font_path), 42)
    caption_font = ImageFont.truetype(str(font_path), 26)
    header = f"{series_name} · {len(items)}集纪录片系列封面预览"
    header_bbox = draw.textbbox((0, 0), header, font=header_font)
    header_y = (header_h - (header_bbox[3] - header_bbox[1])) // 2 - header_bbox[1]
    draw.text((margin, header_y), header, font=header_font, fill=(255, 215, 0))

    for position, (episode, subtitle, _png_path, jpg_path) in enumerate(items):
        row, column = divmod(position, columns)
        x = margin + column * (tile_w + gap)
        y = header_h + margin + row * (tile_h + caption_h + gap)
        with Image.open(jpg_path) as source:
            tile = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGB"), (tile_w, tile_h), Image.Resampling.LANCZOS)
        preview.paste(tile, (x, y))
        caption = f"{episode:02d} {subtitle}"
        draw.text((x, y + tile_h + 8), caption, font=caption_font, fill=(35, 39, 46))

    output_path = output_dir / f"{series_name}系列缩略图.jpg"
    preview.save(output_path, quality=94, subsampling=0, optimize=True)
    return output_path


def load_project(config_path: Path) -> tuple[Path, str, Path, Path, list[dict[str, Any]]]:
    if not config_path.is_file():
        raise ConfigError(f"Config file not found: {config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise ConfigError("Config must be UTF-8 encoded") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Config root must be an object")

    base_dir = config_path.resolve().parent
    series_name = validate_name(data.get("series_name"), "series_name")
    font_path = resolve_font(data.get("font"), base_dir)
    covers = data.get("covers")
    if not isinstance(covers, list) or not covers or not all(isinstance(item, dict) for item in covers):
        raise ConfigError("covers must be a non-empty array of objects")

    normalized: list[dict[str, Any]] = []
    episodes: set[int] = set()
    for index, item in enumerate(covers, start=1):
        cfg = dict(item)
        episode = cfg.get("episode", index)
        if not isinstance(episode, int) or isinstance(episode, bool):
            raise ConfigError("episode must be an integer")
        chinese_number(episode)
        if episode in episodes:
            raise ConfigError(f"Duplicate episode number: {episode}")
        episodes.add(episode)
        cfg["episode"] = episode
        if cfg.get("background_verified_no_text") is not True:
            raise ConfigError(
                f"Episode {episode}: inspect the full-resolution background and set "
                'background_verified_no_text to true only after confirming there is no "AI生成", '
                "watermark, logo, corner label, platform mark, or other unintended text anywhere in the image"
            )
        validate_text(cfg, font_path, series_name)
        normalized.append(cfg)
    normalized.sort(key=lambda item: item["episode"])

    subtitles = [item["subtitle"].strip() for item in normalized]
    subtitle_lengths = {len(text) for text in subtitles}
    subtitle_formats = {subtitle_format(text) for text in subtitles}
    if len(subtitle_lengths) != 1:
        raise ConfigError(f"All subtitles must have the same character count; got {sorted(subtitle_lengths)}")
    if len(subtitle_formats) != 1:
        raise ConfigError(f"All subtitles must use the same connector format; got {sorted(subtitle_formats)}")

    output_root = resolve_path(str(data.get("output_root", "output")), base_dir)
    output_dir = output_root / f"{series_name}系列视频封面"
    return base_dir, series_name, output_dir, font_path, normalized


def main() -> int:
    args = parse_args()
    try:
        base_dir, series_name, output_dir, font_path, configs = load_project(args.config.resolve())
        for cfg in configs:
            joined = "".join(line.strip() for line in cfg["body"])
            lengths = "/".join(str(len(line.strip())) for line in cfg["body"])
            print(f"[{cfg['episode']:02d}] {cfg['subtitle'].strip()} | line lengths {lengths} | {joined}")
            crop_16_9_without_upscale(resolve_path(str(cfg.get("background", "")), base_dir))
        print(f"Package: {output_dir}")
        print(f"Series thumbnail: {output_dir / f'{series_name}系列缩略图.jpg'}")
        if args.dry_run:
            print("Validation complete. Read every joined sentence aloud before the full run.")
            return 0

        output_dir.mkdir(parents=True, exist_ok=True)
        items = [build_cover(cfg, base_dir, output_dir, font_path, series_name) for cfg in configs]
        preview_path = make_series_preview(items, output_dir, series_name, font_path)
        print(f"Generated {len(items)} covers in PNG and JPG, plus {preview_path.name}.")
        return 0
    except (ConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
