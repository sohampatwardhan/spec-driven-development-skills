---
name: spec-discovery
description: Use when starting a new spec-driven feature, changing product behavior, or choosing among materially different solution approaches before requirements are written.
---

# Spec Discovery (Phase 1)

Turn vague intent into an approved problem boundary and approach in `01_discovery.md` before requirements begin.
This is the spec-driven workflow's canonical brainstorming phase: later phases consume its approved
scope and chosen direction rather than repeating solution discovery.

**Core principle:** Understand the problem and compare real alternatives before committing the specification to one solution.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-steering`](../spec-steering/SKILL.md) ·
[`spec-requirements`](../spec-requirements/SKILL.md) · [`mermaid`](../mermaid/SKILL.md)

> [!IMPORTANT]
> Do not write `02_requirements.md`, design, tasks, scaffolding, or implementation code until discovery is approved.

## Workflow

1. **Inspect context first.** Read project instructions, steering, relevant source/docs, recent changes, and current constraints. For brownfield work, use graph-assisted discovery when current and verify material claims against source.
2. **Check scope.** If the request contains independent products or subsystems, decompose it into separately shippable specs and discover the first one only.
3. **Clarify one decision at a time.** Establish user, problem, current workaround, desired outcome, non-goals, constraints, success measures, and one-way-door risks. Prefer concise multiple-choice questions when useful. Do not ask what repository evidence can answer.
4. **Decide whether the solution space needs a mind map.** Add one when relationships among
	alternatives, users, constraints, subsystems, risks, or independently shippable specs are
	materially harder to compare in prose. Omit it for a small, linear choice where the approaches
	table is clearer. When included, capture the alternatives/concern hierarchy as a small
	`graph`/`mindmap` IR JSON (`root`, `nodes`, `edges` — schema:
	[`mermaid/reference/ir.md`](../mermaid/reference/ir.md)), save it to
	`.specs/<slug>/diagrams/solution-space.json`, then run `mermaid/scripts/render.py` on it and
	render-validate the exact generated source (`scripts/check.sh` or
	`validate_and_render_mermaid_diagram`) before presenting or embedding it — the same
	render-validation this skill has always required, just generated instead of hand-typed. Which
	alternatives exist and how they relate is still your judgment call, not something computed from
	another artifact; building it as IR JSON first, rather than typing Mermaid text directly, still
	pays off for judgment-authored content: it leaves a durable, field-by-field record of exactly
	what the mind map asserts (useful to `spec-audit`), and it survives unchanged if a future
	non-Mermaid backend is added, per `ir.md`'s stated purpose. Show the rendered result during
	discovery when the host cannot render Mermaid; persist the validated fenced source under
	`## Solution Space Mind Map` in `01_discovery.md` and keep the IR JSON beside it so both stay in
	sync with the final alternatives and chosen boundary. A mind map clarifies the decision space; it
	never replaces the approaches table or explicit approval. Use the available visual-design
	workflow instead for mockups; text questions remain text.
5. **Compare 2-3 viable approaches.** Lead with the recommendation. For each, state benefits, costs, risks, reversibility, and why it was accepted or rejected. Apply YAGNI and preserve existing project patterns.
6. **Present the proposed boundary.** Cover problem, users, in/out scope, chosen approach,
   architecture outline, data/control flow, failure strategy, verification strategy, and unresolved
   decisions. When the chosen scope contains materially important static subsystem boundaries,
   hardware/software partitions, or independently shippable units, capture the boundary as a
   `graph`/`block` IR JSON (`C4Context` instead when actors and system boundaries are the subject) —
   `nodes`/`edges`/`groups` per [`mermaid/reference/ir.md`](../mermaid/reference/ir.md) — save it to
   `.specs/<slug>/diagrams/architecture-outline.json`, run `mermaid/scripts/render.py` on it, and
   render-validate the generated source exactly as before, then add it under `Architecture and Flow
   Outline`. As with the mind map, the boundary itself is still your call, not a derived fact; the
   IR JSON is worth building anyway for the same durable-record and future-backend reasons, and it
   is what `spec-audit` should check the diagram against, not the prose. Keep it deliberately short
   of detailed design, derive it from the approved boundary, and omit it when prose is clearer. Use
   an ISO 5807-aligned flowchart instead only when branching control flow is the material discovery
   question — hand-author that one directly with the `mermaid` skill, since a discovery-level
   control-flow sketch is typically too provisional to be worth a durable IR record. Get explicit
   user approval.
7. **Write `01_discovery.md` and initialize `00_state.md`.** Record the alternatives and decision for a human reviewer, not the conversation transcript. Set Discovery to `approved` only after acceptance; material discovery changes invalidate downstream gates.
8. Run `spec-nav.py <spec-dir> --write`, self-review for placeholders/contradictions/ambiguity, and ask the user to review the written artifact. Revise until approved.
9. Transition only to `spec-requirements`.

## Required Artifact

IR JSON sources for generated diagrams live in `.specs/<slug>/diagrams/` alongside the numbered
artifacts — e.g. `solution-space.json` for the mind map, `architecture-outline.json` for the
boundary diagram — so a reviewer or `spec-audit` can compare the rendered Mermaid against the
structured data it was generated from.

When the mind-map decision rule applies, build `diagrams/solution-space.json` (step 4), render it,
and insert this section after `Approaches Considered`:

````markdown
## Solution Space Mind Map
```mermaid
mindmap
	root((<problem or outcome>))
		<approach or concern>
```
````

Omit the entire section when a mind map would not materially improve the decision.

When the boundary rule applies, build `diagrams/architecture-outline.json` (step 6) and render it;
`Architecture and Flow Outline` may then contain one render-validated `block`, `C4Context`, or
flowchart selected through the shared diagram policy (a flowchart is still hand-authored directly,
per the `mermaid` skill, when branching control flow is the material question). It must clarify the
chosen scope without introducing implementation detail that belongs in design.

```markdown
# Discovery: <Feature>

## Problem and Outcome
## Users and Current Workaround
## Scope and Non-Goals
## Constraints and Success Measures
## Approaches Considered
| Approach | Benefits | Costs / risks | Decision |
|---|---|---|---|
## Chosen Direction
## Architecture and Flow Outline
## Failure and Verification Strategy
## Open Decisions
## Approval
Status: **Approved on <date>**
```

## Stop Conditions

Stop for user input when the product outcome is ambiguous, alternatives are materially close, the choice is destructive or difficult to reverse, or scope cannot be made independently shippable. Do not manufacture certainty or use requirements drafting to hide an unresolved product decision.
