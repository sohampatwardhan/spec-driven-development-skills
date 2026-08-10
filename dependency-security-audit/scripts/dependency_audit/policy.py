"""Deterministic enforcement and remediation decisions for normalized findings.

This module deliberately has no inventory, network, or report-writing dependencies.  Keeping
the policy pure means every delivery entry point applies the same conservative precedence and
can retain the evidence that caused a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Sequence

from .models import (
    AuditMode,
    AuditResult,
    Decision,
    DecisionRecord,
    DependencyScope,
    Finding,
    GateStatus,
    Reachability,
    SourceState,
)


WITHDRAWN = "advisory_withdrawn"
KEV = "kev_present"
NO_FIX = "no_authoritative_fix"
DEVELOPMENT_ONLY = "development_only"
PROVEN_UNREACHABLE = "proven_unreachable"
RUNTIME_HIGH_OR_CRITICAL = "runtime_high_or_critical"
NON_BLOCKING_SEVERITY = "non_blocking_severity"
STRICTER_POLICY = "project_policy_stricter"
INCOMPLETE_INVENTORY = "inventory_incomplete"
REQUIRED_SOURCE_UNAVAILABLE = "required_source_unavailable"
RELEASE_NO_FIX_UNACCEPTED = "release_no_fix_unaccepted"

_HIGH_SEVERITIES = frozenset({"high", "critical"})
_VERSION_PARTS = re.compile(r"\d+|[A-Za-z]+")


@dataclass(frozen=True)
class Policy:
    """Describe optional monotonic promotions over the default safety policy.

    Each option may turn a default warning into a block, but none can convert a default block
    into a warning or exclusion.  This one-way shape preserves the KEV and runtime-risk floor
    while allowing a project to adopt a stricter delivery gate.
    """

    block_warnings: bool = False
    block_no_fix: bool = False
    block_development: bool = False
    block_proven_unreachable: bool = False
    block_severities: tuple[str, ...] = ()

    def promotes(self, reason_code: str, severity: str) -> bool:
        """Return whether this policy promotes the specified default warning.

        ``severity`` is normalized case-insensitively so source formatting cannot accidentally
        weaken a configured threshold.  The method only evaluates warnings because default
        blocks are already non-downgradable.
        """
        normalized_severities = {item.strip().lower() for item in self.block_severities}
        return (
            self.block_warnings
            or (reason_code == NO_FIX and self.block_no_fix)
            or (reason_code == DEVELOPMENT_ONLY and self.block_development)
            or (reason_code == PROVEN_UNREACHABLE and self.block_proven_unreachable)
            or severity.strip().lower() in normalized_severities
        )


@dataclass(frozen=True)
class FixedVersionSelection:
    """Represent a safe common upgrade or the advisories it cannot jointly resolve.

    ``version`` is the lowest authoritative released candidate satisfying every applicable
    finding's safe-range semantics.  ``unresolved`` remains explicit when no candidate qualifies,
    preventing a newer-looking version from being misrepresented as safe.
    """

    version: str | None
    unresolved: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateResult:
    """Summarize a policy gate with stable status, exit code, and evidence counts.

    Counts exclude withdrawn advisories because their provenance is retained separately but they
    must not affect enforcement.  ``reason_codes`` explains aggregate unavailability without
    hiding any individual block or warning decision.
    """

    status: GateStatus
    exit_code: int
    blocked_count: int = 0
    warning_count: int = 0
    excluded_count: int = 0
    reason_codes: tuple[str, ...] = ()


def classify_finding(finding: Finding, policy: Policy | None = None) -> DecisionRecord:
    """Classify one normalized finding using the non-downgradable policy order.

    Withdrawals precede KEV because a withdrawn record has no current advisory effect; a present
    KEV then blocks before fix, scope, or reachability can dilute it.  The remaining rules order
    no-fix, development-only, proven-unreachable, and severity decisions so a warning never
    becomes a block accidentally.  A project policy may subsequently promote only a warning.

    Args:
        finding: Present package/advisory evidence, including KEV and reachability state.
        policy: Optional stricter project policy; omission applies the approved default.

    Returns:
        A stable decision record suitable for JSON evidence and aggregate gating.
    """
    effective_policy = policy or Policy()
    advisory = finding.advisory
    severity = advisory.severity.strip().lower()

    if advisory.withdrawn:
        return DecisionRecord(Decision.EXCLUDED, (WITHDRAWN,))
    if finding.kev:
        return DecisionRecord(Decision.BLOCK, (KEV,))
    if not advisory.fixed_versions:
        return _warning_or_stricter(NO_FIX, severity, effective_policy)
    if finding.package.scope is DependencyScope.DEVELOPMENT:
        return _warning_or_stricter(DEVELOPMENT_ONLY, severity, effective_policy)
    if (
        finding.reachability is Reachability.UNREACHABLE
        and finding.reachability_evidence
    ):
        return _warning_or_stricter(PROVEN_UNREACHABLE, severity, effective_policy)
    if severity in _HIGH_SEVERITIES:
        return DecisionRecord(Decision.BLOCK, (RUNTIME_HIGH_OR_CRITICAL,))
    return _warning_or_stricter(NON_BLOCKING_SEVERITY, severity, effective_policy)


def select_lowest_common_fixed_version(
    findings: Sequence[Finding],
    *,
    is_safe_version: Callable[[Finding, str], bool] | None = None,
    version_key: Callable[[str], object] | None = None,
) -> FixedVersionSelection:
    """Choose the lowest authoritative released fix shared by all findings.

    A model's ``fixed_versions`` are the only acceptable source of released candidates: this
    function does not invent a later package version.  Callers that parse ecosystem affected
    ranges must supply ``is_safe_version`` and the corresponding ``version_key``; policy remains
    source-agnostic because it cannot safely interpret every package ecosystem's version syntax.
    Range-bearing findings without that predicate stay unresolved; without ranges, the lowest
    authoritative fixed version for each finding is used as its conservative minimum safe release.

    Args:
        findings: Applicable findings for one resolved package, in any deterministic order.
        is_safe_version: Optional ecosystem-aware predicate that confirms a released candidate
            resolves a finding's authoritative affected range.
        version_key: Optional ordering compatible with ``is_safe_version``.  It is also used to
            choose the lowest released candidate deterministically.

    Returns:
        The lowest shared fixed version, or explicit unresolved advisory identifiers.
    """
    applicable = tuple(
        item for item in findings if not item.advisory.withdrawn
    )
    if not applicable:
        return FixedVersionSelection(version=None)

    has_affected_ranges = any(item.advisory.affected_ranges for item in applicable)
    if has_affected_ranges and (is_safe_version is None or version_key is None):
        # A range string without both its parser and ordering semantics cannot establish a safe
        # remediation.  Generic ordering is not a valid substitute for an ecosystem comparator.
        return FixedVersionSelection(
            version=None,
            unresolved=tuple(sorted({item.advisory.id for item in applicable})),
        )

    candidates = {
        version for item in applicable for version in item.advisory.fixed_versions
    }
    order = version_key or _version_key
    safe = is_safe_version or _minimum_fixed_version_predicate(order)
    compatible = sorted(
        (version for version in candidates if all(safe(item, version) for item in applicable)),
        key=order,
    )

    if not compatible:
        return FixedVersionSelection(
            version=None,
            unresolved=tuple(sorted({item.advisory.id for item in applicable})),
        )
    return FixedVersionSelection(version=compatible[0])


def gate_result(result: AuditResult) -> GateResult:
    """Aggregate a completed audit without allowing known findings to erase evidence gaps.

    Invalid results retain exit ``3``.  Main/release inventory and required-source failures, and
    a release no-fix warning without both mitigation and acceptance, have precedence as
    unavailable exit ``2``.  Only then do blocks use exit ``1``; warnings and a clean completion
    both use exit ``0`` with distinct statuses.

    Args:
        result: Normalized audit evidence and per-finding policy decisions.

    Returns:
        Stable aggregate status, exit code, counts, and aggregate reason codes.
    """
    blocked = sum(record.decision is Decision.BLOCK for record in result.decisions)
    warnings = sum(record.decision is Decision.WARN for record in result.decisions)
    excluded = sum(record.decision is Decision.EXCLUDED for record in result.decisions)

    if result.gate_status is GateStatus.INVALID:
        return GateResult(GateStatus.INVALID, 3, blocked, warnings, excluded)

    unavailable_reasons = _unavailability_reasons(result)
    if unavailable_reasons:
        return GateResult(
            GateStatus.UNAVAILABLE, 2, blocked, warnings, excluded, unavailable_reasons
        )
    source_gap = result.mode is AuditMode.CHANGE and _has_source_gap(result)
    if blocked:
        return GateResult(
            GateStatus.BLOCKED,
            1,
            blocked,
            warnings + int(source_gap),
            excluded,
            (REQUIRED_SOURCE_UNAVAILABLE,) if source_gap else (),
        )
    if source_gap:
        return GateResult(
            GateStatus.WARNINGS,
            0,
            blocked,
            warnings + 1,
            excluded,
            (REQUIRED_SOURCE_UNAVAILABLE,),
        )
    if warnings:
        return GateResult(GateStatus.WARNINGS, 0, blocked, warnings, excluded)
    return GateResult(GateStatus.PASS, 0, blocked, warnings, excluded)


def _warning_or_stricter(reason_code: str, severity: str, policy: Policy) -> DecisionRecord:
    """Promote a default warning only when an effective project policy requires it."""
    if policy.promotes(reason_code, severity):
        return DecisionRecord(Decision.BLOCK, (reason_code, STRICTER_POLICY))
    return DecisionRecord(Decision.WARN, (reason_code,))


def _unavailability_reasons(result: AuditResult) -> tuple[str, ...]:
    """Return aggregate evidence gaps that outrank finding enforcement."""
    reasons: list[str] = []
    if result.mode in {AuditMode.MAIN, AuditMode.RELEASE}:
        if not result.inventory.complete:
            reasons.append(INCOMPLETE_INVENTORY)
        if any(
            status.state in {SourceState.PARTIAL, SourceState.UNAVAILABLE}
            for status in (*result.inventory.statuses, *result.sources)
        ):
            reasons.append(REQUIRED_SOURCE_UNAVAILABLE)
    if result.mode is AuditMode.RELEASE and any(
        record.decision is Decision.WARN and NO_FIX in record.reason_codes
        and (not record.mitigation.strip() or not record.risk_acceptance.strip())
        for record in result.decisions
    ):
        reasons.append(RELEASE_NO_FIX_UNACCEPTED)

    return tuple(reasons)


def _has_source_gap(result: AuditResult) -> bool:
    """Return whether a source outage must prevent a change-mode clean result."""
    return any(
        status.state in {SourceState.PARTIAL, SourceState.UNAVAILABLE}
        for status in (*result.inventory.statuses, *result.sources)
    )


def _minimum_fixed_version_predicate(
    version_key: Callable[[str], object],
) -> Callable[[Finding, str], bool]:
    """Build the fallback safety rule when no ecosystem range parser is available.

    Each advisory's earliest authoritative fixed release is its minimum safe candidate.  A caller
    with richer affected-range evidence must replace this fallback rather than relying on generic
    string handling that could misclassify a non-Python ecosystem.
    """
    def is_safe(finding: Finding, candidate: str) -> bool:
        fixed_versions = finding.advisory.fixed_versions
        return bool(fixed_versions) and version_key(candidate) >= min(
            version_key(version) for version in fixed_versions
        )

    return is_safe


def _version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Provide a dependency-free natural order for authoritative version strings."""
    parts = _VERSION_PARTS.findall(version)
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts)
