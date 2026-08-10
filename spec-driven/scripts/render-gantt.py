#!/usr/bin/env python3
"""Deterministic Mermaid Gantt Chart Generator for Spec Execution Ledgers.

Reads `sidecars/05_execution.json` or `05_execution.md` timing intervals and deterministically
derives, formats, validates, and injects syntax-error-free Mermaid gantt charts into
`05_execution.md`. Handles 0-second tasks safely and color-tags bars by outcome.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


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
    lines = [
        "```mermaid",
        "gantt",
        f"    title {title}",
        f"    dateFormat {date_format}",
        f"    axisFormat {axis_format}"
    ]
    
    for section in sections:
        sec_name = section.get("name", "Execution Wave")
        lines.append(f"    section {sec_name}")
        for bar in section.get("bars", []):
            task_label = _sanitize_label(bar.get("label", "Task"))
            task_id = _sanitize_id(bar.get("id", "task"))
            start = bar.get("start")
            end = bar.get("end")
            tags = bar.get("tags", [])
            
            tag_prefix = ""
            if "crit" in tags:
                tag_prefix = "crit, "
            elif "done" in tags:
                tag_prefix = "done, "
            elif "active" in tags:
                tag_prefix = "active, "
                
            lines.append(f"    {task_label} : {tag_prefix}{task_id}, {start}, {end}")
            
    lines.append("```")
    return "\n".join(lines)


def build_gantt_from_execution_data(data: Dict[str, Any], feature_slug: str = "Feature") -> Tuple[str, Dict[str, Any]]:
    """Build Gantt IR and Mermaid diagram from execution sidecar payload.

    Safely computes start and end timestamps, protects against 0-second / inverted
    intervals by guaranteeing a minimum 1-second visual duration, and assigns outcome tags.

    :param data: Loaded dictionary from 05_execution.json.
    :param feature_slug: Feature name slug for the chart title.
    :return: Tuple of (mermaid_diagram_string, intermediate_representation_dict).
    """
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
            "id": f"{task_id}_att_{attempt.get('attempt', 1)}",
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
    
    diagram = render_mermaid_gantt(
        title=f"Spec Execution Timeline: {feature_slug}",
        sections=sections_list
    )
    
    gantt_ir = {
        "diagram": diagram,
        "target": "05_execution.md",
        "dateFormat": "YYYY-MM-DDTHH:mm:ss",
        "axisFormat": "%H:%M:%S",
        "sections": sections_list
    }
    
    return diagram, gantt_ir


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
    active_set = set(active_task_ids or [])
    failed_set = set(failed_task_ids or [])

    tasks = tasks_data.get("tasks", [])
    stages: Dict[int, List[Dict[str, Any]]] = {}
    for task in tasks:
        stage_num = int(task.get("stage") or 1)
        stages.setdefault(stage_num, []).append(task)

    lines = [
        "```mermaid",
        "flowchart TD",
    ]

    # Render Subgraphs per Stage
    for s_num in sorted(stages.keys()):
        s_tasks = stages[s_num]
        lines.append(f'    subgraph Stage_{s_num}["Stage {s_num}"]')
        for t in s_tasks:
            t_id = t["id"]
            node_id = _sanitize_id(t_id)
            title = _sanitize_label(t.get("title", "Task"))
            lines.append(f'        {node_id}["{t_id}: {title}"]')
        lines.append("    end")

    # Render Dependency Edges
    for task in tasks:
        t_id = task["id"]
        target_node = _sanitize_id(t_id)
        for dep in task.get("depends_on", []):
            if dep and dep != "none":
                source_node = _sanitize_id(dep)
                lines.append(f"    {source_node} --> {target_node}")

    # Color classification
    done_nodes: List[str] = []
    in_prog_nodes: List[str] = []
    failed_nodes: List[str] = []
    pending_nodes: List[str] = []

    for task in tasks:
        t_id = task["id"]
        node_id = _sanitize_id(t_id)
        if t_id in failed_set:
            failed_nodes.append(node_id)
        elif t_id in active_set:
            in_prog_nodes.append(node_id)
        elif task.get("checked"):
            done_nodes.append(node_id)
        else:
            pending_nodes.append(node_id)

    # Class Definitions (Grey = Pending, Red = Failed, Amber = In Progress, Green = Done)
    lines.append("")
    lines.append("    classDef pending fill:#f1f5f9,stroke:#94a3b8,stroke-width:1.5px,color:#334155;")
    lines.append("    classDef failed fill:#fee2e2,stroke:#ef4444,stroke-width:2px,color:#991b1b;")
    lines.append("    classDef in_progress fill:#fef3c7,stroke:#f59e0b,stroke-width:2px,color:#92400e;")
    lines.append("    classDef done fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px,color:#14532d;")
    lines.append("")

    if done_nodes:
        lines.append(f"    class {','.join(done_nodes)} done;")
    if in_prog_nodes:
        lines.append(f"    class {','.join(in_prog_nodes)} in_progress;")
    if failed_nodes:
        lines.append(f"    class {','.join(failed_nodes)} failed;")
    if pending_nodes:
        lines.append(f"    class {','.join(pending_nodes)} pending;")

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
    heading = "## Stage and Dependency Overview"

    if heading in content:
        pattern = r"(?ms)##\s+Stage and Dependency Overview\s*\n\s*```mermaid\s*\nflowchart\b.*?```"
        replacement = f"## Stage and Dependency Overview\n\n{diagram}"
        updated = re.sub(pattern, replacement, content)
        if updated != content:
            tasks_md_path.write_text(updated, encoding="utf-8")
            return

    # Insert under spec navigation or top heading
    nav_end = content.find("<!-- spec-nav:end -->")
    if nav_end != -1:
        insert_idx = nav_end + len("<!-- spec-nav:end -->")
        updated = content[:insert_idx] + f"\n\n## Stage and Dependency Overview\n\n{diagram}\n" + content[insert_idx:]
    else:
        first_stage = content.find("## Stage 1")
        if first_stage != -1:
            updated = content[:first_stage] + f"## Stage and Dependency Overview\n\n{diagram}\n\n" + content[first_stage:]
        else:
            updated = content + f"\n\n## Stage and Dependency Overview\n\n{diagram}\n"

    tasks_md_path.write_text(updated, encoding="utf-8")


def write_generated_diagrams(
    spec_dir: Path,
    gantt_diagram: str,
    flowchart_diagram: str,
    *,
    flowchart_only: bool = False,
) -> None:
    """Replace generated diagram sections without creating duplicate Markdown blocks."""
    if not flowchart_only:
        exec_md = spec_dir / "05_execution.md"
        inject_gantt_into_execution_md(exec_md, gantt_diagram)
        print(f"Injected validated Mermaid Gantt into {exec_md}")

    if flowchart_diagram:
        tasks_md = spec_dir / "04_tasks.md"
        inject_flowchart_into_tasks_md(tasks_md, flowchart_diagram)
        print(f"Injected color-coded Mermaid Flowchart into {tasks_md}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic Mermaid Gantt & Flowchart Generator")
    parser.add_argument("spec_dir", type=Path, help="Path to spec directory")
    parser.add_argument("--write", action="store_true", help="Replace generated diagram sections in Markdown")
    parser.add_argument(
        "--flowchart-only",
        action="store_true",
        help="Output only the task flowchart; with --write, leave the execution Gantt unchanged",
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
    if tasks_json_path.is_file():
        tasks_data = json.loads(tasks_json_path.read_text(encoding="utf-8"))
        active_task_ids, failed_task_ids = task_state_ids_from_execution_data(data)
        flowchart_diagram = build_flowchart_from_tasks_data(
            tasks_data,
            feature_slug=args.spec_dir.name,
            active_task_ids=active_task_ids,
            failed_task_ids=failed_task_ids,
        )
    
    if args.write:
        write_generated_diagrams(
            args.spec_dir,
            gantt_diagram,
            flowchart_diagram,
            flowchart_only=args.flowchart_only,
        )
    elif args.flowchart_only:
        print(flowchart_diagram)
    else:
        print(gantt_diagram)
        if flowchart_diagram:
            print("\n" + flowchart_diagram)


if __name__ == "__main__":
    main()
