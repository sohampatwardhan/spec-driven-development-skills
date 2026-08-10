"""Regression tests for deterministic subagent fan-out (contract + fanout script).

reviewer_tier and reviewer_reasoning are two independent axes, mirroring model_routing/
reasoning_routing — tests check each resolves and escalates on its own.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1]
CONTRACT_PATH = SKILL_DIR / "contracts" / "spec-family.yaml"
FANOUT_SCRIPT = SKILL_DIR / "scripts" / "fanout.py"

SPEC = importlib.util.spec_from_file_location("fanout", FANOUT_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
fanout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fanout)


def run_cli(*args: str) -> "subprocess.CompletedProcess":
    import subprocess
    return subprocess.run(
        [sys.executable, str(FANOUT_SCRIPT), *args], capture_output=True, text=True, check=False,
    )


class ContractFanoutFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_contract_declares_delegation_depth_and_fanout(self) -> None:
        self.assertIn("delegation_depth", self.contract)
        self.assertIn("fanout", self.contract)
        for depth in ("quick", "medium", "thorough"):
            self.assertIn(depth, self.contract["delegation_depth"])
            entry = self.contract["fanout"][depth]
            self.assertIn("reviewer_count", entry)
            self.assertIn("reviewer_tier", entry)
            self.assertIn("reviewer_reasoning", entry)
            self.assertIn("self_repair_rounds", entry)


class ResolveFanoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = fanout.load_contract()

    def test_quick_is_one_economical_low_reasoning_reviewer_one_repair_round(self) -> None:
        result = fanout.resolve(self.contract, "quick")
        self.assertEqual(result["reviewer_count"], 1)
        self.assertEqual(result["reviewer_tier"], "economical")
        self.assertEqual(result["reviewer_reasoning"], "low")
        self.assertEqual(result["self_repair_rounds"], 1)
        self.assertFalse(result["escalated"])

    def test_medium_is_one_balanced_medium_reasoning_reviewer_two_repair_rounds(self) -> None:
        result = fanout.resolve(self.contract, "medium")
        self.assertEqual(result["reviewer_count"], 1)
        self.assertEqual(result["reviewer_tier"], "balanced")
        self.assertEqual(result["reviewer_reasoning"], "medium")
        self.assertEqual(result["self_repair_rounds"], 2)

    def test_thorough_is_two_balanced_high_reasoning_reviewers_by_default(self) -> None:
        result = fanout.resolve(self.contract, "thorough")
        self.assertEqual(result["reviewer_count"], 2)
        self.assertEqual(result["reviewer_tier"], "balanced")
        self.assertEqual(result["reviewer_reasoning"], "high")
        self.assertFalse(result["frontier_lens"])

    def test_thorough_escalation_adds_third_frontier_extra_high_lens(self) -> None:
        result = fanout.resolve(self.contract, "thorough", escalate=True)
        self.assertEqual(result["reviewer_count"], 3)
        self.assertTrue(result["frontier_lens"])
        self.assertTrue(result["escalated"])
        # Base two reviewers keep thorough's tier/reasoning; the flag signals the 3rd's upgrade.
        self.assertEqual(result["reviewer_tier"], "balanced")
        self.assertEqual(result["reviewer_reasoning"], "high")

    def test_escalation_only_valid_at_thorough_depth(self) -> None:
        with self.assertRaises(ValueError):
            fanout.resolve(self.contract, "quick", escalate=True)

    def test_unknown_depth_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            fanout.resolve(self.contract, "extreme")


class FanoutCliTests(unittest.TestCase):
    def test_json_output_round_trips(self) -> None:
        import json
        result = run_cli("--depth", "medium")
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["depth"], "medium")
        self.assertIn("reviewer_reasoning", payload)

    def test_text_output_is_human_readable(self) -> None:
        result = run_cli("--depth", "thorough", "--escalate", "--format", "text")
        self.assertEqual(result.returncode, 0)
        self.assertIn("3 reviewer(s)", result.stdout)
        self.assertIn("adversarial", result.stdout)
        self.assertIn("frontier/extra_high", result.stdout)


if __name__ == "__main__":
    unittest.main()
