"""Contract tests for deterministic dependency-audit policy decisions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.models import (  # noqa: E402
    Advisory,
    AuditMode,
    AuditResult,
    Decision,
    DependencyScope,
    Finding,
    GateStatus,
    PackageRef,
    Reachability,
    SourceState,
    SourceStatus,
)
from dependency_audit.policy import (  # noqa: E402
    Policy,
    classify_finding,
    gate_result,
    select_lowest_common_fixed_version,
)


def finding(
    *,
    kev: bool = False,
    scope: DependencyScope = DependencyScope.RUNTIME,
    fixes: tuple[str, ...] = ("1.2.4",),
    severity: str = "high",
    reachability: Reachability = Reachability.NOT_ASSESSED,
    withdrawn: bool = False,
    evidence: tuple[str, ...] = (),
) -> Finding:
    """Create a normalized finding with only policy-relevant fields varied."""
    return Finding(
        package=PackageRef("PyPI", "example", "1.2.3", "pkg:pypi/example@1.2.3",
                           scope=scope),
        advisory=Advisory("OSV-1", severity=severity, withdrawn=withdrawn,
                          fixed_versions=fixes),
        kev=kev,
        reachability=reachability,
        reachability_evidence=evidence,
    )


class FindingPolicyTests(unittest.TestCase):
    """Verify every default precedence rule and monotonic promotion."""

    def test_default_decision_table_and_stable_reason_codes(self) -> None:
        cases = (
            ("withdrawn_kev", finding(withdrawn=True, kev=True),
             Decision.EXCLUDED, "advisory_withdrawn"),
            ("kev_development_no_fix", finding(kev=True, scope=DependencyScope.DEVELOPMENT,
                                                fixes=()), Decision.BLOCK, "kev_present"),
            ("no_fix", finding(fixes=()), Decision.WARN, "no_authoritative_fix"),
            ("development", finding(scope=DependencyScope.DEVELOPMENT,
                                     severity="critical"), Decision.WARN,
             "development_only"),
            ("proven_unreachable", finding(reachability=Reachability.UNREACHABLE,
                                            evidence=("bundle exclusion",)), Decision.WARN,
             "proven_unreachable"),
            ("high_runtime", finding(), Decision.BLOCK, "runtime_high_or_critical"),
            ("critical_unknown_reachability", finding(severity="critical",
                                                       reachability=Reachability.UNKNOWN),
             Decision.BLOCK, "runtime_high_or_critical"),
            ("medium", finding(severity="medium"), Decision.WARN,
             "non_blocking_severity"),
            ("unknown", finding(severity="unrecognized"), Decision.WARN,
             "non_blocking_severity"),
        )

        for name, candidate, expected, reason in cases:
            with self.subTest(name=name):
                decision = classify_finding(candidate, Policy())
                self.assertEqual(decision.decision, expected)
                self.assertEqual(decision.reason_codes, (reason,))

    def test_stricter_policy_can_promote_but_not_downgrade_default_or_kev(self) -> None:
        promoted = classify_finding(finding(severity="low"), Policy(block_warnings=True))
        kev = classify_finding(finding(kev=True), Policy(block_warnings=False))

        self.assertEqual(promoted.decision, Decision.BLOCK)
        self.assertEqual(promoted.reason_codes,
                         ("non_blocking_severity", "project_policy_stricter"))
        self.assertEqual(kev.decision, Decision.BLOCK)
        self.assertEqual(kev.reason_codes, ("kev_present",))

    def test_unreachable_without_evidence_does_not_qualify_for_warning_rule(self) -> None:
        decision = classify_finding(
            finding(reachability=Reachability.UNREACHABLE, evidence=()), Policy()
        )

        self.assertEqual(decision.decision, Decision.BLOCK)
        self.assertEqual(decision.reason_codes, ("runtime_high_or_critical",))


class RemediationTests(unittest.TestCase):
    """Verify authoritative candidates satisfy every safe range without inference."""

    def test_selects_lowest_common_released_fixed_version(self) -> None:
        def version_key(version: str) -> tuple[int, ...]:
            return tuple(int(part) for part in version.split("."))

        def satisfies_affected_range(candidate: Finding, version: str) -> bool:
            minimum = candidate.advisory.affected_ranges[0].removeprefix(">=")
            return version_key(version) >= version_key(minimum)

        selected = select_lowest_common_fixed_version(
            (Finding(
                package=PackageRef("PyPI", "example", "1.2.3", "pkg:pypi/example@1.2.3"),
                advisory=Advisory("OSV-1", fixed_versions=("1.2.4",),
                                  affected_ranges=(">=1.2.4",)),
            ), Finding(
                package=PackageRef("PyPI", "example", "1.2.3", "pkg:pypi/example@1.2.3"),
                advisory=Advisory("OSV-2", fixed_versions=("1.3.0",),
                                  affected_ranges=(">=1.3.0",)),
            )),
            is_safe_version=satisfies_affected_range,
            version_key=version_key,
        )

        self.assertEqual(selected.version, "1.3.0")
        self.assertEqual(selected.unresolved, ())

    def test_preserves_unresolved_findings_when_no_common_authoritative_version(self) -> None:
        first = finding(fixes=("1.2.4",))
        second = Finding(
            package=first.package,
            advisory=Advisory("OSV-2", fixed_versions=("2.0.0",)),
        )

        selected = select_lowest_common_fixed_version(
            (first, second),
            is_safe_version=lambda _finding, _version: False,
        )

        self.assertIsNone(selected.version)
        self.assertEqual(selected.unresolved, ("OSV-1", "OSV-2"))

    def test_range_bearing_findings_require_both_safety_callbacks(self) -> None:
        range_finding = Finding(
            package=PackageRef("PyPI", "example", "1.2.3", "pkg:pypi/example@1.2.3"),
            advisory=Advisory("OSV-range", fixed_versions=("1.3.0",),
                              affected_ranges=(">=1.3.0",)),
        )

        without_callbacks = select_lowest_common_fixed_version((range_finding,))
        without_ordering = select_lowest_common_fixed_version(
            (range_finding,), is_safe_version=lambda _finding, _version: True
        )

        self.assertIsNone(without_callbacks.version)
        self.assertEqual(without_callbacks.unresolved, ("OSV-range",))
        self.assertIsNone(without_ordering.version)
        self.assertEqual(without_ordering.unresolved, ("OSV-range",))

    def test_range_selection_uses_supplied_semver_prerelease_ordering(self) -> None:
        def semver_key(version: str) -> tuple[tuple[int, ...], int, str]:
            release, separator, prerelease = version.partition("-")
            return (
                tuple(int(part) for part in release.split(".")),
                0 if separator else 1,
                prerelease,
            )

        first = Finding(
            package=PackageRef("npm", "example", "0.9.0", "pkg:npm/example@0.9.0"),
            advisory=Advisory("OSV-beta", fixed_versions=("1.0.0-beta",),
                              affected_ranges=(">=1.0.0-beta",)),
        )
        second = Finding(
            package=first.package,
            advisory=Advisory("OSV-release", fixed_versions=("1.0.0",),
                              affected_ranges=(">=1.0.0-beta",)),
        )

        selected = select_lowest_common_fixed_version(
            (first, second),
            is_safe_version=lambda _finding, _version: True,
            version_key=semver_key,
        )

        self.assertEqual(selected.version, "1.0.0-beta")


class AggregatePolicyTests(unittest.TestCase):
    """Verify aggregate precedence and release no-fix acceptance requirements."""

    def test_main_unavailable_precedes_known_block(self) -> None:
        result = AuditResult(mode=AuditMode.MAIN)
        result.findings.append(finding())
        result.decisions.append(classify_finding(result.findings[0], Policy()))
        result.inventory.complete = False

        gate = gate_result(result)

        self.assertEqual(gate.status, GateStatus.UNAVAILABLE)
        self.assertEqual(gate.exit_code, 2)

    def test_block_and_warning_and_pass_statuses_are_stable(self) -> None:
        block = AuditResult(mode=AuditMode.CHANGE)
        block.decisions.append(classify_finding(finding(), Policy()))
        warning = AuditResult(mode=AuditMode.CHANGE)
        warning.decisions.append(classify_finding(finding(severity="low"), Policy()))
        clean = AuditResult(mode=AuditMode.CHANGE)

        self.assertEqual((gate_result(block).status, gate_result(block).exit_code),
                         (GateStatus.BLOCKED, 1))
        self.assertEqual((gate_result(warning).status, gate_result(warning).exit_code),
                         (GateStatus.WARNINGS, 0))
        self.assertEqual((gate_result(clean).status, gate_result(clean).exit_code),
                         (GateStatus.PASS, 0))

    def test_release_no_fix_requires_mitigation_and_explicit_risk_acceptance(self) -> None:
        result = AuditResult(mode=AuditMode.RELEASE)
        result.inventory.complete = True
        no_fix = classify_finding(finding(fixes=()), Policy())
        result.decisions.append(no_fix)

        self.assertEqual(gate_result(result).status, GateStatus.UNAVAILABLE)

        result.decisions[0] = type(no_fix)(
            no_fix.decision, no_fix.reason_codes,
            mitigation="Network isolation and monitoring; owner: security; review: 2026-09-01",
            risk_acceptance="Release owner accepted residual risk",
        )
        self.assertEqual(gate_result(result).status, GateStatus.WARNINGS)

    def test_unavailable_required_source_blocks_main_and_release_only(self) -> None:
        main = AuditResult(mode=AuditMode.MAIN)
        main.sources.append(SourceStatus("osv", SourceState.UNAVAILABLE))
        change = AuditResult(mode=AuditMode.CHANGE)
        change.sources.append(SourceStatus("osv", SourceState.UNAVAILABLE))

        self.assertEqual(gate_result(main).status, GateStatus.UNAVAILABLE)
        self.assertEqual(gate_result(change).status, GateStatus.WARNINGS)

    def test_change_source_gap_does_not_mask_known_block(self) -> None:
        result = AuditResult(mode=AuditMode.CHANGE)
        result.decisions.append(classify_finding(finding(), Policy()))
        result.sources.append(SourceStatus("osv", SourceState.UNAVAILABLE))

        gate = gate_result(result)

        self.assertEqual((gate.status, gate.exit_code), (GateStatus.BLOCKED, 1))
        self.assertEqual(gate.warning_count, 1)
        self.assertEqual(gate.reason_codes, ("required_source_unavailable",))


if __name__ == "__main__":
    unittest.main()
