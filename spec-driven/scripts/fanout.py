#!/usr/bin/env python3
"""Deterministic subagent fan-out resolver for spec-driven delegation.

Given a delegation depth (`quick`/`medium`/`thorough` — a judgment call made by reading
`contracts/spec-family.yaml`'s `delegation_depth` criteria against the task or wave at hand,
the same way `declared_risk` is a judgment call fed into `model-router.py`), resolves how many
independent reviewers to dispatch, at what capability tier AND reasoning level (two independent
axes — see model-routing.md), and how many self-repair rounds are allowed before a defect must
return to its owning approval gate instead of being auto-repaired.

This is "how many subagents", not "which model" — that's `model-router.py`. The two compose:
resolve a depth, resolve its fanout here (reviewer count + tier + reasoning), resolve each
reviewer's exact model there.

Usage:
    scripts/fanout.py --depth quick
    scripts/fanout.py --depth thorough --escalate   # protected-main/release or requested Thorough audit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "spec-family.yaml"
DEPTH_ORDER = ["quick", "medium", "thorough"]


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def resolve(contract: dict, depth: str, escalate: bool = False) -> dict:
    """Deterministically resolve a depth (+ optional escalation) to a fan-out plan.

    `reviewer_tier` and `reviewer_reasoning` are resolved together but remain two independent
    axes: escalation can raise one, the other, or both, per the contract's `fanout.escalation`.
    """
    table = contract["fanout"]
    if depth not in DEPTH_ORDER:
        raise ValueError(f"unknown depth {depth!r}; expected one of {DEPTH_ORDER}")
    entry = dict(table[depth])
    escalated = False
    reason = f"depth_default:{depth}"
    if escalate:
        if depth != "thorough":
            raise ValueError("escalation only applies at thorough depth (protected-main/release, or requested Thorough audit)")
        entry = {
            "reviewer_count": 3,
            "reviewer_tier": entry["reviewer_tier"],
            "reviewer_reasoning": entry["reviewer_reasoning"],
            "frontier_lens": True,
            "self_repair_rounds": entry["self_repair_rounds"],
        }
        escalated = True
        reason += "+escalation:protected_delivery_or_thorough_audit"
    else:
        entry.setdefault("frontier_lens", False)

    return {
        "depth": depth,
        "reviewer_count": entry["reviewer_count"],
        "reviewer_tier": entry["reviewer_tier"],
        "reviewer_reasoning": entry["reviewer_reasoning"],
        "frontier_lens": entry["frontier_lens"],
        "self_repair_rounds": entry["self_repair_rounds"],
        "escalated": escalated,
        "reason": reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--depth", required=True, choices=DEPTH_ORDER)
    parser.add_argument(
        "--escalate", action="store_true",
        help="Protected-main/release delivery gate, or a user-requested Thorough audit.",
    )
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--format", choices=["json", "text"], default="json")
    args = parser.parse_args(argv)

    contract = load_contract(args.contract)
    try:
        result = resolve(contract, args.depth, args.escalate)
    except (ValueError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(result, sort_keys=True))
    else:
        lens = " +adversarial(frontier/extra_high)" if result["frontier_lens"] else ""
        print(
            f"{result['depth']} -> {result['reviewer_count']} reviewer(s) "
            f"@{result['reviewer_tier']}/{result['reviewer_reasoning']}{lens}, "
            f"{result['self_repair_rounds']} self-repair round(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
