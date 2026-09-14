#!/usr/bin/env python3
"""Analyze a Chinese narration draft for timing, text integrity, and style risks."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path


SENTENCE_RE = re.compile(r"[^。！？!?…]+(?:[。！？!?]+|…{2})?")
FILLER_PHRASES = ("值得一提的是", "综上所述", "从某种意义上讲", "其实吧", "然后呢", "就是说")
HYPE_PHRASES = ("世界第一", "最美", "必去", "百分之百", "彻底解决", "保证一学就会", "怎么拍都好看")
MOJIBAKE_MARKERS = ("\ufffd", "锟斤拷", "鐨", "銆", "鈥")


@dataclass(frozen=True)
class Finding:
    level: str
    code: str
    message: str


def effective_char_count(text: str) -> int:
    """Count CJK characters and alphanumerics while ignoring punctuation/spacing."""
    return sum(
        1
        for char in text
        if char.isalnum() or "\u3400" <= char <= "\u9fff"
    )


def sentences(text: str) -> list[str]:
    return [match.group(0).strip() for match in SENTENCE_RE.finditer(text) if match.group(0).strip()]


def estimate_minutes(char_count: int, speed: float) -> tuple[float, float]:
    if speed <= 0:
        raise ValueError("speed must be greater than zero")
    return char_count / (160 * speed), char_count / (120 * speed)


def analyze(text: str, speed: float = 1.0, locations: list[str] | None = None) -> dict[str, object]:
    findings: list[Finding] = []
    normalized_locations = [item.strip() for item in (locations or []) if item.strip()]

    for char in text:
        if unicodedata.category(char) == "Cc" and char not in "\t\n\r":
            findings.append(Finding("error", "control-character", "发现不可见控制字符"))
            break
    for marker in MOJIBAKE_MARKERS:
        if marker in text:
            findings.append(Finding("error", "mojibake", f"发现疑似乱码标记：{marker}"))
    for phrase in FILLER_PHRASES:
        count = text.count(phrase)
        if count:
            findings.append(Finding("warning", "filler", f"套话“{phrase}”出现 {count} 次"))
    for phrase in HYPE_PHRASES:
        count = text.count(phrase)
        if count:
            findings.append(Finding("warning", "hype", f"夸张表达“{phrase}”出现 {count} 次"))

    sentence_list = sentences(text)
    long_sentences = [
        (index, effective_char_count(sentence))
        for index, sentence in enumerate(sentence_list, start=1)
        if effective_char_count(sentence) > 80
    ]
    for index, count in long_sentences:
        findings.append(Finding("warning", "long-sentence", f"第 {index} 句有效字符 {count}，建议检查听辨负担"))

    short_run = 0
    for sentence in sentence_list:
        if effective_char_count(sentence) <= 8:
            short_run += 1
            if short_run == 3:
                findings.append(Finding("warning", "fragmented-rhythm", "发现连续三个短句，建议检查是否机械切句"))
        else:
            short_run = 0

    missing_locations = [location for location in normalized_locations if location not in text]
    for location in missing_locations:
        findings.append(Finding("error", "missing-location", f"用户指定地点未进入正文：{location}"))

    char_count = effective_char_count(text)
    min_minutes, max_minutes = estimate_minutes(char_count, speed)
    errors = sum(item.level == "error" for item in findings)
    warnings = sum(item.level == "warning" for item in findings)
    return {
        "effective_char_count": char_count,
        "sentence_count": len(sentence_list),
        "speed_multiplier": speed,
        "estimated_minutes": {
            "fast_160_cpm": round(min_minutes, 2),
            "slow_120_cpm": round(max_minutes, 2),
        },
        "locations_checked": normalized_locations,
        "missing_locations": missing_locations,
        "error_count": errors,
        "warning_count": warnings,
        "status": "failed" if errors else ("review" if warnings else "passed"),
        "findings": [asdict(item) for item in findings],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 narration text file")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    parser.add_argument("--location", action="append", default=[], help="Required location; repeat as needed")
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when warnings exist")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        text = args.input.read_text(encoding="utf-8")
        report = analyze(text, args.speed, args.location)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if report["error_count"] or (args.strict and report["warning_count"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
