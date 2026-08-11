---
name: spec-tasks
description: Use when breaking an approved design into an implementation plan for spec-driven development — a dependency-ordered checkbox task list with requirement traceability and checkpoints, in 04_tasks.md (phase 4). Triggers on "write tasks", "04_tasks.md", "break down the design", or after a design is approved.
---

# Spec Tasks (Phase 4)

Turn approved `03_design.md` into `04_tasks.md`: discrete, dependency-ordered, checkbox tasks that
`spec-execute` can implement one at a time, each tracing back to requirements.

> [!IMPORTANT]
> Read the approved `01_discovery.md`, `02_requirements.md`, and `03_design.md` first. Do not begin
> implementation until the user approves `04_tasks.md`.

**Core principle:** Each leaf task is a small, verifiable unit of implementation work — a
coding step, not a vague goal. The list is ordered so no task depends on a later one, and
together the tasks cover every requirement criterion.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-design`](../spec-design/SKILL.md) ·
[`spec-execute`](../spec-execute/SKILL.md) · [`mermaid`](../mermaid/SKILL.md) ·
[`context7-mcp`](../context7-mcp/SKILL.md) ·
[`dependency-security-audit`](../dependency-security-audit/SKILL.md) ·
[`code-documenting`](../code-documenting/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md)

**REQUIRED first:** read `00_state.md`, the feature's approved `01_discovery.md`, `03_design.md`,
and `02_requirements.md`. Require Discovery, Requirements, and Design to be `approved`. Resolve the active `spec-driven`
skill directory and use its `references/artifacts.md` template; never assume a tool-specific
home-directory path.

## Workflow

1. **Derive tasks from the design**, grouped by component/milestone. Number them (1, 1.1, 1.2…).
2. For each leaf task, specify **what to build and where** (file(s), function(s)/interfaces
   from the design) and its sub-steps — concrete enough to implement without re-deriving the design.
  Add one **Interfaces** field in the exact form
  `Consumes: <exact inputs/contracts>; Produces: <exact outputs/contracts>`. Name the concrete
  prior-task outputs, artifacts, symbols, signatures, schemas, commands, or observable behavior;
  “implement the design” is not an interface contract. Copy exact signatures and values from the
  approved design rather than making the implementer infer them.
   For brownfield work with a current `codebase-memory-mcp` index, invoke
   `codebase-memory-reference` and verify named symbols, file ownership, affected callers, and
   dependency order against the graph; use source inspection when the graph is inconclusive.
   When the task applies a library, framework, SDK, API, CLI, or cloud-service behavior that
   can evolve, include a sub-step to consult the design's Current Technology Evidence and use
   `context7-mcp` again if its version or question has changed.
   Every leaf declares **Dependency resolution** (`none` or `change`) and **Dependency delivery**
  (`none`, `main`, or `release`); missing fields block readiness. Apply
  [dependency-evidence.md](../spec-driven/references/dependency-evidence.md) when either field is
  not `none`. Shared resolution ownership is not `parallel-safe`.
3. **Make the task contract executable.** Every leaf declares **Files** (comma-separated exact
   owned paths), **Dependency resolution**, **Dependency delivery**, and **Stage**; every later-stage leaf also declares **Depends on**,
  **Interfaces**, **Documentation**, **Verification**, **Estimated effort** (a bounded duration or range),
  **Risk** (including rollback/migration note where
   applicable), **Task category**, and **Delegation** (`controller`, `sequential subagent`, or `parallel-safe`).
   For code-producing tasks, Documentation identifies the public APIs/modules and the contract +
   rationale comments required by `code-documenting`; explicitly state `no public surface` only
   for genuinely trivial private-only work. Default to
   sequential; call something parallel-safe only when its ownership/files and verification are
   disjoint from every concurrent task. Do not mark tasks parallel-safe when they can touch the
   same file, directory-owned generated output, lockfile, schema/migration chain, snapshot set,
   shared test state, or repo-wide formatter/build mutation.
   In `Files` and task prose, render every path that already exists as a Markdown link with its
   project-relative path as the label. Leave planned, nonexistent paths as inline code.
   **Task category** is one of `quick_lookup` / `code_analysis` / `heavy_reasoning` / `review`
   (`contracts/spec-family.yaml`'s `task_categories`, next to Risk and Delegation) — declare it by
   judging what kind of work the leaf actually is, the same judgment call `declared_risk` already
   is elsewhere; never pick it to force a particular model or reasoning level. `--emit-json`
   (step 7) resolves it, together with the leaf's `Risk` word, to a
   `capability_tier`/`resolved_model` AND an independent `reasoning_level` in `04_tasks.json` by
   calling `scripts/model-router.py`'s `resolve()` — you do not resolve or name a model or
   reasoning level yourself here. The two axes are not the same thing (see
   [model-routing.md](../spec-driven/references/model-routing.md)): a `heavy_reasoning` task
   always resolves to `frontier`/`high` at minimum, while a `code_analysis` task resolves to
   `balanced`/`medium` — both can escalate further, independently, when `Risk` is elevated.
4. **Trace:** append `_Requirements: X.Y_` to each task, citing the criteria it satisfies.
5. **Build the dependency graph and order it topologically.** Assign stage 1 to dependency-free
   tasks and stage `1 + max(dependency stages)` to dependent tasks. A Stage 1 leaf may omit
   `Depends on`, although explicit `Depends on: none` is preferred for human clarity. Every
   later-stage leaf must list its prerequisite task IDs. List tasks in non-decreasing stage order,
   with every dependency earlier than its dependent. Never rely on prose or list position as an
   implicit dependency for later stages.
  When the plan has multiple stages, dependency edges, or checkpoints, add a
  **Stage and Dependency Overview** before the checklist, generated deterministically via
  `scripts/render-gantt.py <spec-dir> --write` (or `--flowchart-only`):
  derives `04_tasks.json`'s stages into subgraphs, one node per task (`tasks[].id`/`title`), and
  dependency edges. Color-codes task nodes using the standard 4-color status palette:
  - **Grey (`pending`)**: `fill:#f1f5f9,stroke:#94a3b8` — tasks not yet started, ready, or queued.
  - **Red (`failed`)**: `fill:#fee2e2,stroke:#ef4444` — tasks that failed verification or encountered critical defects.
  - **Amber (`in_progress`)**: `fill:#fef3c7,stroke:#f59e0b` — tasks currently executing in an active wave.
  - **Green (`done`)**: `fill:#dcfce7,stroke:#22c55e` — verified completed tasks with checked status.
  Label task nodes with the task ID and a concise title; include every leaf and every declared dependency exactly once.
  The generator emits `%%{init: {'flowchart': {'defaultRenderer': 'elk'}}}%%` ahead of `flowchart TD`
  so multi-stage dependency graphs render with the ELK layout instead of dagre — these graphs
  routinely have enough subgraphs/edges to cross lines under the default layout (see the `mermaid`
  skill's ELK guidance). Don't strip that line by hand; it's regenerated on every run.
  `spec-execute` regenerates this diagram (fresh status colors) at the same points it refreshes
  the Execution Gantt — a checkpoint, an intentional return, or run completion — not after every
  single task, so the diagram stays live without a render-validate cycle on every checkbox flip.
  The checklist (via the sidecar) is authoritative: the
  diagram must not add dependencies, dates, estimates, or implied ordering beyond what the
  sidecar declares. Node `status` is the one exception, and only because it is itself read
  straight from the same sidecar's `checked`/`concurrency` fields rather than added by hand.
  Omit it for a trivial single-stage plan with no checkpoint. A block diagram is not the default
  here because task dependencies are a graph rather than static composition.
  Add a **Delivery Schedule** table derived from leaf estimates and dependencies, with stage,
  task, estimate, dependencies, and critical-path status. Add a Mermaid `gantt` only when confirmed
  dates exist; otherwise use duration-only planning and never invent calendar dates.
6. **Make verification required.** Mark tests needed to prove a behavioral requirement as `[ ]`;
   reserve `[ ]*` for genuinely optional exploratory or extra-coverage work. Add a **`Checkpoint`**
   group only where a pause earns its place — a protected-main/release delivery gate, an
   irreversible operation, or a milestone materially large enough that silently continuing past it
   risks more than pausing costs. `spec-execute` already runs continuously through every task
   between checkpoints by default, so each `Checkpoint` you add is a deliberate interruption, not a
   routine progress ping; minimize their count rather than sprinkling one at every milestone.
  Protected-main and release delivery leaves declare `main` and `release` and apply
  [dependency-evidence.md](../spec-driven/references/dependency-evidence.md). Keep broad security
  review as a separate checkpoint concern.
7. **Coverage and dependency check:** run `scripts/spec-check.py <spec-dir>` and ensure every
   requirement criterion is covered by ≥1 task, every task cites a real requirement, and the task
   graph has no missing IDs, duplicate IDs, self-dependencies, cycles, stage errors, or forward
   dependencies. It also rejects identical or nested owned paths among same-stage parallel-safe
   tasks and globs in parallel ownership. Use `--format json` when another script needs the normalized
   task graph ephemerally. Its `execution` object identifies the active stage and ready
   parallel/serial candidates from the current checkboxes. The Markdown fields stay canonical —
   you author and read them — but once the check passes, run `scripts/spec-check.py <spec-dir>
   --emit-json` to (re)generate the persisted `04_tasks.json` sidecar (schema:
   `spec-driven/references/artifacts.md`'s **JSON sidecars** section). Never hand-maintain that
   file: regenerate it in the same step whenever `04_tasks.md` changes, including every edit made
   while resolving audit/review feedback before the approval gate below. `--ready` (used later by
   `spec-execute`) fails if the sidecar's `generated_from.sha256` goes stale.
8. **Write** the project-local `.specs/<slug>/04_tasks.md`, update the adjacent `00_state.md`,
   and make the checklist readable without the design conversation: use concise action-oriented
   task names, explain non-obvious verification and risk notes, and keep checkpoints obvious.
   Apply the shared artifact content rule: retain executable contracts, dependencies, risks, and
   expected verification; omit planning-tool narration, generation/validation commentary, agent
   workflow notes, and other process metadata that does not help a human execute the plan.
   Run `scripts/spec-nav.py <spec-dir> --write` before the final `spec-check.py` gate so every
   existing numbered artifact has current cross-links, then run `scripts/spec-check.py <spec-dir>
   --emit-json` last so `sidecars/04_tasks.json` is generated from the exact Markdown text — navigation
   included — conforming to [`spec-driven/contracts/schemas/04_tasks.schema.json`](../spec-driven/contracts/schemas/04_tasks.schema.json).
   Then **gate — get approval:**
   > "Tasks written to `.specs/<slug>/04_tasks.md`. Review and approve, or request changes, before implementation."
   Revise until approved. Mark Tasks `approved` only after user acceptance; set Audit to
   `not_run` and invalidate Execution whenever a material task revision occurs.

## Rules

- **Right size:** a leaf task should be implementable and verifiable in one focused pass. Too
  big → split; trivially small → merge.
- **Only coding/verification tasks.** No "research" or "think about" tasks — those belong in design.
- **Every task earns its place** via a requirement citation; every criterion is covered.
- **Estimates are explicit uncertainty.** Use bounded effort ranges based on the concrete task
  contract. They support scheduling, not completion claims; actual timing belongs in execution.
- **Dependencies are executable.** Every leaf has one integer `Stage` field. Dependency-free work
  is Stage 1 and may omit `Depends on`; omission means an empty dependency list. Dependent work
  must declare `Depends on`, occupy the exact next graph layer, and appear after every prerequisite.
- **Topology is derived.** When present, `Stage and Dependency Overview` mirrors the checklist's
  task IDs, stages, dependencies, and checkpoint placement. It is a human navigation aid, never a
  second task graph or progress tracker.
- **Parallel-safe is a proof obligation.** It means the task can run in an isolated worktree at
  the same time as another ready task without overlapping owned files, mutable external state,
  generated artifacts, verification side effects, or an unfrozen interface decision. The
  checker-preserved `Delegation` values are portable scheduling labels; runtime adapters decide
  whether a separate worker is worthwhile, and resolve its model deterministically via
  [`spec-driven`'s model routing](../spec-driven/references/model-routing.md) rather than naming a
  model/tool allowlist in the task itself.
- **New code is documented as part of the task.** Public functions, classes, modules, and files
  need native doc comments that explain their contract and why; a signature restatement is not
  documentation. The Verification field must include a documentation review.
- **Dependency resolution ownership is explicit.** Enforce
  [dependency-evidence.md](../spec-driven/references/dependency-evidence.md) when applicable.
- Keep `[ ]` boxes intact and unchecked — `spec-execute` checks them off as it verifies.

## Next

On approval → **`spec-execute`**.

## Red flags — STOP

- A task with no `_Requirements:_` line → it's unjustified or a requirement is missing.
- Task 2 needs something built in task 5 → reorder; dependencies point backward only.
- A later-stage dependency is implied by prose but absent from `Depends on` → add it and recompute stages.
- A task's declared stage differs from its computed dependency layer → fix the graph before approval.
- A requirement criterion no task covers → add the task before the gate.
