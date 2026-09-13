#!/usr/bin/env python3
"""从中文纯文本中确定性生成音色克隆单元和字幕单元。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import socket
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LIMIT = 13
MIN_SUBTITLE_CONTENT = 3
SMART_STANDALONE_CONNECTORS = {
    "因此", "所以", "但是", "然而", "不过", "同时", "此外", "于是", "接着", "然后", "最后",
}
FINAL = set("。！？?!")
BREAKS = set("。！？?!；;：:，,、…")
BREAK_PRIORITY = {
    "。": 4, "！": 4, "？": 4, "!": 4, "?": 4, "…": 4,
    "；": 3, ";": 3,
    "：": 2, ":": 2,
    "，": 1, ",": 1, "、": 1,
}
OPEN_TO_CLOSE = {"“": "”", "‘": "’", "「": "」", "『": "』", "（": "）", "《": "》", "【": "】"}
OPENING = set(OPEN_TO_CLOSE)
CLOSING = set(OPEN_TO_CLOSE.values())
NO_LINE_START = set("，。；：！？、,.;:?!…”’」』）》】")
NO_LINE_END = OPENING
INTERNAL_OUTPUT_NAMES = (
    "00-normalized-source.md",
    "01-voice-cloning-copy.txt",
    "02-smart-transcript-subtitles.txt",
    "project-data.json",
    "quality-report.json",
)
OUTPUT_NAMES = INTERNAL_OUTPUT_NAMES
TRANSACTION_MANIFEST_NAME = ".video-copy-splitter-transaction.json"
TRANSACTION_COMPLETE_NAME = ".video-copy-splitter-complete.json"
INTERNAL_TRANSACTION_NAMES = INTERNAL_OUTPUT_NAMES + (
    TRANSACTION_MANIFEST_NAME,
    TRANSACTION_COMPLETE_NAME,
)
FINAL_DELIVERY_NAMES = (
    "01-音色克隆文案.txt",
    "02-智能文稿匹配文案.txt",
    "03-模块化视频脚本与分镜.xlsx",
)
EPISODE_HEADER_RE = re.compile(r"^\s*第(?:\d+|[零〇一二两三四五六七八九十百]+)集\s*$")
AUTO_PROTECTED_RE = re.compile(
    r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万亿点]+)"
    r"(?:平方公里|平方千米|摄氏度|公里|千米|厘米|毫米|分钟|小时|米|年|月|日|时|分|秒|度|倍|座|个|条|人|岁|集|字)?"
    r"|[A-Za-z]+(?:[-_][A-Za-z0-9]+)*"
)
MOJIBAKE_TOKENS = (
    "锟斤拷", "涓€", "瑙嗛", "璐ㄩ", "浣犲ソ", "鏂囨湰", "鏂囦欢", "鍐呭",
    "杈撳嚭", "鐢ㄦ埛", "瀛楃", "缁撴灉", "妯″潡", "鍒嗛暅", "鏅鸿兘",
    "闊宠壊", "浜や粯", "璇箟", "鏁版嵁", "鐩綍", "鎵ц", "鏍￠獙",
    "Ã", "Â", "â€", "â€™", "â€œ", "â€�", "ðŸ", "ï»¿",
)
LOSSY_MOJIBAKE_TOKENS = ("\ufffd", "锟斤拷")


def mojibake_score(text: str) -> int:
    """为常见错误解码痕迹计分；分数大于0表示输出前必须处理。"""
    score = 0
    for ch in text:
        codepoint = ord(ch)
        if ch == "\ufffd":
            score += 100
        elif 0xE000 <= codepoint <= 0xF8FF:
            score += 30
        elif 0x80 <= codepoint <= 0x9F:
            score += 30
        elif 0x3100 <= codepoint <= 0x312F:
            score += 15
    for token in MOJIBAKE_TOKENS:
        score += text.count(token) * 10
    return score


def _decode_mojibake_candidate(text: str) -> str | None:
    """尝试逆转“UTF-8字节被GB18030或西文编码误读”的可逆乱码。"""
    candidates: list[str] = []
    for encoding in ("gb18030", "latin1", "cp1252"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        introduced_unexpected_script = any(
            unicodedata.name(ch, "").startswith(("CYRILLIC", "HIRAGANA", "KATAKANA", "HANGUL", "BOPOMOFO"))
            for ch in candidate
        )
        if candidate != text and not introduced_unexpected_script:
            candidates.append(candidate)
    if not candidates:
        return None
    return min(candidates, key=lambda value: (mojibake_score(value), len(value)))


def _suspicious_positions(text: str) -> list[int]:
    positions: set[int] = set()
    for index, ch in enumerate(text):
        codepoint = ord(ch)
        if ch == "\ufffd" or 0xE000 <= codepoint <= 0xF8FF or 0x80 <= codepoint <= 0x9F or 0x3100 <= codepoint <= 0x312F:
            positions.add(index)
    for token in MOJIBAKE_TOKENS:
        start = 0
        while True:
            index = text.find(token, start)
            if index < 0:
                break
            positions.update(range(index, index + len(token)))
            start = index + 1
    return sorted(positions)


def repair_mojibake(text: str) -> tuple[str, int]:
    """修复可逆乱码片段；原始信息已丢失或仍有疑点时安全失败。"""
    if not isinstance(text, str):
        raise TypeError("乱码检测只接受字符串")
    if any(token in text for token in LOSSY_MOJIBAKE_TOKENS):
        raise ValueError("检测到已丢失原始信息的乱码（�或锟斤拷），无法可靠自动修复")
    repaired = text
    repair_count = 0
    for _ in range(20):
        original_score = mojibake_score(repaired)
        if original_score == 0:
            return repaired, repair_count
        whole = _decode_mojibake_candidate(repaired)
        if whole is not None and mojibake_score(whole) < original_score:
            repaired = whole
            repair_count += 1
            continue
        best: tuple[int, int, str, int] | None = None
        for position in _suspicious_positions(repaired):
            left = max(0, position - 32)
            right = min(len(repaired), position + 65)
            for start in range(left, position + 1):
                for end in range(position + 1, right + 1):
                    source = repaired[start:end]
                    candidate = _decode_mojibake_candidate(source)
                    if candidate is None:
                        continue
                    improvement = mojibake_score(source) - mojibake_score(candidate)
                    if improvement <= 0:
                        continue
                    proposal = (start, end, candidate, improvement)
                    if best is None or (improvement, -(end - start)) > (best[3], -(best[1] - best[0])):
                        best = proposal
        if best is None:
            break
        start, end, candidate, _ = best
        repaired = repaired[:start] + candidate + repaired[end:]
        repair_count += 1
    if mojibake_score(repaired) > 0:
        raise ValueError(f"检测到疑似乱码但无法可靠自动修复：{repaired}")
    return repaired, repair_count


def assert_no_mojibake(text: str, label: str) -> None:
    """阻止任何仍含可疑或损坏字符的文本进入输出。"""
    if any(token in text for token in LOSSY_MOJIBAKE_TOKENS) or mojibake_score(text) > 0:
        raise ValueError(f"{label}仍存在乱码，禁止输出")


def read_text_detect_encoding(path: Path) -> str:
    """优先按UTF-8读取，失败时尝试GB18030，拒绝带损坏字符的解码结果。"""
    payload = path.read_bytes()
    errors: list[str] = []
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = payload.decode(encoding)
        except UnicodeDecodeError as exc:
            errors.append(f"{encoding}: {exc}")
            continue
        if "\ufffd" not in text:
            return text
    raise UnicodeError(f"无法使用UTF-8或GB18030无损读取文本：{path}；{errors}")


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def paragraphs(text: str) -> list[str]:
    return [re.sub(r"\s*\n\s*", "", block).strip() for block in re.split(r"\n\s*\n", text) if block.strip()]


def split_voice(paragraph: str) -> list[str]:
    out: list[str] = []
    start = 0
    stack: list[str] = []
    i = 0
    while i < len(paragraph):
        ch = paragraph[i]
        if ch in OPEN_TO_CLOSE:
            stack.append(OPEN_TO_CLOSE[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
        if ch in FINAL or ch == "…":
            j = i + 1
            while j < len(paragraph) and (paragraph[j] == ch or paragraph[j] in CLOSING):
                j += 1
            # 闭引号归入它所关闭的句子；引文内部的句末标点仍可作为旁白边界。
            unit = paragraph[start:j].strip()
            if unit:
                out.append(unit)
            start = j
            i = j
            continue
        i += 1
    tail = paragraph[start:].strip()
    if tail:
        out.append(tail)
    return out


def apply_pronunciation_map(text: str, replacements: dict[str, str] | None = None) -> str:
    """以不重叠的单次匹配应用替换，禁止级联修改。"""
    if not replacements:
        return text
    normalized: dict[str, str] = {}
    for source, target in replacements.items():
        if not source or not isinstance(target, str):
            raise ValueError("读音替换表必须使用非空字符串作为原文和替换值")
        if source == target:
            raise ValueError(f"替换前后完全相同，无法证明已处理：{source}")
        normalized[source] = target
    sources = set(normalized)
    for source, target in normalized.items():
        hit = [other for other in sources if other in target]
        if hit:
            raise ValueError(f"替换结果会命中其他源词，存在级联或循环风险：{source}->{target}，命中={hit}")
    pattern = re.compile("|".join(re.escape(source) for source in sorted(sources, key=len, reverse=True)))
    return pattern.sub(lambda match: normalized[match.group(0)], text)


def normalize_pronunciation_review(review: dict | list | None, source_hash: str | None = None) -> list[dict]:
    """校验带语境、目标读音和复核状态的内部读音审查表。"""
    if review is None:
        return []
    if isinstance(review, dict) and "entries" not in review:
        # 保留库调用兼容性；正式 CLI 流程必须使用结构化审查表。
        return [
            {
                "source": source,
                "target_pronunciation": "兼容模式未提供",
                "replacement": replacement,
                "sentence_ids": ["*"],
                "review_status": "已替换",
                "reason": "兼容模式",
            }
            for source, replacement in review.items()
        ]
    if isinstance(review, dict):
        if review.get("review_complete") is not True:
            raise ValueError("读音审查表未标记 review_complete=true")
        if source_hash and review.get("source_sha256") != source_hash:
            raise ValueError("读音审查表的 source_sha256 与当前母版不一致")
        entries = review.get("entries")
    else:
        entries = review
    if not isinstance(entries, list):
        raise ValueError("读音审查表 entries 必须是数组")
    required = {"source", "target_pronunciation", "replacement", "sentence_ids", "review_status"}
    allowed_status = {"已替换", "确认无需替换"}
    normalized = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict) or not required.issubset(entry):
            raise ValueError(f"读音审查第{index}项缺少必填字段：{sorted(required)}")
        if entry["review_status"] not in allowed_status:
            raise ValueError(f"读音审查第{index}项尚未完成复核：{entry['review_status']}")
        if not isinstance(entry["sentence_ids"], list) or not entry["sentence_ids"]:
            raise ValueError(f"读音审查第{index}项必须指定 sentence_ids")
        if entry["review_status"] == "已替换" and entry["source"] == entry["replacement"]:
            raise ValueError(f"读音审查第{index}项标记已替换但文本未变化")
        normalized.append(entry)
    return normalized


def apply_pronunciation_review(text: str, sentence_id: str, entries: list[dict]) -> str:
    replacements: dict[str, str] = {}
    for entry in entries:
        if entry["review_status"] != "已替换":
            continue
        if "*" not in entry["sentence_ids"] and sentence_id not in entry["sentence_ids"]:
            continue
        source = entry["source"]
        replacement = entry["replacement"]
        previous = replacements.get(source)
        if previous is not None and previous != replacement:
            raise ValueError(f"同一句中的同一源词存在冲突替换：{sentence_id} {source}")
        replacements[source] = replacement
    return apply_pronunciation_map(text, replacements)


def quote_spans(text: str) -> dict[int, int]:
    """返回必须保持完整的短配对引文范围。"""
    spans: dict[int, int] = {}
    stack: list[tuple[str, int]] = []
    quote_pairs = {k: v for k, v in OPEN_TO_CLOSE.items() if k not in "（《【"}
    for i, ch in enumerate(text):
        if ch in quote_pairs:
            stack.append((quote_pairs[ch], i))
        elif stack and ch == stack[-1][0]:
            _, begin = stack.pop()
            if subtitle_character_count(text[begin:i + 1]) <= LIMIT:
                spans[begin] = i + 1
    return spans


def atoms(text: str, protected_terms: list[str] | None = None) -> list[str]:
    spans = quote_spans(text)
    terms = sorted({term for term in (protected_terms or []) if isinstance(term, str) and len(term) > 1}, key=len, reverse=True)
    result: list[str] = []
    i = 0
    while i < len(text):
        end = spans.get(i)
        if end is not None:
            result.append(text[i:end])
            i = end
            continue
        protected = next((term for term in terms if text.startswith(term, i)), None)
        if protected:
            result.append(protected)
            i += len(protected)
            continue
        automatic = AUTO_PROTECTED_RE.match(text, i)
        if automatic:
            result.append(automatic.group(0))
            i = automatic.end()
            continue
        result.append(text[i])
        i += 1
    return result


def split_smart_units(text: str, protected_terms: list[str] | None = None) -> list[str]:
    """在指定标点处切分，同时保护短引文不被拆开。"""
    result: list[str] = []
    current: list[str] = []
    items = atoms(text.strip(), protected_terms)
    i = 0
    while i < len(items):
        item = items[i]
        current.append(item)
        # 多字符原子代表受保护的短引文，其内部标点不得建立文稿切分边界。
        if len(item) == 1 and item in BREAKS:
            while i + 1 < len(items) and (
                items[i + 1] == item == "…" or
                (len(items[i + 1]) == 1 and items[i + 1] in CLOSING)
            ):
                i += 1
                current.append(items[i])
            result.append("".join(current))
            current = []
        i += 1
    if current:
        result.append("".join(current))
    return [unit for unit in result if unit]


def subtitle_character_count(text: str) -> int:
    """只计算中文字符和数字；标点、引号、空格及其他字符不占13字额度。"""
    count = 0
    for ch in text:
        name = unicodedata.name(ch, "")
        if (
            ch.isdigit()
            or ch == "〇"
            or name.startswith("CJK UNIFIED IDEOGRAPH")
            or name.startswith("CJK COMPATIBILITY IDEOGRAPH")
        ):
            count += 1
    return count


def subtitle_content_character_count(text: str) -> int:
    """只计算字母和数字，用于禁止一两个正文字符单独成行。"""
    return sum(1 for ch in text if unicodedata.category(ch)[0] in {"L", "N"})


def split_at_preferred_boundary(items: list[str], limit: int) -> int:
    candidates: list[tuple[int, int]] = []
    prefix = ""
    for idx, item in enumerate(items):
        candidate = prefix + item
        if subtitle_character_count(candidate) > limit:
            break
        prefix = candidate
        remaining_content = subtitle_content_character_count("".join(items[idx + 1:]))
        if (
            item[-1] in BREAKS
            and subtitle_content_character_count(candidate) >= MIN_SUBTITLE_CONTENT
            and remaining_content not in {1, 2}
        ):
            candidates.append((BREAK_PRIORITY[item[-1]], idx + 1))
    if candidates:
        # 先选择优先级最高的标点，再选该级别中最靠后的边界。
        # 这样可让“他说：”与长引文分行，而不会为了填满行宽延伸到下一个逗号。
        strongest = max(priority for priority, _ in candidates)
        return max(index for priority, index in candidates if priority == strongest)
    # 在保证闭合标点跟随前文的前提下，尽可能利用剩余行宽。
    cut = 0
    prefix = ""
    for idx, item in enumerate(items):
        candidate = prefix + item
        if subtitle_character_count(candidate) > limit:
            break
        prefix = candidate
        cut = idx + 1
    return max(cut, 1)


def is_punctuation_only(text: str) -> bool:
    return bool(text) and all(unicodedata.category(ch).startswith("P") or ch in "…" for ch in text)


def wrap_subtitles(text: str, limit: int = LIMIT, protected_terms: list[str] | None = None) -> list[str]:
    pending = atoms(text.strip(), protected_terms)
    lines: list[str] = []
    while pending:
        remaining = "".join(pending)
        if subtitle_character_count(remaining) <= limit:
            line = remaining
            if line[0] in NO_LINE_START or is_punctuation_only(line):
                raise ValueError(f"无法生成合法字幕行：{line}")
            lines.append(line)
            break
        cut = split_at_preferred_boundary(pending, limit)
        # 若下一段以闭合标点开头，向前回退一个内容原子，把标点和内容留在下一行。
        while cut > 0 and cut < len(pending) and pending[cut] and pending[cut][0] in NO_LINE_START:
            cut -= 1
        while cut > 0 and pending[cut - 1][-1] in NO_LINE_END:
            cut -= 1
        # 标点回退后若只剩一两个正文字符，继续向前移动完整原子，给尾行保留可理解的短语。
        while cut > 0 and 0 < subtitle_content_character_count("".join(pending[cut:])) < MIN_SUBTITLE_CONTENT:
            cut -= 1
        if cut <= 0:
            raise ValueError(f"受保护词组或标点组合无法在{limit}字符内安全切分：{text}")
        line = "".join(pending[:cut])
        if subtitle_character_count(line) > limit:
            raise ValueError(f"不可拆分的表达超过{limit}个字符：{line}")
        if line[0] in NO_LINE_START or is_punctuation_only(line):
            raise ValueError(f"生成了非法字幕行：{line}")
        if subtitle_content_character_count(line) < MIN_SUBTITLE_CONTENT:
            raise ValueError(f"字幕行只有一两个正文字符，必须按语义重新切分：{line}")
        lines.append(line)
        pending = pending[cut:]
    if any(subtitle_content_character_count(line) < MIN_SUBTITLE_CONTENT for line in lines):
        raise ValueError(f"存在少于{MIN_SUBTITLE_CONTENT}个正文字符的字幕行，必须人工按语义合并：{text}")
    return [line for line in lines if line]


def wrap_smart_subtitles(
    text: str,
    limit: int = LIMIT,
    protected_terms: list[str] | None = None,
) -> list[str]:
    """优先保留标点语义边界，并把一两个正文字符的短单元与相邻语义合并。"""
    units = split_smart_units(text, protected_terms)
    lines: list[str] = []
    short_buffer = ""
    for unit in units:
        if subtitle_content_character_count(unit) < MIN_SUBTITLE_CONTENT:
            short_buffer += unit
            continue
        combined = short_buffer + unit
        short_buffer = ""
        lines.extend(wrap_subtitles(combined, limit, protected_terms))
    if short_buffer:
        if not lines:
            raise ValueError(f"整句不足{MIN_SUBTITLE_CONTENT}个正文字符，无法生成独立字幕：{text}")
        previous = lines.pop()
        lines.extend(wrap_subtitles(previous + short_buffer, limit, protected_terms))
    if any(subtitle_content_character_count(line) < MIN_SUBTITLE_CONTENT for line in lines):
        raise ValueError(f"语义合并后仍存在一两个正文字符的字幕行：{text}")
    return lines


def split_smart_transcript_lines(text: str, protected_terms: list[str] | None = None) -> list[str]:
    """先按标点与语气形成语义行，再确保每行不超过13个中文字符或数字。"""
    units = split_smart_units(text, protected_terms)
    lines: list[str] = []
    buffer = ""
    for unit in units:
        content = "".join(ch for ch in unit if unicodedata.category(ch)[0] in {"L", "N"})
        if len(content) <= 2 and content not in SMART_STANDALONE_CONNECTORS:
            buffer += unit
            continue
        line = buffer + unit
        buffer = ""
        lines.append(line)
    if buffer:
        if lines:
            lines[-1] += buffer
        else:
            lines.append(buffer)
    limited_lines: list[str] = []
    for line in lines:
        if subtitle_character_count(line) <= LIMIT:
            limited_lines.append(line)
        else:
            limited_lines.extend(wrap_subtitles(line, LIMIT, protected_terms))
    return limited_lines


def validate_reviewed_smart_lines(source_sentences: list[dict], reviewed_lines: list[str]) -> list[tuple[str, str]]:
    """校验语义切分逐字还原原文、单行归属和13字硬上限。"""
    if not isinstance(reviewed_lines, list) or not reviewed_lines:
        raise ValueError("智能文稿匹配切分必须是非空行数组")
    if any(not isinstance(line, str) or not line or line.strip() != line for line in reviewed_lines):
        raise ValueError("智能文稿匹配切分不得包含空行或行首行尾空白")
    mapped: list[tuple[str, str]] = []
    sentence_index = 0
    offset = 0
    for line in reviewed_lines:
        effective_length = subtitle_character_count(line)
        if effective_length > LIMIT:
            raise ValueError(
                f"智能文稿匹配单行超过{LIMIT}个中文字符或数字：{effective_length}，内容={line}"
            )
        if EPISODE_HEADER_RE.fullmatch(line):
            raise ValueError(f"智能文稿匹配文案包含集数分隔行：{line}")
        if sentence_index >= len(source_sentences):
            raise ValueError("智能文稿匹配切分包含母版以外的多余内容")
        sentence = source_sentences[sentence_index]
        source = sentence["source_sentence_text"]
        if not source.startswith(line, offset):
            raise ValueError(f"智能文稿匹配切分未按原文顺序逐字符还原：{line}")
        offset += len(line)
        if offset == len(source):
            sentence_index += 1
            offset = 0
        elif offset > len(source):
            raise ValueError(f"智能文稿匹配单行跨越完整原文句子：{line}")
        mapped.append((sentence["id"], line))
    if sentence_index != len(source_sentences) or offset != 0:
        raise ValueError("智能文稿匹配切分缺少部分原文")
    return mapped


def spoken_character_count(text: str) -> int:
    return sum(1 for ch in text if unicodedata.category(ch)[0] in {"L", "N"})


def estimate_min_duration(text: str, chars_per_second: float = 4.0, pause_seconds: float = 0.35) -> float:
    if chars_per_second <= 0:
        raise ValueError("每秒字数必须大于0")
    return math.ceil((spoken_character_count(text) / chars_per_second + pause_seconds) * 10) / 10


def process(
    text: str,
    pronunciation_review: dict | list | None = None,
    protected_terms: list[str] | None = None,
    chars_per_second: float = 4.0,
    smart_transcript_lines: list[str] | None = None,
) -> dict:
    text, mojibake_repair_count = repair_mojibake(text)
    text = normalize(text)
    paras = paragraphs(text)
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    pronunciation_entries = normalize_pronunciation_review(pronunciation_review, source_hash)
    source_sentences = []
    voice = []
    captions = []
    for p_index, para in enumerate(paras, 1):
        pid = f"P{p_index:03d}"
        for unit in split_voice(para):
            sid = f"S{len(source_sentences)+1:03d}"
            source_sentences.append(
                {
                    "id": sid,
                    "paragraph_id": pid,
                    "source_sentence_text": unit,
                    "spoken_character_count": spoken_character_count(unit),
                    "minimum_duration_seconds": estimate_min_duration(unit, chars_per_second),
                }
            )
            voice.append(
                {
                    "id": f"V{len(voice)+1:03d}",
                    "sentence_id": sid,
                    "paragraph_id": pid,
                    "voice_text": apply_pronunciation_review(unit, sid, pronunciation_entries),
                }
            )
    if smart_transcript_lines is None:
        smart_transcript_lines = []
        for sentence in source_sentences:
            smart_transcript_lines.extend(
                split_smart_transcript_lines(sentence["source_sentence_text"], protected_terms)
            )
    else:
        clean_lines = []
        for line in smart_transcript_lines:
            clean_line, repair_count = repair_mojibake(line)
            mojibake_repair_count += repair_count
            clean_lines.append(clean_line)
        smart_transcript_lines = clean_lines
    mapped_lines = validate_reviewed_smart_lines(source_sentences, smart_transcript_lines)
    paragraph_by_sentence = {row["id"]: row["paragraph_id"] for row in source_sentences}
    for sid, line in mapped_lines:
        captions.append(
            {
                "id": f"M{len(captions)+1:03d}",
                "sentence_id": sid,
                "paragraph_id": paragraph_by_sentence[sid],
                "text": line,
                "length": subtitle_character_count(line),
                "raw_length": len(line),
                "content_length": subtitle_content_character_count(line),
            }
        )
    return {
        "normalized_source": text,
        "source_sha256": source_hash,
        "paragraphs": paras,
        "source_sentences": source_sentences,
        "voice_units": voice,
        "subtitle_lines": captions,
        "pronunciation_review_entries": pronunciation_entries,
        "chars_per_second": chars_per_second,
        "mojibake_repair_count": mojibake_repair_count,
    }


def render_voice_plain(rows: list[dict]) -> str:
    """只输出一行一句的音色克隆纯文案。"""
    return "\n".join(row["voice_text"] for row in rows) + "\n"


def render_subtitles_plain(rows: list[dict]) -> str:
    """只输出一行一条的智能文稿匹配纯文案。"""
    return "\n".join(row["text"] for row in rows) + "\n"


def build_outputs(data: dict) -> dict[str, str]:
    """先在内存中完整生成全部输出内容。"""
    source_text = "".join(row["source_sentence_text"] for row in data["source_sentences"])
    paragraph_text = "".join(data["paragraphs"])
    caption_text = "".join(row["text"] for row in data["subtitle_lines"])
    subtitle_errors = []
    for row in data["subtitle_lines"]:
        text = row["text"]
        if not text or text[0] in NO_LINE_START:
            subtitle_errors.append(f"{row['id']}存在禁用行首")
        if is_punctuation_only(text):
            subtitle_errors.append(f"{row['id']}是纯标点行")
        if text[-1] in NO_LINE_END:
            subtitle_errors.append(f"{row['id']}存在禁用行尾")
        if row["length"] > LIMIT:
            subtitle_errors.append(f"{row['id']}超过{LIMIT}个中文字符或数字")
    if source_text != paragraph_text:
        raise ValueError("原文句子模型无法逐字符还原规范化段落")
    if caption_text != source_text:
        raise ValueError("字幕无法逐字符还原不可变原文句子")
    if subtitle_errors:
        raise ValueError("字幕硬性校验失败：" + "；".join(subtitle_errors))
    quality_report = {
        "source_sha256": data["source_sha256"],
        "source_sentence_count": len(data["source_sentences"]),
        "voice_unit_count": len(data["voice_units"]),
        "subtitle_line_count": len(data["subtitle_lines"]),
        "subtitle_max_length": max((row["length"] for row in data["subtitle_lines"]), default=0),
        "subtitle_max_raw_length": max((row["raw_length"] for row in data["subtitle_lines"]), default=0),
        "subtitle_bad_start_count": 0,
        "subtitle_punctuation_only_count": 0,
        "source_reconstruction_passed": True,
        "caption_reconstruction_passed": True,
        "pronunciation_review_entry_count": len(data["pronunciation_review_entries"]),
        "mojibake_repair_count": data.get("mojibake_repair_count", 0),
        "mojibake_unresolved_count": 0,
    }
    outputs = {
        "00-normalized-source.md": data["normalized_source"] + "\n",
        "01-voice-cloning-copy.txt": render_voice_plain(data["voice_units"]),
        "02-smart-transcript-subtitles.txt": render_subtitles_plain(data["subtitle_lines"]),
        "project-data.json": json.dumps(data, ensure_ascii=False, indent=2),
        "quality-report.json": json.dumps(quality_report, ensure_ascii=False, indent=2),
    }
    for name, content in outputs.items():
        assert_no_mojibake(content, name)
    return outputs


def validate_output_dir(output_dir: Path) -> Path:
    """拒绝明显过宽的危险输出目录，并返回绝对路径。"""
    resolved = output_dir.expanduser().resolve()
    forbidden = {Path.home().resolve(), Path.cwd().resolve()}
    if resolved.anchor:
        forbidden.add(Path(resolved.anchor).resolve())
    if resolved in forbidden:
        raise ValueError(f"禁止将用户主目录、当前工作目录或磁盘根目录直接作为输出目录：{resolved}")
    return resolved


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_hash_from_outputs(outputs: dict[str, str]) -> str:
    try:
        project_data = json.loads(outputs["project-data.json"])
        source_hash = project_data["source_sha256"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("project-data.json 缺少有效的 source_sha256") from exc
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError("project-data.json 的 source_sha256 格式无效")
    return source_hash


def _lock_path_for(output_dir: Path) -> Path:
    return output_dir.parent / f".{output_dir.name}.video-copy-splitter.lock"


def _is_network_path(path: Path) -> bool:
    """Windows下拒绝UNC或映射网络盘；POSIX无法可靠识别时由部署方限制。"""
    if os.name != "nt":
        return False
    text = str(path)
    if text.startswith("\\\\"):
        return True
    import ctypes

    drive_remote = 4
    root = path.anchor
    return bool(root) and ctypes.windll.kernel32.GetDriveTypeW(root) == drive_remote


def _open_kernel_lock(lock_path: Path) -> tuple[int, str]:
    """非阻塞获取固定锁文件的内核排他锁，并返回持续持有的文件描述符。"""
    if os.name == "nt":
        import ctypes
        import msvcrt
        from ctypes import wintypes

        generic_read = 0x80000000
        generic_write = 0x40000000
        file_share_read = 0x00000001
        open_always = 4
        file_attribute_normal = 0x00000080
        error_sharing_violation = 32
        error_lock_violation = 33
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(lock_path),
            generic_read | generic_write,
            file_share_read,
            None,
            open_always,
            file_attribute_normal,
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            error = ctypes.get_last_error()
            if error in {error_sharing_violation, error_lock_violation}:
                raise FileExistsError(f"事务内核锁正被其他任务持有：{lock_path}")
            if error == 5:
                raise PermissionError(f"没有权限创建或打开事务锁：{lock_path}")
            raise OSError(error, f"无法获取Windows事务锁：{lock_path}")
        try:
            return msvcrt.open_osfhandle(handle, os.O_RDWR), "windows-createfile"
        except Exception:
            kernel32.CloseHandle(handle)
            raise

    import fcntl

    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise FileExistsError(f"事务内核锁正被其他任务持有：{lock_path}") from exc
    except Exception:
        os.close(fd)
        raise
    return fd, "posix-flock"


def _release_kernel_lock(fd: int, protocol: str) -> None:
    if protocol == "posix-flock":
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取事务文件：{path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"事务文件不是JSON对象：{path}")
    return value


@contextmanager
def acquire_output_lock(
    output_dir: Path,
    input_hash: str,
    *,
    transaction_id: str | None = None,
):
    """持续持有操作系统内核排他锁；固定锁文件本身不移动、不删除。"""
    output_dir = validate_output_dir(output_dir)
    if _is_network_path(output_dir):
        raise ValueError(f"不支持在无法保证本地内核锁语义的网络路径写入：{output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path_for(output_dir)
    transaction_id = transaction_id or uuid.uuid4().hex
    try:
        fd, protocol = _open_kernel_lock(lock_path)
    except FileExistsError as exc:
        raise FileExistsError(
            f"另一个任务正在处理同一输出目录，未执行写入：{output_dir}\n"
            f"锁文件：{lock_path}\n"
            "--force 不能绕过事务内核锁。锁文件是否存在不代表锁是否占用，禁止移动或删除该文件。"
        ) from exc
    metadata = {
        "transaction_id": transaction_id,
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "started_at": datetime.now().astimezone().isoformat(),
        "output_path": str(output_dir),
        "input_sha256": input_hash,
        "lock_protocol": protocol,
    }
    payload = json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8")

    try:
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        offset = 0
        while offset < len(payload):
            written = os.write(fd, payload[offset:])
            if written <= 0:
                raise OSError(f"事务锁信息未完整写入：{lock_path}")
            offset += written
        os.fsync(fd)
        yield metadata
    finally:
        _release_kernel_lock(fd, protocol)


def _new_backup_dir(output_dir: Path, timestamp: str | None = None) -> Path:
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_root = output_dir.parent / f".{output_dir.name}.backup"
    candidate = backup_root / f"{stamp}-{uuid.uuid4().hex[:8]}"
    suffix = 1
    while candidate.exists():
        candidate = backup_root / f"{stamp}-{uuid.uuid4().hex[:8]}-{suffix}"
        suffix += 1
    return candidate


def _write_transaction_stage(
    stage_dir: Path,
    outputs: dict[str, str],
    transaction: dict,
) -> None:
    file_entries = []
    for name in OUTPUT_NAMES:
        content = outputs[name]
        assert_no_mojibake(content, name)
        (stage_dir / name).write_text(content, encoding="utf-8")
        reopened = (stage_dir / name).read_text(encoding="utf-8")
        if reopened != content:
            raise ValueError(f"UTF-8回读内容不一致，禁止发布：{name}")
        assert_no_mojibake(reopened, name)
        file_entries.append(
            {"name": name, "sha256": _sha256_text(content), "size_bytes": len(content.encode("utf-8"))}
        )
    manifest = {
        "schema_version": 1,
        **transaction,
        "files": file_entries,
    }
    manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (stage_dir / TRANSACTION_MANIFEST_NAME).write_text(manifest_text, encoding="utf-8")
    complete = {
        "transaction_id": transaction["transaction_id"],
        "input_sha256": transaction["input_sha256"],
        "manifest_sha256": _sha256_text(manifest_text),
        "completed_at": datetime.now().astimezone().isoformat(),
    }
    (stage_dir / TRANSACTION_COMPLETE_NAME).write_text(
        json.dumps(complete, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def validate_internal_transaction(
    output_dir: Path,
    *,
    expected_transaction_id: str | None = None,
    expected_input_hash: str | None = None,
) -> dict:
    """验证整套内部文件来自同一已完成事务，拒绝混合集或残缺目录。"""
    output_dir = validate_output_dir(output_dir)
    if not output_dir.is_dir():
        raise FileNotFoundError(f"内部输出目录不存在：{output_dir}")
    entries = list(output_dir.iterdir())
    actual = {path.name for path in entries if path.is_file()}
    directories = [path.name for path in entries if path.is_dir()]
    expected = set(INTERNAL_TRANSACTION_NAMES)
    if actual != expected or directories:
        raise ValueError(
            f"内部事务目录不完整：缺少={sorted(expected-actual)}，多出={sorted(actual-expected)}，目录={directories}"
        )
    manifest_path = output_dir / TRANSACTION_MANIFEST_NAME
    complete_path = output_dir / TRANSACTION_COMPLETE_NAME
    manifest = _read_json(manifest_path)
    complete = _read_json(complete_path)
    transaction_id = manifest.get("transaction_id")
    input_hash = manifest.get("input_sha256")
    if expected_transaction_id and transaction_id != expected_transaction_id:
        raise ValueError("内部目录不属于预期事务")
    if expected_input_hash and input_hash != expected_input_hash:
        raise ValueError("内部目录的输入哈希不匹配")
    if complete.get("transaction_id") != transaction_id or complete.get("input_sha256") != input_hash:
        raise ValueError("完成标记与事务清单不匹配")
    manifest_text = manifest_path.read_text(encoding="utf-8")
    if complete.get("manifest_sha256") != _sha256_text(manifest_text):
        raise ValueError("事务清单哈希与完成标记不匹配")
    listed = manifest.get("files")
    if not isinstance(listed, list) or {item.get("name") for item in listed if isinstance(item, dict)} != set(OUTPUT_NAMES):
        raise ValueError("事务清单的文件集合无效")
    for item in listed:
        path = output_dir / item["name"]
        content = path.read_text(encoding="utf-8")
        if _sha256_text(content) != item.get("sha256") or len(content.encode("utf-8")) != item.get("size_bytes"):
            raise ValueError(f"内部文件与事务清单不匹配：{path}")
    return manifest


def _directory_belongs_to_transaction(output_dir: Path, transaction_id: str, input_hash: str) -> bool:
    try:
        validate_internal_transaction(
            output_dir,
            expected_transaction_id=transaction_id,
            expected_input_hash=input_hash,
        )
    except (OSError, ValueError, RuntimeError):
        return False
    return True


def write_outputs_safely(
    output_dir: Path,
    outputs: dict[str, str],
    *,
    force: bool = False,
    replace_fn=os.replace,
    timestamp: str | None = None,
) -> Path | None:
    """持锁生成完整事务目录，再以整目录重命名原子发布。"""
    if set(outputs) != set(OUTPUT_NAMES):
        missing = sorted(set(OUTPUT_NAMES) - set(outputs))
        extra = sorted(set(outputs) - set(OUTPUT_NAMES))
        raise ValueError(f"输出集合不完整，缺少={missing}，多出={extra}")

    output_dir = validate_output_dir(output_dir)
    input_hash = _source_hash_from_outputs(outputs)
    transaction_id = uuid.uuid4().hex
    with acquire_output_lock(
        output_dir,
        input_hash,
        transaction_id=transaction_id,
    ) as transaction:
        stage_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.stage-{transaction_id}-", dir=output_dir.parent))
        backup_dir: Path | None = None
        removed_empty_dir = False
        published = False
        try:
            _write_transaction_stage(stage_dir, outputs, transaction)
            validate_internal_transaction(
                stage_dir,
                expected_transaction_id=transaction_id,
                expected_input_hash=input_hash,
            )

            if output_dir.exists():
                if not output_dir.is_dir():
                    raise FileExistsError(f"输出路径已存在且不是目录：{output_dir}")
                existing_entries = list(output_dir.iterdir())
                if existing_entries and not force:
                    joined = "\n".join(f"- {path}" for path in existing_entries)
                    raise FileExistsError(
                        "输出目录已有内容，未执行任何写入。请更换新的空目录；"
                        "仅在用户明确授权后使用 --force：\n"
                        f"{joined}"
                    )
                if existing_entries:
                    backup_dir = _new_backup_dir(output_dir, timestamp)
                    backup_dir.parent.mkdir(parents=True, exist_ok=True)
                    replace_fn(output_dir, backup_dir)
                else:
                    output_dir.rmdir()
                    removed_empty_dir = True

            replace_fn(stage_dir, output_dir)
            published = True
            validate_internal_transaction(
                output_dir,
                expected_transaction_id=transaction_id,
                expected_input_hash=input_hash,
            )
            return backup_dir
        except Exception:
            if published and output_dir.exists():
                if not _directory_belongs_to_transaction(output_dir, transaction_id, input_hash):
                    raise RuntimeError(
                        "发布失败后目标目录已不属于当前事务；为防止删除其他任务成果，已停止自动回滚"
                    )
                failed_dir = output_dir.parent / f".{output_dir.name}.failed-{transaction_id}"
                os.replace(output_dir, failed_dir)
                try:
                    if backup_dir is not None and backup_dir.exists():
                        os.replace(backup_dir, output_dir)
                    elif removed_empty_dir:
                        output_dir.mkdir(exist_ok=False)
                finally:
                    shutil.rmtree(failed_dir, ignore_errors=True)
            elif backup_dir is not None and backup_dir.exists() and not output_dir.exists():
                os.replace(backup_dir, output_dir)
            elif removed_empty_dir and not output_dir.exists():
                output_dir.mkdir(exist_ok=False)
            raise
        finally:
            if stage_dir.exists():
                shutil.rmtree(stage_dir, ignore_errors=True)


def final_delivery_names(episode_count: int = 1) -> tuple[str, ...]:
    """单集为三个标准文件；系列为每集三个带文件名集号前缀的独立文件。"""
    if episode_count < 1:
        raise ValueError("集数必须大于0")
    if episode_count == 1:
        return FINAL_DELIVERY_NAMES
    return tuple(
        f"第{episode:02d}集-{name}"
        for episode in range(1, episode_count + 1)
        for name in FINAL_DELIVERY_NAMES
    )


def validate_final_delivery_dir(delivery_dir: Path, episode_count: int = 1) -> Path:
    """确认最终交付目录恰好包含每集三个文件，且文案没有集数分隔行。"""
    resolved = validate_output_dir(delivery_dir)
    if not resolved.is_dir():
        raise FileNotFoundError(f"最终交付目录不存在：{resolved}")
    entries = list(resolved.iterdir())
    actual_files = {path.name for path in entries if path.is_file()}
    unexpected_dirs = [path.name for path in entries if path.is_dir()]
    expected = set(final_delivery_names(episode_count))
    if actual_files != expected or unexpected_dirs:
        missing = sorted(expected - actual_files)
        extra = sorted(actual_files - expected)
        raise ValueError(
            f"最终交付目录不符合每集三文件白名单：缺少={missing}，多出={extra}，目录={unexpected_dirs}"
        )
    for path in entries:
        if path.suffix.lower() == ".txt":
            text = path.read_text(encoding="utf-8-sig")
            assert_no_mojibake(text, str(path))
            lines = text.splitlines()
            if any(EPISODE_HEADER_RE.fullmatch(line) for line in lines):
                raise ValueError(f"音色克隆文案包含集数分隔行，正文不干净：{path}")
            if path.name.endswith("02-智能文稿匹配文案.txt"):
                if any(not line or line.strip() != line for line in lines):
                    raise ValueError(f"智能文稿匹配文案包含空行或行首行尾空白：{path}")
                over_limit = [
                    (index, subtitle_character_count(line), line)
                    for index, line in enumerate(lines, 1)
                    if subtitle_character_count(line) > LIMIT
                ]
                if over_limit:
                    raise ValueError(
                        f"智能文稿匹配文案存在超过{LIMIT}个中文字符或数字的行：{over_limit}"
                    )
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="UTF-8或GB18030编码的TXT或Markdown原文")
    parser.add_argument("--work-dir", "--output-dir", dest="work_dir", type=Path, required=True, help="内部工作目录，不得用作最终交付目录")
    parser.add_argument("--pronunciation-review", "--pronunciation-map", dest="pronunciation_review", type=Path, help="UTF-8 JSON结构化读音审查表，仅应用于音色克隆文案")
    parser.add_argument("--protected-terms", type=Path, help="UTF-8 JSON不可拆词组数组")
    parser.add_argument("--smart-transcript-lines", type=Path, required=True, help="UTF-8或GB18030纯文本语义切分稿，一行一条；必须逐字还原原文")
    parser.add_argument("--chars-per-second", type=float, default=4.0, help="最低旁白时长计算使用的每秒字数，默认4.0")
    parser.add_argument("--force", action="store_true", help="仅在用户明确授权后覆盖同名输出；覆盖前自动备份")
    args = parser.parse_args()
    pronunciation_review = None
    if args.pronunciation_review:
        pronunciation_review = json.loads(read_text_detect_encoding(args.pronunciation_review))
        if not isinstance(pronunciation_review, (dict, list)):
            raise ValueError("读音审查表必须是JSON对象或数组")
    protected_terms = None
    if args.protected_terms:
        protected_terms = json.loads(read_text_detect_encoding(args.protected_terms))
        if not isinstance(protected_terms, list) or not all(isinstance(term, str) for term in protected_terms):
            raise ValueError("不可拆词组必须是JSON字符串数组")
    smart_transcript_lines = None
    if args.smart_transcript_lines:
        smart_transcript_lines = read_text_detect_encoding(args.smart_transcript_lines).splitlines()
    data = process(
        read_text_detect_encoding(args.input),
        pronunciation_review,
        protected_terms,
        args.chars_per_second,
        smart_transcript_lines,
    )
    outputs = build_outputs(data)
    backup_dir = write_outputs_safely(
        args.work_dir,
        outputs,
        force=args.force,
    )
    print(f"内部文件生成完成：{validate_output_dir(args.work_dir)}")
    if backup_dir is not None:
        print(f"原文件已备份到：{backup_dir}")


if __name__ == "__main__":
    main()
