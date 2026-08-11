#!/usr/bin/env python3
"""Deterministic Mermaid Gantt Chart Generator for Spec Execution Ledgers.

Reads `sidecars/05_execution.json` or `05_execution.md` timing intervals and deterministically
derives, formats, validates, and injects syntax-error-free Mermaid gantt charts into
`05_execution.md`. Handles 0-second tasks safely and color-tags bars by outcome.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_MERMAID_RENDER = None


def _load_mermaid_render():
    """Load the dependent Mermaid skill's deterministic JSON IR renderer once."""
    global _MERMAID_RENDER
    if _MERMAID_RENDER is not None:
        return _MERMAID_RENDER
    candidates: List[Path] = []
    if os.environ.get("MERMAID_SKILL_DIR"):
        candidates.append(Path(os.environ["MERMAID_SKILL_DIR"]))
    candidates.extend([
        Path.home() / "GitRepos" / "mermaid-skill" / "mermaid",
        Path.home() / ".agents" / "skills" / "mermaid",
        Path.home() / ".claude" / "skills" / "mermaid",
        Path.home() / ".codex" / "skills" / "mermaid",
    ])
    for root in candidates:
        script = root / "scripts" / "render.py"
        if not script.is_file():
            continue
        spec = importlib.util.spec_from_file_location("dependent_mermaid_ir_renderer", script)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MERMAID_RENDER = module.render
        return _MERMAID_RENDER
    raise RuntimeError(
        "Mermaid skill not found; set MERMAID_SKILL_DIR to the installable mermaid skill directory"
    )


def render_mermaid_ir(ir: Dict[str, Any]) -> str:
    """Compile JSON IR through the Mermaid skill and return one fenced Markdown block."""
    source = _load_mermaid_render()(ir).rstrip()
    return f"```mermaid\n{source}\n```"


def _sanitize_label(text: str) -> str:
    """Sanitize task title for Mermaid gantt labels by stripping prohibited characters.

    :param text: Raw task title string.
    :return: Cleaned and truncated string safe for Mermaid gantt label rendering.
    """
    clean = re.sub(r"[:#;\"'`\n]", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:40] if len(clean) > 40 else clean


def _sanitize_id(text: str) -> str:
    """Convert dotted or arbitrary task identifiers to valid Mermaid task IDs.

    :param text: Task ID string (e.g. '1.1_att_1').
    :return: Sanitized identifier string prefixed with 't_'.
    """
    return "t_" + re.sub(r"[^a-zA-Z0-9_]", "_", text)


def render_mermaid_gantt(
    title: str,
    sections: List[Dict[str, Any]],
    date_format: str = "YYYY-MM-DDTHH:mm:ss",
    axis_format: str = "%H:%M:%S"
) -> str:
    """Deterministically construct a valid Mermaid Gantt diagram.

    :param title: Header title of the Gantt chart.
    :param sections: List of section definitions containing stage names and bars.
    :param date_format: Mermaid date input parsing format.
    :param axis_format: Mermaid time axis rendering format.
    :return: Complete fenced ```mermaid markdown code block.
    """
    normalized_sections = []
    for section in sections:
        normalized_sections.append({
            "name": _sanitize_label(section.get("name", "Execution Wave")),
            "bars": [{
                **bar,
                "id": _sanitize_id(str(bar.get("id", "task"))),
                "label": _sanitize_label(str(bar.get("label", "Task"))),
            } for bar in section.get("bars", [])],
        })
    return render_mermaid_ir({
        "diagram": "timeline",
        "target": "gantt",
        "title": title,
        "dateFormat": date_format,
        "axisFormat": axis_format,
        "sections": normalized_sections,
    })


