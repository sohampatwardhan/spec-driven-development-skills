import importlib.util
import json
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
        (self.spec_dir / "sidecars").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_tasks(self, tasks: list[dict], ready: list[str]) -> None:
        payload = {
            "schema_version": 1,
            "tasks": tasks,
            "concurrency": {"active_stage": 1, "ready": ready},
        }
        (self.spec_dir / "sidecars" / "04_tasks.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    @staticmethod
    def _task(task_id: str, **overrides) -> dict:
        task = {
            "id": task_id,
            "title": f"Task {task_id}",
            "checked": False,
            "stage": 1,
            "depends_on": [],
            "files": [f"src/{task_id}.ts"],
            "requirements": ["1.1"],
            "verification": "tests pass",
            "interfaces": "Consumes parser; produces a rendered view.",
            "dependency_resolution": "none",
            "dependency_delivery": "none",
            "risk": "medium; visible behavior",
            "documentation": "Update user-facing behavior notes.",
            "delegation": "parallel-safe",
            "task_category": "code_analysis",
            "resolved_model": "claude-sonnet-5",
            "reasoning_level": "medium",
        }
        task.update(overrides)
        return task

    def test_profiles_match_current_installed_cli_flags(self) -> None:
        agents = spec_orca.load_agent_profiles()["agents"]
        self.assertEqual(["--permission-mode", "bypassPermissions"], agents["claude"]["unattended_flags"])
        self.assertEqual(
            ["--ask-for-approval", "never", "--sandbox", "workspace-write"],
            agents["codex"]["unattended_flags"],
        )
        self.assertEqual(
            ["--dangerously-skip-permissions"], agents["agy"]["unattended_flags"]
        )
        self.assertTrue(agents["claude"]["provider_safety"]["real_time_cyber_safeguards"])

    def test_provider_constraint_blocks_unverified_dual_use_for_claude(self) -> None:
        profile = spec_orca.load_agent_profiles()["agents"]["claude"]
        self.assertIn("dual_use", spec_orca.provider_compatibility_error({"safety_classification": "dual_use"}, profile) or "")
        self.assertIsNone(spec_orca.provider_compatibility_error({"safety_classification": "defensive"}, profile))

    def test_receipt_value_prefers_specific_nested_identifier_over_root_id(self) -> None:
        receipt = {"id": "local", "result": {"runId": "run_real"}}
        self.assertEqual("run_real", spec_orca.receipt_value(receipt, "runId", "id"))

    def test_sync_uses_real_receipts_dependencies_parents_and_gate(self) -> None:
        tasks = [
            self._task("1.1"),
            self._task(
                "1.2",
                title="Checkpoint: verify milestone",
                depends_on=["1.1"],
            ),
        ]
        self._write_tasks(tasks, ["1.1"])

        def fake_orca(args, timeout=60):
            if args[1] == "run-create":
                return {"id": "local", "result": {"runId": "run_real"}}
            if args[1] == "task-create":
                title = args[args.index("--task-title") + 1]
                return {"result": {"taskId": {"Stage 1": "task_stage", "1.1 Task 1.1": "task_one", "1.2 Checkpoint: verify milestone": "task_two"}[title]}}
            if args[1] == "gate-create":
                return {"result": {"gateId": "gate_real"}}
            return {"ok": True}

        with patch.object(spec_orca, "run_orca_json", side_effect=fake_orca) as mocked:
            state = spec_orca.sync_spec_to_orca(self.spec_dir)

        self.assertEqual("run_real", state["run_id"])
        self.assertEqual({"1.1": "task_one", "1.2": "task_two"}, state["tasks_map"])
        self.assertEqual("task_stage", state["stage_tasks_map"]["1"])
        self.assertEqual("gate_real", state["decision_gates"][0]["gate_id"])
        leaf_two_call = next(
            item.args[0]
            for item in mocked.call_args_list
            if "--task-title" in item.args[0]
            and item.args[0][item.args[0].index("--task-title") + 1].startswith("1.2 ")
        )
        self.assertEqual('["task_one"]', leaf_two_call[leaf_two_call.index("--deps") + 1])
        self.assertEqual("task_stage", leaf_two_call[leaf_two_call.index("--parent") + 1])
        task_spec = leaf_two_call[leaf_two_call.index("--spec") + 1]
        for expected in (
            "Files: src/1.2.ts",
            "Dependencies: 1.1",
            "Requirements: 1.1",
            "Interfaces: Consumes parser; produces a rendered view.",
            "Dependency resolution: none",
            "Dependency delivery: none",
            "Risk: medium; visible behavior",
            "Documentation: Update user-facing behavior notes.",
            "Verification: tests pass",
            "Resolved model: claude-sonnet-5",
            "Reasoning level: medium",
            "Execution contract:",
        ):
            self.assertIn(expected, task_spec)

    def test_sync_reuses_persisted_run_without_duplicate_task_creation(self) -> None:
        self._write_tasks([self._task("1.1")], ["1.1"])
        state = spec_orca._new_state("run_existing", self.spec_dir.name)
        state["stage_tasks_map"] = {"1": "stage_existing"}
        state["tasks_map"] = {"1.1": "task_existing"}
        spec_orca.save_run_state(self.spec_dir, state)
        with patch.object(spec_orca, "run_orca_json", return_value={"ok": True}) as mocked:
            spec_orca.sync_spec_to_orca(self.spec_dir)
        self.assertEqual(
            ["orchestration", "run-use", "--id", "run_existing"], mocked.call_args_list[0].args[0]
        )
        self.assertFalse(any("task-create" in item.args[0] for item in mocked.call_args_list))

    def test_ready_plans_filter_dependencies_and_build_agent_specific_commands(self) -> None:
        tasks = [
            self._task("1.1"),
            self._task("1.2", depends_on=["1.1"], resolved_model="claude-sonnet-5"),
        ]
        self._write_tasks(tasks, ["1.1", "1.2"])
        state = spec_orca._new_state("run_real", self.spec_dir.name)
        state["tasks_map"] = {"1.1": "task_one", "1.2": "task_two"}
        spec_orca.save_run_state(self.spec_dir, state)

        plans = spec_orca.get_ready_dispatches(self.spec_dir)
        self.assertEqual(["1.1"], [plan["task_id"] for plan in plans])
        self.assertEqual(
            ["claude", "--permission-mode", "bypassPermissions", "--model", "claude-sonnet-5", "--effort", "medium"],
            plans[0]["command_argv"],
        )
        codex = spec_orca.get_ready_dispatches(
            self.spec_dir, agent_override="codex", model_override="gpt-5.5"
        )[0]
        self.assertEqual(
            [
                "codex",
                "--ask-for-approval",
                "never",
                "--sandbox",
                "workspace-write",
                "--model",
                "gpt-5.5",
                "-c",
                "model_reasoning_effort=medium",
            ],
            codex["command_argv"],
        )
        self.assertNotIn("gemini", codex["command"].lower())
        self.assertEqual("orca-task-spec-inject", codex["prompt_delivery"])

    def test_abstract_extra_high_effort_is_normalized_for_each_current_cli(self) -> None:
        tasks = [self._task("1.1", reasoning_level="extra_high")]
        self._write_tasks(tasks, ["1.1"])
        state = spec_orca._new_state("run_real", self.spec_dir.name)
        state["tasks_map"] = {"1.1": "task_one"}
        spec_orca.save_run_state(self.spec_dir, state)

        claude = spec_orca.get_ready_dispatches(self.spec_dir)[0]
        codex = spec_orca.get_ready_dispatches(
            self.spec_dir, agent_override="codex", model_override="gpt-5.5"
        )[0]
        agy = spec_orca.get_ready_dispatches(
            self.spec_dir, agent_override="agy", model_override="gemini-2.5-pro"
        )[0]
        self.assertEqual("xhigh", claude["command_argv"][-1])
        self.assertEqual("model_reasoning_effort=xhigh", codex["command_argv"][-1])
        self.assertEqual("high", agy["command_argv"][-1])

    def test_dispatch_creates_waits_injects_and_persists_real_receipts(self) -> None:
        self._write_tasks([self._task("1.1")], ["1.1"])
        state = spec_orca._new_state("run_real", self.spec_dir.name)
        state["tasks_map"] = {"1.1": "task_real"}
        spec_orca.save_run_state(self.spec_dir, state)
        plan = spec_orca.get_ready_dispatches(self.spec_dir)[0]

        receipts = [
            {"result": {"terminalHandle": "term_real"}},
            {"ok": True},
            {"result": {"dispatchId": "dispatch_real"}},
        ]
        with patch.object(spec_orca, "run_orca_json", side_effect=receipts) as mocked:
            records = spec_orca.dispatch_ready(self.spec_dir, [plan], setup="run", repo=None)

        self.assertEqual("dispatch_real", records[0]["dispatch_id"])
        self.assertEqual("term_real", records[0]["worker_handle"])
        self.assertIn("terminal", mocked.call_args_list[0].args[0])
        self.assertIn("wait", mocked.call_args_list[1].args[0])
        self.assertIn("--inject", mocked.call_args_list[2].args[0])
        disk = spec_orca.load_run_state(self.spec_dir)
        self.assertEqual("dispatch_real", disk["dispatches"][0]["dispatch_id"])


if __name__ == "__main__":
    unittest.main()
