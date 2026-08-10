"""Regression tests for the generated, hash-verified 04_tasks.json/05_execution.json sidecars.

Covers: sidecar generation matching a fixture, staleness detection/rejection, the sidecar's
`concurrency` object matching what `emit_result`'s ephemeral `--format json` already computes,
and the `Task category` -> `capability_tier`/`resolved_model` resolution (calling
`model-router.py`'s `resolve()` in-process, never by shelling out per task).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "spec-check.py"

SPEC = importlib.util.spec_from_file_location("spec_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
spec_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spec_check)


def task_block(
    task_id: str,
    *,
    title: str = "Implement behavior",
    files: str = "`src/a.py`",
    depends_on: str = "none",
    stage: int = 1,
    risk: str = "low; none",
    task_category: str = "code_analysis",
    delegation: str = "sequential subagent",
    requirements: str = "1.1",
) -> str:
    """Build one canonical leaf task contract, including the new Task category field."""
    return f"""  - [ ] {task_id} {title}
    - **Files:** {files}
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Depends on:** {depends_on}
    - **Stage:** {stage}
    - **Interfaces:** Consumes: approved design contract; Produces: `run()` behavior
    - **Documentation:** no public surface
    - **Verification:** Run tests.
    - **Estimated effort:** 15-30 minutes
    - **Risk:** {risk}
    - **Task category:** {task_category}
    - **Delegation:** {delegation}
    - _Requirements: {requirements}_
"""


TASKS_MD = (
    "# Tasks\n\n- [ ] 1. Group\n"
    + task_block("1.1", task_category="code_analysis", delegation="parallel-safe")
    + task_block(
        "1.2",
        title="Implement risky behavior",
        files="`src/b.py`",
        risk="high; rollback documented",
        task_category="heavy_reasoning",
        delegation="parallel-safe",
    )
)

EXECUTION_MD = """# Execution

## Execution Timing

### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|
| run-20260809T120000Z | 2026-08-09T12:00:00Z | 2026-08-09T12:14:00Z | 840 | complete |

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|
| run-20260809T120000Z | Stage 1 | 1.1 | 1 | 2026-08-09T12:00:00Z | 2026-08-09T12:00:00Z | 0 | verified |
| run-20260809T120000Z | Stage 1 | 1.2 | 1 | 2026-08-09T12:00:10Z | 2026-08-09T12:05:10Z | 300 | failed |
"""


STATE_MD = """# Spec State: Example

| Gate | Status | Evidence |
|---|---|---|
| Discovery | approved | 2026-08-09 |
| Requirements | approved | 2026-08-09 |
| Design | draft / approved / invalidated | <approval date or reason> |
| Tasks | not_started / draft / approved / invalidated | <approval date or reason> |
| Audit | not_run | |
| Execution | not_started | |

## Change Control

