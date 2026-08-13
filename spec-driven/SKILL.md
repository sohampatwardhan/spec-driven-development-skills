---
name: spec-driven
description: Use when building a feature or project with a spec-driven / Kiro-style workflow — turning an idea into discovery, requirements, design, and tasks before coding — or when the user mentions specs, EARS, steering, 01_discovery.md/02_requirements.md/03_design.md/04_tasks.md, ".specs", or asks to "build X properly with a spec". Routes to the phase skills.
version: 1.1.0
---

# Spec-Driven Development

A rigorous spec-driven workflow: compare solution approaches, turn the approved direction into
tracked artifacts — **discovery → state → requirements → design → tasks** — then implement them
task-by-task with verification and an explicit integration handoff. This skill is the **router**; it detects where a feature is and hands
off to the phase skill.

**Core principle:** Do not write requirements or implementation code until discovery is approved,
and do not implement until requirements, design, and tasks exist and the user has approved each.
Structure first, code second. Every artifact is
gated by explicit user approval; every task traces back to a numbered requirement.

## The pipeline

| Phase | Skill | Produces | Gate |
|---|---|---|---|
| Context (optional) | [`spec-steering`](../spec-steering/SKILL.md) | `.specs/steering/*.md` | — |
| State | all phases | `00_state.md` (gates and change control) | current |
| 1. Discovery | [`spec-discovery`](../spec-discovery/SKILL.md) | `01_discovery.md` (problem, alternatives, chosen direction) | user approves |
| 2. Requirements | [`spec-requirements`](../spec-requirements/SKILL.md) | `02_requirements.md` (user stories + EARS) | user approves |
| 3. Design | [`spec-design`](../spec-design/SKILL.md) | `03_design.md` (arch + mermaid + properties) | user approves |
| 4. Tasks | [`spec-tasks`](../spec-tasks/SKILL.md) | `04_tasks.md` (traced checkbox tasks) | user approves |
| 4.5 Audit (optional) | [`spec-audit`](../spec-audit/SKILL.md) | findings and audit state | user- or risk-selected quality review |
| 5. Execute | [`spec-execute`](../spec-execute/SKILL.md) | `05_execution.md` + working, verified code | per-task + checkpoints |
| 6. Finish | [`spec-finish`](../spec-finish/SKILL.md) | integration decision + final evidence | user chooses |
| (automation) | [`spec-hooks`](../spec-hooks/SKILL.md) | Claude Code hooks | — |

When working inside a project, create `.specs/` at the project root and keep the feature's
`00_state.md` and `01_discovery.md` through `05_execution.md` together under
`.specs/<feature-slug>/`, with machine-readable sidecars stored in `.specs/<feature-slug>/sidecars/`
validated against formal JSON schemas in [`contracts/schemas/`](contracts/schemas). Never put these
numbered planning artifacts in a global skill directory or unrelated scratch/output location.
Resolve shared references from the active `spec-driven` skill directory; never hard-code a
tool-specific home-directory path. Layout, templates, and the traceability chain:
[references/artifacts.md](references/artifacts.md). Diagram selection and source-of-truth rules:
[references/diagrams.md](references/diagrams.md).
Portable capability, I/O, role, budget, and adapter semantics:
[contracts/spec-family.yaml](contracts/spec-family.yaml) and [contracts/agent_profiles.json](contracts/agent_profiles.json).
Orca orchestration: [`scripts/spec-orca.py`](scripts/spec-orca.py) and [references/orca-orchestration.md](references/orca-orchestration.md).
Deterministic Gantt generation: [`scripts/render-gantt.py`](scripts/render-gantt.py).
Shared dependency rules:
[references/dependency-evidence.md](references/dependency-evidence.md). Deterministic subagent
model-tier routing: [references/model-routing.md](references/model-routing.md), resolved via
`scripts/model-router.py`. Deterministic subagent fan-out (how many reviewers, not which model):
[references/delegation.md](references/delegation.md), resolved via `scripts/fanout.py`.
EARS: [references/ears.md](references/ears.md). Run `scripts/spec-check.py <spec-dir>` at
every gate, and `--ready` immediately before execution.

## Routing — pick the phase from what already exists

```
Is this an unfamiliar / large existing codebase and no .specs/steering/ yet?
    → suggest spec-steering first (optional but recommended).

Look for .specs/<feature>/ :
  no 01_discovery.md                  → spec-discovery      (start here for a new feature)
  01_discovery.md, no 02_requirements.md → spec-requirements (after discovery approved)
  02_requirements.md, no 03_design.md → spec-design         (after requirements approved)
  03_design.md, no 04_tasks.md        → spec-tasks          (after design approved)
  04_tasks.md and user requests an audit → spec-audit         (after tasks approved)
  04_tasks.md                           → spec-execute        (after tasks approved)
  all tasks [x]                       → spec-finish
```

