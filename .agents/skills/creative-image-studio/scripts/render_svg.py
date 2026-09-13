#!/usr/bin/env python3
"""通过 resvg、rsvg-convert 或 Chromium 系浏览器渲染 SVG。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path


class RenderError(RuntimeError):
    pass


def versioned_output(path: str | Path) -> Path:
    path = Path(path).resolve()
    if not path.exists():
        return path
    version = 2
    while True:
        candidate = path.with_name(f"{path.stem}-v{version}{path.suffix}")
        if not candidate.exists():
            return candidate
        version += 1


def svg_dimensions(svg_path: str | Path) -> tuple[int, int]:
    root = ET.parse(svg_path).getroot()
    try:
        width = int(float(str(root.get("width")).replace("px", "")))
        height = int(float(str(root.get("height")).replace("px", "")))
    except (TypeError, ValueError) as exc:
        raise RenderError("SVG 必须提供数字形式的 width 和 height") from exc
    if width <= 0 or height <= 0:
        raise RenderError("SVG 尺寸必须大于零")
    return width, height


def find_browser() -> str | None:
    candidates = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def render(svg_path: str | Path, png_path: str | Path) -> tuple[Path, str]:
    svg_path = Path(svg_path).resolve()
    png_path = versioned_output(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = svg_dimensions(svg_path)

    resvg = shutil.which("resvg")
    if resvg:
        result = subprocess.run([resvg, str(svg_path), str(png_path)], capture_output=True, text=True)
        if result.returncode == 0 and png_path.exists():
            return png_path, "resvg"

    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        result = subprocess.run([rsvg, "-o", str(png_path), str(svg_path)], capture_output=True, text=True)
        if result.returncode == 0 and png_path.exists():
            return png_path, "rsvg-convert"

    browser = find_browser()
    if not browser:
        raise RenderError("未找到 SVG 渲染器（resvg、rsvg-convert、Chromium、Chrome 或 Edge）")
    profile = tempfile.mkdtemp(prefix="creative-image-studio-browser-")
    try:
        command = [
            browser,
            "--headless=new",
            "--no-first-run",
            "--disable-extensions",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--window-size={width},{height}",
            f"--user-data-dir={profile}",
            f"--screenshot={png_path}",
            svg_path.as_uri(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        # Windows 上 Edge 启动器可能在无头子进程写完截图前返回。
        deadline = time.monotonic() + 20
        while not png_path.exists() and time.monotonic() < deadline:
            time.sleep(0.25)
        if result.returncode not in (0, None) or not png_path.exists():
            detail = (result.stderr or result.stdout or "未知浏览器错误")[-2000:]
            raise RenderError(f"浏览器渲染 SVG 失败：{detail}")
    finally:
        # Edge 退出后可能短暂占用 SQLite 文件；清理采用尽力而为策略，不能影响已完成的渲染。
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)

    from PIL import Image

    with Image.open(png_path) as image:
        if image.size != (width, height):
            raise RenderError(f"渲染器返回尺寸 {image.size}，预期为 {(width, height)}")
    return png_path, Path(browser).name


def convert_jpg(png_path: str | Path, jpg_path: str | Path, quality: int = 94) -> Path:
    from PIL import Image

    png_path = Path(png_path)
    jpg_path = versioned_output(jpg_path)
    jpg_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(png_path).convert("RGBA") as source:
        background = Image.new("RGB", source.size, "white")
        background.paste(source, mask=source.getchannel("A"))
        background.save(jpg_path, quality=quality, subsampling=0, optimize=True)
    return jpg_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SVG 内部渲染器")
    parser.add_argument("svg")
    parser.add_argument("--png", required=True)
    parser.add_argument("--jpg")
    args = parser.parse_args(argv)
    png, engine = render(args.svg, args.png)
    result = {"png": str(png), "engine": engine}
    if args.jpg:
        result["jpg"] = str(convert_jpg(png, args.jpg))
    import json

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"错误：{error}", file=sys.stderr)
        raise SystemExit(2)
