# Requirements: Orca Multi-Agent Task Orchestration

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md) · [Execution](05_execution.md)
<!-- spec-nav:end -->

## Introduction

This specification defines the functional and operational requirements for integrating Orca task orchestration into the [`spec-driven`](../../spec-driven/SKILL.md) development skills family. It establishes deterministic task DAG synchronization, unattended agent CLI flag profiles, isolated worktree worker placement, structured inter-agent messaging, decision gates for checkpoints, and telemetry reconciliation with graceful local fallback.

> [!IMPORTANT]
> Approval gate: approve these requirements before work begins on [03_design.md](03_design.md).

## Requirements

### Requirement 1: Orca Runtime Adapter Contract and Agent CLI Profiles
**User Story:** As a spec-driven developer or agent, I want the spec family contract to define the Orca runtime adapter and canonical unattended CLI flag profiles across supported coding agents, so that multi-agent dispatches run without interactive terminal freezes.

#### Acceptance Criteria
1. **R1.1** WHEN the spec family contract is evaluated, THE [`spec-driven/contracts/spec-family.yaml`](../../spec-driven/contracts/spec-family.yaml) contract SHALL define the `orca` runtime adapter with capabilities for runs, task DAGs, dispatches, decision gates, and worktree isolation.
2. **R1.2** WHEN agent CLI launch arguments are resolved for Claude Code, THE adapter profile SHALL include `--dangerously-skip-permissions` for implementers and read-only tool allowlists for reviewers.
3. **R1.3** WHEN agent CLI launch arguments are resolved for OpenAI Codex, THE adapter profile SHALL include `--full-auto` or `--approval-level never`.
4. **R1.4** WHEN agent CLI launch arguments are resolved for Google Antigravity, THE adapter profile SHALL include `--yolo` or `--auto-approve`.
5. **R1.5** WHEN agent CLI launch arguments are resolved for Cursor CLI, THE adapter profile SHALL include `--approve-all` and `--headless`.

### Requirement 2: Task DAG Ingestion and Orca Run Synchronization
**User Story:** As an execution coordinator, I want a deterministic bridge utility to read `04_tasks.json` and register the complete task graph in Orca, so that dependencies, parent-child hierarchies, and checkpoints are faithfully represented in the Orca runtime.

#### Acceptance Criteria
1. **R2.1** WHEN `scripts/spec-orca.py sync` is invoked with a spec directory, THE bridge utility SHALL read `04_tasks.json` and create or bind an Orca Run via `orca orchestration run-create` or `run-use`.
2. **R2.2** WHEN tasks are registered in Orca, THE bridge utility SHALL map each task's `depends_on` array to Orca prerequisite task IDs using `--deps`.
3. **R2.3** WHERE a task in `04_tasks.json` defines a parent stage or task, THE bridge utility SHALL bind the child task to its parent using `--parent`.
4. **R2.4** WHERE [04_tasks.md](04_tasks.md) contains a Checkpoint group, THE bridge utility SHALL register an Orca decision gate using `orca orchestration gate-create`.
5. **R2.5** IF `04_tasks.json` is missing or its hash does not match [04_tasks.md](04_tasks.md), THEN THE bridge utility SHALL reject synchronization and exit with a stale sidecar error.

### Requirement 3: Deterministic Worker Placement and Worktree Isolation
**User Story:** As an execution coordinator, I want to dispatch workers according to their `Delegation` and model-routing metadata, so that parallel tasks run safely in isolated child worktrees without filesystem conflicts.

#### Acceptance Criteria
1. **R3.1** WHEN a task with `Delegation: parallel-safe` is dispatched, THE coordinator SHALL launch the worker in an isolated child worktree using `orca orchestration worker-start --worktree new-child --setup run`.
2. **R3.2** WHEN a task with `Delegation: sequential subagent` is dispatched, THE coordinator SHALL launch the worker in the current worktree using `orca orchestration worker-start --worktree current`.
3. **R3.3** WHEN launching a worker terminal, THE coordinator SHALL resolve model and effort flags from the task's `resolved_model` and `reasoning_level` fields.
4. **R3.4** WHILE launching a worker via custom terminal command, WHEN the terminal process starts, THE coordinator SHALL wait for `tui-idle` before injecting the task brief.

