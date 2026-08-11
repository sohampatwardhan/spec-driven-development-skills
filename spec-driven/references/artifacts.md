# Spec artifacts — layout, templates, and traceability

## Layout

```
.specs/
  steering/
    product.md      # what the product is, who it's for, goals
    tech.md         # stack, libraries, commands, constraints
    structure.md    # directory layout, key modules, conventions
  <feature-slug>/
    00_state.md
    01_discovery.md
    02_requirements.md
    03_design.md
    04_tasks.md
    05_execution.md
    execution/              # task briefs, reports, and review evidence
```

`<feature-slug>` is kebab-case (e.g. `github-issue-automation`). One folder per feature.
When working inside a project or repository, locate its root and create `.specs/` there before
writing the first planning artifact. Keep all six numbered planning files for a feature together
under `.specs/<feature-slug>/`: `00_state.md`, `01_discovery.md`, `02_requirements.md`, `03_design.md`,
`04_tasks.md`, and `05_execution.md`. Do not place them in a global skills directory, home-level
scratch space, `work/`, or a deliverables folder. Honor a different project-local location only
when explicit repository policy requires it.

## Human-readable artifact standard

Write every numbered Markdown artifact for a human collaborator who must review decisions and
resume the work later. Use a descriptive title, meaningful headings, short paragraphs, lists or
tables where they improve scanning, and enough context to understand why a decision exists.
Define project-specific terms on first use, distinguish facts from assumptions, and make approval
state, open questions, risks, and next actions obvious. Prefer links and concise summaries over
raw tool output. Never leave model-oriented notes, hidden reasoning, prompt fragments, unexplained
abbreviations, or placeholder text in an artifact presented for review.

Include only content that helps a human understand the subject, evaluate a decision, execute the
work, verify an outcome, or resume later. Exclude non-material process metadata: tool-call
narration, agent workflow commentary, checker or renderer provenance, statements that content was
generated/rendered/validated, raw command transcripts, and mechanical timestamps. Keep material
evidence such as approval dates, release/security freshness, decisions, failures, verification
outcomes, and reproducible commands, but state the useful result rather than narrating the tool
process that produced it.

## Clickable navigation and repository references

Every existing numbered artifact must contain the same generated navigation block immediately
after its H1. Include only numbered artifacts that currently exist, in `00` through `05` order,
and retain the current document's self-link for consistency:

```markdown
<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md)
<!-- spec-nav:end -->
```

After creating any numbered artifact, run `scripts/spec-nav.py <spec-dir> --write`; this refreshes
the block in every existing numbered artifact. `scripts/spec-check.py <spec-dir>` rejects missing,
stale, duplicated, or misplaced navigation and broken local links.

When a numbered artifact references a project file or directory that already exists, make the
reference clickable. Keep the human-readable label project-root-relative and make the target
relative to `.specs/<feature-slug>/`, normally two levels up:

```markdown
[`src/auth/session.ts`](../../src/auth/session.ts)
```

This applies to design evidence, component descriptions, task `Files` entries, execution evidence,
and state/change-control notes. A path that does not exist yet may remain inline code until it is
created; refresh it to a link during execution once it exists. Commands, globs, placeholders,
URLs, code symbols, and fenced code examples are not file references. The checker flags unlinked
inline-code paths when they resolve to existing project entries.

## State and execution evidence

`00_state.md` is the phase-gate record. Keep it current whenever an artifact is
approved, invalidated, audited, blocked, or resumed. `05_execution.md` is the
durable execution ledger; `04_tasks.md` remains the concise user-facing board. Both must be
understandable without reconstructing the agent's prior conversation.

```markdown
# Spec State: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md)
<!-- spec-nav:end -->

| Gate | Status | Evidence |
|---|---|---|
| Discovery | draft / approved / invalidated | <approval date or reason> |
| Requirements | draft / approved / invalidated | <approval date or reason> |
| Design | not_started / draft / approved / invalidated | <approval date or reason> |
| Tasks | not_started / draft / approved / invalidated | <approval date or reason> |
| Audit | not_run / passed / findings_open / fixes_applied | <audit date, depth, artifact digest, or applied-fixes evidence> |
| Execution | not_started / in_progress / blocked / complete | <active task or checkpoint> |

## Change Control

- <material change, impacted artifacts, re-approval required>
```

