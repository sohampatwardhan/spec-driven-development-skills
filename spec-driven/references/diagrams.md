# Diagram policy for spec artifacts

Diagrams are review aids, not decoration. Add one when it makes a material relationship, boundary,
dependency, transition, interaction, or timeline easier to understand or verify than prose and
tables alone, or when a phase contract mandates a derived evidence view such as the observed-time
Execution Gantt. Invoke the [`mermaid`](../../mermaid/SKILL.md) skill, use one authoritative syntax source, and
render-validate the exact fenced source before saving it.

## Generating from structured data vs. hand-authoring

Before authoring any diagram in this policy, decide whether its content is already fully
determined by structured data you have on disk — task metadata, a timing ledger, a
state-transition table, a requirement-traceability table, a verified host configuration — or
whether it synthesizes judgment with no structured source (an architecture sketch, a discovery
alternatives map, a hypothesized debugging sequence).

- **Structured source exists:** build the IR JSON for the matching family (`graph`, `timeline`,
  `state-machine`, `sequence`, `requirement-links` — see
  [`mermaid/reference/ir.md`](../../mermaid/reference/ir.md)) and generate the Mermaid source
  deterministically with `mermaid/scripts/render.py`, then render-validate exactly as any other
  diagram (`scripts/check.sh` or `validate_and_render_mermaid_diagram`).
- **No structured source:** hand-author the Mermaid source directly, as the rest of this policy
  describes, and render-validate before saving it.

Either way, the diagram still needs render-validation before it counts as verified — generation
changes how the source is authored, not whether it's checked. This doesn't change the phase
decision matrix below: diagram *type* selection is orthogonal to authoring mechanism. It only
decides whether to build IR JSON and run `render.py`, or write Mermaid text by hand, for
whichever diagram type the matrix calls for.

## Source-of-truth rule

Every diagram names or has an obvious authoritative source in the same artifact. Requirements,
task metadata, state tables, timing ledgers, repository facts, and approved decisions remain
canonical. A derived diagram must not introduce facts, dependencies, dates, states, ordering, or
scope absent from that source. Update or remove the diagram when the source changes.

## Phase decision matrix

| Phase / artifact | Useful diagram potential | Preferred type | Default decision |
|---|---|---|---|
| Steering `product.md` | Stable product actors and system boundary | `C4Context` or `block` | Conditional |
| Steering `tech.md` | Stable runtime/deployment composition | `block`, `C4Container`, or `architecture-beta` | Conditional |
| Steering `structure.md` | Stable subsystem/module partition | `block` | Conditional |
| Discovery | Alternatives and concern hierarchy | `mindmap` | Conditional |
| Discovery | Chosen scope boundary or static subsystem partition | `block` or `C4Context` | Conditional, deliberately high-level |
| Requirements | Externally observable lifecycle with many legal/illegal transitions | `stateDiagram-v2` | Exceptional |
| Requirements | Formal requirement-to-verification relationships | `requirementDiagram` | Exceptional, mainly compliance-heavy work |
| Design | Static composition, hardware/software partition, or grouped topology | `block` | Conditional |
| Design | System/cloud boundaries | `C4Context`/`C4Container` or `architecture-beta` | Conditional |
| Design | Messages over time | `sequenceDiagram` | Conditional |
| Design | Lifecycle | `stateDiagram-v2` | Conditional |
| Design | Persisted relationships or object model | `erDiagram` or `classDiagram` | Conditional |
| Design | Branching operational control | ISO 5807-aligned `flowchart` | Conditional |
| Tasks | Stages, checkpoints, and dependency DAG | `flowchart` | Required when topology is non-trivial |
| Tasks | Confirmed calendar schedule | `gantt` | Conditional; never invent dates |
| Execution | Observed run/task intervals | `gantt` | Required by `spec-execute` |
| Debugging evidence | Cross-component event causality or complex diagnostic branching | `sequenceDiagram` or ISO 5807-aligned `flowchart` | Exceptional |
| Hooks | Multi-event unattended automation and safety branches | ISO 5807-aligned `flowchart` or `sequenceDiagram` | Conditional |
| State, verification, finish | Compact status, evidence, or integration choices | Usually table/list/prose | No diagram by default |

## Choosing block diagrams

Use Mermaid `block` when the question is “what static parts exist, how are they grouped, and how
are those groups connected?” It is particularly suitable for hardware/software partitions,
firmware layers, bounded subsystems, pipeline stages as composition, and module ownership maps.
Use `C4Context`/`C4Container` when people/system/container semantics matter, `architecture-beta`
when service or cloud-icon topology matters, and `flowchart` when control, decisions,
prerequisites, or execution order matter.
Do not use a block diagram merely to arrange prose in boxes.

## Review contract

Audit every included diagram for renderability, readability, semantic type choice, and agreement
with its authoritative source. A syntactically valid diagram that contradicts the artifact is a
defect. Do not require a conditional diagram when prose or a table communicates the material facts
more clearly.