### Requirement 4: Supervised Worker Lifecycle and Structured Return Protocol
**User Story:** As an execution coordinator, I want supervised workers to communicate status, questions, and completion through structured Orca messages, so that execution progress and evidence are tracked deterministically.

#### Acceptance Criteria
1. **R4.1** WHEN an implementer finishes a task attempt, THE worker SHALL send a `worker_done` message with an explicit outcome and structured payload containing criteria results, changed files, and verification evidence.
2. **R4.2** WHILE supervising active workers, WHEN the coordinator waits for events, THE coordinator SHALL invoke `orca orchestration check --wait --types worker_done,escalation,question`.
3. **R4.3** WHEN a worker sends an `ask` message, THE coordinator SHALL process the question and reply via `orca orchestration reply`.
4. **R4.4** WHEN a `worker_done` report is accepted, THE coordinator SHALL release the settled worker terminal using `orca orchestration worker-release`.
5. **R4.5** IF a worker dispatch fails or crashes, THEN THE coordinator SHALL capture the buffered terminal transcript, record failure evidence in [05_execution.md](05_execution.md), and initiate a bounded repair attempt within `self_repair_rounds`.

### Requirement 5: Parallel Multi-Lens Audit and Hardening
**User Story:** As a reviewer or audit coordinator, I want to dispatch parallel reviewer agents across independent audit lenses, so that spec artifacts are thoroughly vetted without polluting coordinator context.

#### Acceptance Criteria
1. **R5.1** WHEN [`spec-audit`](../../spec-audit/SKILL.md) is invoked, THE coordinator SHALL resolve reviewer fan-out via [`spec-driven/scripts/fanout.py`](../../spec-driven/scripts/fanout.py) and dispatch independent reviewer workers in parallel Orca terminals.
2. **R5.2** WHEN a reviewer completes its evaluation, THE reviewer SHALL return a structured `review_verdict` payload conforming to [`spec-driven/contracts/spec-family.yaml`](../../spec-driven/contracts/spec-family.yaml).
3. **R5.3** WHEN all reviewer reports settle, THE coordinator SHALL merge findings into deduplicated CERTAIN and UNCERTAIN categories and update [00_state.md](00_state.md).

### Requirement 6: Telemetry Synchronization and Graceful Fallback
**User Story:** As a developer resuming execution, I want Orca run telemetry synchronized with [05_execution.md](05_execution.md) / `05_execution.json` and a reliable fallback when Orca is not installed, so that execution state remains durable and portable across environments.

#### Acceptance Criteria
1. **R6.1** WHEN a task dispatch settles, THE coordinator SHALL record observed start and stop timestamps from Orca dispatch telemetry into [05_execution.md](05_execution.md) and regenerate `05_execution.json`.
2. **R6.2** WHERE the `orca` binary is not present on the host system, THE skills SHALL execute tasks sequentially in standard local mode without error.
3. **R6.3** WHEN resuming an interrupted execution run, THE coordinator SHALL rebind to the existing Orca Run using `orca orchestration run-use` and reconcile task states against `04_tasks.json`.

### Requirement 7: Comprehensive JSON Sidecars and Sidecar-First Testing
**User Story:** As a developer or autonomous toolchain, I want all spec phases to produce and validate machine-readable JSON sidecars via deterministic scripts, so that traceability, audit analysis, and Orca execution are tested against structured data models before and alongside Markdown documentation.

