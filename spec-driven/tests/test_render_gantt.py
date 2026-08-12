"""Unit and regression tests for render-gantt.py deterministic Mermaid Gantt chart generator."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
RENDER_GANTT_SCRIPT = SKILL_DIR / "scripts" / "render-gantt.py"

SPEC = importlib.util.spec_from_file_location("render_gantt", RENDER_GANTT_SCRIPT)
assert SPEC is not None and SPEC.loader is not None
render_gantt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_gantt)


class RenderGanttTests(unittest.TestCase):
    def test_render_mermaid_gantt_structure(self) -> None:
        sections = [
            {
                "name": "Stage 1",
                "bars": [
                    {
                        "id": "1.1_att_1",
                        "label": "Implement Core",
                        "start": "2026-08-10T12:00:00",
                        "end": "2026-08-10T12:05:00",
                        "tags": ["done"]
                    }
                ]
            }
        ]
        mermaid = render_gantt.render_mermaid_gantt(
            title="Spec Timeline: Demo",
            sections=sections
        )
        self.assertTrue(mermaid.startswith("```mermaid\ngantt\n"))
        self.assertIn("title Spec Timeline: Demo", mermaid)
        self.assertIn("section Stage 1", mermaid)
        self.assertIn("Implement Core :done, t_1_1_att_1, 2026-08-10T12:00:00, 2026-08-10T12:05:00", mermaid)
        self.assertTrue(mermaid.endswith("```"))

    def test_build_gantt_from_execution_data_handles_zero_and_negative_duration(self) -> None:
        data = {
            "task_attempts": [
                {
                    "run_id": "run-1",
                    "stage_wave": "Stage 1",
                    "task": "1.1",
                    "attempt": 1,
                    "started_utc": "2026-08-10T12:00:00Z",
                    "stopped_utc": "2026-08-10T12:00:00Z",
                    "elapsed_seconds": 0,
                    "outcome": "verified"
                }
            ]
        }
        diagram, gantt_ir = render_gantt.build_gantt_from_execution_data(data, feature_slug="demo-feature")
        self.assertIn("Task 1.1 :done, t_1_1_att_1, 2026-08-10T12:00:00, 2026-08-10T12:00:01", diagram)

    def test_outcome_color_tags(self) -> None:
        data = {
            "task_attempts": [
                {
                    "run_id": "run-1",
                    "stage_wave": "Stage 1",
                    "task": "1.1",
                    "attempt": 1,
                    "started_utc": "2026-08-10T12:00:00Z",
                    "stopped_utc": "2026-08-10T12:02:00Z",
                    "elapsed_seconds": 120,
                    "outcome": "verified"
                },
                {
                    "run_id": "run-1",
                    "stage_wave": "Stage 1",
                    "task": "1.2",
                    "attempt": 1,
                    "started_utc": "2026-08-10T12:02:00Z",
                    "stopped_utc": "2026-08-10T12:04:00Z",
                    "elapsed_seconds": 120,
                    "outcome": "failed"
                },
                {
                    "run_id": "run-1",
                    "stage_wave": "Stage 1",
                    "task": "1.3",
                    "attempt": 1,
                    "started_utc": "2026-08-10T12:04:00Z",
                    "stopped_utc": "2026-08-10T12:06:00Z",
                    "elapsed_seconds": 120,
                    "outcome": "active"
                }
            ]
        }
        diagram, _ = render_gantt.build_gantt_from_execution_data(data, feature_slug="demo")
        self.assertIn("Task 1.1 :done,", diagram)
        self.assertIn("Task 1.2 :crit,", diagram)
        self.assertIn("Task 1.3 :active,", diagram)

    def test_active_attempt_with_pending_stop_renders_deterministically(self) -> None:
        data = {
            "task_attempts": [{
                "run_id": "run-1",
                "stage_wave": "Stage 3",
                "task": "3.1",
                "attempt": 2,
                "started_utc": "2026-08-10T12:04:00Z",
                "stopped_utc": "pending",
                "elapsed_seconds": "pending",
                "outcome": "active",
            }]
        }
        diagram, _ = render_gantt.build_gantt_from_execution_data(data, feature_slug="demo")
        self.assertIn(
            "Task 3.1 :active, t_3_1_att_2, 2026-08-10T12:04:00, 2026-08-10T12:04:01",
            diagram,
        )

    def test_inject_gantt_into_execution_md(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exec_md = Path(directory) / "05_execution.md"
            exec_md.write_text(
                "# Execution\n\n## Execution Timing\n\n| Run ID | Started | Stopped |\n|---|---|---|\n\n### Execution Gantt\n\n```mermaid\ngantt\n    title Old Gantt\n```\n",
                encoding="utf-8"
            )
            new_diagram = "```mermaid\ngantt\n    title New Gantt\n    dateFormat YYYY-MM-DD\n```"
            render_gantt.inject_gantt_into_execution_md(exec_md, new_diagram)

            content = exec_md.read_text(encoding="utf-8")
            self.assertEqual(1, content.count("### Execution Gantt"))
            self.assertIn("title New Gantt", content)
            self.assertNotIn("title Old Gantt", content)

    def test_flowchart_only_write_replaces_flowchart_without_touching_gantt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory)
            tasks_md = spec_dir / "04_tasks.md"
            execution_md = spec_dir / "05_execution.md"
            tasks_md.write_text(
                "# Tasks\n\n## Stage and Dependency Overview\n\n"
                "```mermaid\nflowchart TD\n    old[Old]\n```\n\n- [ ] 1. Task\n",
                encoding="utf-8",
            )
            execution_md.write_text(
                "# Execution\n\n### Execution Gantt\n\n"
                "```mermaid\ngantt\n    title Existing\n```\n",
                encoding="utf-8",
            )
            new_flowchart = "```mermaid\nflowchart TD\n    new[New]\n```"

            render_gantt.write_generated_diagrams(
                spec_dir,
                "```mermaid\ngantt\n    title Replacement\n```",
                new_flowchart,
                flowchart_only=True,
            )

            task_text = tasks_md.read_text(encoding="utf-8")
            execution_text = execution_md.read_text(encoding="utf-8")
            self.assertEqual(1, task_text.count("## Stage and Dependency Overview"))
            self.assertIn("new[New]", task_text)
            self.assertNotIn("old[Old]", task_text)
            self.assertIn("title Existing", execution_text)
            self.assertNotIn("title Replacement", execution_text)

    def test_flowchart_injection_collapses_preexisting_duplicate_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tasks_md = Path(directory) / "04_tasks.md"
            old = "## Stage and Dependency Overview\n\n```mermaid\nflowchart TD\n    old[Old]\n```"
            tasks_md.write_text(
                f"# Tasks\n\n{old}\n\nPreserve this text.\n\n{old}\n\n- [ ] 1. Task\n",
                encoding="utf-8",
            )

            render_gantt.inject_flowchart_into_tasks_md(
                tasks_md,
                "```mermaid\nflowchart TD\n    new[New]\n```",
            )

            content = tasks_md.read_text(encoding="utf-8")
            self.assertEqual(1, content.count("## Stage and Dependency Overview"))
            self.assertEqual(1, content.count("flowchart TD"))
            self.assertIn("Preserve this text.", content)
            self.assertIn("- [ ] 1. Task", content)

    def test_flowchart_color_coding_standards(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "Done Task", "stage": 1, "depends_on": [], "checked": True},
                {"id": "1.2", "title": "In Progress Task", "stage": 1, "depends_on": [], "checked": False},
                {"id": "1.3", "title": "Failed Task", "stage": 1, "depends_on": [], "checked": False},
                {"id": "1.4", "title": "Pending Task", "stage": 1, "depends_on": ["1.1"], "checked": False},
            ]
        }
        diagram = render_gantt.build_flowchart_from_tasks_data(
            tasks_data,
            feature_slug="demo",
            active_task_ids=["1.2"],
            failed_task_ids=["1.3"]
        )
        self.assertIn("flowchart TD", diagram)
        self.assertIn("classDef pending fill:#f1f5f9,stroke:#94a3b8", diagram)
        self.assertIn("classDef failed fill:#fee2e2,stroke:#ef4444", diagram)
        self.assertIn("classDef in_progress fill:#fef3c7,stroke:#f59e0b", diagram)
        self.assertIn("classDef done fill:#dcfce7,stroke:#22c55e", diagram)
        self.assertIn("class n_1_1 done", diagram)
        self.assertIn("class n_1_2 in_progress", diagram)
        self.assertIn("class n_1_3 failed", diagram)
        self.assertIn("class n_1_4 pending", diagram)

    def test_flowchart_uses_elk_renderer(self) -> None:
        tasks_data = {"tasks": [{"id": "1.1", "title": "T", "stage": 1, "depends_on": [], "checked": False}]}
        diagram = render_gantt.build_flowchart_from_tasks_data(tasks_data)
        self.assertIn("%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%", diagram)
        self.assertIn("flowchart TD", diagram)

    def test_flowchart_title_over_limit_raises_instead_of_truncating(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "X" * 81, "stage": 1, "depends_on": [], "checked": False},
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            render_gantt.build_flowchart_from_tasks_data(tasks_data)
        self.assertIn("Task 1.1 title", str(ctx.exception))
        self.assertIn("81 chars", str(ctx.exception))

    def test_flowchart_title_at_limit_does_not_raise(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "X" * 80, "stage": 1, "depends_on": [], "checked": False},
            ]
        }
        diagram = render_gantt.build_flowchart_from_tasks_data(tasks_data)
        self.assertIn("X" * 80, diagram)

    def test_embedded_sidecar_gantt_ir_is_authoritative(self) -> None:
        embedded = {
            "diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD",
            "sections": [{"name": "Canonical", "bars": [{
                "id": "canonical", "label": "From sidecar", "start": "2026-08-10",
                "end": "2026-08-11", "tags": ["done"],
            }]}],
        }
        diagram, returned = render_gantt.build_gantt_from_execution_data({
            "gantt": embedded,
            "task_attempts": [{"task": "ignored", "outcome": "failed"}],
        })
        self.assertIs(returned, embedded)
        self.assertIn("From sidecar", diagram)
        self.assertNotIn("ignored", diagram)

    def test_kanban_board_groups_by_status_and_omits_empty_columns(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "Done Task", "stage": 1, "depends_on": [], "checked": True},
                {"id": "1.2", "title": "In Progress Task", "stage": 1, "depends_on": [], "checked": False},
                {"id": "1.3", "title": "Failed Task", "stage": 1, "depends_on": [], "checked": False},
                {"id": "1.4", "title": "Pending Task", "stage": 1, "depends_on": ["1.1"], "checked": False},
            ]
        }
        diagram = render_gantt.build_kanban_board_from_tasks_data(
            tasks_data,
            active_task_ids=["1.2"],
            failed_task_ids=["1.3"],
        )
        self.assertTrue(diagram.startswith("```mermaid\nkanban\n"))
        self.assertTrue(diagram.endswith("```"))
        self.assertIn("pending[Pending]", diagram)
        self.assertIn("in_progress[In Progress]", diagram)
        self.assertIn("failed[Failed]", diagram)
        self.assertIn("done[Done]", diagram)
        self.assertIn("kanban_1_4[⚪ 1.4: Pending Task]", diagram)
        self.assertIn("kanban_1_2[🟠 1.2: In Progress Task]", diagram)
        self.assertIn("kanban_1_3[🔴 1.3: Failed Task]", diagram)
        self.assertIn("kanban_1_1[🟢 1.1: Done Task]", diagram)
        # No per-card `style`/`classDef` lines: render-validation showed `style <id> fill:...` is
        # misparsed as a bogus extra kanban column, and `:::class` is a parse error.
        self.assertNotIn("style ", diagram)
        self.assertNotIn(":::", diagram)

    def test_kanban_board_omits_column_with_no_tasks_in_that_state(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "Only Task", "stage": 1, "depends_on": [], "checked": True},
            ]
        }
        diagram = render_gantt.build_kanban_board_from_tasks_data(tasks_data)
        self.assertIn("done[Done]", diagram)
        self.assertNotIn("pending[Pending]", diagram)
        self.assertNotIn("in_progress[In Progress]", diagram)
        self.assertNotIn("failed[Failed]", diagram)

    def test_kanban_board_sanitizes_reserved_characters_in_labels(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": 'Bad [Title] @{x} "quote"', "stage": 1, "depends_on": [], "checked": False},
            ]
        }
        diagram = render_gantt.build_kanban_board_from_tasks_data(tasks_data)
        self.assertNotIn("[Title]", diagram)
        self.assertNotIn("@{x}", diagram)
        self.assertIn("Bad Title", diagram)

    def test_kanban_title_over_limit_raises_instead_of_truncating(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "1.1", "title": "X" * 61, "stage": 1, "depends_on": [], "checked": False},
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            render_gantt.build_kanban_board_from_tasks_data(tasks_data)
        self.assertIn("Task 1.1 title", str(ctx.exception))
        self.assertIn("61 chars", str(ctx.exception))

    def test_flowchart_and_kanban_agree_on_task_status(self) -> None:
        tasks_data = {
            "tasks": [
                {"id": "2.1", "title": "Retry Task", "stage": 2, "depends_on": [], "checked": False},
            ]
        }
        flowchart = render_gantt.build_flowchart_from_tasks_data(
            tasks_data, active_task_ids=["2.1"], failed_task_ids=[]
        )
        kanban = render_gantt.build_kanban_board_from_tasks_data(
            tasks_data, active_task_ids=["2.1"], failed_task_ids=[]
        )
        self.assertIn("class n_2_1 in_progress", flowchart)
        self.assertIn("in_progress[In Progress]", kanban)
        self.assertIn("kanban_2_1", kanban)

    def test_inject_kanban_into_execution_md_places_before_gantt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exec_md = Path(directory) / "05_execution.md"
            exec_md.write_text(
                "# Execution\n\n## Execution Timing\n\n### Execution Gantt\n\n"
                "```mermaid\ngantt\n    title Existing\n```\n",
                encoding="utf-8",
            )
            kanban_diagram = "```mermaid\nkanban\n  done[Done]\n    t_kanban_1_1[1.1: Task]\n```"
            render_gantt.inject_kanban_into_execution_md(exec_md, kanban_diagram)

            content = exec_md.read_text(encoding="utf-8")
            self.assertEqual(1, content.count("### Task Board"))
            self.assertIn("title Existing", content)
            board_idx = content.index("### Task Board")
            gantt_idx = content.index("### Execution Gantt")
            self.assertLess(board_idx, gantt_idx)

    def test_inject_kanban_into_execution_md_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            exec_md = Path(directory) / "05_execution.md"
            exec_md.write_text(
                "# Execution\n\n## Execution Timing\n\n### Execution Gantt\n\n"
                "```mermaid\ngantt\n    title G\n```\n",
                encoding="utf-8",
            )
            old_board = "```mermaid\nkanban\n  pending[Pending]\n    t_kanban_1_1[1.1: Old]\n```"
            new_board = "```mermaid\nkanban\n  done[Done]\n    t_kanban_1_1[1.1: New]\n```"
            render_gantt.inject_kanban_into_execution_md(exec_md, old_board)
            render_gantt.inject_kanban_into_execution_md(exec_md, new_board)

            content = exec_md.read_text(encoding="utf-8")
            self.assertEqual(1, content.count("### Task Board"))
            self.assertIn("1.1: New", content)
            self.assertNotIn("1.1: Old", content)

    def test_write_generated_diagrams_injects_kanban_alongside_gantt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory)
            execution_md = spec_dir / "05_execution.md"
            render_gantt.write_generated_diagrams(
                spec_dir,
                "```mermaid\ngantt\n    title G\n```",
                "```mermaid\nflowchart TD\n    n[N]\n```",
                "```mermaid\nkanban\n  done[Done]\n    t_kanban_1_1[1.1: Task]\n```",
            )
            execution_text = execution_md.read_text(encoding="utf-8")
            self.assertIn("### Execution Gantt", execution_text)
            self.assertIn("### Task Board", execution_text)

    def test_write_generated_diagrams_flowchart_only_skips_kanban(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec_dir = Path(directory)
            tasks_md = spec_dir / "04_tasks.md"
            execution_md = spec_dir / "05_execution.md"
            execution_md.write_text(
                "# Execution\n\n### Execution Gantt\n\n```mermaid\ngantt\n    title Existing\n```\n",
                encoding="utf-8",
            )
            render_gantt.write_generated_diagrams(
                spec_dir,
                "```mermaid\ngantt\n    title Replacement\n```",
                "```mermaid\nflowchart TD\n    n[N]\n```",
                "```mermaid\nkanban\n  done[Done]\n    t_kanban_1_1[1.1: Task]\n```",
                flowchart_only=True,
            )
            execution_text = execution_md.read_text(encoding="utf-8")
            self.assertNotIn("### Task Board", execution_text)
            self.assertIn("title Existing", execution_text)
            self.assertTrue(tasks_md.is_file())

    def test_latest_attempt_drives_active_flowchart_state(self) -> None:
        data = {
            "task_attempts": [
                {"task": "3.1", "attempt": 1, "started_utc": "2026-08-10T12:00:00Z", "outcome": "failed"},
                {"task": "3.1", "attempt": 2, "started_utc": "2026-08-10T12:05:00Z", "outcome": "active"},
                {"task": "3.2", "attempt": 1, "started_utc": "2026-08-10T12:01:00Z", "outcome": "failed"},
            ]
        }
        active, failed = render_gantt.task_state_ids_from_execution_data(data)
        self.assertEqual(["3.1"], active)
        self.assertEqual(["3.2"], failed)


if __name__ == "__main__":
    unittest.main()
