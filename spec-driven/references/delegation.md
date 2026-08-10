# Delegation fan-out — how many subagents, not which model

`model-routing.md` answers "which model resolves a task category". This document answers a
different question: "how many independent subagents does this task, wave, or gate need". The
two compose — resolve a depth here, then resolve each reviewer's model there.

Canonical data lives in [`contracts/spec-family.yaml`](../contracts/spec-family.yaml) under
`delegation_depth` and `fanout`; this document explains it for humans and lightweight models.
Do not hard-code a reviewer count, fix-round cap, or depth threshold in any skill body —
read the contract, or call `scripts/fanout.py`, instead.

## Two-step resolution

1. **Classify a depth** (`quick`/`medium`/`thorough`) by reading the task, wave, or gate
   against `delegation_depth`'s criteria. This step is judgment, not computation — the same
   status `declared_risk` has in model routing: an agent decides it by reading the actual
   work, not by running a script.
2. **Resolve the fan-out** deterministically from that depth with
   `scripts/fanout.py --depth <depth> [--escalate]`. Everything downstream of the depth
   classification — reviewer count, reviewer capability tier, reviewer reasoning level,
   self-repair round budget — is a pure table lookup with no further judgment. Tier and
   reasoning level are two independent axes here too (see model-routing.md): escalation can
   raise either, both, or neither, per the contract's `fanout.escalation`.

## Depth criteria

| Depth | Criteria |
|---|---|
| `quick` | At most 3 files; no public contract, migration, dependency resolution, security, privacy, production, destructive operation, or high-risk task; not a dependency of 3+ other tasks. |
| `medium` | Ordinary multi-file work, one moderate-risk integration boundary, or a task that is a dependency of 3+ other tasks — blast radius promotes depth even when the file count alone looks small. |
| `thorough` | Authentication/authorization, sensitive data, migration, deployment, destructive operations, dependency resolution, public compatibility, a protected-main/release delivery gate, or an explicit high-risk marker. |

This is the same three-way classification `spec-execute`'s self-hardening preflight and
`spec-audit`'s review depth already used as separate prose; it is now one table both read.

## Fan-out per depth

| Depth | Reviewers | Reviewer tier | Reviewer reasoning | Self-repair rounds before returning to the owning gate |
|---|---|---|---|---|
| `quick` | 1 | `economical` | `low` | 1 |
| `medium` | 1 | `balanced` | `medium` | 2 |
| `thorough` | 2 | `balanced` | `high` | 2 |
| `thorough` + escalation | 3 | 2×`balanced` + 1×`frontier` (adversarial) | 2×`high` + 1×`extra_high` | 2 |

Escalation applies only at a protected-main/release delivery gate, or when the user
specifically requests a Thorough audit — pass `--escalate`. Escalation only ever adds
reviewers or raises a tier; it never removes one.

## Other signals worth considering (not fully mechanizable)

Two things legitimately affect fan-out but resist a clean table entry, so they're handled as
an explicit, recorded escalation rather than folded into the deterministic table:

- **Novelty/ambiguity** — first integration of an unfamiliar library, or the first use of a
  pattern in this repository. A controller may raise the depth or reviewer tier once for a
  recorded reason; this mirrors the existing "raise the budget once for a recorded high-risk
  reason" pattern used elsewhere in `spec-execute`.
- **Wave size vs. per-task depth** — an accumulated wave of several `quick` tasks still gets at
  least one wave-level reviewer by default (`spec-execute`'s per-wave review), even though no
  individual task in it reached `medium`. Fan-out is computed once per review unit (task, wave,
  or gate), not summed across the tasks it covers.

## Self-repair rounds vs. returning to the gate

`self_repair_rounds` bounds how many times a defect gets fixed and re-reviewed **in place**
before the loop must stop treating it as routine friction. Within that budget, a task-list- or
implementation-level defect is repaired autonomously (see `spec-execute`'s delegated-authority
rules) — this is not an interruption. Exhausting the budget is not itself a request for user
authorization to keep trying; it is the signal to autonomously classify the defect once more:

- A mechanical task-list defect (wrong scope, missing/incorrect dependency, wrong file, wrong
  size) is still self-repairable under delegated authority — rewrite the task contract, record
  it, and continue.
- A defect that conflicts with an approved requirement/design decision, or would cross the
  delegated-approval boundary, is a genuine stop: return to the owning `spec-*` phase for
  re-approval. This is the only case where exhausting the round budget produces a real
  interruption, and it is deliberate, not "unnecessary".