```markdown
# Execution Ledger: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md) · [Execution](05_execution.md)
<!-- spec-nav:end -->

## Active Wave

| Task | Stage | Mode | Branch / worktree | State |
|---|---:|---|---|---|
| 1.1 | 1 | parallel-safe / sequential | `<branch>` / `<path>` | dispatched / review / integrated |

| Task | Status | Commit / diff | Verification | Reviewer | Notes |
|---|---|---|---|---|---|
| 1.1 | not_started | — | — | — | — |

## Baseline

| Revision | Command | Exit | Pre-existing failures |
|---|---|---:|---|
| `<commit>` | `<full test/build command>` | `<exit>` | <none or exact failures> |

## Execution Timing

### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|

### Execution Gantt
<Validated Mermaid `gantt`, generated from `05_execution.json`'s `gantt` IR object via
`mermaid/scripts/render.py --target gantt` (never hand-transcribed from the tables above), then
render-validated exactly as before.>

### Task Board (conditional, execution-only)
<Validated Mermaid `kanban`, present only when the spec also carries a `04_tasks.md` dependency
flowchart. Grouped into Pending/In Progress/Failed/Done columns derived from `04_tasks.json` and
`05_execution.json` by `spec-driven/scripts/render-gantt.py`'s `build_kanban_board_from_tasks_data`
— the same `derive_task_statuses` helper the flowchart uses, so the two views never disagree on
status. Mermaid kanban has no render-validated per-card `style`/`classDef` mechanism, so each card
carries a colored-circle emoji (⚪🟠🔴🟢) matching the flowchart's pending/in_progress/failed/done
palette instead of a literal fill/stroke color. Hand-authored deterministically rather than via
`mermaid/scripts/render.py`, because the `mermaid` skill's IR has no `kanban` family yet; still
render-validate the exact generated source before saving. Supplements, never replaces, the required
flowchart.>

## Checkpoints

- <checkpoint, decision, date>

## Integration Decision

- Status: pending / merged-local / pull-request / kept
- Base: `<branch>`
- Result: `<commit-or-URL>`
- Post-integration verification: pending / passed / failed

## Delivery Schedule (optional)

<Add a rendered `gantt` only when confirmed dates, dependencies, milestones, or critical work
materially affect execution. Do not invent dates; use the task ledger as the source of truth.>
```

## Traceability chain (bidirectional)

Requirement criterion → design property → task, each citing the last:

```
02_requirements.md:  R1.2  (Requirement 1, criterion 2)
03_design.md:        **Validates: Requirements 1.2, 5.5**
04_tasks.md:         _Requirements: 1.2, 5.5_
```

Every criterion should be validated by at least one design property and covered by at
least one task. Every task should cite the requirement(s) it satisfies. No orphans.

The approved discovery decision precedes this chain: its problem boundary, non-goals, and chosen
direction constrain requirements and design. A material change returns to discovery and invalidates
downstream approvals.

## JSON sidecars (generated, hash-verified)

Numbered artifacts have a JSON twin: a pure derived artifact of the Markdown, never
hand-maintained, always regenerated in the same step the Markdown changes. This mirrors how
`spec-nav.py`'s navigation blocks work — generated, and `spec-check.py` fails the check if a
sidecar goes stale — except a sidecar's absence is not itself an error; only an existing sidecar
whose `generated_from.sha256` no longer matches its Markdown twin's current content, or one whose
Markdown twin has disappeared, is.

- `00_state.json` — derived from `00_state.md`, written by `scripts/spec-check.py <spec-dir>
  --emit-json`. The one sidecar `--ready` gate-checking cares about; see the `Gate` note below.
- `04_tasks.json` — derived from `04_tasks.md`, written by the same `--emit-json` call.
- `05_execution.json` — derived from `05_execution.md`, written by the same `--emit-json` call.
- `02_requirements.json` — derived from `02_requirements.md`. Generated by `spec-requirements`'s
  own workflow rather than `spec-check.py --emit-json` (it is parsed from EARS criteria, not from
  the task graph or timing ledger `spec-check.py` already computes) — the schema below is
  canonical regardless of which tool writes it.

