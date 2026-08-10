import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
SPEC_ORCA_SCRIPT = SKILL_DIR / "scripts" / "spec-orca.py"

SPEC = importlib.util.spec_from_file_location("spec_orca", SPEC_ORCA_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
spec_orca = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spec_orca)


class SpecOrcaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.spec_dir = Path(self.temp_dir.name) / ".specs" / "test-feature"
        self.spec_dir.mkdir(parents=True)
        self.sidecars_dir = self.spec_dir / "sidecars"
        self.sidecars_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_tasks_sidecar(self, tasks_data: dict) -> None:
        tasks_file = self.sidecars_dir / "04_tasks.json"
        tasks_file.write_text(json.dumps(tasks_data, indent=2), encoding="utf-8")

    def test_load_agent_profiles_contains_unattended_flags(self) -> None:
        profiles = spec_orca.load_agent_profiles()
        self.assertIn("agents", profiles)
        agents = profiles["agents"]
        self.assertIn("claude", agents)
        self.assertIn("--dangerously-skip-permissions", agents["claude"]["unattended_flags"])
        self.assertIn("codex", agents)
        self.assertIn("--full-auto", agents["codex"]["unattended_flags"])
        self.assertIn("agy", agents)
        self.assertIn("--yolo", agents["agy"]["unattended_flags"])

    def test_sync_spec_to_orca_creates_run_and_gates(self) -> None:
        tasks_payload = {
            "schema_version": 1,
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "checked": False,
                    "stage": 1,
                    "depends_on": [],
                    "task_category": "core_logic",
                    "capability_tier": "complex_reasoning",
                    "delegation": "parallel-safe"
                },
                {
                    "id": "1.2",
                    "title": "Checkpoint: verify milestone",
                    "checked": False,
                    "stage": 1,
                    "depends_on": ["1.1"],
                    "task_category": "core_logic",
                    "capability_tier": "complex_reasoning",
                    "delegation": "sequential subagent"
                }
            ],
            "concurrency": {
                "active_stage": 1,
                "ready": ["1.1"],
                "parallel_candidates": ["1.1"],
                "serial_candidates": [],
                "blocked": {"1.2": ["1.1"]}
            }
        }
        self._write_tasks_sidecar(tasks_payload)

        run_state = spec_orca.sync_spec_to_orca(self.spec_dir, run_id="run-custom-123")
        self.assertEqual("run-custom-123", run_state["run_id"])
        self.assertIn("1.1", run_state["tasks_map"])
        self.assertIn("1.2", run_state["tasks_map"])
        self.assertEqual(1, len(run_state["decision_gates"]))
        self.assertEqual("gate-1.2", run_state["decision_gates"][0]["gate_id"])

        sidecar_file = self.sidecars_dir / "orca_run.json"
        self.assertTrue(sidecar_file.is_file())
        disk_data = json.loads(sidecar_file.read_text(encoding="utf-8"))
        self.assertEqual("run-custom-123", disk_data["run_id"])

    def test_get_ready_dispatches_filters_by_dependencies(self) -> None:
        tasks_payload = {
            "schema_version": 1,
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Implement model",
                    "checked": False,
                    "stage": 1,
                    "depends_on": [],
                    "task_category": "core_logic",
                    "capability_tier": "complex_reasoning",
                    "delegation": "parallel-safe",
                    "files": ["src/model.py"],
                    "orca_dispatch": {"agent": "claude"}
                },
                {
                    "id": "1.2",
                    "title": "Implement CLI wrapper",
                    "checked": False,
                    "stage": 1,
                    "depends_on": ["1.1"],
                    "task_category": "core_logic",
                    "capability_tier": "complex_reasoning",
                    "delegation": "parallel-safe",
                    "files": ["src/cli.py"],
                    "orca_dispatch": {"agent": "claude"}
                }
            ],
            "concurrency": {
                "active_stage": 1,
                "ready": ["1.1", "1.2"],
                "parallel_candidates": ["1.1"],
                "serial_candidates": [],
                "blocked": {"1.2": ["1.1"]}
            }
        }
        self._write_tasks_sidecar(tasks_payload)

        dispatches = spec_orca.get_ready_dispatches(self.spec_dir)
        # 1.2 is blocked because 1.1 is unchecked
        self.assertEqual(1, len(dispatches))
        self.assertEqual("1.1", dispatches[0]["task_id"])
        self.assertEqual("new-child", dispatches[0]["worktree_mode"])
        self.assertIn("--dangerously-skip-permissions", dispatches[0]["unattended_flags"])

        # When 1.1 is checked, 1.2 becomes eligible
        tasks_payload["tasks"][0]["checked"] = True
        self._write_tasks_sidecar(tasks_payload)

        dispatches = spec_orca.get_ready_dispatches(self.spec_dir)
        self.assertEqual(1, len(dispatches))
        self.assertEqual("1.2", dispatches[0]["task_id"])

    def test_budget_and_quota_inspection_and_down_tiering(self) -> None:
        # Default ok status
        status = spec_orca.check_budget_and_quota()
        self.assertEqual("ok", status["status"])

        # Constrained budget causes down-tiering of lightweight categories
        constrained_status = {"status": "constrained", "remaining_usd": 2.5, "cooldown_sec": 0, "provider": "anthropic"}
        model, effort = spec_orca.resolve_model_with_budget("code_analysis", "complex_reasoning", constrained_status)
        self.assertEqual("gemini-2.5-flash", model)
        self.assertEqual("low", effort)

        # Normal status preserves balanced/pro model
        model_normal, effort_normal = spec_orca.resolve_model_with_budget("code_analysis", "complex_reasoning", status)
        self.assertEqual("gemini-2.5-pro", model_normal)

    def test_budget_exhaustion_defers_execution(self) -> None:
        tasks_payload = {
            "schema_version": 1,
            "tasks": [
                {
                    "id": "1.1",
                    "title": "Task One",
                    "checked": False,
                    "stage": 1,
                    "depends_on": [],
                    "task_category": "core_logic",
                    "capability_tier": "complex_reasoning",
                    "delegation": "parallel-safe"
                }
            ],
            "concurrency": {
                "active_stage": 1,
                "ready": ["1.1"]
            }
        }
        self._write_tasks_sidecar(tasks_payload)

        with patch.dict(os.environ, {"ORCA_BUDGET_REMAINING_USD": "0.0"}):
            dispatches = spec_orca.get_ready_dispatches(self.spec_dir)
            self.assertEqual([], dispatches)


if __name__ == "__main__":
    unittest.main()
