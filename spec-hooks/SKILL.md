---
name: spec-hooks
description: Use when setting up agent hooks (event-triggered automations) for a spec-driven project — selecting safe hooks for supported agent hosts and validating their official configuration before wiring actions around file changes, task completion, or commits. Triggers on "agent hooks", "spec hooks", "run X automatically when Y", or wiring automation into a .specs workflow.
version: 1.0.0
---

# Spec Hooks

The faithful analog of Kiro's agent hooks: event-triggered automations. A supported agent host's
hook system runs them, so they can fire actions around a
spec-driven workflow (e.g. run tests on save, re-render diagrams, sync a task's status).

**Core principle:** A hook is automation the *harness* executes on an event — not something
the model remembers to do. If the user wants "whenever X, do Y", that's a hook, and it must
be configured in `settings.json` to actually happen.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-execute`](../spec-execute/SKILL.md) ·
[`mermaid`](../mermaid/SKILL.md)

**REQUIRED:** resolve the active host's official hook documentation or configuration tool before
writing configuration. Verify event names, matchers, command schema, scope, and safety from that
source; never invent a `settings.json` schema or depend on a missing `update-config` skill. This
skill decides *what* hook serves the spec workflow and validates the supported wiring.

## Useful hooks for a spec-driven project

| Goal | Event | Action (example) |
|---|---|---|
| Keep tests green during `spec-execute` | after edits to source | run the project's test command |
| Re-validate diagrams | after edits to numbered spec artifacts | validate changed ```mermaid blocks (e.g. `mermaid` skill's `check.sh`) |
| Lint/format before commit | pre-commit / stop | run formatter + linter |
| Guard the spec | before edit to `.specs/**` under review | warn if editing an approved artifact without re-approval |
| Announce checkpoints | on task completion | surface a notification |
| Keep a code graph current (optional) | supported source-change/lifecycle event | invoke the installed `codebase-memory-mcp` refresh mechanism or verify its watcher |

(Exact event/matcher keys come from the active host's current official documentation — don't
hardcode them here.)

## Workflow

1. **Clarify the trigger and action** with the user: what event, what command, which scope.
   Confirm the action is safe to run automatically (hooks run unattended).
2. **Resolve the host and settings scope** (project vs user-level) from current official docs —
   usually project-level when the team must share the workflow.
3. **Keep generated project documentation useful.** When a hook writes or updates a spec artifact,
   store only the material event, outcome, evidence, or blocker a human needs. Do not persist hook
   internals, tool-call narration, renderer/checker provenance, generation/validation commentary,
   or routine process metadata.
  For multiple interacting events, conditions, or safety exits, apply the shared diagram policy
  and generate a render-validated ISO 5807 `flowchart` (or `sequenceDiagram` when event ordering
  is the point) from an IR JSON built directly from the verified host configuration — its actual
  configured events/matchers/actions as `graph` nodes/edges (event -> matcher -> action), or as
  `sequence` actors/messages when ordering matters — per
  [`mermaid/reference/ir.md`](../mermaid/reference/ir.md). Run `mermaid/scripts/render.py` on that
  IR and render-validate the result as usual; the hook's configuration is already structured data
  in `settings.json`, so hand-transcribing it into Mermaid text is unnecessary. Omit the diagram
  for one trigger/action.
4. **Wire the hook** with the host's supported configuration mechanism, preserving existing
   settings and minimizing the matcher scope.
5. **Verify** the hook is well-formed, report the evidence source, whether reload is required,
   and how to remove it.

## Example: the spec-execute checklist guard

A ready-to-use hook that mechanically nudges the [[spec-execute]] discipline (mark each task
`[x]` before moving on). It fires only on real drift and never blocks an edit.

- **Script:** [examples/tasks-checkbox-guard.sh](examples/tasks-checkbox-guard.sh) — a
  `PostToolUse` hook. On each `Edit`/`Write`/`MultiEdit` it reads the hook JSON from stdin; if
  the edited file is a **source** file and some `.specs/**/04_tasks.md` still has an unchecked
  **required** item (`- [ ] `; optional `- [ ]*` is ignored), it exits `2` with a reminder on
  stderr — which Claude Code feeds back to the agent. Editing the spec artifacts themselves,
  non-source files, or a fully-checked spec → silent `exit 0`. Any internal error → `exit 0`
  (never wedges the workflow).

- **Wire it up only after verification.** Use the current official schema for the active host,
  scope it to the project when appropriate, and point at the script by an absolute path if the
  host does not expand `~`. The guard is a *nudge*, not a substitute for the discipline in
  `spec-execute`.

## Rules

- Never auto-run destructive or outward-facing actions (deploys, pushes, deletes) from a hook
  without explicit, specific user confirmation for that hook.
- Prefer narrow matchers so a hook fires only for the intended files/events.
- Never create `UserPromptSubmit` hooks. They run on every message and create noise or failures;
  use narrowly scoped post-tool or lifecycle events only when the host supports them.
- Hooks are optional polish on the pipeline — don't gate the core spec workflow on them.
- Do not add graph-refresh hooks when the MCP's documented watcher already keeps the index current.

## Red flags — STOP

- Writing "remember to run X after Y" into a memory/instruction instead of a real hook → the
  harness won't do it; configure a hook.
- Hardcoding a hook schema from memory → verify it in the active host's official documentation first.