All four share the same envelope:

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "04_tasks.md", "sha256": "<hex sha-256 of that file's current text>" },
  // ...artifact-specific fields below
}
```

`generated_from.sha256` is `sha256(<the Markdown file's exact current text>)`. `spec-check.py`
recomputes it on every run and reports `"<name>.json is stale; regenerate with --emit-json"` the
moment it disagrees with the file on disk — the same severity as a stale nav block, checked
unconditionally rather than only under `--ready`.

### `00_state.json`

A direct structural parse of the canonical Gate table — no computed fields, so nothing here can
disagree with the Markdown by construction, only go stale (which the freshness check catches).

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "00_state.md", "sha256": "<hex>" },
  "gates": {
    "discovery": { "status": "approved", "evidence": "2026-08-09" },
    "requirements": { "status": "approved", "evidence": "2026-08-09" },
    "design": { "status": "draft", "evidence": "" },
    "tasks": { "status": "not_started", "evidence": "" },
    "audit": { "status": "not_run", "evidence": "" },
    "execution": { "status": "not_started", "evidence": "" }
  },
  "change_control": ["<material change, impacted artifacts, re-approval required>"]
}
```

`gates` has exactly the six canonical rows (`discovery`/`requirements`/`design`/`tasks`/`audit`/
`execution`, lowercased); a template row still holding its placeholder status text (e.g.
`draft / approved / invalidated`) round-trips verbatim, which is itself the correct signal that
the gate hasn't actually been set yet — `--ready`'s gate check looks for the literal string
`approved`, not a placeholder. `change_control` lists only real entries under `## Change Control`,
never the template's `<...>` placeholder line.

### `04_tasks.json`

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "04_tasks.md", "sha256": "<hex>" },
  "requirement_count": 12,
  "stages": { "1": ["1.1", "1.2"], "2": ["2.1"] },
  "tasks": [
    {
      "id": "1.1", "title": "...", "checked": false, "optional": false, "stage": 1,
      "depends_on": [], "files": ["src/a.py"], "delegation": "parallel-safe",
      "dependency_resolution": "none", "dependency_delivery": "none",
      "interfaces": "Consumes: ...; Produces: ...", "verification": "...",
      "risk": "low; ...", "requirements": ["1.1"],
      "task_category": "code_analysis",
      "capability_tier": "balanced", "resolved_model": "claude-sonnet-5",
      "reasoning_level": "medium"
    }
  ],
  "concurrency": {
    "active_stage": 1, "ready": ["1.1"], "parallel_candidates": ["1.1"],
    "serial_candidates": [], "blocked": {},
    "waves": [{ "wave": 1, "mode": "parallel", "tasks": ["1.1"] }]
  }
}
```

`tasks[]` is the exact normalized field set `spec-check.py`'s task-graph parser already produces
for every leaf, plus the plan author's declared **Task category** (`quick_lookup` /
`code_analysis` / `heavy_reasoning` / `review` — see the `04_tasks.md` template's task contract)
and its derived `capability_tier`/`resolved_model`/`reasoning_level`, resolved in-process by
calling `scripts/model-router.py`'s `resolve()` once per task (never by shelling out per task).
`capability_tier` (which model) and `reasoning_level` (how much deliberation) are two independent
axes — see [model-routing.md](model-routing.md) — resolved together but never collapsed into one
value. A task's free-text `Risk` field maps deterministically to the router's `declared_risk`
vocabulary: `low`→`none`, `medium`→`elevated`, `high`→`high`, and escalates both axes
independently. `--emit-json` refuses to write this sidecar — and reports which task — when a
leaf omits `Task category` or names one outside the four recognized values.

`concurrency` is exactly `compute_execution_view()`'s result — the same computation
`emit_result`'s ephemeral `execution` object in `--format json` output already uses — plus
`waves`: the ready pool grouped into one parallel wave (every ready `parallel-safe` task at once,
when any exist) followed by one single-task serial wave per remaining ready task in checklist
order, mirroring the "parallel batch, then serial tasks one at a time" shape `spec-execute`'s
guarded per-wave scheduler already follows in prose.

### `05_execution.json`

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "05_execution.md", "sha256": "<hex>" },
  "runs": [
    { "run_id": "run-20260809T120000Z", "started_utc": "2026-08-09T12:00:00Z",
      "stopped_utc": "2026-08-09T12:14:00Z", "elapsed_seconds": 840, "outcome": "complete" }
  ],
  "task_attempts": [
    { "run_id": "run-20260809T120000Z", "stage_wave": "Stage 1", "task": "1.1", "attempt": 1,
      "started_utc": "2026-08-09T12:00:00Z", "stopped_utc": "2026-08-09T12:00:00Z",
      "elapsed_seconds": 0, "outcome": "verified" }
  ],
  "gantt": {
    "diagram": "timeline", "target": "gantt",
    "dateFormat": "YYYY-MM-DDTHH:mm:ss", "axisFormat": "%m-%d %H:%M",
    "sections": [
      { "name": "Execution Runs", "bars": [ { "id": "run_20260809T120000Z",
        "label": "run-20260809T120000Z (complete, 840s)",
        "start": "2026-08-09T12:00:00", "end": "2026-08-09T12:14:00", "tags": ["done"] } ] },
      { "name": "Stage 1", "bars": [ { "id": "b_1_1_attempt1",
        "label": "1.1 attempt 1 (verified, 0s)",
        "start": "2026-08-09T12:00:00", "end": "2026-08-09T12:00:01", "tags": ["done"] } ] }
    ]
  },
  "unresolved": []
}
```

