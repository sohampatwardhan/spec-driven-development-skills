# Spec-Driven Development Skills

A rigorous, [Agent Skills](https://agentskills.io/specification)-compatible spec-driven
workflow — Kiro-style discovery → requirements → design → tasks, gated by explicit approval,
then implemented task-by-task with verification and a deterministic evidence trail. Built for
Claude Code, and portable to any tool that reads the open `SKILL.md` format (Codex, Antigravity,
GitHub Copilot CLI, Cursor, Grok CLI, VS Code Copilot).

**Core principle:** do not write requirements or code until discovery is approved, and do not
implement until requirements, design, and tasks exist and the user has approved each. Structure
first, code second. Every artifact is gated by explicit approval; every task traces back to a
numbered requirement.

## The pipeline

| Phase | Skill | Produces | Gate |
|---|---|---|---|
| Context (optional) | `spec-steering` | `.specs/steering/*.md` | — |
| 1. Discovery | `spec-discovery` | `01_discovery.md` (problem, alternatives, chosen direction) | user approves |
| 2. Requirements | `spec-requirements` | `02_requirements.md` (user stories + EARS) | user approves |
| 3. Design | `spec-design` | `03_design.md` (architecture + diagrams + correctness properties) | user approves |
| 4. Tasks | `spec-tasks` | `04_tasks.md` (dependency-ordered, traced checkbox tasks) | user approves |
| 4.5 Audit (optional) | `spec-audit` | Findings + audit state | user- or risk-selected |
| 5. Execute | `spec-execute` | `05_execution.md` + working, verified code | per-task + checkpoints |
| 6. Finish | `spec-finish` | Integration decision + final evidence | user chooses |
| (automation) | `spec-hooks` | Host-native event-triggered automation | — |
| (support) | `spec-debugging`, `spec-verification` | Root-cause fixes, evidence-backed completion claims | — |

## What makes this deterministic, not just prose

- **`scripts/spec-check.py`** validates every numbered artifact: EARS grammar, requirement ↔
  design-property ↔ task traceability, task dependency graphs (stages, cycles, parallel-safety),
  navigation, and dependency-security evidence — and emits three generated, hash-verified JSON
  sidecars (`00_state.json`, `04_tasks.json`, `05_execution.json`) so a computer never has to
  regex the Markdown to know what's approved, what's ready to run, or what's blocked.
- **`scripts/model-router.py`** and **`scripts/fanout.py`** resolve *which model* (capability
  tier: `economical`/`balanced`/`frontier`) and *how much reasoning* (`low`/`medium`/`high`/
  `extra_high`) a delegated subagent gets — two independent axes, resolved deterministically from
  a task's declared category and risk, never hard-coded.
- **`scripts/spec-nav.py`** keeps every artifact's cross-links current and auto-linkifies
  forward references the moment their target exists.

## Requirements

- Copy the skill folders you want into your tool's Agent Skills directory (e.g. `~/.claude/skills/`,
  `~/.agents/skills/` — see the [Agent Skills spec](https://agentskills.io/specification) for
  every supported tool's path).
- Python 3.11+ with PyYAML for the deterministic scripts.
- The companion [`mermaid-skill`](https://github.com/sohampatwardhan/mermaid-skill) is optional
  but recommended: several workflows generate diagrams deterministically from a JSON
  intermediate representation via that skill rather than hand-authoring Mermaid.

## Testing

```bash
cd spec-driven && python3 -m pytest tests/ -q
```

One test gracefully skips unless `mermaid-skill` is installed alongside this family as a sibling
skill (it exercises the deterministic Gantt-generation integration).

## License

MIT — see [LICENSE](LICENSE).
