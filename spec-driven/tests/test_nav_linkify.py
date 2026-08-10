"""Regression tests for spec-nav.py's sibling-reference linkifier.

Covers the exact bug an end-to-end dry run caught: a forward reference to a not-yet-existing
artifact (e.g. an approval-gate callout naming "before work begins on `03_design.md`") is valid
inline code when written, but becomes an unlinked-reference error the moment that file exists.
Also covers the regression this fix initially introduced: `_linkify_text` must never destroy a
fenced code block's content while linkifying the surrounding prose.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "spec-nav.py"

SPEC = importlib.util.spec_from_file_location("spec_nav", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
spec_nav = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spec_nav)


class LinkifyTextTests(unittest.TestCase):
    def test_forward_reference_to_existing_sibling_is_linkified(self) -> None:
        text = "> Approval gate: approve before work begins on `03_design.md`.\n"
        result = spec_nav._linkify_text(text, ["03_design.md"])
        self.assertEqual(
            "> Approval gate: approve before work begins on [03_design.md](03_design.md).\n",
            result,
        )

    def test_already_linked_reference_is_left_alone(self) -> None:
        text = "See [Design](03_design.md) or [`03_design.md`](03_design.md) directly.\n"
        result = spec_nav._linkify_text(text, ["03_design.md"])
        self.assertEqual(text, result)

    def test_fenced_code_block_content_is_preserved_byte_for_byte(self) -> None:
        """The regression this fix itself introduced: `re.split` on a pattern that captures
        only the fence delimiter discards everything matched-but-uncaptured — the entire
        fenced block's content — which silently destroyed real Mermaid diagrams mid-dry-run."""
        text = (
            "Prose mentioning `03_design.md`.\n\n"
            "```mermaid\n"
            "flowchart TD\n"
            "  a@{ shape: rect, label: \"uses 03_design.md literally\" }\n"
            "```\n\n"
            "More prose mentioning `03_design.md` again.\n"
        )
        result = spec_nav._linkify_text(text, ["03_design.md"])
        self.assertIn(
            "```mermaid\nflowchart TD\n"
            "  a@{ shape: rect, label: \"uses 03_design.md literally\" }\n```",
            result,
        )
        self.assertEqual(2, result.count("[03_design.md](03_design.md)"))

    def test_multiple_fenced_blocks_all_survive(self) -> None:
        text = "```\nblock one `03_design.md`\n```\ntext `03_design.md`\n```\nblock two\n```\n"
        result = spec_nav._linkify_text(text, ["03_design.md"])
        self.assertIn("```\nblock one `03_design.md`\n```", result)
        self.assertIn("```\nblock two\n```", result)
        self.assertIn("[03_design.md](03_design.md)", result)

    def test_no_sibling_names_is_a_no_op(self) -> None:
        text = "```\nsome code\n```\nprose `unrelated.md`\n"
        self.assertEqual(text, spec_nav._linkify_text(text, []))


class LinkifySiblingReferencesIntegrationTests(unittest.TestCase):
    def test_write_linkifies_across_real_files_without_touching_fenced_diagrams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            spec_dir.mkdir(parents=True)
            (spec_dir / "01_discovery.md").write_text(
                "# Discovery\n\n"
                "```mermaid\nmindmap\n  ((root))\n    child\n```\n\n"
                "Approved; see `02_requirements.md` next.\n",
                encoding="utf-8",
            )
            (spec_dir / "02_requirements.md").write_text("# Requirements\n\ncontent\n", encoding="utf-8")

            spec_nav.update_navigation(spec_dir)
            updated = spec_nav.linkify_sibling_references(spec_dir)

            self.assertIn("01_discovery.md", updated)
            discovery_text = (spec_dir / "01_discovery.md").read_text(encoding="utf-8")
            self.assertIn("```mermaid\nmindmap\n  ((root))\n    child\n```", discovery_text)
            self.assertIn("[02_requirements.md](02_requirements.md)", discovery_text)


if __name__ == "__main__":
    unittest.main()
