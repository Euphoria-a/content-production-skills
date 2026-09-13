#!/usr/bin/env python3
"""使用正式渲染器重新生成海报，阻止本地放宽脚本伪造通过状态。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from PIL import Image

from render_poster import LAYOUT_PATH, pixel_sha256, render, sha256_file


CANVAS = (1024, 1536)
SCRIPT_DIR = Path(__file__).resolve().parent
OFFICIAL_RENDERER = SCRIPT_DIR / "render_poster.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="用正式 Skill 渲染器独立重渲染并验证最终海报。")
    parser.add_argument("--poster", required=True, type=Path, help="最终 PNG")
    parser.add_argument("--audit", type=Path, help="audit-report.json；省略时按默认工作目录查找")
    return parser.parse_args()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def verify_file_record(record: object, label: str) -> Path:
    if not isinstance(record, dict) or "path" not in record or "sha256" not in record:
        raise ValueError(f"审计报告缺少 {label} 的路径或哈希")
    path = Path(str(record["path"])).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} 不存在：{path}")
    actual_hash = sha256_file(path)
    if actual_hash != str(record["sha256"]):
        raise ValueError(f"{label} 在渲染后被修改，哈希不一致：{path}")
    return path


def verify(poster: Path, audit_path: Path) -> dict[str, object]:
    if not poster.is_file():
        raise FileNotFoundError(f"海报不存在：{poster}")
    with Image.open(poster) as image:
        if image.size != CANVAS:
            raise ValueError(f"海报必须为 {CANVAS[0]}×{CANVAS[1]}，当前为 {image.size}")

    audit = read_json(audit_path)
    if audit.get("automatic_status") != "passed":
        raise ValueError("自动审计未通过")
    provenance = audit.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("审计报告缺少正式渲染器溯源信息；旧报告或本地脚本报告不得交付")

    renderer_path = verify_file_record(provenance.get("renderer"), "渲染器")
    if renderer_path != OFFICIAL_RENDERER.resolve():
        raise ValueError(f"海报不是由当前 Skill 正式渲染器生成：{renderer_path}")
    layout_path = verify_file_record(provenance.get("layout"), "布局配置")
    if layout_path != LAYOUT_PATH.resolve():
        raise ValueError(f"海报使用了非正式布局配置：{layout_path}")

    inputs = provenance.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("审计报告缺少输入文件溯源信息")
    base = verify_file_record(inputs.get("base"), "背景输入")
    portrait = verify_file_record(inputs.get("portrait"), "人物输入")
    data = verify_file_record(inputs.get("data"), "文案输入")

    actual_pixel_hash = pixel_sha256(poster)
    if actual_pixel_hash != str(provenance.get("output_pixel_sha256", "")):
        raise ValueError("最终海报在正式渲染后被修改，像素哈希不一致")

    with tempfile.TemporaryDirectory(prefix="public-course-poster-verify-") as temp_dir:
        rerendered = Path(temp_dir) / "official-rerender.png"
        render(base, portrait, data, rerendered, False)
        rerendered_hash = pixel_sha256(rerendered)
    if rerendered_hash != actual_pixel_hash:
        raise ValueError("正式渲染器重渲染结果与交付海报不同；禁止交付本地修改或放宽版本")

    portrait_metrics = audit.get("portrait", {})
    return {
        "status": "passed",
        "poster": str(poster),
        "official_renderer": str(OFFICIAL_RENDERER.resolve()),
        "official_renderer_sha256": sha256_file(OFFICIAL_RENDERER.resolve()),
        "poster_pixel_sha256": actual_pixel_hash,
        "rerender_pixel_match": True,
        "portrait_alpha_bbox": portrait_metrics.get("alpha_bbox"),
        "portrait_rightmost_x": portrait_metrics.get("rightmost_x"),
        "message": "正式渲染器来源、输入哈希、人物硬约束和独立重渲染比对全部通过",
    }


def main() -> None:
    args = parse_args()
    poster = args.poster.resolve()
    work_dir = poster.parent / f"{poster.stem}_work"
    audit_path = (args.audit or work_dir / "audit-report.json").resolve()
    report_path = work_dir / "verification-report.json"
    try:
        report = verify(poster, audit_path)
    except Exception as exc:
        write_report(report_path, {"status": "failed", "poster": str(poster), "reason": str(exc)})
        raise
    write_report(report_path, report)
    print("正式渲染器独立验证通过。")
    print(f"验证报告：{report_path}")


if __name__ == "__main__":
    main()
