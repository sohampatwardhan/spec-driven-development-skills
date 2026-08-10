#!/usr/bin/env python3
"""Generate and validate navigation for numbered spec artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


ARTIFACTS = (
    ("State", "00_state.md"),
    ("Discovery", "01_discovery.md"),
    ("Requirements", "02_requirements.md"),
    ("Design", "03_design.md"),
    ("Tasks", "04_tasks.md"),
    ("Execution", "05_execution.md"),
)
NAV_START = "<!-- spec-nav:start -->"
NAV_END = "<!-- spec-nav:end -->"
NAV_PATTERN = re.compile(
    rf"(?ms)^[ \t]*{re.escape(NAV_START)}.*?^[ \t]*{re.escape(NAV_END)}[ \t]*\n?"
)
H1_PATTERN = re.compile(r"(?m)^#\s+.+$")


def existing_artifacts(spec_dir: Path) -> list[tuple[str, str]]:
    """Return canonical artifact labels and names for files that exist."""
    return [(label, name) for label, name in ARTIFACTS if (spec_dir / name).is_file()]


def navigation_block(spec_dir: Path) -> str:
    """Render the canonical navigation block for the current artifact set."""
    links = " · ".join(f"[{label}]({name})" for label, name in existing_artifacts(spec_dir))
    return f"{NAV_START}\n**Spec navigation:** {links}\n{NAV_END}"


def with_navigation(text: str, block: str, artifact_name: str) -> str:
    """Insert or replace a navigation block immediately after the document H1."""
    without_existing = NAV_PATTERN.sub("", text)
    heading = H1_PATTERN.search(without_existing)
    if heading is None:
        raise ValueError(f"{artifact_name} must contain an H1 heading")
    before = without_existing[: heading.end()].rstrip()
    after = without_existing[heading.end() :].lstrip("\n")
    return f"{before}\n\n{block}\n\n{after}".rstrip() + "\n"


def update_navigation(spec_dir: Path) -> list[str]:
    """Write canonical navigation into every existing numbered artifact."""
    root = spec_dir.resolve()
    block = navigation_block(root)
    updated: list[str] = []
    for _label, name in existing_artifacts(root):
        path = root / name
        current = path.read_text(encoding="utf-8")
        rendered = with_navigation(current, block, name)
        if rendered != current:
            path.write_text(rendered, encoding="utf-8")
            updated.append(name)
    return updated


FENCED_CODE = re.compile(r"(?ms)^(```|~~~).*?^\1[ \t]*$")


def _linkify_segment(segment: str, sibling_names: list[str]) -> str:
    for other in sibling_names:
        pattern = re.compile(r"(?<!\[)`" + re.escape(other) + r"`(?!\])")
        segment = pattern.sub(f"[{other}]({other})", segment)
    return segment


def _linkify_text(text: str, sibling_names: list[str]) -> str:
    """Convert a bare inline-code mention of an existing sibling artifact into a real link.

    Fenced code blocks are preserved byte-for-byte via `match.group(0)` (the full match) — never
    reconstructed from `re.split`, which keeps only capture groups and silently discards any
    matched-but-uncaptured text, i.e. the entire fenced content, if the pattern captures only its
    delimiter.
    """
    pieces: list[str] = []
    cursor = 0
    for fence in FENCED_CODE.finditer(text):
        pieces.append(_linkify_segment(text[cursor:fence.start()], sibling_names))
        pieces.append(fence.group(0))
        cursor = fence.end()
    pieces.append(_linkify_segment(text[cursor:], sibling_names))
    return "".join(pieces)


def linkify_sibling_references(spec_dir: Path) -> list[str]:
    """Linkify a bare inline-code reference to an existing sibling numbered artifact.

    Mirrors what spec-check.py's artifact_link_errors flags (an unlinked inline-code reference
    to an existing project path) for the one case this script can safely auto-fix: the six
    canonical numbered artifact filenames, always same-directory siblings once they exist. A
    forward reference written before its target existed — e.g. an approval-gate callout naming
    the next phase's file, correctly inline code at the time — becomes exactly this case the
    moment that file is created; nothing else ever revisits an already-approved earlier artifact
    to fix it, so this runs unconditionally alongside navigation on every `--write`.
    """
    root = spec_dir.resolve()
    names = [name for _, name in existing_artifacts(root)]
    updated: list[str] = []
    for name in names:
        path = root / name
        current = path.read_text(encoding="utf-8")
        rendered = _linkify_text(current, names)
        if rendered != current:
            path.write_text(rendered, encoding="utf-8")
            updated.append(name)
    return updated


def navigation_errors(spec_dir: Path) -> list[str]:
    """Report missing, stale, duplicated, or misplaced navigation blocks."""
    root = spec_dir.resolve()
    block = navigation_block(root)
    errors: list[str] = []
    for _label, name in existing_artifacts(root):
        path = root / name
        text = path.read_text(encoding="utf-8")
        matches = list(NAV_PATTERN.finditer(text))
        if not matches:
            errors.append(f"{name} is missing the canonical spec navigation block")
            continue
        if len(matches) > 1:
            errors.append(f"{name} contains more than one spec navigation block")
            continue
        try:
            expected = with_navigation(text, block, name)
        except ValueError as error:
            errors.append(str(error))
            continue
        if text != expected:
            errors.append(f"{name} has stale or misplaced spec navigation; run spec-nav.py --write")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec_dir", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Insert or refresh navigation blocks.")
    mode.add_argument("--check", action="store_true", help="Validate navigation blocks (default).")
    args = parser.parse_args()
    root = args.spec_dir.resolve()
    if not root.is_dir():
        print(f"spec directory does not exist: {root}", file=sys.stderr)
        return 2
    if args.write:
        updated = sorted(set(update_navigation(root)) | set(linkify_sibling_references(root)))
        if updated:
            print(f"Updated spec navigation: {', '.join(updated)}")
        else:
            print("Spec navigation already current")
        return 0
    errors = navigation_errors(root)
    if errors:
        print("SPEC NAVIGATION CHECK FAILED")
        print(*errors, sep="\n")
        return 1
    print("SPEC NAVIGATION CHECK PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
