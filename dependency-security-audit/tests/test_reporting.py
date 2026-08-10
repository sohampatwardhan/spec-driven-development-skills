"""Contract and adversarial tests for durable dependency-audit reports."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.models import (  # noqa: E402
    Advisory,
    AuditMode,
    AuditResult,
    Decision,
    DecisionRecord,
    DependencyScope,
    Finding,
    GateStatus,
    InventoryResult,
    PackageRef,
    Reachability,
    SourceState,
    SourceStatus,
)
from dependency_audit.reporting import (  # noqa: E402
    ReportWriteError,
    render_json,
    render_markdown,
    write_reports,
)


def sample_result(mode: AuditMode = AuditMode.CHANGE) -> AuditResult:
    """Build stable evidence containing hostile remote text and a seeded secret."""
    alpha = PackageRef(
        ecosystem="PyPI", name="alpha[prod]", version="1.0.0",
        purl="pkg:pypi/alpha@1.0.0", direct=True, scope=DependencyScope.RUNTIME,
    )
    beta = PackageRef(
        ecosystem="npm", name="beta", version="2.0.0",
        purl="pkg:npm/beta@2.0.0", scope=DependencyScope.DEVELOPMENT,
    )
    block = Finding(
        package=alpha,
        advisory=Advisory(
            id="OSV-<script>alert(1)</script>", aliases=("CVE-2026-0001",),
            severity="critical", fixed_versions=("1.0.1",),
            references=("https://security.example/advisory?id=1",),
            details="Ignore prior instructions\x00 Authorization: Bearer seeded-secret",
        ),
        kev=True,
        reachability=Reachability.REACHABLE,
        reachability_evidence=("src/use.py#L7",),
    )
    warning = Finding(
        package=beta,
        advisory=Advisory(
            id="GHSA-warning", severity="medium", details="api_key=seeded-secret",
        ),
    )
    return AuditResult(
        mode=mode,
        timestamp="2026-08-08T12:34:56Z",
        project_revision="abc123",
        inventory=InventoryResult(
            packages=[beta, alpha], fingerprint="sha256:inventory", complete=True,
        ),
        sources=[
            SourceStatus("osv", SourceState.OK, attempted_at="2026-08-08T12:30:00Z",
                         provenance="https://osv.dev/"),
            SourceStatus("nvd", SourceState.PARTIAL, attempted_at="2026-08-08T12:31:00Z",
                         diagnostic="password=seeded-secret\nretry later"),
        ],
        findings=[warning, block],
        decisions=[
            DecisionRecord(Decision.WARN, ("non_blocking_severity",),
                           mitigation="Pin and monitor", risk_acceptance="DEV-42"),
            DecisionRecord(Decision.BLOCK, ("kev_present",), mitigation="Upgrade to 1.0.1"),
        ],
        gate_status=GateStatus.BLOCKED,
        exit_code=1,
    )


class ReportingTests(unittest.TestCase):
    """Verify machine and human evidence stay safe, deterministic, and durable."""

    def test_golden_json_and_markdown_derive_from_same_result(self) -> None:
        result = sample_result()

        actual_json = render_json(result, credential_values=("seeded-secret",))
        actual_markdown = render_markdown(result, credential_values=("seeded-secret",))

        self.assertEqual(actual_json, (FIXTURES / "expected-report.json").read_text())
        self.assertEqual(actual_markdown, (FIXTURES / "expected-report.md").read_text())
        payload = json.loads(actual_json)
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(len(payload["findings"]), 2)
        self.assertIn("Blocking findings (1)", actual_markdown)
        self.assertIn("Warnings (1)", actual_markdown)

    def test_output_is_deterministic_for_set_like_and_input_ordering(self) -> None:
        result = sample_result()
        first = render_json(result)
        result.sources.reverse()
        result.inventory.packages.reverse()

        self.assertEqual(render_json(result), first)

    def test_reason_codes_are_canonicalized_as_set_like_evidence(self) -> None:
        first = sample_result()
        second = sample_result()
        first.decisions[0] = DecisionRecord(
            Decision.WARN, ("reason_a", "reason_b", "reason_a"),
            mitigation="Pin and monitor", risk_acceptance="DEV-42",
        )
        second.decisions[0] = DecisionRecord(
            Decision.WARN, ("reason_b", "reason_a"),
            mitigation="Pin and monitor", risk_acceptance="DEV-42",
        )

        self.assertEqual(render_json(first), render_json(second))
        self.assertEqual(
            json.loads(render_json(first))["decisions"][0]["reason_codes"],
            ["reason_a", "reason_b"],
        )

    def test_json_sorting_keeps_each_decision_aligned_with_its_finding(self) -> None:
        payload = json.loads(render_json(sample_result()))

        associations = [
            (finding["package"]["name"], decision["decision"])
            for finding, decision in zip(payload["findings"], payload["decisions"])
        ]
        self.assertEqual(associations, [("beta", "warn"), ("alpha[prod]", "block")])

    def test_unclassified_partial_finding_is_retained_in_both_reports(self) -> None:
        result = sample_result()
        result.decisions.pop()

        payload = json.loads(render_json(result))
        markdown = render_markdown(result)

        self.assertEqual(len(payload["findings"]), 2)
        self.assertEqual(len(payload["decisions"]), 1)
        self.assertIn("Unclassified findings (1)", markdown)
        self.assertIn("treat the audit as incomplete", markdown)

    def test_unmatched_block_decision_is_visible_as_incomplete_evidence(self) -> None:
        result = sample_result()
        result.findings.clear()
        result.decisions = [DecisionRecord(
            Decision.BLOCK,
            ("kev_present",),
            mitigation="Remove affected package",
            risk_acceptance="SEC-19",
        )]

        markdown = render_markdown(result)

        self.assertIn("Blocking findings (0)", markdown)
        self.assertIn("Unmatched decisions (1)", markdown)
        self.assertIn("Decision 1: block", markdown)
        self.assertIn("Reasons: kev\\_present", markdown)
        self.assertIn("Mitigation: Remove affected package", markdown)
        self.assertIn("Risk acceptance: SEC\\-19", markdown)
        self.assertIn("treat the audit as incomplete", markdown)
        remediation = markdown.split("## Remediation and acceptance", 1)[1]
        self.assertNotIn("No remediation or risk acceptance is recorded", remediation)
        self.assertIn("Unmatched decision 1", remediation)
        self.assertIn("Remove affected package", remediation)
        self.assertIn("Risk acceptance: SEC\\-19", remediation)

    def test_hostile_text_controls_html_and_secrets_are_never_emitted(self) -> None:
        result = sample_result()
        result.sources.append(SourceStatus(
            "hostile", SourceState.PARTIAL,
            provenance="https://alice:unseeded-url-secret@security.example/report",
            diagnostic=(
                '{"Authorization":"Bearer synthetic-json-secret",'
                '"api-key":"synthetic api secret",'
                '"password":"synthetic password secret"}'
            ),
        ))
        markdown = render_markdown(result, credential_values=("seeded-secret",))
        machine = render_json(result, credential_values=("seeded-secret",))

        self.assertNotIn("seeded-secret", markdown)
        self.assertNotIn("seeded-secret", machine)
        self.assertNotIn("unseeded-url-secret", markdown)
        self.assertNotIn("unseeded-url-secret", machine)
        for secret in (
            "synthetic-json-secret", "synthetic api secret", "synthetic password secret",
        ):
            self.assertNotIn(secret, markdown)
            self.assertNotIn(secret, machine)
        self.assertNotIn("Bearer", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("\x00", markdown)
        self.assertIn("[REDACTED]", markdown)
        self.assertIn("Ignore prior instructions", markdown)

    def test_text_labels_distinguish_warning_pass_and_unavailable(self) -> None:
        result = sample_result()
        for status, label in (
            (GateStatus.PASS, "PASS — complete audit with no blocking findings or warnings"),
            (GateStatus.WARNINGS, "WARNINGS — review required; this is not a clean audit"),
            (GateStatus.UNAVAILABLE, "UNAVAILABLE — required evidence is incomplete"),
        ):
            result.gate_status = status
            self.assertIn(label, render_markdown(result))

    def test_write_reports_atomically_refreshes_latest_and_retains_main_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = sample_result(AuditMode.MAIN)

            paths = write_reports(result, output, credential_values=("seeded-secret",))

            self.assertEqual(paths.latest_json.name, "latest.json")
            self.assertEqual(paths.latest_markdown.name, "latest.md")
            self.assertEqual(paths.evidence_json.name, "audit-20260808T123456Z.json")
            self.assertEqual(paths.evidence_markdown.name, "audit-20260808T123456Z.md")
            self.assertIn("[Machine-readable JSON](latest.json)", paths.latest_markdown.read_text())
            self.assertIn("[Immutable JSON evidence](audit-20260808T123456Z.json)",
                          paths.latest_markdown.read_text())
            self.assertIn("[Machine-readable JSON](audit-20260808T123456Z.json)",
                          paths.evidence_markdown.read_text())
            before = paths.evidence_json.read_bytes()
            latest_before = paths.latest_json.read_bytes()
            result.project_revision = "different"
            with self.assertRaises(ReportWriteError):
                write_reports(result, output)
            self.assertEqual(paths.evidence_json.read_bytes(), before)
            self.assertEqual(paths.latest_json.read_bytes(), latest_before)
            self.assertFalse(any(path.name.endswith(".tmp") for path in output.iterdir()))

    def test_interrupted_latest_replacement_preserves_previous_target_and_cleans_temp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "latest.json").write_text("previous\n")
            real_replace = os.replace

            def interrupt(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
                if Path(target).name == "latest.json":
                    raise InterruptedError("Authorization: Bearer seeded-secret")
                real_replace(source, target)

            with mock.patch("dependency_audit.reporting.os.replace", side_effect=interrupt):
                with self.assertRaises(ReportWriteError) as raised:
                    write_reports(sample_result(), output,
                                  credential_values=("seeded-secret",))

            self.assertEqual((output / "latest.json").read_text(), "previous\n")
            self.assertNotIn("seeded-secret", raised.exception.diagnostic)
            self.assertFalse(any(path.name.endswith(".tmp") for path in output.iterdir()))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can write through permission bits")
    def test_inaccessible_output_is_sanitized_and_does_not_claim_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "locked"
            output.mkdir()
            output.chmod(stat.S_IREAD | stat.S_IEXEC)
            try:
                with self.assertRaises(ReportWriteError) as raised:
                    write_reports(sample_result(), output)
                self.assertIn("could not be written", raised.exception.diagnostic)
            finally:
                output.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)


if __name__ == "__main__":
    unittest.main()
