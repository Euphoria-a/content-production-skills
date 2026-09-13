from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1080, 2568
HERO_H = 1328
MISSING = "源资料未提供"

SKILL_ROOT = Path(__file__).resolve().parent.parent
FONT_ENV = {
    "regular": "ARTIFACT_V4_FONT_REGULAR",
    "bold": "ARTIFACT_V4_FONT_BOLD",
    "heavy": "ARTIFACT_V4_FONT_HEAVY",
    "english": "ARTIFACT_V4_FONT_ENGLISH",
}
FONT_CANDIDATES = {
    "regular": [
        SKILL_ROOT / "assets" / "fonts" / "NotoSansCJKsc-Regular.otf",
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ],
    "bold": [
        SKILL_ROOT / "assets" / "fonts" / "NotoSansCJKsc-Bold.otf",
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ],
    "heavy": [
        SKILL_ROOT / "assets" / "fonts" / "NotoSansCJKsc-Bold.otf",
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ],
    "english": [
        SKILL_ROOT / "assets" / "fonts" / "NotoSans-Bold.ttf",
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ],
}


def resolve_font_path(role: str) -> Path:
    configured = os.environ.get(FONT_ENV[role])
    candidates = ([Path(configured).expanduser()] if configured else []) + FONT_CANDIDATES[role]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No usable font for role {role!r}. Checked: {checked}")

PALETTES = {
    "snow_highland": {
        "keywords": ["川西", "西藏", "雪山", "高原", "冰川", "新疆"],
        "background": "#071F31", "card_dark": "#112F49", "card_light": "#435677",
        "accent": "#FFD436", "badge": "#21106F", "light": "#FFF5C8",
        "primary_text": "#FFFFFF", "secondary_text": "#C8D7E6",
    },
    "ocean_island": {
        "keywords": ["海岛", "海滨", "三亚", "海南", "舟山", "马尔代夫", "巴厘岛"],
        "background": "#062B3A", "card_dark": "#084B5E", "card_light": "#2F6F7C",
        "accent": "#FFB55A", "badge": "#C94F5D", "light": "#FFF1D2",
        "primary_text": "#FFFFFF", "secondary_text": "#CDE9ED",
    },
    "desert_silk_road": {
        "keywords": ["沙漠", "敦煌", "丝路", "西北", "摩洛哥", "埃及"],
        "background": "#2A1C18", "card_dark": "#4A3025", "card_light": "#72503D",
        "accent": "#E9B949", "badge": "#1E5A59", "light": "#FFF0C4",
        "primary_text": "#FFFFFF", "secondary_text": "#E8D9C7",
    },
    "forest_grassland": {
        "keywords": ["草原", "森林", "呼伦贝尔", "内蒙古", "云南", "贵州"],
        "background": "#0C2B25", "card_dark": "#174538", "card_light": "#3D6656",
        "accent": "#F2B84B", "badge": "#5C2D70", "light": "#FFF4CE",
        "primary_text": "#FFFFFF", "secondary_text": "#D4E4DD",
    },
    "heritage_city": {
        "keywords": ["古城", "人文", "博物馆", "京都", "印度", "欧洲", "中东"],
        "background": "#20252B", "card_dark": "#303A45", "card_light": "#586474",
        "accent": "#D7AA45", "badge": "#7A263A", "light": "#FFF0C7",
        "primary_text": "#FFFFFF", "secondary_text": "#D7DEE6",
    },
}


def get_font(size: int, role: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(resolve_font_path(role)), size=size)


def choose_palette(cfg: dict) -> dict:
    explicit = cfg.get("palette") or {}
    destination = str(cfg.get("destination_name") or "")
    chosen = None
    if explicit.get("mode") not in (None, "auto"):
        chosen = PALETTES.get(explicit.get("mode"))
    if chosen is None:
        for palette in PALETTES.values():
            if any(k in destination for k in palette["keywords"]):
                chosen = palette
                break
    if chosen is None:
        chosen = PALETTES["snow_highland"]
    result = {k: v for k, v in chosen.items() if k != "keywords"}
    for key in result:
        if explicit.get(key):
            result[key] = explicit[key]
    return result


