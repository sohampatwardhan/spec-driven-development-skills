"""Contract tests for dependency-audit domain serialization."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.models import (  # noqa: E402
    Advisory,
    AdvisoryEnrichment,
    AdvisorySearchResult,
    AffectedEvent,
    AffectedEventKind,
    AffectedPackage,
    AffectedRange,
    AuditMode,
    AuditResult,
    DependencyScope,
    Finding,
    PackageRef,
    SearchKind,
    SearchStatus,
)


class ModelSerializationTests(unittest.TestCase):
    """Verify public models produce deterministic JSON-compatible evidence."""

    def test_audit_result_to_dict_is_json_serializable(self) -> None:
        package = PackageRef(
            ecosystem="PyPI",
            name="example",
            version="1.2.3",
            purl="pkg:pypi/example@1.2.3",
            direct=True,
            scope=DependencyScope.RUNTIME,
        )
        advisory = Advisory(
            id="GHSA-aaaa-bbbb-cccc",
            aliases=("CVE-2026-0001",),
            severity="high",
            withdrawn=False,
            fixed_versions=("1.2.4",),
            references=("https://example.invalid/advisory",),
        )
        result = AuditResult.empty(AuditMode.CHANGE)
        result.findings.append(Finding(package=package, advisory=advisory))

        encoded = result.to_dict()

        json.dumps(encoded)
        self.assertEqual(encoded["schema_version"], "1.0")
        self.assertEqual(encoded["mode"], "change")
        self.assertEqual(encoded["findings"][0]["package"]["scope"], "runtime")

    def test_unordered_aliases_are_serialized_canonically(self) -> None:
        advisory = Advisory(
            id="OSV-1",
            aliases=("CVE-2", "GHSA-1", "CVE-1"),
        )

        self.assertEqual(
            advisory.to_dict()["aliases"],
            ["CVE-1", "CVE-2", "GHSA-1"],
        )

    def test_search_result_distinguishes_empty_completion(self) -> None:
        result = AdvisorySearchResult.completed(
            kind=SearchKind.PACKAGE,
            query={"ecosystem": "PyPI", "name": "safe", "version": "1.0.0"},
        )

        encoded = result.to_dict()

        json.dumps(encoded)
        self.assertEqual(encoded["status"], "complete")
        self.assertTrue(encoded["empty"])
        self.assertEqual(encoded["exit_code"], 0)

        unavailable = AdvisorySearchResult(
            kind=SearchKind.PACKAGE,
            query={"name": "unknown"},
            status=SearchStatus.UNAVAILABLE,
            exit_code=2,
        )
        invalid = AdvisorySearchResult(
            kind=SearchKind.PACKAGE,
            query={"name": "invalid"},
            status=SearchStatus.INVALID,
            exit_code=3,
        )
        self.assertFalse(unavailable.to_dict()["empty"])
        self.assertFalse(invalid.to_dict()["empty"])

    def test_multi_package_advisory_keeps_fixes_separate(self) -> None:
        advisory = Advisory(
            id="OSV-MULTI",
            affected_packages=(
                AffectedPackage(
                    ecosystem="PyPI", name="alpha", purl="pkg:pypi/alpha",
                    fixed_versions=("2.0.0",),
                ),
                AffectedPackage(
                    ecosystem="npm", name="beta", purl="pkg:npm/beta",
                    fixed_versions=("9.1.0",),
                ),
            ),
        )

        encoded = advisory.to_dict()

        json.dumps(encoded)
        self.assertEqual(encoded["affected_packages"][0]["name"], "beta")
        self.assertEqual(encoded["affected_packages"][0]["fixed_versions"], ["9.1.0"])
        self.assertEqual(encoded["affected_packages"][1]["fixed_versions"], ["2.0.0"])
        self.assertEqual(encoded["fixed_versions"], [])

    def test_affected_range_preserves_event_order(self) -> None:
        affected = AffectedPackage(
            ecosystem="PyPI",
            name="example",
            versions=("1.5", "1.0", "1.5"),
            ranges=(AffectedRange(
                type="ECOSYSTEM",
                events=(
                    AffectedEvent(AffectedEventKind.INTRODUCED, "0"),
                    AffectedEvent(AffectedEventKind.FIXED, "1.2"),
                    AffectedEvent(AffectedEventKind.INTRODUCED, "1.4"),
                    AffectedEvent(AffectedEventKind.LAST_AFFECTED, "1.8"),
                ),
            ),),
        )

        encoded = affected.to_dict()

        self.assertEqual(encoded["versions"], ["1.0", "1.5"])
        self.assertEqual(
            [(event["kind"], event["value"]) for event in encoded["ranges"][0]["events"]],
            [("introduced", "0"), ("fixed", "1.2"),
             ("introduced", "1.4"), ("last_affected", "1.8")],
        )

    def test_source_enrichment_is_json_compatible_and_canonical(self) -> None:
        advisory = Advisory(
            id="PYSEC-1",
            enrichments=(AdvisoryEnrichment(
                source="github",
                severity="high",
                cvss_scores=(8.1, 7.5, 8.1),
                cvss_vectors=("CVSS:3.1/A", "CVSS:3.1/Z"),
                epss_scores=(0.8, 0.2),
                vulnerable_functions=("z", "a", "z"),
                details="reviewed context",
            ),),
        )

        encoded = advisory.to_dict()

        json.dumps(encoded)
        enrichment = encoded["enrichments"][0]
        self.assertEqual(enrichment["cvss_scores"], [7.5, 8.1])
        self.assertEqual(enrichment["epss_scores"], [0.2, 0.8])
        self.assertEqual(enrichment["vulnerable_functions"], ["a", "z"])

    def test_case_sensitive_package_identities_have_stable_tie_breakers(self) -> None:
        advisory = Advisory(
            id="OSV-CASE",
            affected_packages=(
                AffectedPackage(ecosystem="Go", name="example.com/a"),
                AffectedPackage(ecosystem="Go", name="Example.com/A"),
            ),
        )

        encoded = advisory.to_dict()

        self.assertEqual(
            [item["name"] for item in encoded["affected_packages"]],
            ["Example.com/A", "example.com/a"],
        )


if __name__ == "__main__":
    unittest.main()
