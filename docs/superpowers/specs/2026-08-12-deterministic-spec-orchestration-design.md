# Deterministic Spec Orchestration Design

## Purpose

Make the spec-driven workflow cheaper, more reliable, and easier to follow. Agents retain
judgment for ambiguous discovery and design decisions; deterministic scripts own validation,
routing, scheduling, rendering, execution bookkeeping, and checkpoint advancement.

## Goals

- Detect structural and traceability errors before agents write long-form Markdown or dispatch work.
- Author compact structured facts once, then derive Markdown, prompts, diagrams, schedules, and
  execution views deterministically.
- Execute every safe set of tasks concurrently through Orca with minimal human interruption.
- Keep generated documents concise, visual, current, and readable without duplicating the same
  information in multiple diagrams.

## Non-goals

- Eliminate agent judgment from discovery, design trade-offs, or exception resolution.
- Permit automatic external, irreversible, credentialed, or policy-changing actions.
- Require a new third-party Python dependency for schema validation or scheduling.

## Sources of Truth

`04_tasks.json` is the stable plan source: task IDs, titles, stages, dependencies, ownership,
interfaces, verification, risk, and execution requirements. It does not track live execution
state.

`05_execution.json` is the execution source: append-only task attempts, runs, verification
evidence, checkpoint commits, and a generated current-status projection. Its `task_status` view
is computed from attempts and gates, never separately maintained by an agent.

The status projection contains a task ID, lifecycle state (`blocked`, `ready`, `running`,
`failed`, or `done`), current attempt, evidence reference, update timestamp, and blockers. A task
attempt is the event record; task status is the deterministic materialized view.

## Deterministic Wave Scheduler

A wave is a set of ready tasks that may run concurrently. It is distinct from a lifecycle state.
The scheduler computes waves from the task DAG, completed status, declared file/component
ownership, explicit serialization constraints, and compatible agent profiles.

Every computed wave records its task IDs, parallel/serial mode, agent/model profile,
worktree/sandbox/permission settings, owned-path leases, and an explanation of why it is safe.
Conflicting ownership, unresolved dependencies, or incompatible permissions block dispatch;
the scheduler never silently chooses an unsafe fallback.

## Autonomous Execution and Checkpoints

For each wave, Orca dispatches compatible tasks into isolated worktrees. Workers commit their
scoped changes or record a verified no-change result. The controller then integrates commits in
stable task-ID order, stages only declared owned or generated paths, runs wave verification,
creates a checkpoint commit, and records its SHA and evidence in `05_execution.json`.

The next wave unlocks only after this checkpoint succeeds. Ordinary completion, retries,
rendering, validation, staging, commits, and next-wave dispatch remain autonomous. Human action
is requested only for explicit exception gates: irreversible/external actions, scope-changing
ambiguity, unresolvable integration conflict, exhausted retry budget, or permission/sandbox
escalation.

## Generated Documentation

Generated Markdown uses progressive disclosure.

- `04_tasks.md` owns a generated **Task Views** region with two collapsibles: an ELK-laid-out
  dependency flowchart and a Kanban work board. Both derive from the same task DAG and execution
  status projection. The flowchart answers dependency questions; the Kanban answers current-work
  questions.
- `05_execution.md` owns the execution ledger and exactly one generated Gantt, derived from the
  same attempt/run data. The optional delivery-schedule Gantt is removed.
- Visual status uses text/icon plus color. Diagram generators enforce stable IDs, bounded labels,
  no duplicated generated sections, and render validation. Dense views are split by wave or
  component rather than compressed into unreadable diagrams.

Each generated region has a manifest of its exact input sidecars and canonical source digests.
This replaces circular Markdown-to-JSON mutual hashes: a renderer can recreate and compare a
region from its source, while live execution updates do not falsely stale the static plan body.

## Efficiency Rules

- Validate parsed sidecars once per run and share the in-memory payload with schema,
  traceability, readiness, scheduling, and rendering.
- Build subagent prompts only for ready tasks, using a deterministic manifest of required files
  and relevant contract fragments; do not resend full specs or unrelated profile matrices.
- Debounce the watcher and skip render/write work unless a canonical input digest changes.
- Use compact readiness output at task checkpoints; reserve full DAG output for planning and
  scheduling.
- Preserve existing in-process model-routing resolution and extend that approach to all repeated
  pure computations.

## Skill Publication and Updates

Every skill package has a small publication manifest containing its name, semantic version,
distribution channel, source URL, artifact digest, minimum compatible runtime, and release notes.
At invocation, the runtime performs a lightweight manifest check before loading the workflow. If a
newer compatible release exists, it downloads into a temporary location, verifies the declared
digest and compatibility, acquires an update lock, and atomically replaces the installed package.
The invocation then runs the newly verified version.

An unavailable registry, network failure, invalid manifest, digest mismatch, or locked concurrent
update never blocks normal work: the runtime continues with the known installed version and emits
a concise update diagnostic. An incompatible major release or any migration that would change
local configuration is an exception gate and requires explicit approval. Update checks must never
execute unverified package code or overwrite a locally modified skill; local modifications are
reported and preserved for a deliberate merge or reinstall.

## Validation and Measurement

Validation rejects schema violations, dangling cross-artifact citations, stale generated regions,
ownership collisions, invalid task status transitions, uncommitted wave advancement, and missing
checkpoint evidence.

The implementation records baseline and post-change metrics: prompt/context bytes, repeated
reference reads, render invocations, validation duration, retries, integration conflicts, and
human-intervention rate. Success requires no LLM call for deterministic transforms, no next-wave
dispatch without a verified checkpoint, and no generated visual that disagrees with its sidecars.

## Rollout

Land the control plane first: schemas, canonical status projection, wave scheduling, checkpoints,
and validation. Then migrate renderers and compact Markdown templates. Add the publication
manifest and safe invocation-time update path before distributing the revised skill. Finally
migrate the Orca example spec and run an end-to-end throwaway spec through discovery, planning,
execution, and audit.
