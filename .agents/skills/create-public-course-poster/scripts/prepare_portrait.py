#!/usr/bin/env python3
"""把原分辨率精修人物层一次性缩放并定位到固定海报画布。"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps


CANVAS = (1024, 1536)
TARGET_FACE_CENTER = (300, 770)
TARGET_FACE_HEIGHT = 200
SAFE_MARGIN = 12
RIGHT_LIMIT = 510


def parse_box(value: str) -> tuple[int, int, int, int]:
    try:
        box = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("脸框必须是 左,上,右,下 四个整数") from exc
    if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
        raise argparse.ArgumentTypeError("脸框必须是 左,上,右,下 且宽高为正")
    return box


def premultiplied_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = list(rgba.get_flattened_data())
    premultiplied = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    premultiplied.putdata(
        [
            (
                round(red * opacity / 255),
                round(green * opacity / 255),
                round(blue * opacity / 255),
                opacity,
            )
            for red, green, blue, opacity in pixels
        ]
    )
    resized = premultiplied.resize(size, Image.Resampling.LANCZOS)
    output_pixels = []
    for red, green, blue, opacity in resized.get_flattened_data():
        if opacity <= 0:
            output_pixels.append((0, 0, 0, 0))
        else:
            output_pixels.append(
                (
                    min(255, round(red * 255 / opacity)),
                    min(255, round(green * 255 / opacity)),
                    min(255, round(blue * 255 / opacity)),
                    opacity,
                )
            )
    output = Image.new("RGBA", size, (0, 0, 0, 0))
    output.putdata(output_pixels)
    return output


def prepare(source_path: Path, face_box: tuple[int, int, int, int], out_path: Path) -> None:
    with Image.open(source_path) as source_image:
        source = ImageOps.exif_transpose(source_image).convert("RGBA")
    if source.getchannel("A").getbbox() is None:
        raise ValueError("精修人物层没有可见像素")
    face_height = face_box[3] - face_box[1]
    scale = TARGET_FACE_HEIGHT / face_height
    size = (round(source.width * scale), round(source.height * scale))
    resized = premultiplied_resize(source, size)
    source_face_center = ((face_box[0] + face_box[2]) / 2, (face_box[1] + face_box[3]) / 2)
    paste_x = round(TARGET_FACE_CENTER[0] - source_face_center[0] * scale)
    paste_y = round(TARGET_FACE_CENTER[1] - source_face_center[1] * scale)

    visible = resized.getchannel("A").point(lambda value: 255 if value >= 16 else 0).getbbox()
    if visible is None:
        raise ValueError("缩放后没有可见人物像素")
    left = paste_x + visible[0]
    rightmost = paste_x + visible[2] - 1
    top = paste_y + visible[1]
    if left < SAFE_MARGIN:
        raise ValueError(f"定位后人物左边界 x={left}，必须至少为 {SAFE_MARGIN}")
    if rightmost > RIGHT_LIMIT:
        raise ValueError(f"定位后人物右边界 x={rightmost}，不得超过 {RIGHT_LIMIT}")
    if top < 0:
        raise ValueError(f"定位后人物顶部 y={top} 超出画布")

    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.alpha_composite(resized, (paste_x, paste_y))
    if canvas.getchannel("A").point(lambda value: 255 if value >= 16 else 0).getbbox()[3] != CANVAS[1]:
        raise ValueError("定位后人物没有触及画布底边；请检查原图是否包含足够的下半身")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)
    print(f"已输出预乘透明度人物层：{out_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="一次性缩放并定位精修人物透明层")
    parser.add_argument("--source", required=True, type=Path, help="原分辨率精修 RGBA PNG")
    parser.add_argument("--face-box", required=True, type=parse_box, help="源图可见脸框：左,上,右,下")
    parser.add_argument("--out", required=True, type=Path, help="1024×1536 输出 PNG")
    args = parser.parse_args()
    prepare(args.source, args.face_box, args.out)


if __name__ == "__main__":
    main()