`runs`/`task_attempts` mirror the `### Run Intervals`/`### Task Attempt Intervals` tables in
`05_execution.md` cell-for-cell. `gantt` is literally the `mermaid` skill's `timeline` IR (see
`mermaid/reference/ir.md`) — pass it straight to `mermaid/scripts/render.py --target gantt`
instead of hand-transcribing timing rows into a fenced Mermaid block, then render-validate the
generated source exactly as before. Bars follow the same rules `spec-execute/SKILL.md`'s
Execution Gantt section states: closed run rows form an `Execution Runs` section, task attempts
are grouped into one section per distinct `Stage/Wave` value, a completed zero-second interval
renders as a minimum `1s` while `elapsed_seconds` in `runs`/`task_attempts` keeps the ledger's
exact `0`, and a row with no known duration (`active`, or `interrupted` with `unknown` elapsed)
produces no bar at all — it is listed in `unresolved` (`{"kind": "run"|"task_attempt", "id":
"...", "reason": "active"|"interrupted"}`) instead of being fabricated.

### `02_requirements.json`

This is the canonical schema; `spec-requirements.md`'s own workflow generates it (see that
skill for the exact extraction logic, which reuses `spec-check.py`'s `criterion_pattern`/EARS
matching rather than inventing new patterns) since it is parsed from EARS criteria rather than
from anything `spec-check.py --emit-json` already computes.

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "02_requirements.md", "sha256": "<hex>" },
  "requirements": [
    {
      "id": "1",
      "user_story": { "role": "...", "capability": "...", "benefit": "..." },
      "criteria": [
        { "id": "1.1", "kind": "event" /* | "unwanted" | "state" | "unconditional" | "optional" */,
          "trigger": "...", "actor": "...", "behavior": "..." }
      ]
    }
  ]
}
```

`criteria[].kind` names which EARS sentence form produced the criterion (`event` = WHEN...SHALL,
`unwanted` = IF...THEN...SHALL, `state` = WHILE...SHALL, `unconditional` = THE...SHALL,
`optional` = WHERE...SHALL — see `references/ears.md`); `trigger` is empty for the unconditional
form. `id` values match the canonical `**R<requirement>.<criterion>**` identifiers already used
throughout the traceability chain above, so `design`/`tasks` citations need no translation layer.

## GitHub Markdown alerts

Use alerts only for information crucial to completing the current phase. Limit each artifact
to one or two alerts, never place alerts consecutively, and never nest them. Follow the
[GitHub alert syntax](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#alerts):

```markdown
> [!NOTE]
> Useful context readers should retain while skimming.

> [!TIP]
> Optional advice that makes the workflow easier.

> [!IMPORTANT]
> Required information or an approval gate.

> [!WARNING]
> An urgent stop condition that prevents invalid work.

> [!CAUTION]
> A risk or negative outcome the reader must consider.
```

Choose the alert type by meaning; do not use alerts as decoration. The templates below use
`IMPORTANT` or `WARNING` for phase gates because proceeding without approval invalidates the
spec workflow.

## Current technology evidence

When a design depends on behavior or configuration of an evolving library,
framework, SDK, API, CLI, or cloud service, query its current official
documentation through `context7-mcp`. Add this concise section to
`03_design.md`; when no such dependency applies, retain the heading with a concise not-applicable statement:

```markdown
## Current Technology Evidence