def build_gantt_from_execution_data(data: Dict[str, Any], feature_slug: str = "Feature") -> Tuple[str, Dict[str, Any]]:
    """Build Gantt IR and Mermaid diagram from execution sidecar payload.

    Safely computes start and end timestamps, protects against 0-second / inverted
    intervals by guaranteeing a minimum 1-second visual duration, and assigns outcome tags.

    :param data: Loaded dictionary from 05_execution.json.
    :param feature_slug: Feature name slug for the chart title.
    :return: Tuple of (mermaid_diagram_string, intermediate_representation_dict).
    """
    embedded = data.get("gantt")
    if isinstance(embedded, dict):
        return render_mermaid_ir(embedded), embedded

    sections_by_stage: Dict[str, List[Dict[str, Any]]] = {}
    
    task_attempts = data.get("task_attempts", [])
    for attempt in task_attempts:
        stage = attempt.get("stage_wave", "Stage 1")
        task_id = attempt.get("task", "1.0")
        outcome = attempt.get("outcome", "verified")
        
        start_str = attempt.get("started_utc", "")
        stop_str = attempt.get("stopped_utc", "")
        
        # Parse ISO timestamps. Active attempts intentionally carry pending stop/elapsed values;
        # render them as a deterministic one-second marker until the ledger closes the interval.
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if outcome == "active" and stop_str == "pending":
                stop_dt = start_dt + timedelta(seconds=1)
            else:
                stop_dt = datetime.fromisoformat(stop_str.replace("Z", "+00:00"))
        except Exception:
            # Fallback to synthetic non-zero timestamps if format missing
            start_dt = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
            elapsed = attempt.get("elapsed_seconds", 60)
            stop_dt = start_dt + timedelta(seconds=int(elapsed) if str(elapsed).isdigit() else 60)
            
        # Handle 0-second tasks safely (ensure end is at least start + 1s for Mermaid rendering)
        if stop_dt <= start_dt:
            stop_dt = start_dt + timedelta(seconds=1)
            
        fmt = "%Y-%m-%dT%H:%M:%S"
        start_fmt = start_dt.strftime(fmt)
        stop_fmt = stop_dt.strftime(fmt)
        
        tags = []
        if outcome in ("verified", "complete", "pass"):
            tags.append("done")
        elif outcome in ("failed", "blocked", "fail"):
            tags.append("crit")
        elif outcome == "active":
            tags.append("active")
            
        bar = {
            "id": _sanitize_id(f"{task_id}_att_{attempt.get('attempt', 1)}"),
            "label": f"Task {task_id}",
            "start": start_fmt,
            "end": stop_fmt,
            "tags": tags
        }
        
        sections_by_stage.setdefault(stage, []).append(bar)
        
    sections_list = [
        {"name": stage, "bars": bars}
        for stage, bars in sections_by_stage.items()
    ]
    
    gantt_ir = {
        "diagram": "timeline",
        "target": "gantt",
        "title": f"Spec Execution Timeline: {feature_slug}",
        "dateFormat": "YYYY-MM-DDTHH:mm:ss",
        "axisFormat": "%H:%M:%S",
        "sections": sections_list
    }

    return render_mermaid_ir(gantt_ir), gantt_ir


