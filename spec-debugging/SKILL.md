---
name: spec-debugging
description: Use when a spec-execute task, verification command, build, test, integration, or runtime behavior fails unexpectedly before proposing or applying a fix.
version: 1.0.0
---

# Spec Debugging

Find and prove the root cause before changing implementation or approved artifacts.

## Related Skills

[`spec-execute`](../spec-execute/SKILL.md) ·
[`spec-verification`](../spec-verification/SKILL.md) · [`mermaid`](../mermaid/SKILL.md)

## Iron Law

**No fix without a reproduced failure, evidence, and one falsifiable root-cause hypothesis.**

## Workflow

1. **Preserve evidence.** Keep the task unchecked; record command, full relevant error, environment, revision, and attempt in `05_execution.md` or the task report.
2. **Reproduce.** Run the narrowest reliable check. If intermittent, gather timing/state evidence instead of guessing.
3. **Trace the boundary.** Read the error fully, inspect recent changes, compare a working
	neighbor/reference, and trace bad state backward through component boundaries. Add temporary
	diagnostics when evidence cannot locate the failure. For a cross-component temporal failure
	that is materially hard to explain, invoke `mermaid` and add a `sequenceDiagram` to the task
	report; for complex diagnostic branching, use an ISO 5807-aligned `flowchart`. Both stay
	judgment-authored — a debugging hypothesis, not a mechanical derivation from other structured
	data — but build them as IR JSON instead of typing Mermaid text: capture the hypothesis's
	actors/messages (`sequence` family) or nodes/edges (`graph` family) per
	[`mermaid/reference/ir.md`](../mermaid/reference/ir.md), then generate and render-validate with
	`mermaid/scripts/render.py` exactly as any other diagram. This is still worth doing for a
	one-off hypothesis diagram: the JSON is a structured, editable record that's trivial to update
	when the hypothesis changes — a JSON edit plus regenerate beats hand-editing Mermaid text — and
	`render.py`'s fail-closed generation means the diagram can never carry a Mermaid syntax slip
	that validation missed. Derive either from captured evidence, keep it exceptional, and remove
	or update the IR (then regenerate) when the hypothesis changes; a diagram is never proof by
	itself.
4. **State one hypothesis:** “X is the root cause because Y; check Z would disprove it.”
5. **Test minimally.** Change one variable or add one reversible probe. If disproved, remove the probe and form a new hypothesis.
6. **Implement through TDD.** Add the smallest failing regression test, verify RED for the expected reason, apply one root-cause fix, verify GREEN, then refactor.
7. **Verify broadly.** Run the task contract, affected tests, and appropriate regression suite. Update evidence; never convert a failed baseline into success by changing expectations without an approved behavior change.

After three failed fix hypotheses, stop and reassess the architecture with the user. If the root cause is a spec defect, route to the owning phase and follow its approval rules; do not work around it in code.
