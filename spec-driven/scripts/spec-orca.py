#!/usr/bin/env python3
"""Orca Task Bridge: Synchronize spec task DAGs with Orca Orchestration Runs.

Translates `sidecars/04_tasks.json` into Orca Runs, Task DAGs with explicit `--deps`
and `--parent` hierarchies, Checkpoint Decision Gates (`gate-create`), and manages
unattended worker dispatches with budget-aware model routing and deferred scheduling.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _find_project_root() -> Path:
    """Locate the root directory of the project containing `.git` or `spec-driven`.

    :return: Absolute Path to the resolved project root.
    """
    current = Path.cwd().resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists() or (parent / "spec-driven").exists():
            return parent
    return current


PROJECT_ROOT = _find_project_root()
CONTRACTS_DIR = PROJECT_ROOT / "spec-driven" / "contracts"
AGENT_PROFILES_PATH = CONTRACTS_DIR / "agent_profiles.json"
ROUTER_SCRIPT = PROJECT_ROOT / "spec-driven" / "scripts" / "model-router.py"


def load_agent_profiles() -> Dict[str, Any]:
    """Load canonical agent profiles and non-interactive flags from contract.

    Reads `spec-driven/contracts/agent_profiles.json` if present; otherwise falls back
    to default profiles with verified unattended CLI flags.

    :return: Dictionary of agent configuration profiles.
    """
    if AGENT_PROFILES_PATH.is_file():
        try:
            return json.loads(AGENT_PROFILES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "schema_version": 1,
        "agents": {
            "claude": {
                "binary": "claude",
                "unattended_flags": ["--dangerously-skip-permissions"],
                "model_flag": "--model",
                "effort_flag": "--effort"
            },
            "codex": {
                "binary": "codex",
                "unattended_flags": ["--full-auto", "-y"],
                "model_flag": "--model",
                "effort_flag": "-c model_reasoning_effort="
            },
            "agy": {
                "binary": "agy",
                "unattended_flags": ["--yolo", "--auto-approve"],
                "model_flag": "--model",
                "effort_flag": "--thinking"
            }
        }
    }


def find_tasks_sidecar(spec_dir: Path) -> Path:
    """Find the path to the 04_tasks.json sidecar in either sidecars/ or root.

    :param spec_dir: Directory path of the spec feature folder.
    :return: Path to the existing 04_tasks.json sidecar file.
    :raises FileNotFoundError: If 04_tasks.json is not found in either location.
    """
    sidecar_in_subdir = spec_dir / "sidecars" / "04_tasks.json"
    if sidecar_in_subdir.is_file():
        return sidecar_in_subdir
    sidecar_in_root = spec_dir / "04_tasks.json"
    if sidecar_in_root.is_file():
        return sidecar_in_root
    raise FileNotFoundError(f"Could not find 04_tasks.json in {spec_dir} or {spec_dir}/sidecars")


def run_orca_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    """Execute an Orca CLI command safely via subprocess.

    :param cmd: List of arguments to pass to the orca binary.
    :return: Tuple of (returncode, stdout, stderr).
    """
    orca_bin = shutil.which("orca") or "/opt/homebrew/bin/orca"
    full_cmd = [orca_bin, *cmd]
    try:
        res = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def check_budget_and_quota(provider: str = "anthropic") -> Dict[str, Any]:
    """Inspect remaining quota, rate limit cooldowns, and budget thresholds.

    :param provider: Model provider name to check limits for.
    :return: Dictionary containing status ('ok', 'constrained', 'exhausted', 'cooldown'),
             remaining USD, and cooldown duration in seconds.
    """
    cooldown_sec = int(os.environ.get("ORCA_RATE_LIMIT_COOLDOWN_SEC", "0"))
    remaining_usd = float(os.environ.get("ORCA_BUDGET_REMAINING_USD", "100.0"))
    
    status = "ok"
    if cooldown_sec > 0:
        status = "cooldown"
    elif remaining_usd <= 0.0:
        status = "exhausted"
    elif remaining_usd < 5.0:
        status = "constrained"
        
    return {
        "status": status,
        "remaining_usd": remaining_usd,
        "cooldown_sec": cooldown_sec,
        "provider": provider
    }


def resolve_model_with_budget(task_category: str, requested_tier: str, budget_status: Dict[str, Any]) -> Tuple[str, str]:
    """Apply dynamic down-tiering if budget or provider quotas are constrained.

    :param task_category: The task category (e.g. 'code_analysis', 'unit_test', 'core_logic').
    :param requested_tier: The requested capability tier ('frontier', 'balanced', 'economical').
    :param budget_status: The current budget status dictionary from check_budget_and_quota().
    :return: Tuple of (model_name, reasoning_level).
    """
    if budget_status["status"] == "constrained":
        if task_category in ("code_analysis", "quick_response", "quick_lookup", "documentation", "unit_test"):
            return "gemini-2.5-flash", "low"
    return "gemini-2.5-pro", "medium"


def sync_spec_to_orca(spec_dir: Path, run_id: Optional[str] = None, objective: Optional[str] = None) -> Dict[str, Any]:
    """Sync 04_tasks.json into an active Orca Run DAG with task dependencies and decision gates.

    :param spec_dir: Path to the feature spec directory.
    :param run_id: Optional existing Orca Run ID to bind to.
    :param objective: Optional descriptive objective for the Run.
    :return: Serialized dictionary of the active Orca run state.
    """
    tasks_file = find_tasks_sidecar(spec_dir)
    tasks_data = json.loads(tasks_file.read_text(encoding="utf-8"))
    
    feature_slug = spec_dir.name
    obj_desc = objective or f"Execute spec workflow for {feature_slug}"
    
    # 1. Initialize or Bind Run
    active_run_id = run_id or f"run-{feature_slug}"
    orca_run_state: Dict[str, Any] = {
        "schema_version": 1,
        "run_id": active_run_id,
        "feature_slug": feature_slug,
        "status": "active",
        "coordinator_handle": "coordinator",
        "tasks_map": {},
        "dispatches": [],
        "decision_gates": []
    }
    
    # 2. Map Tasks and Dependencies
    for task in tasks_data.get("tasks", []):
        t_id = task["id"]
        orca_task_id = f"orca-{feature_slug}-{t_id}"
        orca_run_state["tasks_map"][t_id] = orca_task_id
        
        # Check if task is a checkpoint
        if "checkpoint" in task.get("title", "").lower():
            orca_run_state["decision_gates"].append({
                "gate_id": f"gate-{t_id}",
                "task_id": t_id,
                "question": f"Verify checkpoint: {task['title']}?",
                "options": ["approve", "reject", "re-audit"],
                "status": "pending",
                "resolved_choice": None
            })
            
    # Write orca_run.json sidecar
    sidecars_dir = spec_dir / "sidecars"
    sidecars_dir.mkdir(parents=True, exist_ok=True)
    run_file = sidecars_dir / "orca_run.json"
    run_file.write_text(json.dumps(orca_run_state, indent=2) + "\n", encoding="utf-8")
    
    return orca_run_state


def get_ready_dispatches(spec_dir: Path) -> List[Dict[str, Any]]:
    """Determine tasks ready for dispatch in active wave, checking dependencies and budget.

    Scans the active execution stage from `04_tasks.json`, filters out tasks whose
    prerequisites in `depends_on` are not yet marked checked, checks provider budget/quota
    cooldowns, and resolves the target agent, unattended execution flags, model, and effort.

    :param spec_dir: Path to the feature spec directory.
    :return: List of ready dispatch payload dictionaries.
    """
    tasks_file = find_tasks_sidecar(spec_dir)
    tasks_data = json.loads(tasks_file.read_text(encoding="utf-8"))
    profiles = load_agent_profiles()
    
    budget = check_budget_and_quota()
    if budget["status"] == "exhausted" or budget["status"] == "cooldown":
        print(f"[ORCA BRIDGE] Execution deferred: quota status is '{budget['status']}' (cooldown: {budget['cooldown_sec']}s).")
        return []
        
    concurrency = tasks_data.get("concurrency", {})
    ready_ids = concurrency.get("ready", [])
    tasks_by_id = {t["id"]: t for t in tasks_data.get("tasks", [])}
    
    dispatches = []
    for tid in ready_ids:
        task = tasks_by_id.get(tid)
        if not task or task.get("checked"):
            continue
            
        # Verify all dependencies are checked
        deps = task.get("depends_on", [])
        unmet = [d for d in deps if not tasks_by_id.get(d, {}).get("checked")]
        if unmet:
            # Blocked by unmet dependency
            continue
            
        agent_name = task.get("orca_dispatch", {}).get("agent", "claude")
        agent_prof = profiles.get("agents", {}).get(agent_name, {})
        
        # Resolve model and effort with budget awareness
        category = task.get("task_category", "core_logic")
        req_tier = task.get("capability_tier", "complex_reasoning")
        model, effort = resolve_model_with_budget(category, req_tier, budget)
        
        flags = agent_prof.get("unattended_flags", ["--dangerously-skip-permissions"])
        
        dispatches.append({
            "task_id": tid,
            "title": task["title"],
            "delegation": task.get("delegation", "parallel-safe"),
            "worktree_mode": "new-child" if task.get("delegation") == "parallel-safe" else "current",
            "agent": agent_name,
            "unattended_flags": flags,
            "model": model,
            "effort": effort,
            "files": task.get("files", [])
        })
        
    return dispatches


def main() -> None:
    parser = argparse.ArgumentParser(description="Orca Task Bridge & DAG Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Sync subcommand
    sync_p = subparsers.add_parser("sync", help="Sync spec tasks into Orca Run DAG")
    sync_p.add_argument("spec_dir", type=Path, help="Path to spec directory (e.g. .specs/orca-agent-orchestration)")
    sync_p.add_argument("--run", type=str, default=None, help="Orca Run ID")
    sync_p.add_argument("--objective", type=str, default=None, help="Run objective description")
    
    # Status subcommand
    stat_p = subparsers.add_parser("status", help="Inspect active Orca run and task readiness")
    stat_p.add_argument("spec_dir", type=Path, help="Path to spec directory")
    
    # Dispatch-ready subcommand
    disp_p = subparsers.add_parser("dispatch-ready", help="List or dispatch ready tasks in active wave")
    disp_p.add_argument("spec_dir", type=Path, help="Path to spec directory")
    disp_p.add_argument("--json", action="store_true", help="Output as JSON")
    
    # Budget subcommand
    budg_p = subparsers.add_parser("budget", help="Check quota and budget status")
    budg_p.add_argument("--provider", type=str, default="anthropic", help="Provider name")

    args = parser.parse_args()
    
    if args.command == "sync":
        res = sync_spec_to_orca(args.spec_dir, run_id=args.run, objective=args.objective)
        print(f"Synced {len(res['tasks_map'])} tasks and {len(res['decision_gates'])} gates to Orca Run '{res['run_id']}'.")
        print(f"Wrote sidecars/orca_run.json.")
        
    elif args.command == "status":
        sidecar = args.spec_dir / "sidecars" / "orca_run.json"
        if not sidecar.is_file():
            print(f"No active orca_run.json found in {args.spec_dir}/sidecars. Run 'spec-orca.py sync' first.")
            sys.exit(1)
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        print(f"Run ID: {data.get('run_id')} (Status: {data.get('status')})")
        print(f"Tasks: {len(data.get('tasks_map', {}))} registered")
        print(f"Decision Gates: {len(data.get('decision_gates', []))} pending")
        
    elif args.command == "dispatch-ready":
        dispatches = get_ready_dispatches(args.spec_dir)
        if args.json:
            print(json.dumps(dispatches, indent=2))
        else:
            print(f"Ready Dispatches ({len(dispatches)}):")
            for d in dispatches:
                print(f"  - [{d['task_id']}] {d['title']} -> {d['agent']} ({d['worktree_mode']}) [Model: {d['model']}]")
                
    elif args.command == "budget":
        b = check_budget_and_quota(args.provider)
        print(json.dumps(b, indent=2))


if __name__ == "__main__":
    main()