def derive_task_statuses(
    tasks: List[Dict[str, Any]],
    active_task_ids: Optional[List[str]] = None,
    failed_task_ids: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Derive each task's single-source-of-truth status: failed, in_progress, done, or pending.

    Shared by the Stage and Dependency Overview flowchart and the execution Task Board kanban so
    both derived views always agree on a task's state.

    :param tasks: Task dicts from 04_tasks.json's `tasks` array (each needs `id`/`checked`).
    :param active_task_ids: Task IDs whose latest recorded attempt is still active.
    :param failed_task_ids: Task IDs whose latest recorded attempt failed.
    :return: Mapping of task ID to status string.
    """
    active_set = set(active_task_ids or [])
    failed_set = set(failed_task_ids or [])
    statuses: Dict[str, str] = {}
    for task in tasks:
        t_id = task["id"]
        if t_id in failed_set:
            statuses[t_id] = "failed"
        elif t_id in active_set:
            statuses[t_id] = "in_progress"
        elif task.get("checked"):
            statuses[t_id] = "done"
        else:
            statuses[t_id] = "pending"
    return statuses


def build_flowchart_from_tasks_data(
    tasks_data: Dict[str, Any],
    feature_slug: str = "Feature",
    active_task_ids: Optional[List[str]] = None,
    failed_task_ids: Optional[List[str]] = None,
) -> str:
    """Build a deterministic color-coded Mermaid flowchart for Stage and Dependency Overview.

    Color coding standard:
    - Grey (pending): Tasks not yet started or queued.
    - Red (failed): Tasks that failed verification or encountered critical defects.
    - Amber (in_progress): Tasks currently executing or in active waves.
    - Green (done): Verified completed tasks with checked status.

    :param tasks_data: Dictionary loaded from 04_tasks.json sidecar.
    :param feature_slug: Name slug for the diagram title.
    :param active_task_ids: Optional list of task IDs currently in progress.
    :param failed_task_ids: Optional list of task IDs that failed.
    :return: Complete fenced ```mermaid flowchart block.
    """
    tasks = tasks_data.get("tasks", [])
    statuses = derive_task_statuses(tasks, active_task_ids, failed_task_ids)
    stages: Dict[int, List[Dict[str, Any]]] = {}
    for task in tasks:
        stage_num = int(task.get("stage") or 1)
        stages.setdefault(stage_num, []).append(task)

    nodes: List[Dict[str, Any]] = []
    for task in tasks:
        t_id = task["id"]
        nodes.append({
            "id": t_id,
            "label": f"{t_id}: {_sanitize_label(task.get('title', 'Task'))}",
            "kind": "process",
            "group": f"stage-{int(task.get('stage') or 1)}",
            "status": statuses[t_id],
        })
    edges = [
        {"from": dep, "to": task["id"], "kind": "dependency"}
        for task in tasks for dep in task.get("depends_on", []) if dep and dep != "none"
    ]
    groups = [
        {"id": f"stage-{stage}", "label": f"Stage {stage}"}
        for stage in sorted(stages)
    ]
    return render_mermaid_ir({
        "diagram": "graph", "target": "flowchart", "direction": "TD",
        "groups": groups, "nodes": nodes, "edges": edges,
    })


_KANBAN_COLUMNS: List[Tuple[str, str]] = [
    ("pending", "Pending"),
    ("in_progress", "In Progress"),
    ("failed", "Failed"),
    ("done", "Done"),
]

# Mermaid's kanban diagram has no confirmed, stable per-card fill mechanism: `style <id> fill:...`
# is parsed as a bogus extra column (render-validated and rejected), and `:::class`/`classDef` is a
# parse error (kanban has no CLASS token). A colored-circle emoji prefix is the only render-validated
# way to carry the flowchart's pending/failed/in_progress/done color semantics onto kanban cards.
_STATUS_EMOJI: Dict[str, str] = {
    "pending": "⚪",
    "failed": "🔴",
    "in_progress": "🟠",
    "done": "🟢",
}


def _sanitize_kanban_label(text: str) -> str:
    """Sanitize a task title for a Mermaid kanban card, stripping chars the `[...]`/`@{...}` syntax reserves.

    :param text: Raw task title string.
    :return: Cleaned and truncated string safe for Mermaid kanban card labels.
    """
    clean = re.sub(r"[\[\]{}@:#;\"'`\n]", " ", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:60] if len(clean) > 60 else clean


def build_kanban_board_from_tasks_data(
    tasks_data: Dict[str, Any],
    active_task_ids: Optional[List[str]] = None,
    failed_task_ids: Optional[List[str]] = None,
) -> str:
    """Build a deterministic Mermaid kanban Task Board, hand-authored since the shared `mermaid`
    skill's IR renderer has no `kanban` diagram family yet (see `references/diagrams.md`).

    Reuses the same status derivation as the Stage and Dependency Overview flowchart so the two
    execution-time views of task state never disagree, and prefixes each card with the colored
    circle matching the flowchart's pending/failed/in_progress/done palette (kanban has no
    render-validated per-card fill/stroke mechanism to carry that color literally). Columns with
    no tasks in that state are omitted rather than emitted empty.

    :param tasks_data: Dictionary loaded from 04_tasks.json sidecar.
    :param active_task_ids: Optional list of task IDs currently in progress.
    :param failed_task_ids: Optional list of task IDs that failed.
    :return: Complete fenced ```mermaid kanban block.
    """
    tasks = tasks_data.get("tasks", [])
    statuses = derive_task_statuses(tasks, active_task_ids, failed_task_ids)

    cards_by_status: Dict[str, List[str]] = {status_id: [] for status_id, _ in _KANBAN_COLUMNS}
    for task in tasks:
        t_id = task["id"]
        card_id = _sanitize_id(f"kanban_{t_id}")
        status = statuses[t_id]
        label = f"{_STATUS_EMOJI[status]} {t_id}: {_sanitize_kanban_label(task.get('title', 'Task'))}"
        cards_by_status[status].append(f"{card_id}[{label}]")

    lines = ["```mermaid", "kanban"]
    for status_id, column_title in _KANBAN_COLUMNS:
        cards = cards_by_status[status_id]
        if not cards:
            continue
        lines.append(f"  {status_id}[{column_title}]")
        for card in cards:
            lines.append(f"    {card}")
    lines.append("```")
    return "\n".join(lines)


