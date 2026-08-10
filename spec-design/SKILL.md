---
name: spec-design
description: Use when writing the technical design for an approved requirements spec in spec-driven development — architecture, components, data models, mermaid diagrams, and correctness properties traced to requirements, in 03_design.md (phase 3). Triggers on "write the design", "03_design.md", or after requirements are approved.
---

# Spec Design (Phase 3)

Turn approved `02_requirements.md` into `03_design.md`: the technical approach, with diagrams,
and **correctness properties** that trace back to specific requirements.

> [!IMPORTANT]
> Read the approved `01_discovery.md` and `02_requirements.md` before designing, and do not begin
> `04_tasks.md` until the user approves `03_design.md`.

**Core principle:** The design must be *sufficient and traceable* — every requirement
criterion is satisfied by something in the design, and every correctness property cites the
requirement(s) it validates (`Validates: Requirements X.Y`). No requirement left unaddressed.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-discovery`](../spec-discovery/SKILL.md) ·
[`spec-requirements`](../spec-requirements/SKILL.md) · [`spec-tasks`](../spec-tasks/SKILL.md) ·
[`mermaid`](../mermaid/SKILL.md) · [`context7-mcp`](../context7-mcp/SKILL.md) ·
[`dependency-security-audit`](../dependency-security-audit/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md)

**REQUIRED first:** read `00_state.md`, the feature's approved `01_discovery.md` and
`02_requirements.md`, and, if present, `.specs/steering/*.md`. Require the Discovery and
Requirements gates to be `approved` before
designing. Resolve the active `spec-driven` skill directory and use its
`references/artifacts.md` template; never assume a tool-specific home-directory path.

## Workflow

1. **Map every requirement.** Before designing, list the numbered criteria; you'll ensure
   each is covered. If a requirement is unbuildable or ambiguous, go back to `spec-requirements`.
2. **Ground the design in the existing code.** For a brownfield feature, invoke
   `codebase-memory-reference` when `codebase-memory-mcp` has a current index. Use `search_graph`
   to locate candidate components and interfaces, `trace_path` to verify callers, dependencies,
   data flow, and cross-service effects, and `get_code_snippet` for targeted source. Use
   `query_graph` only for complex multi-hop questions. Record material repository evidence and
   verify it against source; fall back to normal discovery when graph evidence is insufficient.
3. **Research evolving technologies.** For each design decision that depends on a library,
   framework, SDK, API, CLI, or cloud service, use `context7-mcp` to resolve the library and
   affirmatively query the exact current behavior or configuration. Record the consulted Context7 identity/source, exact
   selected version, question answered, and decision in a concise **Current Technology Evidence**
   section. Split distinct concepts into separate queries. If no material dependency applies,
   retain the heading with a concise not-applicable statement.
4. **Record dependency security evidence.** Keep the section beside Current Technology Evidence
   nonempty. Apply [dependency-evidence.md](../spec-driven/references/dependency-evidence.md) for
   material dependencies; otherwise state a concise reason. Keep broad security and authorization
   review as a separate risk gate.
5. **Design the solution.** Cover: overview, architecture, components & interfaces (per
   component: responsibility, exact consumed/produced inputs and outputs, public and cross-task
   signatures with parameter/return/error contracts), data models, key flows,
   error handling (satisfying the IF/THEN criteria), testing strategy, and the applicable
   cross-cutting risk gates: security/authorization, privacy, accessibility, performance,
   observability, migration, rollout, and rollback. For each gate, name its failure mode,
   verification, and owner/decision; explicitly say why an inapplicable gate does not apply.
   Confirm this realizes the discovery's chosen direction. Reference its rejected alternatives;
   do not silently make a second approach decision after discovery approval.
   Use concrete names and signatures where the implementation language permits them; for
   declarative or document-only work, name the exact schema, artifact shape, command, or
   observable contract that substitutes for a code signature. Do not defer interface discovery
   to implementation.
6. **Diagram with the `mermaid` skill when a visual resolves a material question, generating
   each from an IR JSON first.** Choose the type per the shared diagram policy, then build a
   small `graph` IR JSON (`nodes`/`edges`/`groups` — schema:
   [`mermaid/reference/ir.md`](../mermaid/reference/ir.md)) capturing that decision as data before
   writing any Mermaid text, save it under `.specs/<slug>/diagrams/`, run
   `mermaid/scripts/render.py` on it, and render-validate the exact generated output — the same
   render-validation this skill has always required, just generated instead of hand-typed:
   - **Architecture diagram** (`diagrams/architecture.json`): `block` for static composition,
     nested subsystems, firmware layers, hardware/software partitions, or grouped topology where
     C4-model/cloud semantics would be artificial; `C4Context`/`C4Container` or `architecture-beta`
     for system or service boundaries.
   - **Data Models diagram** (`diagrams/data-models.json`): `classDiagram` for an object model,
     `erDiagram` for persisted relationships.
   - **Sequence/Flows diagram** (`diagrams/flows.json`): `sequenceDiagram` for messages over time,
     `stateDiagram-v2` for lifecycle transitions.

   Which components exist, how they're grouped, and what the data model or message flow looks like
   is still your design judgment — none of this is computed from another artifact. Building the IR
   JSON first anyway is what makes a judgment-authored diagram durable: it gives `spec-audit` a
   structured record to check field-by-field against the Components & Interfaces / Data Models
   prose instead of re-parsing Mermaid text, and it survives unchanged if a future non-Mermaid
   backend is added, per `ir.md`'s stated purpose. Use a flowchart only for control flow, hand-authored
   directly with the `mermaid` skill (branching control flow rarely reduces cleanly to
   nodes/edges/groups the way composition or data-model diagrams do); it must follow the Mermaid
   skill's ISO 5807 flowchart profile (semantic shapes and labelled decision branches). Do not add
   decorative diagrams. **Show the rendered image in chat; embed the ```mermaid source in
   `03_design.md`** (raw fences don't render in the Claude app, but do on GitHub), and keep the
   source IR JSON alongside it in `.specs/<slug>/diagrams/` so both stay in sync. Treat the diagram
   as ordinary documentation.
7. **Write correctness properties.** For each non-trivial behavior, state a property and
   annotate `**Validates: Requirements X.Y**`. Together the properties must cover all criteria.
8. **Write** the project-local `.specs/<slug>/03_design.md` for a human technical reviewer.
   Explain consequential choices and rejected alternatives briefly, define project-specific
   terms, and summarize evidence rather than pasting tool output. Apply the shared artifact content
   rule: include useful design content and material evidence, not research/tool narration,
   generation/rendering/validation commentary, agent workflow, or other process metadata.
   Hyperlink every referenced
   project file or directory that already exists, using the project-relative path as the label.
   Then run `scripts/spec-nav.py <spec-dir> --write` to refresh links across all existing numbered
   artifacts.
9. **Self-review:** every requirement criterion is covered by ≥1 property/component; every
   property cites real requirement numbers; diagrams render; no "TBD"; assumptions, risks, and
   decisions are easy for a human to find without the prior conversation.
10. **Gate — get approval:** Run `scripts/spec-check.py <spec-dir>`, update `00_state.md`, and ask:
   > "Design written to `.specs/<slug>/03_design.md`. Review and approve, or request changes, before we break it into tasks."
   Revise until approved. Mark Design `approved` in `00_state.md` only after user acceptance.
   A material design revision invalidates Tasks, Audit, and Execution in `00_state.md`. If design
   forces a requirements change, update `02_requirements.md` and re-approve that too. If it changes
   the chosen approach or product boundary, return to `spec-discovery` first.

## Rules

- **Coverage:** a requirement with no design element = a gap. Add the design or drop the requirement (with the user).
- **Traceability:** properties without `Validates:` annotations, or citing non-existent
  requirement numbers, are bugs — fix before the gate.
- **Right altitude:** enough that tasks can be written and code verified; not a line-by-line
  transcript. Name components, interfaces, and data shapes.
- **Diagrams are validated, not hand-written** — always via the `mermaid` skill.
- **Block diagrams show composition, not control.** Switch to a flowchart for decisions/order,
   sequence for messages, state for lifecycle, and `C4Context`/`C4Container` or
   `architecture-beta` for explicit system semantics.

## Next

On approval → **`spec-tasks`**.

## Red flags — STOP

- A correctness property with no `Validates: Requirements …` line → add the trace.
- A requirement criterion nothing in the design addresses → close the gap before the gate.
- Pasting an unvalidated ```mermaid block → render it via the `mermaid` skill first.