- <material change, impacted artifacts, re-approval required>
- Design revised after discovery clarified rate limits; requirements re-approved 2026-08-09.
"""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StateSidecarGenerationTests(unittest.TestCase):
    """`build_state_sidecar` parses the canonical Gate table and Change Control notes."""

    def test_sidecar_matches_expected_fixture(self) -> None:
        payload, errors = spec_check.build_state_sidecar(STATE_MD)
        self.assertEqual([], errors)
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(
            {"file": "00_state.md", "sha256": _sha256(STATE_MD)}, payload["generated_from"]
        )
        self.assertEqual(
            {"status": "approved", "evidence": "2026-08-09"}, payload["gates"]["discovery"]
        )
        self.assertEqual(
            {"status": "approved", "evidence": "2026-08-09"}, payload["gates"]["requirements"]
        )
        self.assertEqual({"status": "not_run", "evidence": ""}, payload["gates"]["audit"])
        self.assertEqual(
            ["Design revised after discovery clarified rate limits; requirements re-approved 2026-08-09."],
            payload["change_control"],
        )

    def test_unfilled_template_placeholder_status_round_trips_verbatim(self) -> None:
        """An unapproved template row is not an error — it's the correct signal that the gate
        hasn't been set, exactly as the literal-substring `--ready` check already relies on."""
        payload, errors = spec_check.build_state_sidecar(STATE_MD)
        self.assertEqual([], errors)
        self.assertEqual(
            "draft / approved / invalidated", payload["gates"]["design"]["status"]
        )

    def test_two_column_table_without_evidence_is_tolerated(self) -> None:
        text = (
            "# State\n\n| Gate | Status |\n|---|---|\n"
            "| Discovery | approved |\n| Requirements | approved |\n"
            "| Design | approved |\n| Tasks | approved |\n"
            "| Audit | not_run |\n| Execution | not_started |\n"
        )
        payload, errors = spec_check.build_state_sidecar(text)
        self.assertEqual([], errors)
        self.assertEqual({"status": "approved", "evidence": ""}, payload["gates"]["discovery"])

    def test_missing_gate_row_is_a_clear_error(self) -> None:
        text = "# State\n\n| Gate | Status | Evidence |\n|---|---|---|\n| Discovery | approved | |\n"
        payload, errors = spec_check.build_state_sidecar(text)
        self.assertIsNone(payload)
        self.assertTrue(any("Gate table row" in error for error in errors))

    def test_change_control_placeholder_line_is_excluded(self) -> None:
        text = STATE_MD.replace(
            "- Design revised after discovery clarified rate limits; requirements re-approved 2026-08-09.\n",
            "",
        )
        payload, _errors = spec_check.build_state_sidecar(text)
        self.assertEqual([], payload["change_control"])


class TasksSidecarGenerationTests(unittest.TestCase):
    """`build_tasks_sidecar` output matches a fixture built independently of the generator."""

    def setUp(self) -> None:
        self.task_graph, self.graph_errors = spec_check.task_dependency_graph(TASKS_MD)
        self.assertEqual([], self.graph_errors)
        self.contract = spec_check.MODEL_ROUTER.load_contract()

    def test_sidecar_matches_expected_fixture(self) -> None:
        payload, errors = spec_check.build_tasks_sidecar(
            TASKS_MD, self.task_graph, self.graph_errors, {"1.1"}, self.contract,
        )
        self.assertEqual([], errors)
        assert payload is not None
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(
            {"file": "04_tasks.md", "sha256": _sha256(TASKS_MD)}, payload["generated_from"],
        )
        self.assertEqual(1, payload["requirement_count"])
        self.assertEqual({"1": ["1.1", "1.2"]}, payload["stages"])
        self.assertEqual(["1.1", "1.2"], [entry["id"] for entry in payload["tasks"]])

        by_id = {entry["id"]: entry for entry in payload["tasks"]}
        self.assertEqual(
            {
                "id": "1.1", "title": "Implement behavior", "checked": False, "optional": False,
                "stage": 1, "depends_on": [], "files": ["src/a.py"],
                "delegation": "parallel-safe", "dependency_resolution": "none",
                "dependency_delivery": "none",
                "interfaces": "Consumes: approved design contract; Produces: `run()` behavior",
                "verification": "Run tests.", "risk": "low; none", "requirements": ["1.1"],
                "task_category": "code_analysis", "capability_tier": "balanced",
                "resolved_model": "claude-sonnet-5", "reasoning_level": "medium",
            },
            by_id["1.1"],
        )
        self.assertEqual("heavy_reasoning", by_id["1.2"]["task_category"])
        # heavy_reasoning floors at balanced/high, then a declared `high` risk escalates further.
        self.assertEqual("frontier", by_id["1.2"]["capability_tier"])
        self.assertEqual("claude-opus-5", by_id["1.2"]["resolved_model"])
        self.assertEqual("extra_high", by_id["1.2"]["reasoning_level"])

    def test_missing_task_category_is_a_clear_emit_error(self) -> None:
        tasks_md_missing_category = TASKS_MD.replace(
            "    - **Task category:** heavy_reasoning\n", ""
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md_missing_category)
        self.assertEqual([], graph_errors)
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md_missing_category, task_graph, graph_errors, {"1.1"}, self.contract,
        )
        self.assertIsNone(payload)
        self.assertTrue(any("1.2" in error and "Task category" in error for error in errors))

    def test_invalid_task_category_is_rejected(self) -> None:
        tasks_md_bad_category = TASKS_MD.replace(
            "**Task category:** code_analysis", "**Task category:** invents_a_category"
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md_bad_category)
        self.assertEqual([], graph_errors)
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md_bad_category, task_graph, graph_errors, {"1.1"}, self.contract,
        )
        self.assertIsNone(payload)
        self.assertTrue(any("1.1" in error and "Task category must be one of" in error for error in errors))

    def test_graph_errors_block_sidecar_emission(self) -> None:
        broken = TASKS_MD.replace("**Stage:** 1", "**Stage:** 2", 1)
        task_graph, graph_errors = spec_check.task_dependency_graph(broken)
        self.assertTrue(graph_errors)
        payload, errors = spec_check.build_tasks_sidecar(
            broken, task_graph, graph_errors, {"1.1"}, self.contract,
        )
        self.assertIsNone(payload)
        self.assertTrue(errors)


