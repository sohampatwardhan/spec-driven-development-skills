---
name: spec-audit
description: Optionally audit a spec-driven feature's requirements, design, and task artifacts with parallel review agents. Use when asked to audit, scrutinize, harden, pressure-test, or validate a spec plan, or when risk warrants an extra quality gate.
---

# Spec Audit (Optional Phase 4.5)

Audit the current feature's `01_discovery.md`, `02_requirements.md`, `03_design.md`, and
`04_tasks.md` as one traceable unit. Find concrete defects before execution when selected;
do not rewrite approved artifacts unless the user asks to apply a finding.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-discovery`](../spec-discovery/SKILL.md) ·
[`spec-requirements`](../spec-requirements/SKILL.md) · [`spec-design`](../spec-design/SKILL.md) ·
[`spec-tasks`](../spec-tasks/SKILL.md) · [`spec-execute`](../spec-execute/SKILL.md) ·
[`mermaid`](../mermaid/SKILL.md) · [`context7-mcp`](../context7-mcp/SKILL.md) ·
[`dependency-security-audit`](../dependency-security-audit/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md)

> [!WARNING]
> An audit is an optional review gate, not an implementation phase. If it finds a
> material requirements or design defect, stop execution until the relevant
> `spec-*` artifact is corrected and re-approved.

**REQUIRED BACKGROUND:** Use the portable
[spec-family contract](../spec-driven/contracts/spec-family.yaml), shared artifact references, and
this audit contract. Do not preload every phase skill; open the owning phase skill only when a
finding must be routed or repaired. When a reviewed artifact contains Mermaid, use
[`mermaid`](../mermaid/SKILL.md) to verify it rather than treating fenced source as sufficient
evidence.

## Workflow

1. **Locate the feature artifacts.** Read `.specs/<slug>/00_state.md`, `01_discovery.md`,
   `02_requirements.md`, `03_design.md`, and `04_tasks.md`; read `.specs/steering/*.md` when present.
   If an artifact is absent, report that as a P0 audit finding and do not
   substitute an informal artifact.
2. **Verify the gate preconditions.** Run `scripts/spec-check.py <spec-dir>` and require
  Discovery, Requirements, Design, and Tasks to be approved in `00_state.md`. A failed check or missing
   approval is a P0 finding; do not launch an execution-readiness audit against it. Treat
   missing/stale artifact navigation, broken local links, or unlinked references to existing
   project paths as human-usability findings that must be corrected before a passed audit.
3. **Verify JSON-sidecar freshness and consistency.** For whichever of `02_requirements.json`,
   `04_tasks.json`, and `05_execution.json` exist for the audited feature, confirm each was
   regenerated alongside its Markdown source rather than hand-edited or left behind after a
   revision — once the "whenever the Markdown updates, the JSON updates too" rule applies to a
   sidecar, a stale or missing one is a CERTAIN finding, the same severity class as a broken
   navigation link, not a stylistic nit. When a sidecar exists, spot-check a sample of its
   structured fields directly against the Markdown's authoritative state instead of only trusting
   rendered prose — e.g. diff `04_tasks.json`'s `concurrency.ready`/`parallel_candidates` against
   the checklist's checkbox and `Depends on` state, or `02_requirements.json`'s
   `requirements[].criteria[]` against the numbered `**R<n>.<m>**` EARS criteria — this is
   strictly easier for a reviewer than re-deriving the dependency graph or criterion set from
   Markdown regex by hand, and it is required wherever the sidecar exists, not only when a
   Technical/factual reviewer happens to notice a discrepancy.
4. **Establish the audit boundary.** Confirm that requirements preserve the approved problem,
   scope, non-goals, and chosen approach, then list the requirement criteria, design
   correctness properties, task leaves, proposed changed files, and checkpoints.
   When `codebase-memory-mcp` has a current index, invoke `codebase-memory-reference`; use
   `search_graph` to validate named symbols and `trace_path` to check hidden callers,
   dependencies, data flow, cross-service effects, and proposed impact. Use `query_graph` only
   for a necessary multi-hop question, and corroborate material findings against source.
   Read only the source files named by the design or tasks, plus the smallest
   authoritative source needed to verify a factual claim. For claims that
   depend on evolving libraries, frameworks, SDKs, APIs, CLIs, or cloud
   services, use `context7-mcp` to query current official documentation and
   compare it with the design's Current Technology Evidence. Do not broaden
   the implementation scope while auditing it.
  Review dependency evidence independently under
  [dependency-evidence.md](../spec-driven/references/dependency-evidence.md). Treat any violated
  applicability, ownership, order, record, status, or freshness rule as a defect. This focused
  check does not replace broad security, authorization, privacy, or threat-model review.
5. **Confirm depth.** Classify a depth (`quick`/`medium`/`thorough`) by default from the
   artifacts' own signals per [delegation.md](../spec-driven/references/delegation.md)'s criteria
   — a `Risk: high` task, a `main`/`release` delivery gate, or a security/migration/destructive
   marker in the design pushes to `thorough`; ordinary multi-file work is `medium`; a narrow,
   low-risk feature is `quick`. Ask the user only when the user hasn't stated a depth **and** the
   signals genuinely don't indicate one (e.g. a brand-new feature with no risk markers yet).
   Resolve the reviewer count and lens assignment deterministically with
   `scripts/fanout.py --depth <depth> [--escalate]` (escalate only for a requested Thorough audit)
   — never hard-code a reviewer count here:
   - **Quick** fan-out → one traceability reviewer; certain fixes only.
   - **Medium** fan-out → one reviewer covering traceability plus technical/factual review;
     include a short uncertainty checklist.
   - **Thorough** fan-out (escalated) → two reviewers split across traceability and
     technical/factual review, plus the third, frontier-tier/extra-high-reasoning reviewer taking
     the adversarial lens; add an execution-risk review and a compact risk register.
   Resolve each reviewer's model AND reasoning level together, deterministically, per
   [references/model-routing.md](../spec-driven/references/model-routing.md): classify traceability
   and technical/factual lenses as `task_category: review`, run
   `scripts/model-router.py --category review [--risk <declared_risk>]` from the `spec-driven`
   skill directory, and use its `resolved_model` and `reasoning_level` together. The adversarial
   lens is `task_category: heavy_reasoning`, which never resolves below the balanced tier or high
   reasoning. Never hard-code a model name or reasoning level in a reviewer's context packet.
6. **Launch bounded reviewers.** Compute a deterministic SHA-256 digest over
  `01_discovery.md` through `04_tasks.md`. Give each reviewer a context packet containing only
  the artifact digest, its assigned criteria/properties/tasks and directly relevant excerpts,
  the in-scope source list, applicable policy links, and one independent lens. Do not send raw
  artifacts, full conversation history, or unrelated steering. Use the portable `reviewer` role
  and `review_verdict` return contract from
  [spec-family.yaml](../spec-driven/contracts/spec-family.yaml). Run independent lenses in
  parallel only when the selected depth requires more than one:
   - **Traceability:** EARS quality; criterion → property → task coverage;
     discovery decision → requirement boundary → design approach consistency;
     diagram, test, and documentation-contract coverage; dependency IDs, cycles, computed stages,
    task ordering, and checkpoints. Verify
    that any operational/control flowchart follows the Mermaid ISO 5807 profile and that any Gantt has evidence for
    its dates and dependencies. When discovery includes a mind map, verify that complexity made it
    useful, it appears under `## Solution Space Mind Map` between the approaches table and chosen
    direction, it matches the final alternatives and boundary, and it supplements rather than
    replaces comparison and approval. Do not require a mind map for a small linear decision.
    When tasks include `Stage and Dependency Overview`, verify every leaf task appears in its
    declared stage, every `Depends on` edge appears exactly once, checkpoint gates are distinct,
    and the diagram adds no undeclared order, date, or estimate. A node's `status` color is not
    an undeclared addition when it matches the sidecar's `checked`/`concurrency` fields at the
    digest being audited — treat a status that disagrees with those fields as a CERTAIN finding
    instead. Require the overview only when the task topology is non-trivial. For every block diagram, verify static
    composition/grouping is the actual question and that it agrees with its authoritative scope,
    repository, or design source.
   - **Technical/factual:** current repository facts, design feasibility,
     source-of-truth alignment, documentation links, Mermaid renderability, and applicable
     cross-cutting risk gates (security, privacy, accessibility, performance, observability,
     migration, rollout, rollback). Separately verify `dependency-security-audit` mode, report,
     freshness, and `pass`/`warnings`/`blocked`/`unavailable`/`invalid` semantics. Perform the
     JSON-sidecar freshness and structured-field spot-check from step 3 as part of this lens when
     it has not already been resolved.
   - **Adversarial (thorough only):** ambiguous scope, unstated assumptions,
     unsafe execution ordering, missing failure paths, and invalid approval
     gates.
7. **Classify and merge findings.** Include only findings with at least 80%
   confidence. Deduplicate them, then label each as:
   - **CERTAIN:** statically provable from the artifacts, repository source,
     project rules, or a Mermaid renderer result; propose an exact fix.
   - **UNCERTAIN:** dependent on runtime state, user review, external systems,
     or visual judgment; give a focused verification method.
   Prioritize P0 (blocks execution), P1 (must resolve before shipping), or P2
   (improves clarity or resilience).
8. **Render when applicable.** For every Mermaid diagram in reviewed steering docs, numbered
  artifacts, and reviewed debugging evidence, validate and render it through the `mermaid` skill;
  treat a syntax failure,
  clipped label, unreadable render, semantically inappropriate type, contradiction with its
  authoritative source, task-topology drift, or discovery mind map that violates the conditional
  placement and synchronization contract as a CERTAIN finding. Follow the shared diagram policy;
  do not require conditional diagrams when prose or a table is clearer. When a diagram's fenced
  Mermaid source was generated from an IR JSON per
  [`mermaid/reference/ir.md`](../mermaid/reference/ir.md) (a `state-machine` requirements
  lifecycle, a `requirement-links` traceability diagram, a `flowchart` stage/dependency overview,
  or a `gantt` timing chart), locate that IR JSON and diff its structural fields — states and
  transitions; requirements, elements, and links; nodes, groups, and edges; or sections and bars,
  as applicable — directly against the artifact's authoritative source: the numbered EARS
  criteria, the task checklist's `Stage`/`Depends on` fields, or the timing ledger's closed
  interval rows. This structural diff is deterministic and strictly stronger than judging only
  whether the rendered image looks plausible; treat a mismatch between the IR JSON and its
  authoritative source as a CERTAIN finding. Perform this diff in addition to, not instead of, the
  render-validation check above — render/validate the exact fenced Mermaid source regardless of
  whether it was hand-authored or IR-generated; a diagram that diffs clean against its IR JSON but
  fails to render (or vice versa) is still a CERTAIN finding.
9. **Report and request disposition.** Present only the findings in language a human reviewer can
   act on without reconstructing agent context. Update only the project-local
   `.specs/<slug>/00_state.md`:
  set Audit to `passed` when there are no P0/P1 findings, otherwise `findings_open`; record
  depth, date, and artifact digest. Keep the state entry to the material audit outcome and evidence; do not add
   reviewer-agent choreography, tool-call/checker narration, validation provenance, or other
   process metadata. When the user applies all audit fixes and re-approves affected artifacts,
   set Audit to `fixes_applied`; a repeat audit is optional unless requested or policy requires it.
   Never alter the reviewed specification artifacts unless the user directs it. If the audit
   contains one or more fixes, end by asking: “Would you like me to apply these
   audit fixes to the spec?” Do not check off tasks, modify a spec, or begin
   `spec-execute` unless the user explicitly directs that next step.

## Required Output

```markdown
## Audit summary

<depth, artifacts reviewed, reviewer lenses, and result>

## Fix before execution

### P0
- [ ] AUDIT-1: `<artifact-or-source>:<line>` — <defect>
  **Why certain:** <static evidence>
  **Fix:** <specific change>

### P1
...

## Verify before execution

- [ ] CHECK-1: <focused validation>
  **Why uncertain:** <runtime or judgment dependency>
  **How to check:** <concrete method>

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| <thorough audits only; keep concise> | <low/medium/high> | <low/medium/high> | <action> |
```

Output limits:

- Quick: no uncertainty checklist or risk register.
- Medium: at most 10 uncertainty checks; no risk register.
- Thorough: at most 15 uncertainty checks and 10 risks.
- If no findings exist, state that explicitly and report the evidence checked.

## Phase Routing

- Defective, ambiguous, or non-EARS acceptance criterion → `spec-requirements`,
  then re-approve requirements and downstream artifacts.
- Missing design coverage, stale fact, invalid diagram, or conflicting design
  decision → `spec-design`, then re-approve design and revise tasks if needed.
- Missing requirement citation, incorrect task order, absent verification, or
  ineffective checkpoint → `spec-tasks`, then approve the revised task plan.
- Audit passes → proceed to `spec-execute` after the user approves the task plan. Applied audit
  fixes → proceed after affected artifacts are re-approved, unless the user or policy requests a
  repeat audit. Any material spec revision makes an earlier audit result stale but does not add a
  mandatory audit gate.

## Review Rules

- Treat the EARS criteria, not prose intent, as the acceptance boundary.
- Treat missing or superficial documentation for planned public code as a task-contract gap;
  route it to `spec-tasks` before execution.
- Treat missing/stale dependency evidence, unreviewed warnings, blocked/unavailable/invalid
  results, or a clean claim unsupported by linked reports as an actionable defect before the
  affected integration or release gate.
- Preserve the planned file scope unless a P0 finding proves it cannot meet a
  stated requirement.
- Never report a speculative concern as certain.
- Do not pad the checklist or risk register to reach a limit.
- Do not persist audit learnings or edit repository documentation without the
  user's explicit request.