| Technology | Context7 identity/source | Exact selected version | Current-doc question | Decision |
|---|---|---|---|---|
| `<library>` | `/<publisher>/<project>` | `<exact version>` | `<one concept queried>` | `<design decision>` |
```

Do not copy documentation into the artifact. Record enough provenance for a
later task or audit to repeat the query when the version or question changes.

## Dependency security evidence

Place this nonempty section immediately after Current Technology Evidence in every `03_design.md`.
For each material third-party library, name the exact resolved version and mode, use Markdown links
for both current reports, and state the effective status and decision. If the feature selects no
material dependency, retain the section with a concise reason rather than a bare `N/A`.

```markdown
## Dependency Security Evidence

| Dependency / resolved version | Trigger and mode | Evidence | Result and decision |
|---|---|---|---|
| `<library>@<exact-version>` | dependency selection / `change` | [JSON](../../.security/dependency-audit/latest.json) · [Markdown](../../.security/dependency-audit/latest.md) | `pass` / `warnings` / `blocked` / `unavailable` / `invalid`; <review decision> |

Protected-main requires a fresh `main` audit. Release requires a fresh `release` audit and its
timestamped evidence. Warnings require review and must not be described as clean. `pass` and
reviewed `warnings` use exit `0`; `blocked`, `unavailable`, and `invalid` use exits `1`, `2`, and
`3` respectively. Only `pass` or explicitly reviewed `warnings` may proceed; warnings are not clean,
and `blocked`, `unavailable`, or `invalid` cannot ship.
```

Use the focused `dependency-security-audit` skill for this evidence. It supplements, and never
replaces, the design's broad security and authorization risk analysis. A dependency-changing task
must own every applicable manifest and lock/resolution file—including existing `uv.lock` with
`pyproject.toml`, Bun locks with `package.json`, and shared-stem `requirements*.in/.txt/.lock`—and
the nearest applicable ancestor workspace lock for a nested declared npm, pnpm, Yarn, Bun, or Cargo
member. It must
require Current Technology Evidence/Context7, a pre-change `change` audit followed by review of Markdown-linked JSON and
Markdown reports, the resolution edit, relevant project tests, a fresh post-change audit, and a
second review of both linked reports. The post-change invocation must explicitly run
`dependency-security-audit` in `change` mode; a generic audit reference is insufficient.
Each pre/post audit record contains both clickable report fields and the exact
`review=completed` field. Narrative wording remains useful context but cannot replace any canonical
record, field, link, status, or freshness value.

## 01_discovery.md template

```markdown
# Discovery: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md)
<!-- spec-nav:end -->

## Problem and Outcome
## Users and Current Workaround
## Scope and Non-Goals
## Constraints and Success Measures
## Approaches Considered
| Approach | Benefits | Costs / risks | Reversibility | Decision |
|---|---|---|---|---|
## Chosen Direction
## Architecture and Flow Outline
## Failure and Verification Strategy
## Open Decisions
## Approval
Status: **Approved on <date>**
```

When the discovery's alternatives, actors, constraints, risks, or subsystem boundaries have
material relationships that are difficult to scan in prose, insert `## Solution Space Mind Map`
between `Approaches Considered` and `Chosen Direction`. Author it through the `mermaid` skill as a
`mindmap`, render-validate the exact fenced source, and keep it consistent with the table and chosen
boundary. Omit the section for small linear decisions; it is never a substitute for the comparison
table or approval record.

When the approved boundary contains materially important static subsystem grouping,
hardware/software partitioning, or independently shippable units, `Architecture and Flow Outline`
may include a render-validated `block` diagram. Use `C4Context` for actors/system boundaries and an
ISO 5807-aligned flowchart for branching control flow. Keep this discovery view high-level and
derived from the chosen scope; detailed component design belongs in `03_design.md`.

## 02_requirements.md template

```markdown
# Requirements: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md)
<!-- spec-nav:end -->

## Introduction
<1–3 sentences: the feature and its value.>

> [!IMPORTANT]
> Approval gate: approve these requirements before work begins on `03_design.md`.

## Requirements

### Requirement 1: <short name>
**User Story:** As a <role>, I want <capability>, so that <benefit>.

#### Acceptance Criteria
1. **R1.1** WHEN <trigger>, THE <actor> SHALL <behavior>
2. **R1.2** IF <unwanted condition>, THEN THE <actor> SHALL <behavior>

### Requirement 2: <short name>
...
```

(EARS templates: `references/ears.md`.)

Requirements have no diagram by default. For a complex externally observable lifecycle, add a
render-validated `stateDiagram-v2` derived from the numbered EARS criteria. Use
`requirementDiagram` only when formal requirement-to-verification traceability materially helps.
The criteria remain authoritative, and diagrams must not introduce implementation detail.