class ConcurrencyMatchesEmitResultTests(unittest.TestCase):
    """The sidecar's `concurrency` object agrees with emit_result's ephemeral `execution` object."""

    def test_ready_parallel_serial_blocked_match_across_both_views(self) -> None:
        tasks_md = (
            "# Tasks\n\n- [ ] 1. Group\n"
            + task_block("1.1", task_category="code_analysis", delegation="parallel-safe")
            + task_block(
                "1.2", title="Second", files="`src/c.py`",
                task_category="review", delegation="sequential subagent",
            )
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md)
        self.assertEqual([], graph_errors)
        contract = spec_check.MODEL_ROUTER.load_contract()
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md, task_graph, graph_errors, {"1.1"}, contract,
        )
        self.assertEqual([], errors)
        assert payload is not None
        concurrency = payload["concurrency"]

        buffer = __import__("io").StringIO()
        from contextlib import redirect_stdout
        with redirect_stdout(buffer):
            spec_check.emit_result("json", Path("/tmp/example"), {"1.1"}, task_graph, [], [])
        emitted = json.loads(buffer.getvalue())["execution"]

        self.assertEqual(emitted["active_stage"], concurrency["active_stage"])
        self.assertEqual(emitted["ready"], concurrency["ready"])
        self.assertEqual(emitted["parallel_candidates"], concurrency["parallel_candidates"])
        self.assertEqual(emitted["serial_candidates"], concurrency["serial_candidates"])
        self.assertEqual(emitted["blocked"], concurrency["blocked"])
        # concurrency.waves is a strict refinement (parallel batch, then one wave per serial
        # task) of the same ready/parallel/serial split emit_result already reports.
        self.assertEqual(
            [{"wave": 1, "mode": "parallel", "tasks": ["1.1"]}, {"wave": 2, "mode": "serial", "tasks": ["1.2"]}],
            concurrency["waves"],
        )

    def test_blocked_task_is_excluded_from_ready_in_both_views(self) -> None:
        tasks_md = (
            "# Tasks\n\n- [ ] 1. Group\n"
            + task_block("1.1", task_category="code_analysis", delegation="parallel-safe")
            + "\n- [ ] 2. Group\n"
            + task_block(
                "2.1", title="Second stage", files="`src/d.py`", depends_on="1.1", stage=2,
                task_category="review",
            )
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md)
        self.assertEqual([], graph_errors)
        # Stage 1 is active while 1.1 is unchecked; stage 2's 2.1 is not yet in the active pool,
        # so it is neither ready nor blocked at this point (both views agree it is absent).
        contract = spec_check.MODEL_ROUTER.load_contract()
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md, task_graph, graph_errors, {"1.1"}, contract,
        )
        self.assertEqual([], errors)
        assert payload is not None
        self.assertEqual(1, payload["concurrency"]["active_stage"])
        self.assertEqual(["1.1"], payload["concurrency"]["ready"])
        self.assertNotIn("2.1", payload["concurrency"]["ready"])
        self.assertNotIn("2.1", payload["concurrency"]["blocked"])