def value(v, default=MISSING):
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def cover(im: Image.Image, size: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    tw, th = size
    scale = max(tw / im.width, th / im.height)
    rw, rh = round(im.width * scale), round(im.height * scale)
    im = im.resize((rw, rh), Image.Resampling.LANCZOS)
    left = max(0, (rw - tw) // 2)
    top = max(0, min(rh - th, round((rh - th) * focus_y)))
    return im.crop((left, top, left + tw, top + th))


def placeholder_image(size: tuple[int, int], palette: dict) -> Image.Image:
    im = Image.new("RGB", size, palette["card_dark"])
    d = ImageDraw.Draw(im)
    d.line((0, 0, size[0], size[1]), fill=palette["secondary_text"], width=2)
    d.line((size[0], 0, 0, size[1]), fill=palette["secondary_text"], width=2)
    f = get_font(max(18, min(28, size[1] // 6)), "bold")
    d.text((size[0] // 2, size[1] // 2), MISSING, font=f, fill=palette["primary_text"], anchor="mm")
    return im


def load_image(path_value, size: tuple[int, int], palette: dict, focus_y: float = 0.5) -> Image.Image:
    p = Path(str(path_value)) if path_value else None
    if p and p.exists():
        return cover(Image.open(p).convert("RGB"), size, focus_y)
    return placeholder_image(size, palette)


def rounded(im: Image.Image, radius: int = 8) -> Image.Image:
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width, im.height), radius=radius, fill=255)
    im = im.convert("RGBA")
    im.putalpha(mask)
    return im


def fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, preferred: int, minimum: int, role="bold"):
    for size in range(preferred, minimum - 1, -1):
        f = get_font(size, role)
        b = draw.textbbox((0, 0), text, font=f)
        if b[2] - b[0] <= max_width:
            return f
    return get_font(minimum, role)


def shadow_text(draw, xy, text, fnt, fill, offset=5):
    x, y = xy
    draw.text((x + offset, y + offset), text, font=fnt, fill=(0, 0, 0, 180))
    draw.text((x, y), text, font=fnt, fill=fill)


def starburst_points(cx, cy, outer, inner, spikes=28):
    pts = []
    for i in range(spikes * 2):
        angle = -math.pi / 2 + i * math.pi / spikes
        radius = outer if i % 2 == 0 else inner
        pts.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return pts


def card(draw, box, fill):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle((x1 + 5, y1 + 7, x2 + 5, y2 + 7), radius=11, fill=(0, 9, 19, 95))
    draw.rounded_rectangle(box, radius=8, fill=fill)


def icon(draw, center, kind, color):
    cx, cy = center
    if kind == "pin":
        draw.ellipse((cx - 11, cy - 14, cx + 11, cy + 8), outline=color, width=3)
        draw.ellipse((cx - 3, cy - 6, cx + 3, cy), fill=color)
        draw.polygon([(cx - 7, cy + 5), (cx + 7, cy + 5), (cx, cy + 15)], fill=color)
    else:
        draw.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), outline=color, width=3)
        draw.line((cx - 7, cy, cx - 1, cy + 6, cx + 8, cy - 6), fill=color, width=3)


def label(draw, xy, title, width, kind, palette):
    x, y = xy
    draw.rounded_rectangle((x, y, x + width, y + 58), radius=29, fill=palette["badge"])
    draw.ellipse((x + 8, y + 8, x + 50, y + 50), fill=palette["light"])
    icon(draw, (x + 29, y + 29), kind, palette["badge"])
    draw.text((x + 60, y + 29), title, font=get_font(30, "bold"), fill=palette["primary_text"], anchor="lm")


def ribbon_label(draw, xy, chinese, english, palette):
    x, y = xy
    draw.rounded_rectangle((x, y, x + 146, y + 54), radius=27, fill=palette["light"])
    draw.polygon([(x + 112, y), (x + 162, y), (x + 143, y + 54), (x + 93, y + 54)], fill=palette["badge"])
    draw.text((x + 22, y + 27), chinese, font=get_font(29, "bold"), fill=palette["badge"], anchor="lm")
    draw.text((x + 177, y + 29), english, font=get_font(25, "english"), fill=palette["primary_text"], anchor="lm")


def draw_lines(draw, x, y, lines, size, fill, max_lines, step=None):
    lines = list(lines or [])[:max_lines]
    while len(lines) < max_lines:
        lines.append(MISSING)
    f = get_font(size, "bold")
    step = step or size + 12
    for i, line in enumerate(lines):
        draw.text((x, y + i * step), value(line), font=f, fill=fill)


def render(cfg: dict, output: Path):
    p = choose_palette(cfg)
    canvas = Image.new("RGB", (W, H), p["background"])
    hero = load_image((cfg.get("images") or {}).get("hero"), (W, HERO_H), p, 0.48)
    canvas.paste(hero, (0, 0))
    canvas = canvas.convert("RGBA")

    shade = Image.new("RGBA", (W, HERO_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for y in range(HERO_H):
        top_alpha = int(max(0, 160 * (1 - y / 630)))
        bottom_alpha = int(max(0, 190 * ((y - 760) / (HERO_H - 760)))) if y > 760 else 0
        sd.line((0, y, W, y), fill=(5, 20, 35, min(205, max(top_alpha, bottom_alpha))))
    canvas.alpha_composite(shade, (0, 0))
    draw = ImageDraw.Draw(canvas)

    # Hero content.
    company_bar = (50, 30, 505, 76)
    draw.rounded_rectangle(company_bar, radius=23, fill=(7, 31, 49, 185))
    draw.text(((company_bar[0] + company_bar[2]) / 2, 53), value(cfg.get("company_name")), font=get_font(22, "bold"), fill=p["primary_text"], anchor="mm")

    title1 = value(cfg.get("title_line_1"))
    title2 = value(cfg.get("title_line_2"))
    shadow_text(draw, (65, 118), title1, fit_font(draw, title1, 590, 142, 86, "heavy"), p["primary_text"], 6)
    shadow_text(draw, (65, 265), title2, fit_font(draw, title2, 620, 118, 86, "heavy"), p["primary_text"], 6)
    draw.text((72, 421), value(cfg.get("theme_phrase")), font=fit_font(draw, value(cfg.get("theme_phrase")), 600, 33, 24, "bold"), fill=p["accent"])

    draw.ellipse((718, 105, 910, 297), fill=p["accent"])
    draw.text((814, 153), value(cfg.get("transport_mode"), "交通"), font=get_font(34, "bold"), fill="#101010", anchor="mm")
    draw.text((814, 205), value(cfg.get("duration_text")), font=get_font(52, "heavy"), fill="#101010", anchor="mm")
    badge_date = value(cfg.get("badge_date"), value(cfg.get("departure_date")))
    draw.text((814, 257), badge_date, font=fit_font(draw, badge_date, 150, 24, 18, "bold"), fill="#101010", anchor="mm")

    subtitle = value(cfg.get("destination_subtitle"))
    shadow_text(draw, (68, 492), subtitle, fit_font(draw, subtitle, 920, 34, 26, "bold"), p["primary_text"], 3)
    draw.text((65, 942), value(cfg.get("departure_city")), font=get_font(54, "bold"), fill=p["primary_text"])
    draw.text((65, 1011), value(cfg.get("departure_date")), font=get_font(74, "heavy"), fill=p["primary_text"])
    draw.text((68, 1097), value(cfg.get("return_date")), font=get_font(29, "bold"), fill=p["secondary_text"])

    prices = list(cfg.get("prices") or [])
    if not prices:
        prices = [{"label": MISSING, "amount": MISSING, "unit": ""}]
    main_price = prices[0]
    cx, cy = 812, 979
    draw.polygon(starburst_points(cx, cy, 205, 177), fill=p["accent"])
    draw.ellipse((cx - 163, cy - 163, cx + 163, cy + 163), fill=p["badge"], outline=p["accent"], width=6)
    draw.text((cx, cy - 84), value(main_price.get("label")), font=get_font(26, "bold"), fill=p["primary_text"], anchor="mm")
    draw.text((cx, cy - 4), value(main_price.get("amount")), font=fit_font(draw, value(main_price.get("amount")), 270, 69, 42, "heavy"), fill=p["accent"], anchor="mm")
    draw.text((cx, cy + 75), value(main_price.get("unit"), "元/人"), font=get_font(28, "bold"), fill=p["primary_text"], anchor="mm")

    draw.rounded_rectangle((572, 1214, 1028, 1301), radius=10, fill=(7, 31, 49, 205))
    secondary = prices[1:3]
    while len(secondary) < 2:
        secondary.append({"label": "其他价格", "amount": MISSING, "unit": ""})
    for i, tier in enumerate(secondary):
        text = f"{value(tier.get('label'))}   {value(tier.get('amount'))}{value(tier.get('unit'), '')}"
        draw.text((595, 1231 + i * 34), text, font=fit_font(draw, text, 410, 22, 18, "bold"), fill=p["primary_text"])

    # Aviation card.
    card(draw, (52, 1340, 1028, 1590), p["card_dark"])
    transport = cfg.get("transport") or {}
    kicker_font = get_font(28)
    kicker_left_x = 84
    kicker_suffix_x = 215
    draw.text((kicker_left_x, 1371), "尊享", font=kicker_font, fill=p["primary_text"])
    kicker_left_end = kicker_left_x + draw.textlength("尊享", font=kicker_font)
    small_day_circle_cx = round((kicker_left_end + kicker_suffix_x) / 2)
    draw.ellipse((small_day_circle_cx - 20, 1357, small_day_circle_cx + 20, 1397), fill=p["light"])
    draw.text((small_day_circle_cx, 1377), value(transport.get("kicker_number"), value(cfg.get("duration_text"))), font=get_font(21, "bold"), fill=p["badge"], anchor="mm")
    draw.text((kicker_suffix_x, 1371), value(transport.get("kicker_suffix"), "日全景游"), font=kicker_font, fill=p["primary_text"])
    transport_prefix = value(transport.get("title_prefix"), "精选")
    transport_suffix = value(transport.get("title_suffix"), "交通")
    draw.text((84, 1422), transport_prefix, font=get_font(49, "heavy"), fill=p["accent"])
    draw.text((187, 1422), transport_suffix, font=get_font(49, "heavy"), fill=p["primary_text"])
    transport_lines = list(transport.get("lines") or [])
    while len(transport_lines) < 2:
        transport_lines.append(MISSING)
    draw.text((86, 1492), value(transport_lines[0]), font=fit_font(draw, value(transport_lines[0]), 340, 27, 20, "bold"), fill=p["primary_text"])
    draw.text((86, 1532), value(transport_lines[1]), font=fit_font(draw, value(transport_lines[1]), 340, 24, 20, "bold"), fill=p["secondary_text"])
    aviation = list((cfg.get("images") or {}).get("aviation") or [])
    while len(aviation) < 2:
        aviation.append(None)
    canvas.alpha_composite(rounded(load_image(aviation[0], (264, 176), p), 7), (456, 1381))
    canvas.alpha_composite(rounded(load_image(aviation[1], (264, 176), p, 0.54), 7), (736, 1381))

    # Accommodation and service card.
    card(draw, (52, 1610, 1028, 1840), p["card_light"])
    draw.line((540, 1635, 540, 1815), fill=(255, 255, 255, 90), width=2)
    ribbon_label(draw, (82, 1640), "住宿", "HOTEL", p)
    ribbon_label(draw, (578, 1640), "服务", "SERVICE", p)
    draw_lines(draw, 88, 1712, cfg.get("accommodation"), 25, p["primary_text"], 3, 39)
    draw_lines(draw, 584, 1712, cfg.get("service"), 25, p["primary_text"], 3, 39)

    # Attractions card.
    card(draw, (52, 1860, 1028, 2100), p["card_light"])
    attraction_paths = list((cfg.get("images") or {}).get("attractions") or [])
    while len(attraction_paths) < 2:
        attraction_paths.append(None)
    canvas.alpha_composite(rounded(load_image(attraction_paths[0], (232, 150), p, 0.46), 6), (82, 1912))
    canvas.alpha_composite(rounded(load_image(attraction_paths[1], (232, 150), p), 6), (328, 1912))
    label(draw, (600, 1882), "精选景点", 330, "pin", p)
    draw_lines(draw, 606, 1950, cfg.get("highlights"), 25, p["primary_text"], 4, 36)

    # Dining card.
    card(draw, (52, 2120, 1028, 2370), p["card_light"])
    dining_path = (cfg.get("images") or {}).get("dining")
    canvas.alpha_composite(rounded(load_image(dining_path, (510, 174), p, 0.58), 7), (82, 2160))
    label(draw, (620, 2140), "用餐安排", 330, "service", p)
    dining = list(cfg.get("dining") or [])
    while len(dining) < 3:
        dining.append(MISSING)
    draw.text((626, 2220), value(dining[0]), font=fit_font(draw, value(dining[0]), 360, 31, 22, "bold"), fill=p["primary_text"])
    draw.text((626, 2267), value(dining[1]), font=fit_font(draw, value(dining[1]), 360, 31, 22, "bold"), fill=p["primary_text"])
    draw.text((626, 2314), value(dining[2]), font=fit_font(draw, value(dining[2]), 360, 22, 20, "bold"), fill=p["secondary_text"])

    footer = cfg.get("footer") or {}
    draw.rectangle((0, 2394, W, H), fill=p["background"])
    line1 = value(footer.get("line_1"))
    line2 = value(footer.get("line_2"))
    draw.text((52, 2424), line1, font=fit_font(draw, line1, 976, 21, 20, "bold"), fill=p["secondary_text"])
    draw.text((52, 2463), line2, font=fit_font(draw, line2, 976, 20, 18, "bold"), fill=p["primary_text"])

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output, quality=95)


def main():
    parser = argparse.ArgumentParser(description="Render the approved V4 Chinese travel poster template")
    parser.add_argument("--input", required=True, help="Run JSON path")
    parser.add_argument("--output", required=True, help="Final PNG path")
    args = parser.parse_args()
    cfg = json.loads(Path(args.input).read_text(encoding="utf-8"))
    render(cfg, Path(args.output))
    print(Path(args.output).resolve())


if __name__ == "__main__":
    main()
