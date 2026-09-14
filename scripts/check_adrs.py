#!/usr/bin/env python3
"""Validate the repository's numbered ADRs without third-party dependencies."""

import argparse
from datetime import date
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


SECTIONS = ("Status", "Context", "Decision", "Consequences")
FILENAME = re.compile(r"^(\d{4,})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
STATUSES = {"Proposed", "Accepted", "Rejected", "Deprecated", "Superseded"}
PLACEHOLDERS = (
    "PENDIENTE:",
    "The issue motivating this decision",
    "The change that we're proposing",
    "What becomes easier or more difficult",
)


def validate(adr_dir: Path) -> tuple[int, list[str]]:
    errors = []
    records = []
    numbers = set()
    for path in sorted(adr_dir.glob("*.md")):
        # Existing handout templates and the usage guide are not decisions.
        if path.name == "README.md" or path.name.startswith("ADR-TEMPLATE"):
            continue
        match = FILENAME.fullmatch(path.name)
        if not match or int(match[1]) < 1:
            errors.append(f"{path.name}: expected NNNN-title-in-kebab-case.md")
            continue
        records.append(path)
        number = int(match[1])
        if number in numbers:
            errors.append(f"{path.name}: duplicate ADR number {number}")
        numbers.add(number)
        text = path.read_text(encoding="utf-8")
        title = re.match(r"# (\d+)\. (\S[^\n]*)\n", text)
        if not title or int(title[1]) != number:
            errors.append(f"{path.name}: title number must match filename")
        dates = re.findall(r"^Date: (.+)$", text, re.MULTILINE)
        try:
            if len(dates) != 1 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dates[0]):
                raise ValueError
            date.fromisoformat(dates[0])
        except ValueError:
            errors.append(f"{path.name}: expected one valid Date: YYYY-MM-DD")

        headings = list(re.finditer(r"^## (.+)$", text, re.MULTILINE))
        contents = {}
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            name = heading[1]
            if name in contents:
                errors.append(f"{path.name}: duplicate section {name}")
            contents[name] = text[heading.end():end].strip()
        for section in SECTIONS:
            if not contents.get(section):
                errors.append(f"{path.name}: missing or empty section {section}")
        status = contents.get("Status", "").splitlines()
        # adr new -s uses the upstream spelling 'Superceded by'.
        if status and status[0] not in STATUSES and not re.match(
            r"^(?:Superseded|Superceded) by \[.+\]\(.+\)$", status[0]
        ):
            errors.append(f"{path.name}: unsupported status {status[0]!r}")
        if any(placeholder in text for placeholder in PLACEHOLDERS):
            errors.append(f"{path.name}: unfinished template text")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if not parsed.scheme and parsed.path and not (path.parent / unquote(parsed.path)).exists():
                errors.append(f"{path.name}: broken local link {target}")
    if not records:
        errors.append(f"{adr_dir}: no numbered ADRs found")
    return len(records), errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("docs/adr"))
    args = parser.parse_args()
    count, errors = validate(args.directory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {count} ADRs; numbering, dates, sections, status and local links valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