#### Acceptance Criteria
1. **R7.1** WHEN spec artifacts are validated or emitted, THE [`spec-driven/scripts/spec-check.py`](../../spec-driven/scripts/spec-check.py) script SHALL support JSON sidecars across discovery ([`01_discovery.json`](sidecars/01_discovery.json)), requirements ([`02_requirements.json`](sidecars/02_requirements.json)), design (`03_design.json`), tasks (`04_tasks.json`), state ([`00_state.json`](sidecars/00_state.json)), and execution (`05_execution.json`).
2. **R7.2** WHEN `03_design.json` is generated, THE sidecar SHALL structure architecture components, correctness properties with `validates` requirement references, current technology evidence, and dependency security evidence.
3. **R7.3** WHEN `04_tasks.json` is generated, THE sidecar SHALL include Orca dispatch configuration, unattended agent CLI flags, and explicit dependency IDs.
4. **R7.4** WHEN [`spec-audit`](../../spec-audit/SKILL.md) evaluates a spec, THE audit toolchain SHALL support emitting a structured `audit_findings.json` sidecar classifying P0/P1/P2 findings and CERTAIN/UNCERTAIN fixes.
5. **R7.5** WHILE verifying traceability, THE [`spec-driven/scripts/spec-check.py`](../../spec-driven/scripts/spec-check.py) script SHALL perform 3-way in-memory validation among [`02_requirements.json`](sidecars/02_requirements.json), `03_design.json`, and `04_tasks.json`.

### Requirement 8: Formal JSON Schema System and Dedicated Sidecar Directory
**User Story:** As a developer or toolchain maintainer, I want formal JSON Schemas for all sidecars and a clean folder separation between human-facing Markdown docs and machine-readable sidecars, so that data integrity is strictly enforced.

#### Acceptance Criteria
1. **R8.1** WHEN JSON sidecars are defined or generated, THE [`spec-driven/contracts/schemas/`](../../spec-driven/contracts/schemas) directory SHALL provide formal JSON Schemas for each sidecar artifact.
2. **R8.2** WHEN sidecars are saved in a feature directory, THE sidecar files SHALL be stored in a dedicated `.specs/<slug>/sidecars/` directory separate from the Markdown documentation in `.specs/<slug>/`.
3. **R8.3** WHEN `spec-check.py` validates sidecars, THE script SHALL validate each sidecar against its corresponding JSON Schema.

### Requirement 9: Deterministic and Scripted Gantt Chart Generation
**User Story:** As an execution coordinator or viewer, I want execution Gantt charts to be generated and refreshed automatically by a deterministic script whenever schedules or timing intervals change, so that progress visualization is always accurate and syntax-error-free.

#### Acceptance Criteria
1. **R9.1** WHEN execution intervals or schedules update in `05_execution.json` or [`sidecars/04_tasks.json`](sidecars/04_tasks.json), THE system SHALL automatically generate and refresh the Mermaid `gantt` chart via script.
2. **R9.2** WHEN generating Mermaid Gantt source, THE generator script SHALL validate syntax deterministically, handle sub-second or 0-second intervals safely, format dates without manual transcription, and inject the validated fenced block into [05_execution.md](05_execution.md).
3. **R9.3** IF a generated Mermaid Gantt fails syntax validation, THEN THE generator script SHALL reject the invalid diagram and preserve diagnostic failure evidence without corrupting the execution ledger.

### Requirement 10: Budget, Quota, and Usage-Aware Model Routing and Deferred Scheduling
**User Story:** As an orchestration operator or automated developer, I want the system to check remaining credits, usage limits, and provider quotas to intelligently select models and defer execution when budget or rate limits require it, so that orchestration optimizes cost and avoids hard exhaustion failures.

#### Acceptance Criteria
1. **R10.1** WHEN resolving task models or preparing dispatch envelopes, THE system SHALL inspect remaining credits, token budget, or provider usage constraints.
2. **R10.2** IF credits or quota limits are constrained below threshold levels, THEN THE model router SHALL dynamically down-tier lower-complexity task categories to budget-efficient models while preserving high-tier reasoning for core logic.
3. **R10.3** IF provider credits or quota limits are exhausted or rate-limited, THEN THE orchestration engine SHALL pause execution and schedule resumption for a later time with persistent state checkpoints.
