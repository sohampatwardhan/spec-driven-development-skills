# Changelog

All notable changes to the Spec-Driven Development Skills suite are documented in this file.

## [Unreleased] - 2026-08-10

### Added
- **Orca Multi-Agent Task Orchestration**:
  - Registered `orca` runtime adapter in [`spec-driven/contracts/spec-family.yaml`](spec-driven/contracts/spec-family.yaml) supporting persistent coordination Runs, task DAG dependencies (`--deps`), parent-child hierarchies (`--parent`), decision gates (`gate-create`), and isolated child worktree worker placement (`--worktree new-child --setup run`).
  - Added [`spec-driven/scripts/spec-orca.py`](spec-driven/scripts/spec-orca.py) bridge utility for syncing `04_tasks.json` DAGs into Orca Runs, inspecting ready waves, dispatching workers with unattended CLI flags, managing decision gates, and supervising PTY lifecycles.
  - Added [`spec-driven/references/orca-orchestration.md`](spec-driven/references/orca-orchestration.md) architecture and command surface reference guide.
- **Formal JSON Schemas & Dedicated Sidecar Directory**:
  - Registered 9 formal Draft 2020-12 JSON schemas in [`spec-driven/contracts/schemas/`](spec-driven/contracts/schemas/) for all phase documents, agent profiles, audit findings, and Orca runs:
    - `00_state.schema.json`, `01_discovery.schema.json`, `02_requirements.schema.json`, `03_design.schema.json`, `04_tasks.schema.json`, `05_execution.schema.json`, `agent_profiles.schema.json`, `audit_findings.schema.json`, `orca_run.schema.json`.
  - Added first-class support for the `.specs/<slug>/sidecars/` directory layout across all tools and validators.
- **Canonical Agent CLI Flag Matrix**:
  - Added [`spec-driven/contracts/agent_profiles.json`](spec-driven/contracts/agent_profiles.json) with Context7-verified unattended non-interactive flags for `claude` (`--dangerously-skip-permissions`), `codex` (`--full-auto`, `-y`), `agy` (`--yolo`, `--auto-approve`), `cursor` (`--approve-all`), and `opencode` (`--auto-confirm`).
  - Added [`spec-driven/references/agent-cli-flags.md`](spec-driven/references/agent-cli-flags.md) reference guide.
- **Deterministic Mermaid Visualization**:
  - Implemented [`spec-driven/scripts/render-gantt.py`](spec-driven/scripts/render-gantt.py) to deterministically generate syntax-error-free Mermaid Gantt charts in `05_execution.md` from `05_execution.json` timing intervals, with safe handling of 0-second and sub-second task durations.
  - Added deterministic 4-color Mermaid flowchart generator (`build_flowchart_from_tasks_data()`) for `04_tasks.md` Stage and Dependency Overview:
    - **Grey (`pending`)**: `fill:#f1f5f9,stroke:#94a3b8` (not started/queued)
    - **Red (`failed`)**: `fill:#fee2e2,stroke:#ef4444` (verification defect)
    - **Amber (`in_progress`)**: `fill:#fef3c7,stroke:#f59e0b` (active executing wave)
    - **Green (`done`)**: `fill:#dcfce7,stroke:#22c55e` (verified completed)
- **Budget & Quota Aware Routing**:
  - Integrated quota inspection and budget cooldown checks in `spec-orca.py` and `model-router.py` to dynamically down-tier lightweight tasks under credit constraints and defer execution if provider quotas are exhausted.
- **Testing & Verification Suites**:
  - Added [`spec-driven/tests/test_spec_orca.py`](spec-driven/tests/test_spec_orca.py) (5 tests) for DAG mapping, dependency blocking, decision gates, and budget routing.
  - Added [`spec-driven/tests/test_render_gantt.py`](spec-driven/tests/test_render_gantt.py) (5 tests) for Mermaid Gantt syntax, 0-second duration protection, outcome tags, and 4-color flowchart standards.
  - Extended [`spec-driven/tests/test_sidecars.py`](spec-driven/tests/test_sidecars.py) for schema validation and `sidecars/` subfolder emission.
  - Full test suite passing at 114 passed, 3 skipped.

### Changed
- **`spec-execute/SKILL.md`**: Integrated Orca wave dispatching, child worktree placement, TUI idle synchronization, and supervised PTY event loops.
- **`spec-audit/SKILL.md`**: Integrated parallel reviewer dispatch and structured `audit_findings.json` emission.
- **`spec-tasks/SKILL.md`**, **`spec-driven/SKILL.md`**, and **`spec-driven/references/artifacts.md`**: Synchronized `sidecars/` subfolder layout and 4-color flowchart status standards.
- **`spec-driven/scripts/spec-check.py`**: Enhanced with `sidecars/` subfolder lookup, SHA-256 freshness tracking across all 6 spec artifacts, and in-memory 3-way traceability validation.
