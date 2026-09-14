#!/usr/bin/env python3
"""Validate the public skill collection without requiring Codex internals."""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
SENSITIVE_PATTERNS = {
    "personal Windows profile path": re.compile(r"C:\\Users\\[^\\\s]+", re.IGNORECASE),
    "GitHub token": re.compile(r"(?:gho_|github_pat_)[A-Za-z0-9_]+"),
    "mainland China mobile number": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
}
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".svg", ".txt", ".gitignore"}


@dataclass
class Result:
    checks: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def frontmatter_value(frontmatter: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", frontmatter, re.MULTILINE)
    return unquote(match.group(1)) if match else None


def quoted_yaml_value(text: str, key: str) -> str | None:
    match = re.search(rf"^\s{{2}}{re.escape(key)}:\s*\"([^\"]*)\"\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def validate_skill(skill_dir: Path, result: Result) -> None:
    relative = skill_dir.relative_to(REPO_ROOT)
    skill_md = skill_dir / "SKILL.md"
    metadata = skill_dir / "agents" / "openai.yaml"

    result.check(skill_md.is_file(), f"{relative}: missing SKILL.md")
    result.check(metadata.is_file(), f"{relative}: missing agents/openai.yaml")
    if not skill_md.is_file() or not metadata.is_file():
        return

    text = skill_md.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    result.check(match is not None, f"{relative}: invalid YAML frontmatter")
    if match is None:
        return

    frontmatter = match.group("body")
    name = frontmatter_value(frontmatter, "name")
    description = frontmatter_value(frontmatter, "description")
    result.check(name == skill_dir.name, f"{relative}: name must match folder ({name!r})")
    result.check(bool(name and NAME_RE.fullmatch(name)), f"{relative}: invalid skill name")
    result.check(bool(description and 20 <= len(description) <= 600), f"{relative}: description is missing or poorly scoped")
    result.check("# " in text[match.end():], f"{relative}: missing Markdown title")

    metadata_text = metadata.read_text(encoding="utf-8")
    display_name = quoted_yaml_value(metadata_text, "display_name")
    short_description = quoted_yaml_value(metadata_text, "short_description")
    default_prompt = quoted_yaml_value(metadata_text, "default_prompt")
    result.check(bool(display_name), f"{relative}: missing quoted display_name")
    result.check(
        bool(short_description and 25 <= len(short_description) <= 64),
        f"{relative}: short_description must contain 25-64 characters",
    )
    result.check(
        bool(default_prompt and f"${name}" in default_prompt),
        f"{relative}: default_prompt must explicitly mention ${name}",
    )

    for link in re.findall(r"\((?P<path>(?:references|scripts|assets)/[^)#]+)", text):
        result.check((skill_dir / link).is_file(), f"{relative}: broken resource link {link}")


def validate_repository() -> Result:
    result = Result()
    result.check(SKILLS_ROOT.is_dir(), "missing .agents/skills")
    skill_dirs = sorted(path for path in SKILLS_ROOT.iterdir() if path.is_dir())
    result.check(bool(skill_dirs), "no skills found")

    for skill_dir in skill_dirs:
        validate_skill(skill_dir, result)

    for path in REPO_ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_dir():
            result.check(path.name != "__pycache__", f"cache directory committed: {path}")
            continue
        result.check(path.suffix != ".pyc", f"bytecode committed: {path}")

        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError) as exc:
                result.errors.append(f"{path.relative_to(REPO_ROOT)}: Python parse failed: {exc}")
            result.check(True, f"parsed {path}")

        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                result.errors.append(f"{path.relative_to(REPO_ROOT)}: JSON parse failed: {exc}")
            result.check(True, f"parsed {path}")

        if path.suffix.lower() in TEXT_SUFFIXES or path.name == ".gitignore":
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                result.errors.append(f"{path.relative_to(REPO_ROOT)}: not UTF-8: {exc}")
                continue
            for label, pattern in SENSITIVE_PATTERNS.items():
                result.check(
                    pattern.search(content) is None,
                    f"{path.relative_to(REPO_ROOT)}: detected {label}",
                )

    return result


def main() -> int:
    result = validate_repository()
    skill_count = sum(1 for path in SKILLS_ROOT.iterdir() if path.is_dir()) if SKILLS_ROOT.is_dir() else 0
    if result.errors:
        print(f"FAIL: {len(result.errors)} error(s) across {result.checks} checks")
        for error in result.errors:
            print(f"- {error}")
        return 1
    print(f"PASS: {skill_count} skills, {result.checks} repository checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