## 03_design.md template

```markdown
# Design: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md)
<!-- spec-nav:end -->

## Overview
<what we're building and the approach in a paragraph.>

> [!IMPORTANT]
> Approval gate: approve this design before work begins on `04_tasks.md`.

## Architecture
<components and how they fit; use a Mermaid `block` diagram for static composition or partitioning,
`C4Context`/`C4Container` or `architecture-beta` for system/service boundaries, and another truthful type from the shared diagram
policy when it resolves a material question.>

## Components and Interfaces
<per component: responsibility, inputs/outputs, key functions/signatures.>

## Data Models
<types/schemas; a mermaid classDiagram or erDiagram where it helps.>

## Sequence / Flows
<Use sequenceDiagram for interactions/messages, stateDiagram-v2 for lifecycle transitions, or
an ISO 5807-aligned flowchart for branching control flow. Follow the `mermaid` skill's flowchart
profile: semantic shapes, labelled decision branches, and a clear primary direction.>

## Correctness Properties
### Property 1: <name>
<statement of an invariant/behavior that must hold.>
**Validates: Requirements 1.1, 5.5**

## Error Handling / Edge Cases
<how the IF/THEN criteria are met.>

## Testing Strategy
<how properties and criteria will be verified.>

## Cross-Cutting Risk Gates
<For applicable work: security/authorization, privacy, accessibility, performance,
observability, data migration, rollout, and rollback. State why a gate is not applicable.>

## Current Technology Evidence
<Current Context7 decisions for evolving technologies, or a concise not-applicable statement.>

## Dependency Security Evidence
<Material resolved dependencies, `dependency-security-audit` mode, linked JSON/Markdown reports,
result semantics, and main/release gates; or a concise not-applicable statement.>
```

## 04_tasks.md template

```markdown
# Tasks: <Feature>

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md)
<!-- spec-nav:end -->

> [!WARNING]
> Execute dependency stages in order. Run tasks concurrently only when each is marked
> `parallel-safe`, their ownership is disjoint, and isolated worktrees are available. Stop at
> every checkpoint for human review.

## Stage and Dependency Overview

<For plans with multiple stages, dependency edges, or checkpoints, add a render-validated Mermaid
`flowchart` generated from `04_tasks.json`'s `stages`/`tasks[].depends_on` (regenerate the sidecar
first with `--emit-json` if the checklist changed) via `spec-driven/scripts/render-gantt.py <spec-dir> --write`:
build a `flowchart TD` whose `subgraphs` are the stages, one `node` per task labelled with its
ID and concise title, and one `edge` per declared dependency.
Set each node's `status` class using the standard 4-color palette:
- **Grey (`pending`)**: `fill:#f1f5f9,stroke:#94a3b8` — tasks not yet started, ready, or queued.
- **Red (`failed`)**: `fill:#fee2e2,stroke:#ef4444` — tasks that failed verification or encountered critical defects.
- **Amber (`in_progress`)**: `fill:#fef3c7,stroke:#f59e0b` — tasks currently executing in an active wave.
- **Green (`done`)**: `fill:#dcfce7,stroke:#22c55e` — verified completed tasks with checked status.
Regenerate whenever the execution status or sidecar is updated so the colors match reality. Show no dates, estimates,
or undeclared ordering beyond what the sidecar declares. Omit this section for a trivial single-stage plan with no checkpoint.>

