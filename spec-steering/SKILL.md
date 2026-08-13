---
name: spec-steering
description: Use when onboarding a codebase or capturing persistent project context for spec-driven development — creating or updating steering docs (product, tech stack, structure) under .specs/steering/, or when the user says "steering", "onboard this repo", or wants the agent to learn the project before building features.
version: 1.0.0
---

# Spec Steering

Steering docs give every later phase durable, accurate context about the project so
requirements/design/tasks aren't written against guesses. Analogous to Kiro's Agent Steering.

**Core principle:** Capture what is *true and stable* about the project, verified from the
code — not aspirations. Steering is read by `spec-requirements`, `spec-design`, and
`spec-tasks`; wrong steering silently corrupts every spec.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-discovery`](../spec-discovery/SKILL.md) ·
[`spec-requirements`](../spec-requirements/SKILL.md) · [`spec-design`](../spec-design/SKILL.md) ·
[`spec-tasks`](../spec-tasks/SKILL.md) · [`mermaid`](../mermaid/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md) ·
[`context7-mcp`](../context7-mcp/SKILL.md)

## The three docs (`.specs/steering/`)

| File | Contents |
|---|---|
| `product.md` | What the product is, who it's for, the problem it solves, primary goals/non-goals. |
| `tech.md` | Language(s), frameworks/libraries, datastore, build/test/run commands, key constraints (perf, compliance, versions). |
| `structure.md` | Directory layout, key modules and their responsibilities, naming/style conventions, where new code of each kind goes. |

## Workflow

1. **Explore the repo** before writing. When `codebase-memory-mcp` is available and its index is
   current, invoke `codebase-memory-reference` and start with `get_architecture` to map packages,
   entry points, routes, boundaries, and clusters. Then read `README`, manifests (`package.json`,
   `pyproject.toml`, `go.mod`, etc.), config, the directory tree, and representative core source
   directly. Prefer corroborated evidence over assumption; do not copy graph output unverified.
2. **Draft each doc** from what you found. Keep them concise and scannable — bullets and
   short tables, not prose walls. Write for a human joining the project: define local terms,
   explain non-obvious conventions, and distinguish verified facts from assumptions. Record
   commands verbatim (how to build, test, run, lint). Include useful project facts and decisions,
   not discovery-tool narration, agent workflow, generation/validation commentary, or other
   process metadata.
   Apply the shared `spec-driven` diagram policy. When stable subsystem grouping or runtime
   composition is materially difficult to scan, build a `graph` IR JSON (`mermaid/reference/ir.md`)
   from the verified repository facts — `block` target for composition/partitioning, `C4Context`/
   `C4Container` or `architecture-beta` when system or service semantics are the actual subject —
   store it at `.specs/steering/diagrams/<tech-or-structure>.json`, generate the diagram with
   `mermaid/scripts/render.py`, and render-validate the exact generated source before adding it to
   `structure.md` or `tech.md`. Never hand-transcribe the diagram from the facts by typing Mermaid
   directly: the JSON is the durable record a later `spec-audit` or steering refresh diffs against,
   and keeping it means an out-of-date steering diagram is a detectable JSON/repository mismatch,
   not just a stale picture nobody notices. Omit the diagram entirely when a table or directory
   summary is clearer. Steering diagrams must remain high-level and durable because stale steering
   silently misleads every later phase.
3. **Flag unknowns** explicitly (`> TBD: <question>`) rather than inventing — ask the user.
4. **Confirm** with the user; steering is long-lived, so accuracy matters more than speed.
5. **Mark evolving dependencies.** Record installed versions and compatibility constraints
   from manifests/configuration, but defer behavior/configuration decisions to fresh
   `context7-mcp` research in the feature design; steering must not fossilize changing API docs.
6. **Update, don't duplicate.** If a steering doc exists, revise it in place when the
   project changes; note what changed and the evidence date so readers can assess staleness.

## When to run

- First time using spec-driven in an existing/unfamiliar repo (recommended).
- After a significant stack or structure change.
- Not needed for a brand-new empty project — steering can be written alongside the first feature.

## Rules

- Verify commands actually exist (check scripts / manifests) before recording them.
- Don't put feature-specific detail here — that belongs in a feature's `02_requirements.md`.
- Steering is context, not a gate: it doesn't need formal approval, but confirm accuracy.

Layout reference: resolve the active `spec-driven` skill directory, then read
`references/artifacts.md`; never assume a tool-specific home-directory path.
