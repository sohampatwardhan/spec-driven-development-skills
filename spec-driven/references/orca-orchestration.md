# Reference: Orca Multi-Agent Task Orchestration

## Overview

Orca provides a daemon-backed orchestration runtime for managing concurrent multi-agent workflows, isolated git worktrees, and supervised execution.

---

## Core Command Surface

### 1. Run Management

A **Run** encapsulates a coordinated multi-task workflow with shared state, dependency tracking, and decision gates.

```bash
# Create and bind an active Run
orca orchestration run-create --objective "<objective description>" --json

# Bind an existing Run to the active terminal context
orca orchestration run-use --id <run_id> --json

# List active or recent Runs
orca orchestration run-list --json
```

---

### 2. Task DAG Creation

Tasks represent discrete work nodes with explicit prerequisites and parent-child hierarchy.

```bash
# Create a root or child task
orca orchestration task-create \
  --spec "Implement core data model in src/model.py" \
  --deps '["<prerequisite_task_id>"]' \
  --parent "<parent_stage_task_id>" \
  --json
```

---

### 3. Worker Placement and Custom Agent Arguments

Workers execute tasks in supervised background PTYs. Use `worker-start` when its known-agent launch is sufficient. It does not pass arbitrary agent CLI flags.

```bash
# Dispatch worker in child worktree
orca orchestration worker-start \
  --task <task_id> \
  --worktree new-child \
  --agent claude \
  --model claude-3-7-sonnet \
  --effort high \
  --setup run \
  --json
```

For unattended flags or other custom argv, use the low-level path that Orca documents for topology `worker-start` does not express:

```bash
orca terminal create --worktree active --command "codex --approve-for-me" --json
orca terminal wait --terminal <terminal_handle> --for tui-idle --timeout-ms 60000 --json
orca orchestration dispatch --task <task_id> --to <terminal_handle> --inject --json
```

Stay in the current worktree by default. Create a child worktree only when the user requested one or a verified checkout/file conflict makes sharing impossible. Custom argv in a new child requires `worktree create --setup run` followed by `terminal create`; it cannot enforce a repository's `wait-for-setup` launch policy.

---

### 4. TUI Idle Synchronization

Before sending input to a newly launched TUI agent, wait for idle to prevent character drops during initialization:

```bash
orca terminal wait --terminal <terminal_handle> --for tui-idle --timeout-ms 10000 --json
```

---

### 5. Supervised Event Loop & Terminal Release

The coordinator listens for events using `check --wait`:

```bash
# Listen for worker completion, escalations, or questions
orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 30000 --json

# Answer a worker question
orca orchestration send --type reply --to <worker_handle> --payload '{"answer": "..."}'

# Release terminal after worker_done
orca orchestration worker-release --dispatch <dispatch_id> --json
```

---

### 6. Decision Gates (Spec Checkpoints)

Checkpoints in a spec map to Orca Decision Gates:

```bash
# Create a gate
orca orchestration gate-create --task <task_id> --question "Approve design changes?" --options '["approve", "reject"]' --json

# Resolve a gate
orca orchestration gate-resolve --id <gate_id> --resolution "approve" --json
```
