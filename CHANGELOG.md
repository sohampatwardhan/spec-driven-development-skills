# Changelog

All notable changes to the Spec-Driven Development Skills suite are documented in this file.

## Versioning

Each skill directory (`spec-discovery/`, `spec-driven/`, `dependency-security-audit/`, etc.) is
versioned independently via a `version:` field in its `SKILL.md` frontmatter, following
[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`, where MAJOR is a breaking change
to a skill's triggers/workflow, MINOR is a backward-compatible capability addition, and PATCH is a
bug fix with no behavior change for existing users. There is no single version number for the
suite as a whole — a release below lists exactly the skills it changed and their old → new
version, and skills it doesn't mention are unchanged at their last-listed version.

## [1.1.0] - 2026-08-12

Orca multi-agent task orchestration, deterministic sidecar tooling, an execution status control
plane, and provider safety profile enforcement.

**Versions:** `spec-driven` 1.0.0 → 1.1.0 · `spec-execute` 1.0.0 → 1.1.0 · `spec-audit` 1.0.0 →
1.1.0 · `spec-tasks` 1.0.0 → 1.1.0 · `dependency-security-audit` 1.0.0 → 1.0.1

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
  - Added deterministic 4-color Mermaid flowchart generator (`build_flowchart_from_tasks_data()`) for `04_tasks.md` Stage and Dependency Overview, leveraging the ELK layout renderer (`%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%`) to minimize edge overlap.
    - **Grey (`pending`)**: `fill:#f1f5f9,stroke:#94a3b8` (not started/queued)
    - **Red (`failed`)**: `fill:#fee2e2,stroke:#ef4444` (verification defect)
    - **Amber (`in_progress`)**: `fill:#fef3c7,stroke:#f59e0b` (active executing wave)
    - **Green (`done`)**: `fill:#dcfce7,stroke:#22c55e` (verified completed)
  - Added `### Task Board` kanban generator (`build_kanban_board_from_tasks_data()`), an
    execution-only, conditional companion to the Execution Gantt in `05_execution.md`. Groups
    tasks into Pending/In Progress/Failed/Done columns using the same `derive_task_statuses()`
    helper the flowchart uses, so the two views can never disagree. Mermaid kanban has no
    render-validated per-card `style`/`classDef` mechanism (`style <id> fill:...` renders as a
    bogus extra column; `:::class` is a parse error), so status is carried via a colored-circle
    emoji prefix (⚪🟠🔴🟢) instead of a literal fill/stroke color — confirmed by direct
    render-validation. Supplements, never replaces, the required `04_tasks.md` flowchart.
- **Budget & Quota Aware Routing**:
  - Integrated quota inspection and budget cooldown checks in `spec-orca.py` and `model-router.py` to dynamically down-tier lightweight tasks under credit constraints and defer execution if provider quotas are exhausted.
- **Execution Status Control Plane**:
  - Added `derive_task_status_projection()` to [`spec-driven/scripts/spec-check.py`](spec-driven/scripts/spec-check.py), deriving each task's one current lifecycle state (`blocked`/`ready`/`running`/`failed`/`done`) from the task list and attempt ledger rather than hand-authoring it separately, and exposing it as the new `task_status` field in [`05_execution.schema.json`](spec-driven/contracts/schemas/05_execution.schema.json).
  - Added `execution_wave_errors()` to reject a parallel wave with overlapping file ownership across its tasks, and to block a wave from starting until the prior wave's checkpoint is recorded `verified` in the new `checkpoint_commits` field.
  - Extended [`04_tasks.schema.json`](spec-driven/contracts/schemas/04_tasks.schema.json) with per-task `components`, per-wave `profile`/`owned_paths`/`reason`, and a task-level `safety_classification` field.
- **Provider Safety Profile Enforcement**:
  - Added a `provider_safety` block (`real_time_cyber_safeguards`, `defensive_use_verified`, `allowed_safety_classifications`) to [`spec-driven/contracts/agent_profiles.json`](spec-driven/contracts/agent_profiles.json) and its schema.
  - Added `provider_compatibility_error()` to [`spec-driven/scripts/spec-orca.py`](spec-driven/scripts/spec-orca.py), raising a non-retryable dispatch error — never a prompt-rewriting workaround — when a task's declared `safety_classification` isn't in the target agent's allowed list, or when `dual_use` work is dispatched to an agent with real-time cyber safeguards but no verified defensive-use entitlement.
- **Testing & Verification Suites**:
  - Added [`spec-driven/tests/test_spec_orca.py`](spec-driven/tests/test_spec_orca.py) (5 tests) for DAG mapping, dependency blocking, decision gates, and budget routing.
  - [`spec-driven/tests/test_render_gantt.py`](spec-driven/tests/test_render_gantt.py) now has 18 tests, covering Mermaid Gantt syntax, 0-second duration protection, outcome tags, 4-color flowchart standards, Task Board kanban grouping/omission/sanitization, flowchart↔kanban status agreement, and idempotent Task Board injection.
  - Extended [`spec-driven/tests/test_sidecars.py`](spec-driven/tests/test_sidecars.py) for schema validation and `sidecars/` subfolder emission.
  - Full `spec-driven/tests/` suite passing at 140 passed, 3 skipped, 170 subtests passed.

- **Bidirectional skill-sync check**: Added
  [`spec-driven/scripts/check-skill-sync.py`](spec-driven/scripts/check-skill-sync.py), which
  diffs the installed `spec-*`/`dependency-security-audit` skill directories against the latest
  `main` of this repo and reports drift in either direction — files the local copy is missing
  (a pushed improvement not yet pulled) as well as files only present locally (a fix made
  mid-session and never pushed back), since one direction silently masking the other defeats
  the point of maintaining this repo. Documented in a new "Staying current" section in
  `spec-driven/SKILL.md`, run once per session before nontrivial spec-driven work.

### Changed
- **`spec-execute/SKILL.md`**: Integrated Orca wave dispatching, child worktree placement, TUI idle synchronization, and supervised PTY event loops. Relaxed the prior blanket "do not add a new Kanban" rule into a named, execution-only exception for the Task Board that supplements (never replaces) the required flowchart.
- **`spec-audit/SKILL.md`**: Integrated parallel reviewer dispatch and structured `audit_findings.json` emission.
- **`spec-tasks/SKILL.md`**, **`spec-driven/SKILL.md`**, and **`spec-driven/references/artifacts.md`**: Synchronized `sidecars/` subfolder layout, 4-color flowchart status standards, and the new Task Board section.
- **`spec-driven/references/diagrams.md`**: Documented the "structured source exists but no IR family covers it yet" case (e.g. `kanban`) alongside the existing IR-generation/hand-authoring split, and added the Task Board to the phase decision matrix.
- **`spec-driven/scripts/spec-check.py`**: Enhanced with `sidecars/` subfolder lookup, SHA-256 freshness tracking across all 6 spec artifacts, and in-memory 3-way traceability validation.

### Fixed
- **`spec-driven/scripts/render-gantt.py`**: The Stage-and-Dependency-Overview dedup regex now
  tolerates the `%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%` directive
  `build_flowchart_from_tasks_data` inserts right after the ` ```mermaid ` fence — without this,
  the pattern never matched an existing generated block, so every regeneration appended a
  duplicate flowchart instead of replacing the one already there.
- **`spec-driven/scripts/spec-orca.py`**: `receipt_value()` now searches `result.<resource>`
  instead of the raw `orca ... --json` envelope, so the envelope's own per-request UUID `id`
  no longer shadows the real nested resource id for any caller searching for a generic `"id"`
  key.
- **`spec-driven/scripts/render-gantt.py`**: Gantt/flowchart and kanban task labels no longer
  silently truncate over-length titles into mangled diagram text. `_sanitize_label` and
  `_sanitize_kanban_label` now raise a `ValueError` naming the offending task and its char count
  instead, so an over-length title fails `--write` immediately rather than producing a diagram
  that needs a manual post-hoc fix. Raised the flowchart/gantt label cap from 40 to 80 characters
  to match realistic task title lengths. Documented the caps in `spec-tasks/SKILL.md`.
- **Dependency security source compatibility**: Updated NVD CVE 2.0 lookups from the deprecated
  `cveId` parameter to `cveIds`. Hardened CycloneDX ingestion to require the standard
  `bomFormat`/`specVersion` identity, accept the specification's metadata-component graph root,
  derive direct dependencies from that root, and fail closed when component graph nodes are
  omitted. Added regression coverage for both current API contracts.
- **`spec-driven/scripts/spec-check.py`**: `--emit-json` is now the default behavior of every
  invocation instead of an opt-in flag — a caller who runs a plain `spec-check.py <spec-dir>`
  after writing/updating `00_state.md`, `04_tasks.md`, or `05_execution.md` now gets a current
  sidecar without having to remember the flag, closing the exact failure mode where a phase
  wrote `00_state.md` and validated it, but never regenerated `00_state.json` because the flag
  was omitted. Implicit (flag-omitted) emission is best-effort: a source doc not yet in
  canonical shape (e.g. `00_state.md` before its Gate table is filled in) downgrades the failure
  to a warning rather than failing an ordinary check that never asked for JSON at all. Added
  `--check-only` for validation without writing (e.g. a CI gate that must fail on a sidecar
  someone forgot to regenerate, rather than silently repairing it); pass `--emit-json` explicitly
  when a malformed-source build failure should be fatal instead of a warning.
- Fixed `04_tasks.md` and `03_design.md` in the `orca-agent-orchestration` dogfood spec to use
  the `task_categories` vocabulary (`quick_lookup`/`code_analysis`/`heavy_reasoning`/`review`)
  `model-router.py` actually validates against, instead of an informal vocabulary
  (`architecture_design`/`core_logic`/`unit_test`) that predates it. Regenerated its sidecars,
  renamed its `run-orca-1` execution run ID to the `run-<timestamp>Z` format `spec-check.py`
  enforces, and moved its Audit gate status from `approved` to the canonical `passed`.

## [1.0.0] - 2026-08-09

Initial release: the spec-driven development skill family for Claude Code / Agent Skills —
`spec-steering`, `spec-discovery`, `spec-requirements`, `spec-design`, `spec-tasks`, `spec-audit`,
`spec-execute`, `spec-debugging`, `spec-verification`, `spec-finish`, `spec-hooks`, and the
`spec-driven` router skill, plus the standalone `dependency-security-audit` skill. Established
the phase-gated `.specs/<slug>/` artifact layout (`00_state.md` through `05_execution.md`), EARS
acceptance criteria, deterministic Mermaid diagram generation, and the `spec-family.yaml`
model-routing contract.
