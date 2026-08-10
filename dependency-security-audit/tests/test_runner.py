"""Offline integration contracts for mode-aware dependency-audit orchestration."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.models import (  # noqa: E402
    Advisory, AffectedPackage, AuditMode, Decision, DependencyScope, GateStatus,
    InventoryResult, PackageRef, Reachability, SourceState, SourceStatus,
)
from dependency_audit.policy import NO_FIX  # noqa: E402
from dependency_audit.reachability import ReachabilityAssessment, ReachabilityResult  # noqa: E402
from dependency_audit.reporting import ReportPaths  # noqa: E402
from dependency_audit.runner import (  # noqa: E402
    AuditConfig, AuditServices, NativeAuditResult, RemediationEvidence, RiskAcceptance,
    remediation_preconditions, run_audit,
)
from dependency_audit.sources import SourceResult  # noqa: E402


NOW = "2026-08-08T12:00:00Z"


def status(source: str, state: SourceState = SourceState.OK, *, attempted_at: str = NOW) -> SourceStatus:
    return SourceStatus(source, state, attempted_at=attempted_at, diagnostic="fake diagnostic" if state is not SourceState.OK else "")


def package(*, scope: DependencyScope = DependencyScope.RUNTIME) -> PackageRef:
    return PackageRef("PyPI", "demo", "1.0.0", "pkg:pypi/demo@1.0.0", True, scope)


def inventory(*, complete: bool = True, fingerprint: str = "current") -> InventoryResult:
    return InventoryResult(packages=[package()], fingerprint=fingerprint, complete=complete,
                           statuses=[status("inventory")],
                           incomplete_reasons=[] if complete else ["incomplete fixture"])


def advisory(*, severity: str = "high", fixed: tuple[str, ...] = ("1.0.1",),
             withdrawn: bool = False, identifier: str = "OSV-1", source: str = "osv") -> Advisory:
    affected = AffectedPackage("PyPI", "demo", fixed_versions=fixed)
    return Advisory(identifier, aliases=("CVE-2025-0001", "GHSA-abcd-1234-efgh"), severity=severity,
                    withdrawn=withdrawn, fixed_versions=fixed, source=source,
                    affected_packages=(affected,))


class FakeOsv:
    """Return configured primary evidence and record whether a full query occurred."""

    def __init__(self, value: list[Advisory] | None = None, state: SourceState = SourceState.OK,
                 attempted_at: str = NOW) -> None:
        self.value = list(value or ())
        self.state = state
        self.attempted_at = attempted_at
        self.calls = 0

    def query(self, packages: tuple[PackageRef, ...]) -> SourceResult[list[Advisory]]:
        self.calls += 1
        return SourceResult(list(self.value), status("osv", self.state, attempted_at=self.attempted_at))


class FakeKev:
    """Return configured catalog evidence and record freshness-triggered calls."""

    def __init__(self, ids: frozenset[str] = frozenset(), state: SourceState = SourceState.OK,
                 attempted_at: str = NOW) -> None:
        self.ids = ids
        self.state = state
        self.attempted_at = attempted_at
        self.calls = 0

    def fetch_ids(self) -> SourceResult[frozenset[str]]:
        self.calls += 1
        return SourceResult(self.ids, status("kev", self.state, attempted_at=self.attempted_at))


class FakeEnrichment:
    """Exercise secondary failure retention without changing authoritative evidence."""

    def __init__(self, state: SourceState, source: str = "github") -> None:
        self.state = state
        self.source = source

    def enrich(self, advisory: Advisory, *, package: PackageRef | None = None) -> SourceResult[Advisory]:
        return SourceResult(advisory, status(self.source, self.state))


class FakeReports:
    """Capture every completed result instead of touching durable output."""

    def __init__(self) -> None:
        self.results = []

    def __call__(self, result, output_dir, *, credential_values=()):
        self.results.append(result.to_dict())
        root = Path(output_dir)
        return ReportPaths(root / "latest.json", root / "latest.md")


class RunnerTests(unittest.TestCase):
    """Verify orchestration modes, evidence requirements, and aggregate precedence."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def services(self, *, inv: InventoryResult | None = None, osv: FakeOsv | None = None,
                 kev: FakeKev | None = None, github=None, nvd=None, native=None, reachability=None,
                 reports=None, is_safe_version=None, version_key=None, is_major_upgrade=None,
                 now=None) -> AuditServices:
        return AuditServices(
            inventory=lambda root, sbom: inv or inventory(),
            osv=osv or FakeOsv(), kev=kev or FakeKev(), github=github, nvd=nvd,
            native_audits=native or (lambda value: NativeAuditResult()),
            reachability=reachability or (lambda path: ReachabilityResult()),
            reports=reports or FakeReports(), now=now or (lambda: NOW),
            is_safe_version=is_safe_version, version_key=version_key,
            is_major_upgrade=is_major_upgrade,
        )

    def test_unchanged_change_mode_skips_full_remote_audit(self) -> None:
        osv, kev, reports = FakeOsv([advisory()]), FakeKev(), FakeReports()
        result = run_audit(AuditConfig(self.root, AuditMode.CHANGE, baseline_fingerprint="current"),
                           self.services(osv=osv, kev=kev, reports=reports))

        self.assertEqual((osv.calls, kev.calls), (0, 0))
        self.assertEqual(result.gate_status, GateStatus.PASS)
        self.assertEqual(result.findings, [])
        self.assertEqual(len(reports.results), 1)

    def test_changed_fingerprint_triggers_change_mode_sources(self) -> None:
        osv, kev = FakeOsv(), FakeKev()
        result = run_audit(AuditConfig(self.root, AuditMode.CHANGE, baseline_fingerprint="previous"),
                           self.services(osv=osv, kev=kev))

        self.assertEqual((osv.calls, kev.calls), (1, 1))
        self.assertEqual(result.gate_status, GateStatus.PASS)

    def test_incomplete_matching_inventory_never_skips_and_is_an_explicit_warning(self) -> None:
        osv, kev = FakeOsv(), FakeKev()
        result = run_audit(
            AuditConfig(self.root, AuditMode.CHANGE, baseline_fingerprint="current"),
            self.services(inv=inventory(complete=False), osv=osv, kev=kev),
        )

        self.assertEqual((osv.calls, kev.calls), (1, 1))
        self.assertEqual(result.gate_status, GateStatus.WARNINGS)
        self.assertTrue(any(item.source == "inventory-completeness"
                            and item.state is SourceState.PARTIAL
                            for item in result.inventory.statuses))

    def test_main_and_release_always_run_fresh_full_sources(self) -> None:
        for mode in (AuditMode.MAIN, AuditMode.RELEASE):
            with self.subTest(mode=mode):
                osv, kev = FakeOsv(), FakeKev()
                result = run_audit(AuditConfig(self.root, mode, baseline_fingerprint="current"),
                                   self.services(osv=osv, kev=kev))
                self.assertEqual((osv.calls, kev.calls), (1, 1))
                self.assertEqual(result.gate_status, GateStatus.PASS)

    def test_known_block_is_retained_but_required_failure_wins_aggregate(self) -> None:
        result = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(
            osv=FakeOsv([advisory()], SourceState.PARTIAL), kev=FakeKev()))

        self.assertEqual(result.decisions[0].decision, Decision.BLOCK)
        self.assertEqual(result.gate_status, GateStatus.UNAVAILABLE)
        self.assertEqual(result.exit_code, 2)

    def test_secondary_failure_retains_primary_block_without_making_main_unavailable(self) -> None:
        for source in ("github", "nvd"):
            with self.subTest(source=source):
                enrichment = FakeEnrichment(SourceState.UNAVAILABLE, source)
                kwargs = {source: enrichment}
                result = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(
                    osv=FakeOsv([advisory()]), **kwargs))

                self.assertEqual(result.decisions[0].decision, Decision.BLOCK)
                self.assertEqual(result.gate_status, GateStatus.BLOCKED)
                self.assertEqual(result.exit_code, 1)
                self.assertTrue(any(item.source == source and item.state is SourceState.UNAVAILABLE
                                    for item in result.sources))

    def test_change_source_failure_is_warning_not_clean(self) -> None:
        result = run_audit(AuditConfig(self.root, AuditMode.CHANGE), self.services(
            osv=FakeOsv(state=SourceState.UNAVAILABLE), kev=FakeKev()))

        self.assertEqual(result.gate_status, GateStatus.WARNINGS)
        self.assertEqual(result.exit_code, 0)

    def test_kev_blocks_and_withdrawn_advisory_is_excluded(self) -> None:
        kev_block = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(
            osv=FakeOsv([advisory(severity="low", fixed=())]),
            kev=FakeKev(frozenset({"CVE-2025-0001"}))))
        withdrawn = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(
            osv=FakeOsv([advisory(withdrawn=True)])))

        self.assertEqual(kev_block.decisions[0].decision, Decision.BLOCK)
        self.assertEqual(kev_block.gate_status, GateStatus.BLOCKED)
        self.assertEqual(withdrawn.decisions[0].decision, Decision.EXCLUDED)
        self.assertEqual(withdrawn.gate_status, GateStatus.PASS)

    def test_warning_and_clean_pass_remain_distinct(self) -> None:
        warning = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(
            osv=FakeOsv([advisory(severity="medium")])))
        clean = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(osv=FakeOsv()))

        self.assertEqual(warning.gate_status, GateStatus.WARNINGS)
        self.assertEqual(clean.gate_status, GateStatus.PASS)
        self.assertEqual((warning.exit_code, clean.exit_code), (0, 0))

    def test_incomplete_inventory_and_applicable_native_failure_are_required_for_delivery(self) -> None:
        incomplete = run_audit(AuditConfig(self.root, AuditMode.MAIN),
                               self.services(inv=inventory(complete=False)))
        native = lambda value: NativeAuditResult(statuses=(status("npm-audit", SourceState.UNAVAILABLE),))
        native_failure = run_audit(AuditConfig(self.root, AuditMode.RELEASE),
                                   self.services(native=native))
        kev_failure = run_audit(AuditConfig(self.root, AuditMode.MAIN),
                                self.services(kev=FakeKev(state=SourceState.UNAVAILABLE)))

        self.assertEqual(incomplete.gate_status, GateStatus.UNAVAILABLE)
        self.assertEqual(native_failure.gate_status, GateStatus.UNAVAILABLE)
        self.assertEqual(kev_failure.gate_status, GateStatus.UNAVAILABLE)

    def test_not_applicable_native_audit_never_becomes_required_when_timestamp_is_empty(self) -> None:
        native = lambda value: NativeAuditResult(
            statuses=(SourceStatus("cargo-audit", SourceState.NOT_APPLICABLE),))

        result = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(native=native))

        self.assertEqual(result.gate_status, GateStatus.PASS)
        self.assertTrue(any(item.source == "cargo-audit"
                            and item.state is SourceState.NOT_APPLICABLE for item in result.sources))

    def test_native_advisories_without_applicable_status_fail_delivery_without_being_lost(self) -> None:
        cases = (
            NativeAuditResult(advisories=(advisory(source="cargo-audit"),)),
            NativeAuditResult(advisories=(advisory(source="cargo-audit"),), statuses=(
                SourceStatus("cargo-audit", SourceState.NOT_APPLICABLE),)),
            NativeAuditResult(advisories=(advisory(source="cargo-audit"),), statuses=(
                status("npm-audit"),)),
            NativeAuditResult(statuses=(status("cargo-audit"),
                                         status("cargo-audit", SourceState.NOT_APPLICABLE))),
        )
        for native_result in cases:
            with self.subTest(native_result=native_result):
                result = run_audit(
                    AuditConfig(self.root, AuditMode.MAIN),
                    self.services(native=lambda value, item=native_result: item),
                )
                self.assertEqual(result.gate_status, GateStatus.UNAVAILABLE)
                self.assertTrue(any(item.source.endswith("-consistency")
                                    and item.state is SourceState.PARTIAL for item in result.sources))
        self.assertEqual(len(run_audit(
            AuditConfig(self.root, AuditMode.MAIN),
            self.services(native=lambda value: cases[0]),
        ).findings), 1)

    def test_native_only_exact_package_fix_is_retained_and_blocks_critical_runtime(self) -> None:
        native_advisory = advisory(
            severity="critical", fixed=("1.0.1",), source="npm-audit",
        )
        native = lambda value: NativeAuditResult(
            advisories=(native_advisory,), statuses=(status("npm-audit"),),
        )

        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN),
            self.services(osv=FakeOsv(), native=native),
        )

        self.assertEqual(result.findings[0].advisory.fixed_versions, ("1.0.1",))
        self.assertEqual(result.decisions[0].decision, Decision.BLOCK)
        self.assertEqual(result.gate_status, GateStatus.BLOCKED)

    def test_osv_exact_package_fix_wins_over_conflicting_correlated_native_fix(self) -> None:
        native = lambda value: NativeAuditResult(
            advisories=(advisory(fixed=("1.0.1",), source="npm-audit"),),
            statuses=(status("npm-audit"),),
        )
        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN),
            self.services(osv=FakeOsv([advisory(fixed=("1.0.2",))]), native=native),
        )

        self.assertEqual(result.findings[0].advisory.fixed_versions, ("1.0.2",))

    def test_secondary_enrichment_cannot_replace_authoritative_fix_or_applicability(self) -> None:
        class MaliciousSecondary:
            def enrich(self, current, *, package=None):
                changed = Advisory(
                    "EVIL-9", aliases=("OTHER-1",), severity="low",
                    withdrawn=True, fixed_versions=("9.9.9",), source="github",
                    affected_packages=(AffectedPackage("PyPI", "other", fixed_versions=("9.9.9",)),),
                )
                return SourceResult(changed, status("github"))

        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN),
            self.services(
                osv=FakeOsv([advisory(fixed=("1.0.2",))]),
                kev=FakeKev(frozenset({"CVE-2025-0001"})),
                github=MaliciousSecondary(),
            ),
        )

        self.assertEqual(result.findings[0].advisory.id, "OSV-1")
        self.assertEqual(result.findings[0].advisory.aliases,
                         ("CVE-2025-0001", "GHSA-abcd-1234-efgh", "OSV-1"))
        self.assertEqual(result.findings[0].advisory.severity, "high")
        self.assertEqual(result.findings[0].advisory.source, "osv")
        self.assertEqual(result.findings[0].advisory.fixed_versions, ("1.0.2",))
        self.assertEqual(result.findings[0].advisory.affected_packages[0].name, "demo")
        self.assertFalse(result.findings[0].advisory.withdrawn)
        self.assertTrue(result.findings[0].kev)
        self.assertEqual(result.decisions[0].decision, Decision.BLOCK)
        self.assertEqual(result.gate_status, GateStatus.BLOCKED)
        self.assertTrue(any(item.source == "github" and item.state is SourceState.PARTIAL
                            for item in result.sources))

    def test_valid_secondary_severity_is_monotonic_and_source_remains_authoritative(self) -> None:
        class SeveritySecondary:
            def __init__(self, source, severity):
                self.source = source
                self.severity = severity

            def enrich(self, current, *, package=None):
                changed = Advisory(
                    f"{self.source.upper()}-1", aliases=(current.id,), severity=self.severity,
                    source=self.source, details=f"{self.source} detail",
                )
                return SourceResult(changed, status(self.source))

        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN),
            self.services(
                osv=FakeOsv([advisory(severity="high")]),
                github=SeveritySecondary("github", "low"),
                nvd=SeveritySecondary("nvd", "critical"),
            ),
        )

        self.assertEqual(result.findings[0].advisory.severity, "critical")
        self.assertEqual(result.findings[0].advisory.id, "OSV-1")
        self.assertEqual(result.findings[0].advisory.source, "osv")

    def test_reachability_evidence_and_native_advisories_flow_into_policy(self) -> None:
        key = "pkg:pypi/demo@1.0.0|NATIVE-1"
        reachability = lambda path: ReachabilityResult(
            assessments={key: ReachabilityAssessment(Reachability.UNREACHABLE,
                                                      evidence=("report://call-graph",))})
        native_advisory = Advisory(
            "NATIVE-1", severity="high", source="npm-audit",
            affected_packages=(AffectedPackage("PyPI", "demo", fixed_versions=("1.0.1",)),),
        )
        native = lambda value: NativeAuditResult(advisories=(native_advisory,),
                                                  statuses=(status("npm-audit"),))
        result = run_audit(AuditConfig(self.root, AuditMode.MAIN, reachability_path=self.root / "reach.json"),
                           self.services(osv=FakeOsv(), native=native, reachability=reachability))

        self.assertEqual(result.findings[0].reachability, Reachability.UNREACHABLE)
        self.assertEqual(result.findings[0].reachability_evidence, ("report://call-graph",))
        self.assertEqual(result.decisions[0].decision, Decision.WARN)

    def test_reachability_loader_failure_preserves_finding_as_unknown(self) -> None:
        def failing_reachability(path):
            raise ValueError("malformed reachability evidence")

        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, reachability_path=self.root / "reach.json"),
            self.services(osv=FakeOsv([advisory()]), reachability=failing_reachability),
        )

        self.assertEqual(result.findings[0].reachability, Reachability.UNKNOWN)
        self.assertEqual(result.decisions[0].decision, Decision.BLOCK)
        self.assertTrue(any(item.source == "reachability" and item.state is SourceState.UNAVAILABLE
                            for item in result.sources))

    def test_stale_required_source_is_unavailable_but_stale_secondary_does_not_erase_block(self) -> None:
        stale = "2020-01-01T00:00:00Z"
        required = run_audit(AuditConfig(self.root, AuditMode.MAIN, source_max_age_seconds=60),
                             self.services(osv=FakeOsv(attempted_at=stale)))
        secondary = FakeEnrichment(SourceState.OK)
        original = secondary.enrich
        secondary.enrich = lambda advisory, package=None: SourceResult(advisory, status("github", attempted_at=stale))
        retained = run_audit(AuditConfig(self.root, AuditMode.MAIN, source_max_age_seconds=60),
                             self.services(osv=FakeOsv([advisory()]), github=secondary))

        self.assertEqual(required.gate_status, GateStatus.UNAVAILABLE)
        self.assertEqual(retained.gate_status, GateStatus.BLOCKED)
        self.assertTrue(any(item.source == "github" and item.state is SourceState.PARTIAL
                            for item in retained.sources))

    def test_release_no_fix_requires_mitigation_and_explicit_acceptance(self) -> None:
        finding = advisory(fixed=())
        unavailable = run_audit(AuditConfig(self.root, AuditMode.RELEASE),
                                self.services(osv=FakeOsv([finding])))
        accepted = run_audit(AuditConfig(
            self.root, AuditMode.RELEASE,
            release_acceptances={"OSV-1": RiskAcceptance("owner/date mitigation", "approved by release owner")},
        ), self.services(osv=FakeOsv([finding])))

        self.assertIn(NO_FIX, unavailable.decisions[0].reason_codes)
        self.assertEqual(unavailable.gate_status, GateStatus.UNAVAILABLE)
        self.assertEqual(accepted.gate_status, GateStatus.WARNINGS)

    def test_remediation_preconditions_require_guidance_approval_tests_and_reaudit(self) -> None:
        incomplete = RemediationEvidence("2.0.0", major_upgrade=True)
        complete = RemediationEvidence("2.0.0", context7_evidence="official current docs",
                                       major_upgrade=True, explicit_approval="approved",
                                       project_tests_passed=True, post_change_audit_passed=True)

        gaps = remediation_preconditions(incomplete)
        self.assertEqual(len(gaps), 4)
        self.assertEqual(remediation_preconditions(complete), ())

    def test_remediation_uses_safe_callbacks_validates_target_and_infers_safeguards(self) -> None:
        ranged = advisory()
        ranged = Advisory(
            ranged.id, aliases=ranged.aliases, severity=ranged.severity,
            fixed_versions=ranged.fixed_versions, affected_ranges=("introduced:0",), source="osv",
        )
        key = "pkg:pypi/demo@1.0.0|OSV-1"
        unverified = RemediationEvidence(
            "2.0.0", context7_evidence="current official docs", major_upgrade=False,
            resolution_changed=False,
        )
        result = run_audit(AuditConfig(
            self.root, AuditMode.MAIN, remediations={key: unverified},
        ), self.services(
            osv=FakeOsv([ranged]), is_safe_version=lambda finding, version: True,
            version_key=lambda version: tuple(int(part) for part in version.split(".")),
        ))

        mitigation = result.decisions[0].mitigation
        self.assertIn("target must equal authoritative safe version 1.0.1", mitigation)
        self.assertIn("explicit approval", mitigation)
        self.assertIn("project tests", mitigation)
        self.assertIn("post-change", mitigation)

        unresolved = run_audit(
            AuditConfig(self.root, AuditMode.MAIN), self.services(osv=FakeOsv([ranged])))
        self.assertIn("unresolved advisories: OSV-1", unresolved.decisions[0].mitigation)

    def test_inferred_resolution_change_cannot_be_disabled_by_evidence_boolean(self) -> None:
        key = "pkg:pypi/demo@1.0.0|OSV-1"
        evidence = RemediationEvidence(
            "1.0.1", context7_evidence="current official docs", resolution_changed=False,
        )
        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, remediations={key: evidence}),
            self.services(osv=FakeOsv([advisory()])),
        )

        self.assertIn("project tests", result.decisions[0].mitigation)
        self.assertIn("post-change", result.decisions[0].mitigation)

    def test_inferred_major_upgrade_requires_approval_even_when_caller_flag_is_false(self) -> None:
        key = "pkg:pypi/demo@1.0.0|OSV-1"
        evidence = RemediationEvidence(
            "2.0.0", context7_evidence="current official docs", major_upgrade=False,
            resolution_changed=False, project_tests_passed=True, post_change_audit_passed=True,
        )
        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, remediations={key: evidence}),
            self.services(osv=FakeOsv([advisory(fixed=("2.0.0",))]),
                          is_major_upgrade=lambda package, target: True),
        )

        self.assertIn("explicit approval", result.decisions[0].mitigation)

    def test_absent_major_semantics_require_approval_but_verified_nonmajor_does_not(self) -> None:
        key = "pkg:pypi/demo@1.0.0|OSV-1"
        evidence = RemediationEvidence(
            "2.0.0", context7_evidence="current official docs", major_upgrade=False,
            resolution_changed=False, project_tests_passed=True, post_change_audit_passed=True,
        )
        unresolved = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, remediations={key: evidence}),
            self.services(osv=FakeOsv([advisory(fixed=("2.0.0",))])),
        )
        verified = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, remediations={key: evidence}),
            self.services(osv=FakeOsv([advisory(fixed=("2.0.0",))]),
                          is_major_upgrade=lambda package, target: False),
        )

        self.assertIn("explicit approval", unresolved.decisions[0].mitigation)
        self.assertIn("remediation evidence complete", verified.decisions[0].mitigation)

    def test_safe_version_callback_failures_are_sanitized_required_evidence(self) -> None:
        ranged = Advisory(
            "OSV-1", aliases=("CVE-2025-0001",), severity="high",
            fixed_versions=("1.0.1",), affected_ranges=("introduced:0",), source="osv",
        )
        secret = "version-evaluation-secret"

        def explode(*args):
            raise RuntimeError(f"private_token={secret}")

        cases = (
            {"is_safe_version": explode, "version_key": lambda version: version},
            {"is_safe_version": lambda finding, version: True, "version_key": explode},
        )
        for callbacks in cases:
            with self.subTest(callback=next(iter(callbacks))):
                reports = FakeReports()
                result = run_audit(
                    AuditConfig(self.root, AuditMode.MAIN, credential_values=(secret,)),
                    self.services(osv=FakeOsv([ranged]), reports=reports, **callbacks),
                )
                self.assertEqual(result.gate_status, GateStatus.UNAVAILABLE)
                self.assertEqual(len(result.findings), 1)
                evaluation = next(item for item in result.sources
                                  if item.source == "remediation-version-evaluation")
                self.assertEqual(evaluation.state, SourceState.PARTIAL)
                self.assertNotIn(secret, evaluation.diagnostic)
                self.assertIn("unresolved advisories: OSV-1", result.decisions[0].mitigation)
                self.assertEqual(len(reports.results), 1)

    def test_major_version_callback_failure_never_claims_remediation_complete(self) -> None:
        key = "pkg:pypi/demo@1.0.0|OSV-1"
        secret = "major-evaluation-secret"
        evidence = RemediationEvidence(
            "2.0.0", context7_evidence="current official docs", explicit_approval="all majors approved",
            resolution_changed=False, project_tests_passed=True, post_change_audit_passed=True,
        )

        def explode(package, target):
            raise RuntimeError(f"password={secret}")

        result = run_audit(
            AuditConfig(self.root, AuditMode.MAIN, remediations={key: evidence},
                        credential_values=(secret,)),
            self.services(osv=FakeOsv([advisory(fixed=("2.0.0",))]),
                          is_major_upgrade=explode),
        )

        self.assertEqual(result.gate_status, GateStatus.UNAVAILABLE)
        self.assertIn("approval scope remains unresolved", result.decisions[0].mitigation)
        diagnostic = next(item.diagnostic for item in result.sources
                          if item.source == "remediation-version-evaluation")
        self.assertNotIn(secret, diagnostic)

    def test_invalid_configuration_and_report_failure_have_stable_precedence(self) -> None:
        invalid = run_audit(AuditConfig(self.root / "missing", AuditMode.MAIN), self.services())

        def failing_reports(*args, **kwargs):
            raise OSError("write failed")

        failed = run_audit(AuditConfig(self.root, AuditMode.MAIN), self.services(reports=failing_reports))
        self.assertEqual((invalid.gate_status, invalid.exit_code), (GateStatus.INVALID, 3))
        self.assertEqual((failed.gate_status, failed.exit_code), (GateStatus.UNAVAILABLE, 2))

    def test_freshness_configuration_rejects_bool_nonfinite_and_wrong_types_without_crashing(self) -> None:
        for value in (True, float("nan"), float("inf"), "60", 10 ** 10000):
            with self.subTest(value=type(value).__name__):
                result = run_audit(
                    AuditConfig(self.root, AuditMode.MAIN, source_max_age_seconds=value),
                    self.services(),
                )
                self.assertEqual((result.gate_status, result.exit_code), (GateStatus.INVALID, 3))

    def test_clock_exception_is_redacted_unavailable_and_reported(self) -> None:
        reports = FakeReports()
        secret = "clock-secret"

        def exploding_clock():
            raise OverflowError(f"token={secret}")

        result = run_audit(
            AuditConfig(self.root, AuditMode.CHANGE, credential_values=(secret,)),
            self.services(now=exploding_clock, reports=reports),
        )

        self.assertEqual((result.gate_status, result.exit_code), (GateStatus.UNAVAILABLE, 2))
        self.assertNotIn(secret, result.sources[0].diagnostic)
        self.assertEqual(len(reports.results), 1)

    def test_unexpected_required_service_exception_is_sanitized_unavailable_evidence(self) -> None:
        secret = "top-secret-value"

        class ExplodingOsv:
            def query(self, packages):
                raise RuntimeError(f"authorization={secret}")

        result = run_audit(AuditConfig(self.root, AuditMode.MAIN, credential_values=(secret,)),
                           self.services(osv=ExplodingOsv()))

        self.assertEqual(result.gate_status, GateStatus.UNAVAILABLE)
        diagnostic = next(item.diagnostic for item in result.sources if item.source == "osv")
        self.assertNotIn(secret, diagnostic)
        self.assertIn("[REDACTED]", diagnostic)


if __name__ == "__main__":
    unittest.main()
