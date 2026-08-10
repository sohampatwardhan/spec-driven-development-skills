# Model routing policy

Deterministic model and reasoning-level selection for subagent-delegated work across the
spec-driven family. Canonical data lives in
[`contracts/spec-family.yaml`](../contracts/spec-family.yaml) under `capability_tiers`,
`reasoning_levels`, `task_categories`, `model_routing`, and `reasoning_routing`; this document
explains it for humans and lightweight models. Do not hard-code a vendor model name in any skill
body or reference other than the defaults table below — read the contract instead.

## Two independent axes, not one combined rank

**`capability_tier`** is *which model* — its base capability, speed, and unit cost.
**`reasoning_level`** is *how much deliberation* that chosen model spends on this one task.
They are resolved through separate tables from the same declared inputs (`task_category`,
`declared_risk`), so they can diverge:

- A well-specified but effortful task can be `balanced` + `high` — a mid-tier model reasoning
  hard beats a top-tier model reasoning shallowly.
- An easy task that still needs deep world knowledge can be `frontier` + `low`.

Approximate mental model: outcome quality ≈ capability × reasoning × task clarity. Never fold
these into one combined tier name, and never assume "stronger model" implies "more reasoning" or
vice versa — resolve both, independently, every time.

## Fields (stable, machine-parseable)

| Field | Meaning |
|---|---|
| `task_category` | One of `quick_lookup`, `code_analysis`, `heavy_reasoning`, `review`. |
| `capability_tier` | One of `economical`, `balanced`, `frontier`. |
| `reasoning_level` | One of `low`, `medium`, `high`, `extra_high`. |
| `default_tier` | The tier a task category resolves to with no override or escalation. |
| `default_reasoning` | The reasoning level a task category resolves to with no override or escalation. |
| `requested_override` | An explicit user- or policy-named model or tier. Always wins. |
| `requested_reasoning_override` | An explicit user- or policy-named reasoning level. Always wins. |
| `declared_risk` | `none`, `elevated`, or `high`; drives escalation on *both* axes, never de-escalation. |
| `resolved_model` | The concrete model name chosen for this run; always recorded. |
| `substitution` | `true`/`false`; set `true` when the requested tier's model was unavailable. |

## Task category → default tier and reasoning level

| `task_category` | `default_tier` | `default_reasoning` | Typical work |
|---|---|---|---|
| `quick_lookup` | `economical` | `low` | Single fact, path lookup, file existence check, short status read. |
| `code_analysis` | `balanced` | `medium` | Multi-file trace, requirement/design/task consistency check, normal implementation. |
| `heavy_reasoning` | `frontier` | `high` | Architecture decisions, adversarial/security review, high-risk integration, escalated fixes. |
| `review` | `balanced` | `medium` | Traceability/technical review; escalate to `frontier`/`extra_high` only for adversarial/high-risk lens. |

## Capability tier → safe default model

| `capability_tier` | Default model (this environment) | Notes |
|---|---|---|
| `economical` | `claude-haiku-4-5-20251001` | Cheapest/fastest; use for `quick_lookup` and mechanical steps. |
| `balanced` | `claude-sonnet-5` | Default for normal implementation and single-lens review. |
| `frontier` | `claude-opus-5` | Reserve for architecture, adversarial review, and escalated fixes. |

### Cross-vendor tier mapping (for portability, not for hard-coding)

These tiers are a vendor-neutral concept; other tools/runtimes may resolve the same tier to a
different provider's model. Reference only — the contract's `defaults` table above is what this
family actually resolves to in this environment.

| Capability tier | OpenAI (GPT-5.6 family) | Anthropic (Claude family) | Google (Gemini) |
|---|---|---|---|
| `frontier` | Sol | Opus | Gemini Pro |
| `balanced` | Terra | Sonnet | Gemini Flash |
| `economical` | Luna | Haiku | Gemini Flash-Lite |

Note: some vendors' "balanced" releases target sustained frontier/agentic performance and can
overlap with another vendor's `frontier` tier on particular workloads — the tier name is a
role, not a strict cross-vendor equality.

## Reasoning level

| `reasoning_level` | Use it when | Typical tasks |
|---|---|---|
| `low` | The task is explicit, local, and easy to verify | Summaries, formatting, small edits, lookups |
| `medium` | Normal default; some planning or multiple steps needed | Feature work, ordinary debugging, multi-file changes |
| `high` | Ambiguity, non-obvious causality, or meaningful failure risk | Complex bugs, code review, design tradeoffs |
| `extra_high` | System-wide, irreversible, security-sensitive, or expensive to get wrong | Architecture, migrations, concurrency, auth |

Higher reasoning trades more latency/usage for deeper investigation and validation; treat `high`
as the practical default escalation point and `extra_high` as a quality mode reserved for
genuinely consequential or cross-cutting work — do not reach for it merely because a task feels
important.

## Selection order (deterministic)

Each axis resolves independently through this same three-step order:

1. **`requested_override`** (or `requested_reasoning_override`) — an explicit user- or
   project-policy-named value always wins. Record it in the report; do not silently substitute.
2. **`risk_escalation`** — if `declared_risk` is `elevated` or `high`, raise to the next stronger
   value on *that* axis. Tier escalation only ever moves `economical` → `balanced` → `frontier`;
   reasoning escalation only ever moves `low` → `medium` → `high` → `extra_high`. Never the
   reverse, and escalating one axis does not force the other to escalate too.
3. **`task_category_default`** — otherwise use the tables above.

`heavy_reasoning` tasks never resolve below `balanced` tier or `high` reasoning, even under
override, per `model_routing.override_policy`/`reasoning_routing.override_policy` in the
contract. If a resolved tier's model is unavailable, escalate to the next stronger available
tier, set `substitution: true`, and record the reason. Never invent a model ID, never omit
`resolved_model` or `reasoning_level` from a report.

## Using the router

Run:

```bash
scripts/model-router.py --category <task_category> \
    [--risk <declared_risk>] \
    [--override <model_or_tier>] \
    [--reasoning-override <reasoning_level>]
```

from the `spec-driven` skill directory. It prints one JSON object with `task_category`,
`capability_tier`, `resolved_model`, `substitution`, `reasoning_level`, `reason`, and
`reasoning_reason` — safe for a script or a lightweight model to parse without prose. Use
`--format text` for a one-line human summary that names both the resolved model and the
reasoning level.

## Where this applies

- `spec-execute` capability-tier and reasoning-level selection for implementer/reviewer
  subagents (`SKILL.md` "Capability mapping").
- `spec-audit` reviewer-lens depth selection (`SKILL.md` "Confirm depth").
- `spec-tasks` `04_tasks.json`, which records each task's resolved `capability_tier`,
  `resolved_model`, and `reasoning_level` alongside its declared `Task category`/`Risk`.
- `spec-tasks` `Delegation` metadata, which names *whether* a worker is separate; this policy
  names *which* tier/model/reasoning-level a runtime adapter should use once delegated.

This policy changes only the deterministic input to model and reasoning selection; it does not
change any phase's approval gates, task contracts, or verification requirements.
