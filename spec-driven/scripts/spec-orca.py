#!/usr/bin/env python3
"""Synchronize a spec task DAG with Orca and launch supervised workers.

The bridge treats Orca's JSON receipts as authoritative.  It never fabricates
Run, Task, Gate, Dispatch, terminal, or worktree identifiers.  ``sync`` creates
or binds the Run and mirrors the task DAG.  ``dispatch-ready`` previews ready
workers by default and launches them only with ``--apply``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
AGENT_PROFILES_PATH = SKILL_DIR / "contracts" / "agent_profiles.json"


class OrcaCommandError(RuntimeError):
    """Raised when an Orca mutation or JSON query does not return a usable receipt."""


def load_agent_profiles() -> dict[str, Any]:
    """Load the canonical, version-controlled agent launch profiles."""
    try:
        data = json.loads(AGENT_PROFILES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot load agent profiles at {AGENT_PROFILES_PATH}: {exc}") from exc
    if not isinstance(data.get("agents"), dict):
        raise RuntimeError(f"invalid agent profiles at {AGENT_PROFILES_PATH}: missing agents map")
    return data


def find_tasks_sidecar(spec_dir: Path) -> Path:
    """Return the generated task sidecar, preferring the organized sidecars directory."""
    for candidate in (spec_dir / "sidecars" / "04_tasks.json", spec_dir / "04_tasks.json"):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"could not find 04_tasks.json in {spec_dir}/sidecars or {spec_dir}")


def run_state_path(spec_dir: Path) -> Path:
    """Return the project-local Orca bridge state path."""
    return spec_dir / "sidecars" / "orca_run.json"


def load_tasks(spec_dir: Path) -> dict[str, Any]:
    """Load and minimally validate the generated task sidecar."""
    data = json.loads(find_tasks_sidecar(spec_dir).read_text(encoding="utf-8"))
    if not isinstance(data.get("tasks"), list) or not isinstance(data.get("concurrency"), dict):
        raise RuntimeError("04_tasks.json is missing tasks or concurrency data; run spec-check.py --emit-json")
    return data


def load_run_state(spec_dir: Path) -> dict[str, Any]:
    """Load the persisted Orca receipt map."""
    path = run_state_path(spec_dir)
    if not path.is_file():
        raise FileNotFoundError(f"no {path}; run spec-orca.py sync first")
    return json.loads(path.read_text(encoding="utf-8"))


def save_run_state(spec_dir: Path, state: dict[str, Any]) -> None:
    """Persist receipt-derived bridge state after each successful mutation."""
    path = run_state_path(spec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_orca_cmd(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run the installed Orca CLI without invoking a shell."""
    orca_bin = shutil.which("orca") or shutil.which("orca-ide")
    if not orca_bin:
        return 127, "", "orca CLI is not on PATH"
    try:
        result = subprocess.run(
            [orca_bin, *args], capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _parse_json_output(output: str) -> Any:
    """Parse one JSON receipt, tolerating non-JSON diagnostic lines before it."""
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        starts = [position for token in ("{", "[") if (position := output.find(token)) >= 0]
        if not starts:
            raise
        return json.loads(output[min(starts) :])


def run_orca_json(args: list[str], timeout: int = 60) -> Any:
    """Run Orca with ``--json`` and return its authoritative result object."""
    command = [*args, "--json"]
    code, stdout, stderr = run_orca_cmd(command, timeout=timeout)
    if code != 0:
        detail = stdout or stderr or "no diagnostic output"
        raise OrcaCommandError(f"orca {' '.join(args)} failed ({code}): {detail}")
    try:
        receipt = _parse_json_output(stdout)
    except json.JSONDecodeError as exc:
        raise OrcaCommandError(f"orca {' '.join(args)} returned invalid JSON: {stdout!r}") from exc
    if isinstance(receipt, dict) and receipt.get("ok") is False:
        raise OrcaCommandError(f"orca {' '.join(args)} rejected the request: {json.dumps(receipt)}")
    return receipt


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def receipt_value(receipt: Any, *keys: str) -> str:
    """Find the first non-empty string value for a known receipt key."""
    mappings = list(_walk_dicts(receipt))
    for key in keys:
        for mapping in mappings:
            value = mapping.get(key)
            if isinstance(value, str) and value:
                return value
    raise OrcaCommandError(f"Orca receipt did not contain any of {keys}: {json.dumps(receipt)}")


def _new_state(run_id: str, feature_slug: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "feature_slug": feature_slug,
        "status": "active",
        "coordinator_handle": "coordinator",
        "stage_tasks_map": {},
        "tasks_map": {},
        "dispatches": [],
        "decision_gates": [],
    }


def _task_spec(task: dict[str, Any]) -> str:
    """Build the bounded worker prompt stored in Orca's authoritative Task spec."""
    values = {
        "Files": ", ".join(task.get("files", [])) or "none declared",
        "Dependencies": ", ".join(task.get("depends_on", [])) or "none",
        "Requirements": ", ".join(task.get("requirements", [])) or "none declared",
        "Interfaces": task.get("interfaces") or "none declared",
        "Dependency resolution": task.get("dependency_resolution") or "none",
        "Dependency delivery": task.get("dependency_delivery") or "none",
        "Delegation": task.get("delegation") or "unspecified",
        "Risk": task.get("risk") or "unspecified",
        "Documentation": task.get("documentation") or "none declared",
        "Verification": task.get("verification") or "none declared",
        "Resolved model": task.get("resolved_model") or "runtime default",
        "Reasoning level": task.get("reasoning_level") or "runtime default",
    }
    contract = "\n".join(f"{label}: {value}" for label, value in values.items())
    return (
        f"Implement bounded spec task {task['id']}: {task['title']}\n\n"
        f"{contract}\n\n"
        "Execution contract:\n"
        "- Read and obey the repository AGENTS.md and the cited spec requirements/design.\n"
        "- Stay within the declared files and interfaces; escalate before expanding scope.\n"
        "- Implement the task, run the exact verification, and report changed files plus evidence.\n"
        "- Do not check off the task or edit the execution ledger; the coordinator owns integration."
    )


def _bind_or_create_run(spec_dir: Path, requested_run: str | None, objective: str) -> dict[str, Any]:
    path = run_state_path(spec_dir)
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    if previous:
        previous_run = previous["run_id"]
        if requested_run and requested_run != previous_run:
            raise RuntimeError(
                f"{path} already tracks {previous_run}; remove or archive it before binding {requested_run}"
            )
        run_orca_json(["orchestration", "run-use", "--id", previous_run])
        return previous
    if requested_run:
        run_orca_json(["orchestration", "run-use", "--id", requested_run])
        return _new_state(requested_run, spec_dir.name)
    receipt = run_orca_json(["orchestration", "run-create", "--objective", objective])
    return _new_state(receipt_value(receipt, "runId", "run_id", "id"), spec_dir.name)


def sync_spec_to_orca(
    spec_dir: Path, run_id: str | None = None, objective: str | None = None
) -> dict[str, Any]:
    """Create or bind a real Orca Run and idempotently mirror stages, tasks, deps, and gates."""
    spec_dir = spec_dir.resolve()
    tasks_data = load_tasks(spec_dir)
    state = _bind_or_create_run(
        spec_dir, run_id, objective or f"Execute spec workflow for {spec_dir.name}"
    )
    save_run_state(spec_dir, state)

    tasks = tasks_data["tasks"]
    stages = sorted({task.get("stage") for task in tasks if isinstance(task.get("stage"), int)})
    for stage in stages:
        key = str(stage)
        if key in state.setdefault("stage_tasks_map", {}):
            continue
        receipt = run_orca_json(
            [
                "orchestration", "task-create", "--run", state["run_id"],
                "--task-title", f"Stage {stage}", "--display-name", f"Stage {stage}",
                "--spec", f"Grouping task for spec stage {stage}.",
            ]
        )
        state["stage_tasks_map"][key] = receipt_value(receipt, "taskId", "task_id", "id")
        save_run_state(spec_dir, state)

    pending = {task["id"]: task for task in tasks if task["id"] not in state["tasks_map"]}
    while pending:
        progressed = False
        for task_id, task in list(pending.items()):
            deps = task.get("depends_on", [])
            if any(dep not in state["tasks_map"] for dep in deps):
                continue
            args = [
                "orchestration", "task-create", "--run", state["run_id"],
                "--task-title", f"{task_id} {task['title']}",
                "--display-name", f"{task_id} {task['title']}", "--spec", _task_spec(task),
            ]
            if deps:
                args.extend(["--deps", json.dumps([state["tasks_map"][dep] for dep in deps])])
            stage = task.get("stage")
            if isinstance(stage, int):
                args.extend(["--parent", state["stage_tasks_map"][str(stage)]])
            receipt = run_orca_json(args)
            orca_task_id = receipt_value(receipt, "taskId", "task_id", "id")
            state["tasks_map"][task_id] = orca_task_id
            save_run_state(spec_dir, state)
            if task.get("checked"):
                run_orca_json(
                    ["orchestration", "task-update", "--run", state["run_id"],
                     "--id", orca_task_id, "--status", "completed",
                     "--result", json.dumps({"source": "04_tasks.json", "checked": True})]
                )
            if "checkpoint" in task.get("title", "").lower() and not task.get("checked"):
                gate = run_orca_json(
                    ["orchestration", "gate-create", "--task", orca_task_id,
                     "--question", f"Approve checkpoint: {task['title']}?",
                     "--options", json.dumps(["approve", "reject", "re-audit"])]
                )
                state.setdefault("decision_gates", []).append(
                    {
                        "gate_id": receipt_value(gate, "gateId", "gate_id", "id"),
                        "task_id": task_id,
                        "question": f"Approve checkpoint: {task['title']}?",
                        "options": ["approve", "reject", "re-audit"],
                        "status": "pending",
                    }
                )
                save_run_state(spec_dir, state)
            del pending[task_id]
            progressed = True
        if not progressed:
            raise RuntimeError(f"cannot topologically sync tasks; unresolved dependencies: {sorted(pending)}")

    for stage in stages:
        children = [task for task in tasks if task.get("stage") == stage]
        if children and all(task.get("checked") for task in children):
            run_orca_json(
                ["orchestration", "task-update", "--run", state["run_id"],
                 "--id", state["stage_tasks_map"][str(stage)], "--status", "completed",
                 "--result", json.dumps({"source": "04_tasks.json", "stage": stage})]
            )
    save_run_state(spec_dir, state)
    return state


def _infer_agent(model: str | None, fallback: str) -> str:
    lowered = (model or "").lower()
    if lowered.startswith("claude"):
        return "claude"
    if lowered.startswith(("gpt", "o1", "o3", "o4", "codex")):
        return "codex"
    if lowered.startswith("gemini"):
        return "agy"
    return fallback


def _model_matches_agent(model: str | None, agent: str) -> bool:
    return model is not None and _infer_agent(model, "") == agent


def _profile_flags(profile: dict[str, Any], role: str) -> list[str]:
    override = profile.get("role_overrides", {}).get(role, {})
    return list(override.get("unattended_flags", profile.get("unattended_flags", [])))


def _agent_command(
    agent: str, profile: dict[str, Any], role: str, model: str | None, effort: str | None
) -> list[str]:
    command = [profile.get("binary", agent), *_profile_flags(profile, role)]
    if model and profile.get("model_flag"):
        command.extend([profile["model_flag"], model])
    effort_flag = profile.get("effort_flag")
    if effort and effort_flag:
        effort = profile.get("effort_map", {}).get(effort, effort)
        if effort_flag.endswith("="):
            head, prefix = effort_flag.split(" ", 1)
            command.extend([head, prefix + effort])
        else:
            command.extend([effort_flag, effort])
    return command


def get_ready_dispatches(
    spec_dir: Path,
    *,
    task_filter: set[str] | None = None,
    default_agent: str = "claude",
    agent_override: str | None = None,
    role: str = "implementer",
    model_override: str | None = None,
    worktree_override: str | None = None,
) -> list[dict[str, Any]]:
    """Return receipt-linked launch plans for unchecked, dependency-ready spec tasks."""
    tasks_data = load_tasks(spec_dir)
    state = load_run_state(spec_dir)
    profiles = load_agent_profiles()["agents"]
    tasks_by_id = {task["id"]: task for task in tasks_data["tasks"]}
    dispatches = []
    for task_id in tasks_data["concurrency"].get("ready", []):
        if task_filter and task_id not in task_filter:
            continue
        task = tasks_by_id.get(task_id)
        if not task or task.get("checked"):
            continue
        if any(not tasks_by_id.get(dep, {}).get("checked") for dep in task.get("depends_on", [])):
            continue
        if task_id not in state.get("tasks_map", {}):
            raise RuntimeError(f"spec task {task_id} has not been synced to Orca")
        configured = task.get("orca_dispatch", {})
        task_model = task.get("resolved_model")
        agent = agent_override or configured.get("agent") or _infer_agent(task_model, default_agent)
        if agent not in profiles:
            raise RuntimeError(f"unknown agent {agent!r}; expected one of {sorted(profiles)}")
        model = model_override or (task_model if _model_matches_agent(task_model, agent) else None)
        effort = task.get("reasoning_level")
        worktree_mode = worktree_override or configured.get("worktree_mode") or "current"
        command = _agent_command(agent, profiles[agent], role, model, effort)
        dispatches.append(
            {
                "task_id": task_id,
                "orca_task_id": state["tasks_map"][task_id],
                "title": task["title"],
                "agent": agent,
                "role": role,
                "model": model,
                "effort": effort,
                "worktree_mode": worktree_mode,
                "command_argv": command,
                "command": shlex.join(command),
                "prompt_delivery": "orca-task-spec-inject",
                "files": task.get("files", []),
            }
        )
    return dispatches


def _create_worker_terminal(
    plan: dict[str, Any], feature_slug: str, setup: str, repo: str | None
) -> tuple[str, str | None]:
    if plan["worktree_mode"] == "current":
        receipt = run_orca_json(
            ["terminal", "create", "--worktree", "active", "--title",
             f"{feature_slug}-{plan['task_id']}", "--command", plan["command"]]
        )
        return receipt_value(receipt, "terminalHandle", "terminal_handle", "handle"), None
    if plan["worktree_mode"] != "new-child":
        raise RuntimeError(f"unsupported worktree mode {plan['worktree_mode']!r}")
    name = f"{feature_slug}-{plan['task_id'].replace('.', '-')}"
    args = ["worktree", "create", "--name", name, "--parent-worktree", "active", "--setup", setup]
    if repo:
        args.extend(["--repo", repo])
    worktree = run_orca_json(args, timeout=120)
    worktree_id = receipt_value(worktree, "fullWorktreeId", "worktreeId", "worktree_id", "id")
    terminal = run_orca_json(
        ["terminal", "create", "--worktree", f"id:{worktree_id}", "--title", name,
         "--command", plan["command"]]
    )
    return receipt_value(terminal, "terminalHandle", "terminal_handle", "handle"), worktree_id


def dispatch_ready(
    spec_dir: Path, plans: list[dict[str, Any]], *, setup: str, repo: str | None
) -> list[dict[str, Any]]:
    """Launch custom-argv terminals, wait for TUI readiness, inject tasks, and save receipts."""
    state = load_run_state(spec_dir)
    results = []
    for plan in plans:
        terminal_handle, worktree_id = _create_worker_terminal(
            plan, state["feature_slug"], setup, repo
        )
        run_orca_json(
            ["terminal", "wait", "--terminal", terminal_handle, "--for", "tui-idle",
             "--timeout-ms", "60000"], timeout=75
        )
        receipt = run_orca_json(
            ["orchestration", "dispatch", "--run", state["run_id"],
             "--task", plan["orca_task_id"], "--to", terminal_handle, "--inject"]
        )
        record: dict[str, Any] = {
            "task_id": plan["task_id"],
            "orca_task_id": plan["orca_task_id"],
            "dispatch_id": receipt_value(receipt, "dispatchId", "dispatch_id", "id"),
            "worker_handle": terminal_handle,
            "worktree_path": worktree_id or "current",
            "agent": plan["agent"],
            "effort": plan["effort"],
            "status": "dispatched",
        }
        if plan["model"]:
            record["model"] = plan["model"]
        state.setdefault("dispatches", []).append(record)
        save_run_state(spec_dir, state)
        results.append(record)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="Create/bind a Run and mirror the spec DAG")
    sync_parser.add_argument("spec_dir", type=Path)
    sync_parser.add_argument("--run")
    sync_parser.add_argument("--objective")

    status_parser = subparsers.add_parser("status", help="Print persisted receipt-derived state")
    status_parser.add_argument("spec_dir", type=Path)
    status_parser.add_argument("--json", action="store_true")

    dispatch_parser = subparsers.add_parser(
        "dispatch-ready", help="Preview ready workers; add --apply to launch and inject"
    )
    dispatch_parser.add_argument("spec_dir", type=Path)
    dispatch_parser.add_argument("--apply", action="store_true")
    dispatch_parser.add_argument("--json", action="store_true")
    dispatch_parser.add_argument("--task", action="append", dest="tasks")
    dispatch_parser.add_argument("--default-agent", default="claude")
    dispatch_parser.add_argument("--agent")
    dispatch_parser.add_argument("--role", choices=["implementer", "reviewer", "explorer"], default="implementer")
    dispatch_parser.add_argument("--model")
    dispatch_parser.add_argument("--worktree", choices=["current", "new-child"])
    dispatch_parser.add_argument("--setup", choices=["run", "skip", "inherit"], default="run")
    dispatch_parser.add_argument("--repo")

    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            state = sync_spec_to_orca(args.spec_dir, args.run, args.objective)
            print(json.dumps(state, indent=2) if getattr(args, "json", False) else
                  f"Synced {len(state['tasks_map'])} tasks to Orca Run {state['run_id']}.")
        elif args.command == "status":
            state = load_run_state(args.spec_dir)
            print(json.dumps(state, indent=2) if args.json else
                  f"Run {state['run_id']}: {len(state['tasks_map'])} tasks, "
                  f"{len(state.get('dispatches', []))} dispatches")
        else:
            plans = get_ready_dispatches(
                args.spec_dir,
                task_filter=set(args.tasks) if args.tasks else None,
                default_agent=args.default_agent,
                agent_override=args.agent,
                role=args.role,
                model_override=args.model,
                worktree_override=args.worktree,
            )
            output = dispatch_ready(args.spec_dir, plans, setup=args.setup, repo=args.repo) if args.apply else plans
            if args.json:
                print(json.dumps(output, indent=2))
            else:
                verb = "Dispatched" if args.apply else "Ready"
                print(f"{verb} workers ({len(output)}):")
                for item in output:
                    if args.apply:
                        print(f"  - {item['task_id']} -> {item['dispatch_id']}")
                    else:
                        print(f"  - {item['task_id']} -> {item['agent']} ({item['worktree_mode']}): {item['command']}")
    except (FileNotFoundError, RuntimeError, OrcaCommandError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
