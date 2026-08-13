#!/usr/bin/env python3
"""Diff the installed spec-driven skill family against the latest GitHub main.

Skills in this family (`spec-*`, `dependency-security-audit`) are mirrored between
a local installation directory and https://github.com/sohampatwardhan/spec-driven-development-skills.
Drift can go either direction: local can lag a pushed improvement, or local can carry
a fix never pushed upstream. This script reports both, without assuming either side
is authoritative.

Usage: check-skill-sync.py [--repo OWNER/NAME] [--ref main] [--json]

Exit code 0 when everything matches; 1 when there is drift to reconcile; 2 on a
fetch error (network, missing git, unknown ref).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_REPO = "sohampatwardhan/spec-driven-development-skills"
IGNORE_PARTS = {".git", "__pycache__", ".pytest_cache"}
IGNORE_TOP_LEVEL = {".git", ".github", "docs", ".specs", "LICENSE", "README.md", "CHANGELOG.md"}


def skills_root() -> Path:
    """Directory containing all installed skills (parent of this skill's own folder).

    This script lives at ``<skills-root>/spec-driven/scripts/check-skill-sync.py`` —
    derive the root from that fixed position instead of a hard-coded home-directory
    path, since the installation root varies across hosting tools/environments.
    """
    return Path(__file__).resolve().parents[2]


def clone_latest(repo: str, ref: str, dest: Path) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, f"https://github.com/{repo}.git", str(dest)],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git clone failed")


def iter_files(root: Path) -> set[Path]:
    if not root.is_dir():
        return set()
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORE_PARTS for part in path.parts)
    }


def compare_dir(local_dir: Path, remote_dir: Path) -> dict[str, list[str]]:
    local_files = iter_files(local_dir)
    remote_files = iter_files(remote_dir)
    differing = sorted(
        str(rel)
        for rel in local_files & remote_files
        if (local_dir / rel).read_bytes() != (remote_dir / rel).read_bytes()
    )
    return {
        "missing_locally": sorted(str(p) for p in remote_files - local_files),
        "local_only": sorted(str(p) for p in local_files - remote_files),
        "differing": differing,
    }


def run(repo: str, ref: str) -> dict[str, dict[str, list[str]]]:
    root = skills_root()
    with tempfile.TemporaryDirectory() as tmp:
        remote_root = Path(tmp) / "repo"
        clone_latest(repo, ref, remote_root)
        shared_dirs = sorted(
            p.name
            for p in remote_root.iterdir()
            if p.is_dir() and p.name not in IGNORE_TOP_LEVEL
        )
        report: dict[str, dict[str, list[str]]] = {}
        for name in shared_dirs:
            result = compare_dir(root / name, remote_root / name)
            if any(result.values()):
                report[name] = result
        return report


def print_report(report: dict[str, dict[str, list[str]]], repo: str, ref: str) -> None:
    if not report:
        print(f"CURRENT: all shared spec-driven-family skills match {repo}@{ref}.")
        return
    for name, result in report.items():
        print(f"=== {name} ===")
        if result["missing_locally"]:
            print("  behind remote (pull these):")
            for f in result["missing_locally"]:
                print(f"    + {f}")
        if result["local_only"]:
            print("  ahead of remote (push, or ignore if scratch/cache):")
            for f in result["local_only"]:
                print(f"    - {f}")
        if result["differing"]:
            print("  content differs (diff and reconcile):")
            for f in result["differing"]:
                print(f"    ~ {f}")
    print(
        "\nDRIFT DETECTED — reconcile before relying on these skills for "
        "nontrivial work (see spec-driven/SKILL.md 'Staying current')."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name of the mirror repo")
    parser.add_argument("--ref", default="main", help="branch or tag to compare against")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        report = run(args.repo, args.ref)
    except RuntimeError as exc:
        print(f"ERROR: could not fetch {args.repo}@{args.ref}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"repo": args.repo, "ref": args.ref, "drift": report}, indent=2))
    else:
        print_report(report, args.repo, args.ref)

    return 1 if report else 0


if __name__ == "__main__":
    raise SystemExit(main())