- [ ] 1. <Group / milestone>
  - [ ] 1.1 <discrete task — file(s) to create/change and what to implement>
    - <sub-step>
    - <sub-step>
    - **Files:** [`<existing-path>`](../../<existing-path>), `<new-path>`
    - **Dependency resolution:** none / change
    - **Dependency delivery:** none / main / release
    - **Context7 evidence:** state=pending | identity=/org/library | version=1.2.3 | decision=<selected API decision>
    - **Pre-change dependency audit:** state=pending | command=dependency-security-audit change | expected_json=.security/dependency-audit/pre-change.json | expected_markdown=.security/dependency-audit/pre-change.md | review=pending
    - **Resolution edit:** state=pending | expected_files=path/to/manifest, path/to/lock
    - **Project tests:** state=pending | expected_evidence=path/to/test-evidence
    - **Post-change dependency audit:** state=pending | command=dependency-security-audit change | expected_json=.security/dependency-audit/post-change.json | expected_markdown=.security/dependency-audit/post-change.md | review=pending
    - **Depends on:** none
    - **Stage:** 1
    - **Interfaces:** Consumes: `<exact input, prior task output, or approved design contract>`; Produces: `<exact artifact, symbol, signature, schema, or observable behavior>`
    - **Documentation:** public API/module comments required / no public surface; `<contract and rationale to capture>`
    - **Verification:** `<command>` or <observable check, including documentation review>
    - **Estimated effort:** <bounded duration or range>
    - **Risk:** low / medium / high; <rollback or migration note when applicable>
    - **Task category:** quick_lookup / code_analysis / heavy_reasoning / review
    - **Delegation:** controller / sequential subagent / parallel-safe
    - _Requirements: 1.1, 1.2_
  - [ ] 1.2 <dependent implementation or verification task>
    - **Files:** [`<existing-path>`](../../<existing-path>), `<new-path>`
    - **Dependency resolution:** none / change
    - **Dependency delivery:** none / main / release
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Interfaces:** Consumes: `<exact output or contract from task 1.1>`; Produces: `<exact artifact, symbol, signature, schema, or observable behavior>`
    - **Documentation:** `<contract and rationale to capture>` / no public surface
    - **Verification:** `<command>` or <observable check, including documentation review>
    - **Estimated effort:** <bounded duration or range>
    - **Risk:** low / medium / high; <rollback or migration note when applicable>
    - **Task category:** quick_lookup / code_analysis / heavy_reasoning / review
    - **Delegation:** controller / sequential subagent / parallel-safe
    - _Requirements: 1.1_

- [ ] 2. Checkpoint — <milestone reached>
  - [ ] 2.1 Verify <protected-main or release> dependency evidence
    - **Dependency delivery evidence:** state=pending | mode=<main-or-release> | expected_json=.security/dependency-audit/latest.json | expected_markdown=.security/dependency-audit/latest.md
    - **Files:** [`<existing-evidence-or-delivery-path>`](../../<existing-evidence-or-delivery-path>)
    - **Dependency resolution:** none
    - **Dependency delivery:** main / release
    - **Depends on:** 1.2
    - **Stage:** 3
    - **Interfaces:** Consumes: `<exact delivery evidence inputs>`; Produces: `<explicit integration or release decision>`
    - **Documentation:** no public surface
    - **Verification:** <freshness, timestamp, report review, and status decision>
    - **Estimated effort:** <bounded duration or range>
    - **Risk:** high; stale or fail-closed evidence stops delivery
    - **Task category:** review
    - **Delegation:** controller
    - _Requirements: 1.1_

- [ ] 3. <next group>
  - <repeat the complete leaf-task contract above>

## Delivery Schedule

| Stage | Task | Estimate | Depends on | Critical path |
|---:|---|---|---|---|
| 1 | 1.1 | <range> | none | yes / no |

