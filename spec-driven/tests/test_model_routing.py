"""Regression tests for deterministic model routing (contract + router script).

capability_tier and reasoning_level are two independent axes — resolved through separate
tables from the same declared inputs (task_category, declared_risk) — so tests check each
axis's resolution and escalation behavior separately, not as one combined value.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = SKILL_DIR.parent
CONTRACT_PATH = SKILL_DIR / "contracts" / "spec-family.yaml"
ROUTER_SCRIPT = SKILL_DIR / "scripts" / "model-router.py"
ROUTING_DOC = SKILL_DIR / "references" / "model-routing.md"

SPEC = importlib.util.spec_from_file_location("model_router", ROUTER_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
model_router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model_router)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROUTER_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class ContractRoutingFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_declares_capability_tiers_reasoning_levels_and_task_categories(self) -> None:
        self.assertIn("capability_tiers", self.contract)
        self.assertIn("reasoning_levels", self.contract)
        self.assertIn("task_categories", self.contract)
        self.assertIn("model_routing", self.contract)
        self.assertIn("reasoning_routing", self.contract)
        for tier in ("economical", "balanced", "frontier"):
            self.assertIn(tier, self.contract["capability_tiers"])
        for level in ("low", "medium", "high", "extra_high"):
            self.assertIn(level, self.contract["reasoning_levels"])
        for category in ("quick_lookup", "code_analysis", "heavy_reasoning", "review"):
            entry = self.contract["task_categories"][category]
            self.assertIn("default_tier", entry)
            self.assertIn("default_reasoning", entry)

    def test_model_routing_defaults_cover_every_tier(self) -> None:
        defaults = self.contract["model_routing"]["defaults"]
        for tier in ("economical", "balanced", "frontier"):
            self.assertIn(tier, defaults)
            self.assertTrue(defaults[tier])

    def test_override_policy_documents_precedence_and_no_downgrade(self) -> None:
        policy_text = " ".join(self.contract["model_routing"]["override_policy"]).casefold()
        self.assertIn("precedence", policy_text)
        self.assertIn("never silently downgrade", policy_text)
        self.assertIn("heavy_reasoning tasks never resolve below the balanced tier", policy_text)

    def test_reasoning_override_policy_documents_no_downgrade(self) -> None:
        policy_text = " ".join(self.contract["reasoning_routing"]["override_policy"]).casefold()
        self.assertIn("precedence", policy_text)
        self.assertIn("only ever raises reasoning level, never lowers it", policy_text)
        self.assertIn("heavy_reasoning tasks never resolve below high reasoning", policy_text)


class RouterResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = model_router.load_contract(CONTRACT_PATH)

    def test_default_resolution_per_category(self) -> None:
        expected = {
            "quick_lookup": ("economical", "claude-haiku-4-5-20251001", "low"),
            "code_analysis": ("balanced", "claude-sonnet-5", "medium"),
            "heavy_reasoning": ("frontier", "claude-opus-5", "high"),
            "review": ("balanced", "claude-sonnet-5", "medium"),
        }
        for category, (tier, model, reasoning) in expected.items():
            with self.subTest(category=category):
                result = model_router.resolve(self.contract, category)
                self.assertEqual(result["capability_tier"], tier)
                self.assertEqual(result["resolved_model"], model)
                self.assertEqual(result["reasoning_level"], reasoning)
                self.assertFalse(result["substitution"])

    def test_risk_escalation_raises_tier_never_lowers(self) -> None:
        result = model_router.resolve(self.contract, "review", declared_risk="high")
        self.assertEqual(result["capability_tier"], "frontier")
        result_elevated = model_router.resolve(self.contract, "quick_lookup", declared_risk="elevated")
        self.assertEqual(result_elevated["capability_tier"], "balanced")
        # Already at the top tier: escalation is a no-op, not an error.
        result_top = model_router.resolve(self.contract, "heavy_reasoning", declared_risk="high")
        self.assertEqual(result_top["capability_tier"], "frontier")

    def test_risk_escalation_raises_reasoning_independently_of_tier(self) -> None:
        result = model_router.resolve(self.contract, "quick_lookup", declared_risk="elevated")
        # Tier escalates economical->balanced; reasoning escalates low->medium — same input,
        # two independent tables, not one combined jump.
        self.assertEqual(result["capability_tier"], "balanced")
        self.assertEqual(result["reasoning_level"], "medium")
        result_top = model_router.resolve(self.contract, "heavy_reasoning", declared_risk="high")
        self.assertEqual(result_top["reasoning_level"], "extra_high")

    def test_reasoning_and_tier_can_diverge_via_independent_overrides(self) -> None:
        """The whole point of two axes: override one without touching the other."""
        result = model_router.resolve(
            self.contract, "code_analysis", override="economical", reasoning_override="extra_high"
        )
        self.assertEqual(result["capability_tier"], "economical")
        self.assertEqual(result["reasoning_level"], "extra_high")

    def test_explicit_model_override_wins_over_category_default(self) -> None:
        result = model_router.resolve(self.contract, "quick_lookup", override="claude-opus-5")
        self.assertEqual(result["resolved_model"], "claude-opus-5")
        self.assertIn("requested_override", result["reason"])

    def test_explicit_tier_override_applies(self) -> None:
        result = model_router.resolve(self.contract, "quick_lookup", override="frontier")
        self.assertEqual(result["capability_tier"], "frontier")
        self.assertEqual(result["resolved_model"], "claude-opus-5")

    def test_explicit_reasoning_override_applies_and_is_recorded(self) -> None:
        result = model_router.resolve(self.contract, "quick_lookup", reasoning_override="high")
        self.assertEqual(result["reasoning_level"], "high")
        self.assertIn("requested_reasoning_override", result["reasoning_reason"])

    def test_heavy_reasoning_never_resolves_below_balanced_even_with_economical_override(self) -> None:
        result = model_router.resolve(self.contract, "heavy_reasoning", override="economical")
        self.assertEqual(result["capability_tier"], "balanced")
        self.assertNotEqual(
            result["resolved_model"], self.contract["model_routing"]["defaults"]["economical"]
        )

    def test_heavy_reasoning_never_resolves_below_high_reasoning_even_with_low_override(self) -> None:
        result = model_router.resolve(self.contract, "heavy_reasoning", reasoning_override="low")
        self.assertEqual(result["reasoning_level"], "high")

    def test_unknown_reasoning_override_raises(self) -> None:
        with self.assertRaises(ValueError):
            model_router.resolve(self.contract, "quick_lookup", reasoning_override="ultra")

    def test_unavailable_default_escalates_and_records_substitution(self) -> None:
        result = model_router.resolve(
            self.contract,
            "quick_lookup",
            available_models={"economical": None},
        )
        self.assertEqual(result["capability_tier"], "balanced")
        self.assertTrue(result["substitution"])
        self.assertIn("substitution", result["reason"])

    def test_unknown_task_category_raises(self) -> None:
        with self.assertRaises(ValueError):
            model_router.resolve(self.contract, "not_a_real_category")

    def test_unknown_declared_risk_raises(self) -> None:
        with self.assertRaises(ValueError):
            model_router.resolve(self.contract, "quick_lookup", declared_risk="extreme")


class RouterCliTests(unittest.TestCase):
    def test_json_output_is_parseable_and_complete(self) -> None:
        proc = run_cli("--category", "code_analysis")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        for field in (
            "task_category", "declared_risk", "capability_tier",
            "resolved_model", "substitution", "reasoning_level", "reason", "reasoning_reason",
        ):
            self.assertIn(field, payload)

    def test_text_output_is_one_line_and_names_reasoning(self) -> None:
        proc = run_cli("--category", "review", "--risk", "high", "--format", "text")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
        self.assertIn("reasoning:", proc.stdout)

    def test_reasoning_override_flag_applies(self) -> None:
        proc = run_cli("--category", "quick_lookup", "--reasoning-override", "extra_high")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["reasoning_level"], "extra_high")

    def test_invalid_category_exits_nonzero_with_json_error(self) -> None:
        proc = run_cli("--category", "nonsense")
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stderr)
        self.assertIn("error", payload)


class DocumentationMachineReadabilityTests(unittest.TestCase):
    """Docs must stay structured/parseable and reference the contract, not hard-coded models."""

    def test_model_routing_doc_has_stable_headings(self) -> None:
        text = ROUTING_DOC.read_text(encoding="utf-8")
        for heading in (
            "# Model routing policy",
            "## Fields (stable, machine-parseable)",
            "## Task category → default tier and reasoning level",
            "## Capability tier → safe default model",
            "## Reasoning level",
            "## Selection order (deterministic)",
            "## Using the router",
        ):
            self.assertIn(heading, text)

    def test_model_routing_doc_names_current_models(self) -> None:
        text = ROUTING_DOC.read_text(encoding="utf-8")
        self.assertIn("claude-haiku-4-5-20251001", text)
        self.assertIn("claude-sonnet-5", text)
        self.assertIn("claude-opus-5", text)

    def test_model_routing_doc_documents_cross_vendor_tier_mapping(self) -> None:
        text = ROUTING_DOC.read_text(encoding="utf-8")
        for name in ("Sol", "Terra", "Luna", "Opus", "Sonnet", "Haiku", "Gemini Pro", "Flash"):
            self.assertIn(name, text)

    def test_model_routing_doc_tables_are_parseable_markdown(self) -> None:
        text = ROUTING_DOC.read_text(encoding="utf-8")
        table_rows = re.findall(r"^\|.+\|$", text, flags=re.MULTILINE)
        self.assertGreaterEqual(len(table_rows), 10)

    def test_phase_skills_reference_the_router_not_a_hard_coded_model(self) -> None:
        spec_execute = (SKILLS_ROOT / "spec-execute" / "SKILL.md").read_text(encoding="utf-8")
        spec_audit = (SKILLS_ROOT / "spec-audit" / "SKILL.md").read_text(encoding="utf-8")
        for text in (spec_execute, spec_audit):
            self.assertIn("model-routing.md", text)


if __name__ == "__main__":
    unittest.main()
