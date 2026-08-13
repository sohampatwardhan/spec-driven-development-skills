"""Regression tests for check-skill-sync.py's local/remote comparison logic.

Covers the bidirectional-drift bug class this script exists to catch: version skew
between an installed skill copy and its GitHub mirror can go either direction (local
behind a pushed improvement, or local ahead with an unpushed fix), and both must be
reported distinctly rather than one masking the other.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "check-skill-sync.py"

SPEC = importlib.util.spec_from_file_location("check_skill_sync", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
check_skill_sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_skill_sync)


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class CompareDirTests(unittest.TestCase):
    def test_identical_trees_report_no_drift(self) -> None:
        with TemporaryDirectory() as local, TemporaryDirectory() as remote:
            _write(Path(local), "scripts/a.py", "same\n")
            _write(Path(remote), "scripts/a.py", "same\n")
            result = check_skill_sync.compare_dir(Path(local), Path(remote))
            self.assertEqual(result, {"missing_locally": [], "local_only": [], "differing": []})

    def test_file_only_on_remote_is_missing_locally(self) -> None:
        with TemporaryDirectory() as local, TemporaryDirectory() as remote:
            _write(Path(remote), "scripts/new_feature.py", "content\n")
            result = check_skill_sync.compare_dir(Path(local), Path(remote))
            self.assertEqual(result["missing_locally"], ["scripts/new_feature.py"])
            self.assertEqual(result["local_only"], [])
            self.assertEqual(result["differing"], [])

    def test_file_only_on_local_is_local_only_not_missing(self) -> None:
        """An unpushed local fix must not be misreported as something to pull."""
        with TemporaryDirectory() as local, TemporaryDirectory() as remote:
            _write(Path(local), "scripts/unpushed_fix.py", "content\n")
            result = check_skill_sync.compare_dir(Path(local), Path(remote))
            self.assertEqual(result["local_only"], ["scripts/unpushed_fix.py"])
            self.assertEqual(result["missing_locally"], [])
            self.assertEqual(result["differing"], [])

    def test_differing_content_is_flagged_regardless_of_direction(self) -> None:
        with TemporaryDirectory() as local, TemporaryDirectory() as remote:
            _write(Path(local), "scripts/a.py", "local version\n")
            _write(Path(remote), "scripts/a.py", "remote version\n")
            result = check_skill_sync.compare_dir(Path(local), Path(remote))
            self.assertEqual(result["differing"], ["scripts/a.py"])

    def test_cache_and_git_directories_are_ignored(self) -> None:
        with TemporaryDirectory() as local, TemporaryDirectory() as remote:
            _write(Path(local), "scripts/__pycache__/a.pyc", "junk\n")
            _write(Path(local), ".git/HEAD", "ref: refs/heads/main\n")
            _write(Path(remote), "scripts/a.py", "content\n")
            _write(Path(local), "scripts/a.py", "content\n")
            result = check_skill_sync.compare_dir(Path(local), Path(remote))
            self.assertEqual(result, {"missing_locally": [], "local_only": [], "differing": []})

    def test_missing_local_directory_reports_everything_as_missing(self) -> None:
        with TemporaryDirectory() as remote:
            _write(Path(remote), "scripts/a.py", "content\n")
            missing_local_dir = Path(remote) / "does-not-exist"
            result = check_skill_sync.compare_dir(missing_local_dir, Path(remote))
            self.assertEqual(result["missing_locally"], ["scripts/a.py"])


class SkillsRootTests(unittest.TestCase):
    def test_skills_root_is_two_levels_above_scripts_dir(self) -> None:
        # <skills-root>/spec-driven/scripts/check-skill-sync.py -> <skills-root>
        self.assertEqual(check_skill_sync.skills_root(), SKILL_DIR.parent)


if __name__ == "__main__":
    unittest.main()