Announce the phase and the feature slug, then invoke the matching phase skill. If the
user names a feature that has no project-local `.specs/<feature-slug>/` folder yet, create
`.specs/` and the feature folder, then start at discovery. An existing feature without
`01_discovery.md` is legacy, not execution-ready; migrate it explicitly through discovery.

## Staying current

This skill family is mirrored between an installed copy (wherever the current host loads
skills from) and [`sohampatwardhan/spec-driven-development-skills`](https://github.com/sohampatwardhan/spec-driven-development-skills)
on GitHub. Drift between the two can go **either direction** — a pushed improvement not yet
pulled locally, or a local fix (made mid-session, debugging a script) never pushed back — and
one direction silently masking the other defeats the point of maintaining the repo at all.

Before starting nontrivial spec-driven work in a session (first invocation of this router or
any phase skill that session — not on every single tool call), run:

```bash
python3 scripts/check-skill-sync.py
```

- **Exit 0 ("CURRENT")** — proceed normally.
- **Exit 1 (drift reported)** — reconcile before relying on the affected skill(s) for the work
  at hand:
  - Files `missing_locally` (remote has them, local doesn't) or `differing` where the remote
    side looks newer/more correct — pull them into the local installation.
  - Files `local_only` or `differing` where the local side looks newer/more correct (e.g. a
    fix made earlier this session) — this is a shared, visible action (a GitHub push), so
    confirm with the user before pushing, per this project's normal confirm-before-push
    practice.
  - Don't assume either side is authoritative by default; read the actual diff.
- **Exit 2 (fetch error)** — network or `git` unavailable; note the check couldn't run and
  proceed with the installed copy, flagging that currency is unverified.

Skip this check for a trivial one-off ask (a single small edit with no phase-skill routing
decision involved) — it exists to protect nontrivial, multi-step spec-driven work, not to gate
every interaction.

## Rules (apply across phases)

- **Progressive disclosure.** The active phase skill and portable contract govern the current
  operation. Load only the artifact sections and shared policies needed for the current decision;
  related-skill links are navigation, not instructions to preload every skill body.
- **One phase at a time, each gated.** Never draft requirements before discovery is approved,
  design before requirements are approved, or tasks before design is approved. Revise the current
  artifact in place until approved.
- **Write for human readers.** Treat `01_discovery.md` and `00_state.md` through
  `05_execution.md` as reviewable project
  documents, not agent scratchpads. Use descriptive headings, concise prose, scannable tables or
  lists, explicit assumptions and decisions, and clear risks, status, and next actions. Exclude raw
  tool dumps, prompt fragments, hidden reasoning, unexplained abbreviations, and placeholders.
  Include useful subject matter and material evidence, not tool-call narration, agent workflow,
  renderer/checker provenance, generation/validation commentary, or other process metadata.
- **Keep navigation clickable.** After creating any numbered artifact, run
  `scripts/spec-nav.py <spec-dir> --write` so every existing `00`–`05` document links to every
  other existing document. Hyperlink references to existing project files/directories using a
  project-root-relative label and a target relative to the spec document; leave future paths as
  inline code only until they exist. `spec-check.py` enforces navigation and local file links.
- **Keep the state sidecar current.** Whenever any phase writes or updates `00_state.md` — a
  gate approval, an invalidation, an audit result, a checkpoint — run `scripts/spec-check.py
  <spec-dir>` in the same step; regenerating `00_state.json` is the default behavior of every
  invocation, not something that requires remembering `--emit-json`. It is a generated artifact
  like `04_tasks.json`/`05_execution.json`: never hand-maintained, and `sidecar_freshness_errors`
  rejects it as stale on every ordinary check once its hash no longer matches `00_state.md`. Pass
  `--check-only` when you specifically want validation without writing (e.g. a CI gate that must
  fail rather than silently repair a sidecar someone forgot to regenerate); pass `--emit-json`
  explicitly when a build failure in the sidecar itself (a malformed source doc) should fail the
  check rather than only warn — bare, implicit emission warns instead of erroring so an
  early-phase doc that is not yet in canonical shape (e.g. `00_state.md` before its Gate table is
  filled in) does not fail an ordinary check that never asked for JSON at all.
- **Keep skill references clickable.** When naming another local skill or a shared reference,
  use a relative Markdown link to its `SKILL.md` or reference file. Preserve the exact skill name
  in the link label so dependency detection and human navigation agree.
- **Traceability is mandatory.** Number requirement criteria (R1.1…); design properties cite
  `Validates: Requirements X.Y`; tasks cite `_Requirements: X.Y_`. No orphan criteria or tasks.
- **Task dependencies are machine-validated.** Every leaf task declares `Stage`. A Stage 1 task
  may omit `Depends on` and is normalized to an empty dependency list; explicit `none` remains
  preferred for human clarity. Later stages must name their prerequisites. `spec-check.py` rejects
  ambiguous omissions, unknown dependencies, cycles, forward references, and tasks outside their
  computed topological stage. Use its JSON output for automation.
- **Dependency intent is explicit.** Every leaf declares `Dependency resolution: none|change` and
  `Dependency delivery: none|main|release`; missing metadata blocks readiness. Apply
  [dependency-evidence.md](references/dependency-evidence.md) only when either field is not `none`.
- **Code documentation is part of delivery.** Every code-producing task defines its documentation
  surface; execution uses [`code-documenting`](../code-documenting/SKILL.md) for native comments that explain contract and why,
  not mechanics. Verify them before marking the task complete.
- **Keep artifacts in sync.** If a later phase reveals a gap, go back and update the earlier
  artifact (and re-approve) rather than silently diverging.
- **Diagrams answer material questions.** Follow [references/diagrams.md](references/diagrams.md)
  across every phase. Invoke `mermaid`, choose the truthful diagram type, and render-validate the
  exact source. Use `block` for static composition/grouping, flowcharts for control or dependency
  graphs, and Gantt only for real dates or observed intervals. Keep every diagram derived from and
  synchronized with the artifact's authoritative prose, table, checklist, repository evidence, or
  timing ledger; omit diagrams that would only decorate the page.
- **Current technology evidence via [`context7-mcp`](../context7-mcp/SKILL.md).** When a feature depends on evolving
  library, framework, SDK, API, CLI, or cloud-service behavior, resolve and query its current
  official documentation before making an implementation decision. Record the version/source
  and the decision in the design; do not rely on model memory for those claims.
- **Dependency Security Evidence via [`dependency-security-audit`](../dependency-security-audit/SKILL.md).** Keep the
  design section nonempty and apply [dependency-evidence.md](references/dependency-evidence.md)
  when material dependencies apply; otherwise state a concise reason.
- **Graph-assisted discovery for brownfield work.** When `codebase-memory-mcp` is available and
  its repository index is current, invoke [`codebase-memory-reference`](../codebase-memory-reference/SKILL.md) and use graph tools first
  for architecture, symbols, callers, dependencies, data flow, and impact. Verify config and
  runtime claims with authoritative files and tests; fall back to ordinary repository discovery
  whenever the graph is unavailable, stale, truncated, or inconclusive. Treat indexing as a
  controller-owned, serialized operation: one controller or designated explorer may make one
  authorized `index_repository` attempt for a repository, then share bounded evidence with the
  workers. Parallel workers must not index independently or retry after a session-visibility or
  project-name mismatch; they fall back to scoped source discovery instead.
- **Retrieval over this family's own artifacts is exact, not approximate — keep it that way.**
  The `R1.2` → `Validates: Requirements 1.2` → `_Requirements: 1.2_` traceability chain, and the
  `04_tasks.json`/`05_execution.json`/`02_requirements.json` sidecars, are already an ID-addressed
  retrieval mechanism strictly stronger than embedding/semantic search for this content: exact
  lookup has no recall/precision tradeoff to make. Do not add vector or embedding-based retrieval
  over `.specs/` artifacts — it would trade a correctness guarantee for an approximate one on data
  that is already exactly addressable. The one place semantic retrieval would add real value —
  searching unstructured history across many past features' `execution/task-*-report.md` files
  for prior art with no exact ID to look up — is a genuine future enhancement, not a core-path
  requirement; do not build it speculatively.
- **Use GitHub Markdown alerts selectively.** Apply `IMPORTANT` to approval gates,
  `WARNING` or `CAUTION` to stop conditions and risks, and `NOTE` or `TIP` to genuinely
  useful supporting guidance. Limit each artifact to one or two non-consecutive alerts.
- **Self-contained.** This family does not require superpowers; it has its own execution loop.
- **Audit is a selectable quality gate.** Run [`spec-audit`](../spec-audit/SKILL.md) when the user requests it and strongly
  recommend a Thorough audit for high-risk security, data, migration, or deployment changes.
  A passed audit—or approved fixes from an audit—improves confidence but is not a prerequisite
  for [`spec-execute`](../spec-execute/SKILL.md) unless project policy explicitly makes it one.

## When NOT to use

- A trivial one-line change with no design surface — just make it (say why you're skipping specs).
- Pure debugging of existing behavior — reach for a debugging approach, not a new spec.

## Red flags — STOP

- "The approach is obvious" → compare viable approaches and approve discovery first.
- "I'll just start coding, the spec is obvious" → complete every approval gate first.
- "I'll write all three artifacts, then get one approval" → each phase gates independently.
- "This task doesn't need a requirement" → then either it's out of scope or the requirement is missing.