<Add a Mermaid `gantt` only when dates are externally confirmed. Never invent calendar dates.>
```

Conventions:
- `Stage and Dependency Overview`, when present, is a derived navigation view. Its task nodes,
  stage groups, dependency edges, and checkpoint gates must agree with the checklist. Use a
  `flowchart` for this dependency graph; reserve `block` for static composition and `gantt` for
  schedules with confirmed dates.
- Every leaf declares exactly one **Task category** (`quick_lookup` / `code_analysis` /
  `heavy_reasoning` / `review`, per `contracts/spec-family.yaml`'s `task_categories`) next to
  `Risk` and `Delegation`. `--emit-json` resolves it (with the leaf's `Risk` word) to a
  `capability_tier`/`resolved_model` AND an independent `reasoning_level` in `04_tasks.json` by
  calling `scripts/model-router.py`'s `resolve()`; a leaf missing or misdeclaring it blocks
  sidecar generation with a named error.
- Regenerate the sidecar in the same step the Markdown changes: run `scripts/spec-check.py
  <spec-dir> --emit-json` after any edit to `04_tasks.md` or `05_execution.md`. `--ready` (and
  every ordinary run) rejects a `04_tasks.json`/`05_execution.json` whose `generated_from.sha256`
  no longer matches its Markdown twin — see **JSON sidecars** above.
- Unchecked leaves use only the exact `state=pending` schemas above, so expected evidence is
  safely identifiable without pretending execution completed. Pending report, test, and resolution
  targets are plain project-relative `expected_*` paths; they are intentionally not Markdown links
  because the future files need not exist yet. Before checking a dependency-change leaf, replace
  every record with `state=completed`. Completed pre/post audit records contain exactly `state`,
  `command`, `mode=change`, timezone-aware ISO `timestamp`, full hexadecimal `project_revision`,
  `inventory_fingerprint`, linked `JSON` and `Markdown`, `review`, `result`, `exit`, `decision`,
  `warnings_reviewed`, and `clean`. The linked JSON must validate and agree with those fields. The
  pre-change record precedes the post-change record in time; neither timestamp is future-dated,
  their sequence spans no more than seven days, and the post-change report is no more than 24
  hours old. Both identify the same project revision and distinct inventory fingerprints and
  report pairs.
- A completed delivery record contains exactly `state`, `mode`, timezone-aware ISO `timestamp`,
  hexadecimal `revision`, linked `JSON` and `Markdown`, `review`, `result`, `exit`, `decision`,
  `warnings_reviewed`, and `clean`. Completed targets exist inside the project, report pairs share
  a stem under `.security/dependency-audit`, and delivery JSON agrees with the record and current
  Git target. Delivery evidence must be current (no more than 24 hours old and not future-dated).
  Pending targets may name safe expected paths that do not exist yet.
- JSON evidence must implement the required `AuditResult` schema version `1.0`, including the
  complete required top-level and inventory fields and well-typed source, finding, and decision
  containers. Its inventory fingerprint is the 64-hex SHA-256 value. Unknown JSON fields are
  retained for forward compatibility; this does not relax the canonical Markdown records, whose
  allowed keys are exact and closed.
- Every pending `expected_*` value resolves inside the project even when existing parent path
  components are symbolic links. A nonexistent future leaf is valid, but an existing symlink that
  would place the future report, resolution artifact, or test evidence outside the project is not.
- Every leaf has one positive integer `**Stage:**` field. A Stage 1 leaf may omit
  `**Depends on:**`; omission is normalized to an empty dependency list. Prefer the explicit
  `**Depends on:** none` form for readability. Every later-stage leaf must have exactly one
  machine-parseable `**Depends on:**` field containing comma-separated prerequisite task IDs.
- Every leaf has exactly one `**Interfaces:**` field in the form
  `Consumes: <exact inputs/contracts>; Produces: <exact outputs/contracts>`. Name concrete
  artifacts, symbols, signatures, schemas, commands, or observable behaviors; placeholders and
  “implement the design” summaries are not executable contracts.
- Every leaf has exactly one bounded `**Estimated effort:**` duration or range and exactly one
  `_Requirements: ..._` field citing one or more canonical criterion IDs.
- Stages are deterministic topological layers: dependency-free tasks are stage 1; each dependent
  task is stage `1 + max(stage of its dependencies)`. List leaves in non-decreasing stage order,
  and place every dependency before its dependent.
- `scripts/spec-check.py <spec-dir> --format json` emits the normalized dependency graph and
  validation result using Python's standard JSON support. Its `execution` object reports the
  active stage, ready task IDs, parallel candidates, serial candidates, and unmet blockers.
  Markdown stays the source of truth you author and read; `04_tasks.json` is its persisted,
  hash-verified derived artifact (see **JSON sidecars** below) — regenerate it with
  `--emit-json` in the same step you edit `04_tasks.md`, never hand-maintain it.
- `parallel-safe` is valid only for tasks with disjoint owned paths, generated outputs, mutable
  state, and verification side effects. Shared migrations, schemas, lockfiles, snapshots,
  repo-wide formatting, or unresolved shared interfaces require sequential execution.
- Each leaf task is small enough to implement and verify in one focused pass.
- Each code-producing leaf declares its documentation surface. New or changed public APIs,
  classes, modules, and non-trivial files receive native documentation comments that state the
  contract and rationale; genuinely trivial private helpers may be explicitly exempted. Use
  `code-documenting` during execution to select and apply the project's documentation convention.
- `[ ]*` marks genuinely optional exploratory or coverage work. Tests needed to verify a
  behavioral requirement are required `[ ]` tasks. `Checkpoint` groups are explicit human-review gates.
- `spec-execute` checks off `[ ]` → `[x]` as each task passes verification, marking each task
  done **before** starting the next (never in batches).
- **Parent roll-up:** a parent task is checked only once all its required children are `[x]`
  (a skipped optional `[ ]*` child does not block the parent).
