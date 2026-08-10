#!/usr/bin/env python3
"""Deterministic model-tier and reasoning-level router for spec-driven subagent delegation.

Reads `contracts/spec-family.yaml` (`capability_tiers`, `reasoning_levels`, `task_categories`,
`model_routing`, `reasoning_routing`) and resolves a task category, optional declared risk, and
optional explicit overrides to one concrete model AND one reasoning level.

capability_tier and reasoning_level are two INDEPENDENT axes, not one combined rank:
capability_tier is *which model* (base capability/speed/cost); reasoning_level is *how much
deliberation* that chosen model spends on this one task. They are resolved through separate
tables from the same declared inputs, so they can diverge — e.g. `balanced` + `high` for a
well-specified but effortful task, or `frontier` + `low` for an easy task that still needs
top-tier world knowledge. Never collapse them into one combined tier.

Usage:
    scripts/model-router.py --category code_analysis
    scripts/model-router.py --category review --risk high
    scripts/model-router.py --category quick_lookup --override claude-haiku-4-5-20251001
    scripts/model-router.py --category heavy_reasoning --override economical   # tier override, clamped
    scripts/model-router.py --category code_analysis --reasoning-override extra_high

Output is one JSON object by default (--format json), or a single human-readable line
with --format text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "spec-family.yaml"

TIER_ORDER = ["economical", "balanced", "frontier"]
REASONING_ORDER = ["low", "medium", "high", "extra_high"]


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _stronger(order: list[str], value: str) -> str:
    """Return the next stronger value in `order`, or the same value if already strongest."""
    idx = order.index(value)
    return order[min(idx + 1, len(order) - 1)]


def _clamp_min(order: list[str], value: str, floor: str) -> str:
    """Return whichever of value/floor is stronger, per `order`."""
    return value if order.index(value) >= order.index(floor) else floor


def _resolve_tier(
    contract: dict,
    task_category: str,
    declared_risk: str,
    override: str | None,
    available_models: dict | None,
) -> tuple[dict, str]:
    """Resolve capability_tier + resolved_model. Returns (fields, reason)."""
    task_categories = contract["task_categories"]
    routing = contract["model_routing"]
    defaults = dict(routing["defaults"])
    if available_models:
        defaults.update(available_models)

    category = task_categories[task_category]
    tier = category["default_tier"]
    reason = f"task_category_default:{task_category}->{tier}"
    substitution = False

    override_tier = None
    override_model = None
    if override:
        if override in TIER_ORDER:
            override_tier = override
        else:
            override_model = override
        if override_tier is not None:
            tier = override_tier
        reason = f"requested_override:{override}"

    if override_model is None and declared_risk in ("elevated", "high"):
        escalated = _stronger(TIER_ORDER, tier)
        if escalated != tier:
            tier = escalated
            reason += f"+risk_escalation:{declared_risk}"

    if task_category == "heavy_reasoning":
        clamped = _clamp_min(TIER_ORDER, tier, "balanced")
        if clamped != tier:
            tier = clamped
            reason += "+heavy_reasoning_floor:balanced"

    if override_model is not None:
        resolved_model = override_model
    else:
        resolved_model = defaults.get(tier)
        if resolved_model is None:
            escalate_tier = tier
            while resolved_model is None and escalate_tier != TIER_ORDER[-1]:
                escalate_tier = _stronger(TIER_ORDER, escalate_tier)
                resolved_model = defaults.get(escalate_tier)
            if resolved_model is None:
                raise RuntimeError("no available model for any tier; check model_routing.defaults")
            if escalate_tier != tier:
                tier = escalate_tier
                substitution = True
                reason += f"+substitution:escalated_to:{tier}"

    return (
        {"capability_tier": tier, "resolved_model": resolved_model, "substitution": substitution},
        reason,
    )


def _resolve_reasoning(
    contract: dict,
    task_category: str,
    declared_risk: str,
    reasoning_override: str | None,
) -> tuple[str, str]:
    """Resolve reasoning_level independently of capability_tier. Returns (level, reason)."""
    task_categories = contract["task_categories"]
    category = task_categories[task_category]
    level = category["default_reasoning"]
    reason = f"task_category_default:{task_category}->{level}"

    if reasoning_override:
        if reasoning_override not in REASONING_ORDER:
            raise ValueError(
                f"unknown reasoning level {reasoning_override!r}; expected one of {REASONING_ORDER}"
            )
        level = reasoning_override
        reason = f"requested_reasoning_override:{reasoning_override}"
    elif declared_risk in ("elevated", "high"):
        escalated = _stronger(REASONING_ORDER, level)
        if escalated != level:
            level = escalated
            reason += f"+risk_escalation:{declared_risk}"

    if task_category == "heavy_reasoning":
        clamped = _clamp_min(REASONING_ORDER, level, "high")
        if clamped != level:
            level = clamped
            reason += "+heavy_reasoning_floor:high"

    return level, reason


def resolve(
    contract: dict,
    task_category: str,
    declared_risk: str = "none",
    override: str | None = None,
    available_models: dict | None = None,
    reasoning_override: str | None = None,
) -> dict:
    """Deterministically resolve a task category (+ risk, + overrides) to a model and a
    reasoning level — two independent axes, each resolved through its own table."""
    task_categories = contract["task_categories"]

    if task_category not in task_categories:
        raise ValueError(
            f"unknown task_category {task_category!r}; expected one of {sorted(task_categories)}"
        )
    if declared_risk not in ("none", "elevated", "high"):
        raise ValueError(f"unknown declared_risk {declared_risk!r}")

    tier_fields, tier_reason = _resolve_tier(
        contract, task_category, declared_risk, override, available_models
    )
    reasoning_level, reasoning_reason = _resolve_reasoning(
        contract, task_category, declared_risk, reasoning_override
    )

    return {
        "task_category": task_category,
        "declared_risk": declared_risk,
        "capability_tier": tier_fields["capability_tier"],
        "resolved_model": tier_fields["resolved_model"],
        "substitution": tier_fields["substitution"],
        "reasoning_level": reasoning_level,
        "reason": tier_reason,
        "reasoning_reason": reasoning_reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--category",
        required=True,
        help="Task category: quick_lookup, code_analysis, heavy_reasoning, or review.",
    )
    parser.add_argument("--risk", default="none", help="Declared risk: none, elevated, or high.")
    parser.add_argument(
        "--override",
        default=None,
        help="Explicit model name or capability tier (economical/balanced/frontier) that always wins.",
    )
    parser.add_argument(
        "--reasoning-override",
        default=None,
        help="Explicit reasoning level (low/medium/high/extra_high) that always wins.",
    )
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH, help="Path to spec-family.yaml.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args(argv)

    contract = load_contract(args.contract)
    try:
        result = resolve(
            contract, args.category, args.risk, args.override,
            reasoning_override=args.reasoning_override,
        )
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, sort_keys=True))
    else:
        sub = " (substituted)" if result["substitution"] else ""
        print(
            f"{result['task_category']} -> {result['capability_tier']} -> "
            f"{result['resolved_model']}{sub} | reasoning: {result['reasoning_level']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