class TaskCategoryModelRoutingTests(unittest.TestCase):
    """Per-task capability_tier/resolved_model/reasoning_level resolution calls
    model-router.resolve() in-process — checking both independent axes, not just tier."""

    def setUp(self) -> None:
        self.contract = spec_check.MODEL_ROUTER.load_contract()

    def test_quick_lookup_low_risk_resolves_economical_low(self) -> None:
        tasks_md = "# Tasks\n\n- [ ] 1. Group\n" + task_block(
            "1.1", task_category="quick_lookup", risk="low; none",
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md)
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md, task_graph, graph_errors, {"1.1"}, self.contract,
        )
        self.assertEqual([], errors)
        assert payload is not None
        entry = payload["tasks"][0]
        direct = spec_check.MODEL_ROUTER.resolve(self.contract, "quick_lookup", "none")
        self.assertEqual(direct["capability_tier"], entry["capability_tier"])
        self.assertEqual(direct["resolved_model"], entry["resolved_model"])
        self.assertEqual(direct["reasoning_level"], entry["reasoning_level"])
        self.assertEqual("economical", entry["capability_tier"])
        self.assertEqual("low", entry["reasoning_level"])

    def test_review_medium_risk_escalates_tier_and_reasoning_independently(self) -> None:
        tasks_md = "# Tasks\n\n- [ ] 1. Group\n" + task_block(
            "1.1", task_category="review", risk="medium; needs a second reviewer",
        )
        task_graph, graph_errors = spec_check.task_dependency_graph(tasks_md)
        payload, errors = spec_check.build_tasks_sidecar(
            tasks_md, task_graph, graph_errors, {"1.1"}, self.contract,
        )
        self.assertEqual([], errors)
        assert payload is not None
        entry = payload["tasks"][0]
        direct = spec_check.MODEL_ROUTER.resolve(self.contract, "review", "elevated")
        self.assertEqual(direct["capability_tier"], entry["capability_tier"])
        self.assertEqual(direct["resolved_model"], entry["resolved_model"])
        self.assertEqual(direct["reasoning_level"], entry["reasoning_level"])
        # review's default_tier balanced escalates one step to frontier; default_reasoning
        # medium escalates one step to high — two separate tables, both moved by the same risk.
        self.assertEqual("frontier", entry["capability_tier"])
        self.assertEqual("high", entry["reasoning_level"])

    def test_declared_risk_mapping_is_deterministic(self) -> None:
        self.assertEqual("none", spec_check._task_declared_risk("low; rollback trivial"))
        self.assertEqual("elevated", spec_check._task_declared_risk("medium; needs review"))
        self.assertEqual("high", spec_check._task_declared_risk("high; destructive"))
        self.assertEqual("none", spec_check._task_declared_risk(None))
        self.assertEqual("none", spec_check._task_declared_risk(""))


