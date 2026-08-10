# Spec-Driven Development skill family — design

Approved design (2026-08-07). A faithful, self-contained clone of Kiro's spec-driven
workflow as a family of personal Claude Code skills. Durable in `~/.claude/skills/`
(not the plugin cache), works with superpowers uninstalled.

## Skills

| Skill | Kiro pillar | Responsibility |
|---|---|---|
| `spec-driven` | overview | Router/entry. Explains workflow + `.specs/` layout, detects current phase, routes. |
| `spec-steering` | Steering | `.specs/steering/{product,tech,structure}.md`; onboard existing codebases. |
| `spec-discovery` | Phase 1 | Problem boundary, alternatives, and approved direction → `01_discovery.md`. Gated. |
| `spec-requirements` | Phase 2 | User stories + EARS criteria → `02_requirements.md`. Gated. |
| `spec-design` | Phase 3 | Architecture, data models, mermaid diagrams, correctness properties `Validates: Requirements X.Y` → `03_design.md`. Gated. |
| `spec-tasks` | Phase 4 | Dependency-ordered task contracts, requirement traceability, required verification, checkpoints → `04_tasks.md`. Gated. |
| `spec-audit` | Phase 4.5 (optional) | Parallel traceability, factual, and risk review before execution. |
| `spec-execute` | Phase 5 | Per-task TDD loop with a durable `05_execution.md` ledger, verification, recovery, and checkpoints. |
| `spec-finish` | Phase 6 | Final verification and user-owned integration decision. |
| `spec-hooks` | Hooks | Select and safely configure supported host hooks from verified current documentation. |

## Artifacts

```
.specs/
  steering/{product,tech,structure}.md
  <feature-slug>/{00_state.md, 01_discovery.md, 02_requirements.md, 03_design.md, 04_tasks.md, 05_execution.md}
```

## Traceability chain (bidirectional)

EARS criterion `R1.2` → design property `Validates: Requirements 1.2` → task `_Requirements: 1.2_`.
`spec-execute` verifies each finished task against its cited criteria.

## Principles

- **Phase gating.** `00_state.md` records approval, invalidation, audit, and execution gates.
- **EARS.** Requirements are testable (`references/ears.md`).
- **Self-contained.** No dependency on superpowers or a missing configuration skill.
- **Mermaid.** `spec-design` uses the `mermaid` skill; render inline in chat, embed source in `03_design.md`.
- **Alerts.** Use one or two purposeful GitHub Markdown alerts per artifact for approval gates,
  stop conditions, risks, or essential skimming context; never place them consecutively.
- **Durable.** Personal skills, upgrade-proof.