def task_state_ids_from_execution_data(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Return active/failed task IDs from each task's latest recorded attempt."""
    latest: Dict[str, Dict[str, Any]] = {}
    for attempt in data.get("task_attempts", []):
        task_id = str(attempt.get("task", "")).strip()
        if not task_id:
            continue
        current = latest.get(task_id)
        order = (int(attempt.get("attempt", 0)), str(attempt.get("started_utc", "")))
        current_order = (
            int(current.get("attempt", 0)), str(current.get("started_utc", ""))
        ) if current else (-1, "")
        if order >= current_order:
            latest[task_id] = attempt
    active = sorted(task_id for task_id, row in latest.items() if row.get("outcome") == "active")
    failed = sorted(task_id for task_id, row in latest.items() if row.get("outcome") == "failed")
    return active, failed


def inject_gantt_into_execution_md(execution_md_path: Path, diagram: str) -> None:
    """Inject or replace ### Execution Gantt in 05_execution.md idempotently without duplication.

    :param execution_md_path: Path to the 05_execution.md Markdown file.
    :param diagram: Valid Mermaid fenced markdown string to inject.
    """
    if not execution_md_path.is_file():
        content = f"# Execution\n\n## Execution Timing\n\n### Execution Gantt\n\n{diagram}\n"
        execution_md_path.write_text(content, encoding="utf-8")
        return

    content = execution_md_path.read_text(encoding="utf-8")

    # Strip any existing ### Execution Gantt sections completely to avoid duplicates
    cleaned = re.sub(r"(?ms)\n*###\s+Execution Gantt\s*\n\s*```mermaid\s*\ngantt\b.*?```\n*", "\n\n", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    # Append single ### Execution Gantt under ## Execution Timing or at the end
    if "## Execution Timing" in cleaned:
        # Place at the bottom of the document or after tables
        updated = cleaned + f"\n\n### Execution Gantt\n\n{diagram}\n"
    else:
        updated = cleaned + f"\n\n## Execution Timing\n\n### Execution Gantt\n\n{diagram}\n"

    execution_md_path.write_text(updated, encoding="utf-8")


def inject_kanban_into_execution_md(execution_md_path: Path, diagram: str) -> None:
    """Inject or replace ### Task Board in 05_execution.md idempotently without duplication.

    Places the Task Board immediately after ### Execution Gantt under ## Execution Timing,
    assuming the Gantt has already been injected (or the file already existed) in the same pass.

    :param execution_md_path: Path to the 05_execution.md Markdown file.
    :param diagram: Valid Mermaid fenced kanban markdown string to inject.
    """
    if not execution_md_path.is_file():
        content = f"# Execution\n\n## Execution Timing\n\n### Task Board\n\n{diagram}\n"
        execution_md_path.write_text(content, encoding="utf-8")
        return

    content = execution_md_path.read_text(encoding="utf-8")

    # Strip any existing ### Task Board sections completely to avoid duplicates
    cleaned = re.sub(r"(?ms)\n*###\s+Task Board\s*\n\s*```mermaid\s*\nkanban\b.*?```\n*", "\n\n", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    gantt_match = re.search(r"(?ms)###\s+Execution Gantt\s*\n\s*```mermaid\s*\ngantt\b.*?```", cleaned)
    if gantt_match:
        insert_idx = gantt_match.end()
        updated = cleaned[:insert_idx] + f"\n\n### Task Board\n\n{diagram}\n" + cleaned[insert_idx:].lstrip("\n")
    elif "## Execution Timing" in cleaned:
        updated = cleaned + f"\n\n### Task Board\n\n{diagram}\n"
    else:
        updated = cleaned + f"\n\n## Execution Timing\n\n### Task Board\n\n{diagram}\n"

    execution_md_path.write_text(updated, encoding="utf-8")


def inject_flowchart_into_tasks_md(tasks_md_path: Path, diagram: str) -> None:
    """Inject or replace ## Stage and Dependency Overview in 04_tasks.md.

    :param tasks_md_path: Path to the 04_tasks.md Markdown file.
    :param diagram: Valid Mermaid fenced flowchart markdown string.
    """
    if not tasks_md_path.is_file():
        content = f"# Tasks\n\n## Stage and Dependency Overview\n\n{diagram}\n"
        tasks_md_path.write_text(content, encoding="utf-8")
        return

    content = tasks_md_path.read_text(encoding="utf-8")
    pattern = r"(?ms)^##\s+Stage and Dependency Overview\s*\n\s*```mermaid\s*\nflowchart\b.*?```\s*"
    # Remove every generated copy first. Replacing each match would preserve the duplicate count.
    cleaned = re.sub(pattern, "", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
    replacement = f"## Stage and Dependency Overview\n\n{diagram}\n"

    # Insert one canonical section under spec navigation or the document title.
    nav_end = cleaned.find("<!-- spec-nav:end -->")
    if nav_end != -1:
        insert_idx = nav_end + len("<!-- spec-nav:end -->")
        updated = cleaned[:insert_idx] + f"\n\n{replacement}" + cleaned[insert_idx:].lstrip("\n")
    else:
        title = re.match(r"^#\s+.*\n", cleaned)
        if title:
            insert_idx = title.end()
            updated = cleaned[:insert_idx] + f"\n{replacement}\n" + cleaned[insert_idx:].lstrip("\n")
        else:
            updated = replacement + "\n" + cleaned

    tasks_md_path.write_text(updated, encoding="utf-8")


def write_generated_diagrams(
    spec_dir: Path,
    gantt_diagram: str,
    flowchart_diagram: str,
    kanban_diagram: str = "",
    *,
    flowchart_only: bool = False,
) -> None:
    """Replace generated diagram sections without creating duplicate Markdown blocks."""
    if not flowchart_only:
        exec_md = spec_dir / "05_execution.md"
        inject_gantt_into_execution_md(exec_md, gantt_diagram)
        print(f"Injected validated Mermaid Gantt into {exec_md}")

        if kanban_diagram:
            inject_kanban_into_execution_md(exec_md, kanban_diagram)
            print(f"Injected Mermaid Task Board kanban into {exec_md}")

    if flowchart_diagram:
        tasks_md = spec_dir / "04_tasks.md"
        inject_flowchart_into_tasks_md(tasks_md, flowchart_diagram)
        print(f"Injected color-coded Mermaid Flowchart into {tasks_md}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Mermaid Gantt, Flowchart & Kanban Generator")
    parser.add_argument("spec_dir", type=Path, help="Path to spec directory")
    parser.add_argument("--write", action="store_true", help="Replace generated diagram sections in Markdown")
    parser.add_argument(
        "--flowchart-only",
        action="store_true",
        help="Output only the task flowchart; with --write, leave the Execution Gantt and Task Board unchanged",
    )
    args = parser.parse_args()

    sidecars_dir = args.spec_dir / "sidecars"
    exec_json_path = sidecars_dir / "05_execution.json" if sidecars_dir.is_dir() else args.spec_dir / "05_execution.json"
    tasks_json_path = sidecars_dir / "04_tasks.json" if sidecars_dir.is_dir() else args.spec_dir / "04_tasks.json"

    if not exec_json_path.is_file():
        data = {
            "runs": [{
                "run_id": "run-initial",
                "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stopped_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "elapsed_seconds": 0,
                "outcome": "active"
            }],
            "task_attempts": []
        }
    else:
        data = json.loads(exec_json_path.read_text(encoding="utf-8"))

    gantt_diagram, _ = build_gantt_from_execution_data(data, feature_slug=args.spec_dir.name)

    flowchart_diagram = ""
    kanban_diagram = ""
    if tasks_json_path.is_file():
        tasks_data = json.loads(tasks_json_path.read_text(encoding="utf-8"))
        active_task_ids, failed_task_ids = task_state_ids_from_execution_data(data)
        flowchart_diagram = build_flowchart_from_tasks_data(
            tasks_data,
            feature_slug=args.spec_dir.name,
            active_task_ids=active_task_ids,
            failed_task_ids=failed_task_ids,
        )
        kanban_diagram = build_kanban_board_from_tasks_data(
            tasks_data,
            active_task_ids=active_task_ids,
            failed_task_ids=failed_task_ids,
        )

    if args.write:
        write_generated_diagrams(
            args.spec_dir,
            gantt_diagram,
            flowchart_diagram,
            kanban_diagram,
            flowchart_only=args.flowchart_only,
        )
    elif args.flowchart_only:
        print(flowchart_diagram)
    else:
        print(gantt_diagram)
        if kanban_diagram:
            print("\n" + kanban_diagram)
        if flowchart_diagram:
            print("\n" + flowchart_diagram)


if __name__ == "__main__":
    main()