class ExecutionSidecarGenerationTests(unittest.TestCase):
    """`build_execution_sidecar` matches a fixture and embeds a render.py-ready gantt IR."""

    def test_sidecar_matches_expected_fixture(self) -> None:
        payload, errors = spec_check.build_execution_sidecar(EXECUTION_MD)
        self.assertEqual([], errors)
        assert payload is not None
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual(
            {"file": "05_execution.md", "sha256": _sha256(EXECUTION_MD)}, payload["generated_from"],
        )
        self.assertEqual(1, len(payload["runs"]))
        self.assertEqual(840, payload["runs"][0]["elapsed_seconds"])
        self.assertEqual(2, len(payload["task_attempts"]))
        self.assertEqual([], payload["unresolved"])

        gantt = payload["gantt"]
        self.assertEqual("timeline", gantt["diagram"])
        self.assertEqual("gantt", gantt["target"])
        self.assertEqual("YYYY-MM-DDTHH:mm:ss", gantt["dateFormat"])
        section_names = [section["name"] for section in gantt["sections"]]
        self.assertEqual(["Execution Runs", "Stage 1"], section_names)
        stage_bars = gantt["sections"][1]["bars"]
        # A completed zero-second interval renders as a minimum 1s bar; the ledger keeps the 0.
        self.assertEqual("2026-08-09T12:00:00", stage_bars[0]["start"])
        self.assertEqual("2026-08-09T12:00:01", stage_bars[0]["end"])
        self.assertEqual(["done"], stage_bars[0]["tags"])
        self.assertEqual(["crit"], stage_bars[1]["tags"])

    def test_gantt_ir_renders_through_mermaid_render_py(self) -> None:
        render_path = SKILL_DIR.parent / "mermaid" / "scripts" / "render.py"
        if not render_path.is_file():
            self.skipTest("mermaid skill not present in this checkout")
        payload, errors = spec_check.build_execution_sidecar(EXECUTION_MD)
        self.assertEqual([], errors)
        assert payload is not None
        with tempfile.TemporaryDirectory() as directory:
            ir_path = Path(directory) / "gantt.json"
            ir_path.write_text(json.dumps(payload["gantt"]), encoding="utf-8")
            result = subprocess.run(
                ["python3", str(render_path), str(ir_path)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertIn("gantt", result.stdout)
            self.assertIn("section Execution Runs", result.stdout)

    def test_active_and_interrupted_unknown_rows_are_excluded_from_bars(self) -> None:
        execution_md = """# Execution

## Execution Timing

### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|
| run-20260809T120000Z | 2026-08-09T12:00:00Z | pending | pending | active |
| run-20260809T110000Z | 2026-08-09T11:00:00Z | unknown | unknown | interrupted |

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|
"""
        payload, errors = spec_check.build_execution_sidecar(execution_md)
        self.assertEqual([], errors)
        assert payload is not None
        self.assertEqual([], payload["gantt"]["sections"])
        self.assertEqual(
            [
                {"kind": "run", "id": "run-20260809T120000Z", "reason": "active"},
                {"kind": "run", "id": "run-20260809T110000Z", "reason": "interrupted"},
            ],
            payload["unresolved"],
        )


class SidecarFreshnessTests(unittest.TestCase):
    """`sidecar_freshness_errors` and the `--ready` gate reject a stale or orphaned sidecar."""

    def _write_minimal_spec(self, spec_dir: Path) -> None:
        spec_dir.mkdir(parents=True)
        (spec_dir / "00_state.md").write_text(
            "# State\n\n| Gate | Status |\n|---|---|\n"
            "| Discovery | approved |\n| Requirements | approved |\n"
            "| Design | approved |\n| Tasks | approved |\n"
            "| Audit | not_run |\n| Execution | not_started |\n",
            encoding="utf-8",
        )
        (spec_dir / "01_discovery.md").write_text("# Discovery\n\nApproved scope.\n", encoding="utf-8")
        (spec_dir / "02_requirements.md").write_text(
            "# Requirements\n\n**R1.1** WHEN a user acts, THE system SHALL respond.\n",
            encoding="utf-8",
        )
        (spec_dir / "03_design.md").write_text(
            "# Design\n\n**Validates: Requirement 1.1**\n\n"
            "## Current Technology Evidence\n\nNo evolving technology behavior applies.\n\n"
            "## Dependency Security Evidence\n\nNo material third-party runtime dependency is selected.\n",
            encoding="utf-8",
        )
        (spec_dir / "04_tasks.md").write_text(TASKS_MD, encoding="utf-8")
        spec_check.NAV_MODULE.update_navigation(spec_dir)

    def test_no_sidecar_present_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            self.assertEqual([], spec_check.sidecar_freshness_errors(spec_dir))

    def test_emit_json_then_check_passes_and_hash_matches_current_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            emit = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, emit.returncode, emit.stdout + emit.stderr)
            self.assertEqual([], spec_check.sidecar_freshness_errors(spec_dir))
            sidecar = json.loads((spec_dir / "04_tasks.json").read_text(encoding="utf-8"))
            self.assertEqual(
                _sha256((spec_dir / "04_tasks.md").read_text(encoding="utf-8")),
                sidecar["generated_from"]["sha256"],
            )

    def test_editing_markdown_without_regenerating_is_caught_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            tasks_path = spec_dir / "04_tasks.md"
            tasks_path.write_text(tasks_path.read_text(encoding="utf-8") + "\n<!-- edited -->\n", encoding="utf-8")

            stale_errors = spec_check.sidecar_freshness_errors(spec_dir)
            self.assertTrue(any("04_tasks.json is stale" in error for error in stale_errors))

            result = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--format", "json"],
                check=False, capture_output=True, text=True,
            )
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(any("04_tasks.json is stale" in error for error in payload["errors"]))

    def test_orphaned_sidecar_without_its_markdown_twin_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            (spec_dir / "04_tasks.md").unlink()
            errors = spec_check.sidecar_freshness_errors(spec_dir)
            self.assertTrue(any("orphaned sidecar" in error for error in errors))

    def test_emit_json_also_writes_state_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            emit = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, emit.returncode, emit.stdout + emit.stderr)
            self.assertEqual([], spec_check.sidecar_freshness_errors(spec_dir))
            sidecar = json.loads((spec_dir / "00_state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                _sha256((spec_dir / "00_state.md").read_text(encoding="utf-8")),
                sidecar["generated_from"]["sha256"],
            )
            self.assertEqual("approved", sidecar["gates"]["discovery"]["status"])

    def test_editing_state_markdown_without_regenerating_is_caught_as_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            state_path = spec_dir / "00_state.md"
            state_path.write_text(state_path.read_text(encoding="utf-8") + "\n<!-- edited -->\n", encoding="utf-8")
            stale_errors = spec_check.sidecar_freshness_errors(spec_dir)
            self.assertTrue(any("00_state.json is stale" in error for error in stale_errors))

    def test_emit_json_regenerates_within_the_same_ready_gated_invocation(self) -> None:
        """--emit-json refreshes a sidecar it is about to write before the freshness gate runs,
        so requesting regeneration and validation in one command does not self-reject."""
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
    def test_all_nine_schemas_valid_and_loadable(self) -> None:
        schemas_dir = SKILL_DIR / "contracts" / "schemas"
        schema_files = list(schemas_dir.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_files), 7)
        for schema_file in schema_files:
            data = json.loads(schema_file.read_text(encoding="utf-8"))
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", data.get("$schema"))
            self.assertTrue(data.get("title"))

    def test_sidecars_in_dedicated_subfolder_are_discovered_and_checked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory) / ".specs" / "example"
            self._write_minimal_spec(spec_dir)
            sidecars_dir = spec_dir / "sidecars"
            sidecars_dir.mkdir(parents=True, exist_ok=True)
            
            # Emit sidecars into sidecars/ folder
            emit = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--emit-json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, emit.returncode, emit.stdout + emit.stderr)
            self.assertTrue((sidecars_dir / "00_state.json").is_file())
            self.assertTrue((sidecars_dir / "04_tasks.json").is_file())
            
            # Verify freshness passes
            errors = spec_check.sidecar_freshness_errors(spec_dir)
            self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()

