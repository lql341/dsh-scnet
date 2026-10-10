#!/usr/bin/env python3
"""Render the current release block in English and Chinese READMEs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$")
LEGACY_RELEASE_HEADING_RE = re.compile(
    r"^## (?:"
    r"What's new in [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?"
    r"|[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?: highlights| 更新)?"
    r")\s*$"
)
MANAGED_BLOCK_RE = re.compile(
    r"\n?<!-- scnet-release:start -->\n.*?"
    r"<!-- scnet-release:end -->\n?",
    re.DOTALL,
)


def _read_nonempty(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"{path} must not be empty")
    return text


def _remove_legacy_release_lists(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    index = 0

    while index < len(lines):
        if not LEGACY_RELEASE_HEADING_RE.fullmatch(lines[index]):
            output.append(lines[index])
            index += 1
            continue

        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1

        saw_bullet = False
        while index < len(lines):
            line = lines[index]
            if line.startswith("- "):
                saw_bullet = True
                index += 1
                continue
            if saw_bullet and (line.startswith("  ") or not line.strip()):
                index += 1
                continue
            break

        while output and not output[-1].strip():
            output.pop()
        output.append("")

    return "\n".join(output).rstrip() + "\n"


def _render_readme(
    path: Path,
    *,
    version: str,
    highlights: str,
    language: str,
) -> str:
    text = path.read_text(encoding="utf-8")
    text = MANAGED_BLOCK_RE.sub("\n", text)
    text = _remove_legacy_release_lists(text)

    if language == "en":
        marker_re = re.compile(r"(?m)^Current release:\s*\*\*[^*]+\*\*$")
        marker = f"Current release: **{version}**"
        heading = f"## {version} highlights"
    else:
        marker_re = re.compile(r"(?m)^当前版本：\s*\*\*[^*]+\*\*$")
        marker = f"当前版本：**{version}**"
        heading = f"## {version} 更新"

    text, count = marker_re.subn(marker, text)
    if count != 1:
        raise ValueError(f"expected one release marker in {path}, found {count}")

    lines = text.splitlines()
    marker_index = lines.index(marker)
    insert_at = marker_index + 1

    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1
    if insert_at < len(lines) and lines[insert_at].startswith("```"):
        insert_at += 1
        while insert_at < len(lines) and not lines[insert_at].startswith("```"):
            insert_at += 1
        if insert_at >= len(lines):
            raise ValueError(f"unterminated code fence after release marker in {path}")
        insert_at += 1
    while insert_at < len(lines) and not lines[insert_at].strip():
        insert_at += 1

    block = [
        "",
        "<!-- scnet-release:start -->",
        heading,
        "",
        *highlights.splitlines(),
        "<!-- scnet-release:end -->",
        "",
    ]
    lines[insert_at:insert_at] = block

    rendered = "\n".join(lines).rstrip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", rendered)


def _top_changelog_version(path: Path) -> str:
    match = re.search(
        r"(?m)^## ([0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)"
        r"(?:\s+-\s+\d{4}-\d{2}-\d{2})?\s*$",
        path.read_text(encoding="utf-8"),
    )
    if not match:
        raise ValueError(f"no release heading found in {path}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-file", type=Path, default=Path("VERSION"))
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument(
        "--highlights-en", type=Path, default=Path("RELEASE_HIGHLIGHTS.md")
    )
    parser.add_argument(
        "--highlights-cn", type=Path, default=Path("RELEASE_HIGHLIGHTS_CN.md")
    )
    parser.add_argument("--readme-en", type=Path, default=Path("README.md"))
    parser.add_argument("--readme-cn", type=Path, default=Path("README_CN.md"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        version = _read_nonempty(args.version_file)
        if not SEMVER_RE.fullmatch(version):
            raise ValueError(f"invalid SemVer in {args.version_file}: {version}")
        changelog_version = _top_changelog_version(args.changelog)
        if changelog_version != version:
            raise ValueError(
                f"{args.changelog} starts at {changelog_version}, expected {version}"
            )

        rendered = {
            args.readme_en: _render_readme(
                args.readme_en,
                version=version,
                highlights=_read_nonempty(args.highlights_en),
                language="en",
            ),
            args.readme_cn: _render_readme(
                args.readme_cn,
                version=version,
                highlights=_read_nonempty(args.highlights_cn),
                language="cn",
            ),
        }
    except (OSError, ValueError) as exc:
        print(f"release docs error: {exc}", file=sys.stderr)
        return 1

    stale = [path for path, content in rendered.items() if path.read_text() != content]
    if args.check:
        if stale:
            print(
                "release docs are stale: " + ", ".join(str(path) for path in stale),
                file=sys.stderr,
            )
            return 1
        return 0

    for path, content in rendered.items():
        path.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
