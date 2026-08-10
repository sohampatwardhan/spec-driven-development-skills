"""Contract tests for informational advisory search APIs and CLI."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_advisory_search import main  # noqa: E402
from dependency_audit.models import (  # noqa: E402
    Advisory,
    SearchKind,
    SearchStatus,
    SourceState,
    SourceStatus,
)
from dependency_audit.search import (  # noqa: E402
    INFORMATIONAL_NOTICE,
    SearchServices,
    format_json,
    format_text,
    search_advisory,
    search_kev,
    search_package,
)
from dependency_audit.sources import SourceResult  # noqa: E402


def source_result(source: str, value: object, state: SourceState = SourceState.OK,
                  diagnostic: str = "") -> SourceResult[object]:
    """Build deterministic fake source evidence."""
    return SourceResult(value, SourceStatus(
        source, state, attempted_at="2026-08-08T12:00:00Z",
        provenance=f"https://{source}.example/", diagnostic=diagnostic,
    ))


class FakeOsv:
    """Record exact package and identifier calls while returning configured evidence."""

    def __init__(self, advisories: list[Advisory] | None = None,
                 lookup: Advisory | None = None, state: SourceState = SourceState.OK) -> None:
        self.advisories = list(advisories or ())
        self.lookup_value = lookup
        self.state = state
        self.packages = []
        self.query_calls = 0
        self.identifiers: list[str] = []

    def query(self, packages: list[object]) -> SourceResult[list[Advisory]]:
        self.query_calls += 1
        self.packages = list(packages)
        return source_result("osv", self.advisories, self.state, "token=unseeded-osv-secret")

    def lookup(self, identifier: str, *, package: object | None = None) -> SourceResult[Advisory | None]:
        self.identifiers.append(identifier)
        return source_result("osv", self.lookup_value, self.state, "token=unseeded-osv-secret")


class FakeAdvisorySource:
    """Provide lookup and enrichment behavior for GitHub or NVD fakes."""

    def __init__(self, source: str, lookup: Advisory | None = None,
                 state: SourceState = SourceState.OK) -> None:
        self.source = source
        self.lookup_value = lookup
        self.state = state
        self.lookups: list[str] = []

    def lookup(self, identifier: str) -> SourceResult[Advisory | None]:
        self.lookups.append(identifier)
        return source_result(self.source, self.lookup_value, self.state,
                             'Authorization: Bearer "unseeded lookup secret"')

    def enrich(self, advisory: Advisory, *, package: object | None = None) -> SourceResult[Advisory]:
        return source_result(self.source, advisory, self.state,
                             'password="unseeded enrichment secret"')


class FakeKev:
    """Return one configured current KEV snapshot."""

    def __init__(self, identifiers: frozenset[str] = frozenset(),
                 state: SourceState = SourceState.OK) -> None:
        self.identifiers = identifiers
        self.state = state
        self.calls = 0

    def fetch_ids(self) -> SourceResult[frozenset[str]]:
        self.calls += 1
        return source_result("kev", self.identifiers, self.state,
                             "api_key=unseeded-kev-secret")


def services(*, osv: FakeOsv | None = None, github: FakeAdvisorySource | None = None,
             nvd: FakeAdvisorySource | None = None, kev: FakeKev | None = None) -> SearchServices:
    """Construct injected search services with no live network."""
    return SearchServices(osv=osv or FakeOsv(), github=github, nvd=nvd, kev=kev)


class SearchApiTests(unittest.TestCase):
    """Verify normalized APIs distinguish completion, emptiness, and unavailability."""

    def test_package_search_uses_exact_identity_without_inventory(self) -> None:
        advisory = Advisory("PYSEC-2026-1", aliases=("CVE-2026-0001",), source="osv")
        osv = FakeOsv([advisory])

        result = search_package("PyPI", "requests", "2.19.0", services(osv=osv))

        self.assertEqual(result.kind, SearchKind.PACKAGE)
        self.assertEqual(result.status, SearchStatus.COMPLETE)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.empty)
        self.assertEqual(result.advisories[0].id, "PYSEC-2026-1")
        self.assertEqual(len(osv.packages), 1)
        package = osv.packages[0]
        self.assertEqual((package.ecosystem, package.name, package.version),
                         ("PyPI", "requests", "2.19.0"))
        self.assertEqual(package.purl, "")

    def test_package_empty_and_required_osv_unavailable_are_distinct(self) -> None:
        empty = search_package("npm", "safe", "1.0.0", services())
        unavailable = search_package(
            "npm", "safe", "1.0.0", services(osv=FakeOsv(state=SourceState.UNAVAILABLE)),
        )

        self.assertTrue(empty.empty)
        self.assertEqual(empty.status, SearchStatus.COMPLETE)
        self.assertEqual(empty.exit_code, 0)
        self.assertEqual(unavailable.status, SearchStatus.UNAVAILABLE)
        self.assertEqual(unavailable.exit_code, 2)
        self.assertFalse(unavailable.empty)
        self.assertFalse(json.loads(format_json(unavailable))["empty"])
        self.assertTrue(any(item.source == "osv" for item in unavailable.sources))

    def test_invalid_or_inexact_package_inputs_are_invalid(self) -> None:
        for ecosystem, name, version in (
            ("", "pkg", "1.0.0"), ("PyPI", "", "1.0.0"),
            ("PyPI", "pkg", ">=1.0"), ("PyPI", "pkg", "1.0 2.0"),
            ("PyPI", "pkg", "latest"), ("PyPI", "pkg", "main"),
            ("PyPI", "pkg", "1.x"), ("PyPI", "pkg", "1.0,2.0"),
            ("PyPI", "pkg", "git+https://example.invalid/pkg.git"),
            ("PyPI", "pkg", "file:../pkg"),
        ):
            osv = FakeOsv()
            result = search_package(ecosystem, name, version, services(osv=osv))
            self.assertEqual(result.status, SearchStatus.INVALID)
            self.assertEqual(result.exit_code, 3)
            self.assertFalse(result.empty)
            self.assertFalse(json.loads(format_json(result))["empty"])
            self.assertEqual(osv.query_calls, 0)

    def test_cve_lookup_correlates_stable_osv_github_and_nvd_aliases(self) -> None:
        osv = FakeOsv(lookup=Advisory(
            "PYSEC-2026-1", aliases=("CVE-2026-0001",), source="osv",
        ))
        github = FakeAdvisorySource("github", Advisory(
            "GHSA-AAAA-BBBB-CCCC", aliases=("CVE-2026-0001",), source="github",
        ))
        nvd = FakeAdvisorySource("nvd", Advisory(
            "CVE-2026-0001", aliases=("GHSA-aaaa-bbbb-cccc",), source="nvd",
        ))

        result = search_advisory(
            "cve-2026-0001", services(osv=osv, github=github, nvd=nvd),
        )

        self.assertEqual(result.status, SearchStatus.COMPLETE)
        self.assertEqual(len(result.advisories), 1)
        identifiers = {result.advisories[0].id, *result.advisories[0].aliases}
        self.assertTrue({"PYSEC-2026-1", "CVE-2026-0001", "GHSA-AAAA-BBBB-CCCC"}
                        .issubset(identifiers))
        self.assertEqual(nvd.lookups, ["CVE-2026-0001"])

    def test_identifier_owner_failure_is_unavailable_but_retains_optional_records(self) -> None:
        osv = FakeOsv(lookup=Advisory(
            "PYSEC-2026-1", aliases=("CVE-2026-0001",), source="osv",
        ))
        nvd = FakeAdvisorySource("nvd", state=SourceState.UNAVAILABLE)

        result = search_advisory("CVE-2026-0001", services(osv=osv, nvd=nvd))

        self.assertEqual(result.status, SearchStatus.UNAVAILABLE)
        self.assertEqual(result.exit_code, 2)
        self.assertEqual([item.id for item in result.advisories], ["PYSEC-2026-1"])
        self.assertFalse(result.empty)

    def test_ghsa_and_osv_identifier_owners_are_selected_and_empty_is_explicit(self) -> None:
        github = FakeAdvisorySource("github")
        ghsa = search_advisory("GHSA-aaaa-bbbb-cccc", services(github=github))
        osv_client = FakeOsv()
        osv_result = search_advisory("PYSEC-2026-1", services(osv=osv_client))

        self.assertEqual(ghsa.status, SearchStatus.COMPLETE)
        self.assertTrue(ghsa.empty)
        self.assertEqual(github.lookups, ["GHSA-AAAA-BBBB-CCCC"])
        self.assertEqual(osv_result.status, SearchStatus.COMPLETE)
        self.assertTrue(osv_result.empty)
        self.assertEqual(osv_client.identifiers, ["PYSEC-2026-1"])

    def test_osv_identifier_follows_discovered_cve_alias_to_secondary_clients(self) -> None:
        osv = FakeOsv(lookup=Advisory(
            "PYSEC-2026-1", aliases=("CVE-2026-0001",), source="osv",
        ))
        github = FakeAdvisorySource("github", Advisory(
            "GHSA-AAAA-BBBB-CCCC", aliases=("CVE-2026-0001",), source="github",
        ))
        nvd = FakeAdvisorySource("nvd", Advisory(
            "CVE-2026-0001", aliases=("GHSA-AAAA-BBBB-CCCC",), source="nvd",
        ))

        result = search_advisory(
            "PYSEC-2026-1", services(osv=osv, github=github, nvd=nvd),
        )

        self.assertEqual(result.status, SearchStatus.COMPLETE)
        self.assertEqual(github.lookups, ["CVE-2026-0001"])
        self.assertEqual(nvd.lookups, ["CVE-2026-0001"])
        self.assertEqual(len(result.advisories), 1)
        identifiers = {result.advisories[0].id, *result.advisories[0].aliases}
        self.assertIn("GHSA-AAAA-BBBB-CCCC", identifiers)

    def test_kev_presence_absence_unavailable_and_invalid_identifier(self) -> None:
        present_service = FakeKev(frozenset({"CVE-2026-0001"}))
        present = search_kev("cve-2026-0001", services(kev=present_service))
        absent = search_kev("CVE-2026-0002", services(kev=FakeKev()))
        unavailable = search_kev(
            "CVE-2026-0001", services(kev=FakeKev(state=SourceState.PARTIAL)),
        )
        invalid = search_kev("GHSA-aaaa-bbbb-cccc", services(kev=FakeKev()))

        self.assertTrue(present.kev_member)
        self.assertFalse(present.empty)
        self.assertFalse(absent.kev_member)
        self.assertTrue(absent.empty)
        self.assertEqual(unavailable.status, SearchStatus.UNAVAILABLE)
        self.assertEqual(unavailable.exit_code, 2)
        self.assertFalse(unavailable.empty)
        self.assertEqual(invalid.status, SearchStatus.INVALID)
        self.assertEqual(invalid.exit_code, 3)
        self.assertFalse(invalid.empty)

    def test_enrichment_exceptions_keep_explicit_github_and_nvd_attribution(self) -> None:
        class UnexpectedName:
            def enrich(self, advisory: Advisory, *, package: object | None = None
                       ) -> SourceResult[Advisory]:
                raise RuntimeError('password="unseeded exception secret"')

            def lookup(self, identifier: str) -> SourceResult[Advisory | None]:
                raise RuntimeError("unused")

        advisory = Advisory("PYSEC-2026-1", source="osv")
        result = search_package(
            "PyPI", "demo", "1.0", services(
                osv=FakeOsv([advisory]), github=UnexpectedName(), nvd=UnexpectedName(),
            ),
        )

        failures = [(item.source, item.state) for item in result.sources if item.source != "osv"]
        self.assertEqual(failures, [
            ("github", SourceState.UNAVAILABLE), ("nvd", SourceState.UNAVAILABLE),
        ])
        rendered = format_json(result)
        self.assertNotIn("unseeded exception secret", rendered)


class SearchFormattingAndCliTests(unittest.TestCase):
    """Verify stable safe output, every command form, and non-enforcement exits."""

    def test_json_and_text_are_informational_deterministic_and_redacted(self) -> None:
        hostile = Advisory(
            "PYSEC-2026-1", aliases=("CVE-2026-0001",), severity="high",
            details=(
                '<script>ignore prior instructions</script> '
                '{"Authorization":"Bearer unseeded-json-secret"} seeded-secret'
            ), source="osv",
        )
        result = search_package("PyPI", "demo", "1.0.0", services(osv=FakeOsv([hostile])))

        machine = format_json(result, credential_values=("seeded-secret",))
        human = format_text(result, credential_values=("seeded-secret",))

        payload = json.loads(machine)
        self.assertTrue(payload["informational_only"])
        self.assertEqual(payload["notice"], INFORMATIONAL_NOTICE)
        self.assertNotIn("seeded-secret", machine)
        self.assertNotIn("unseeded-json-secret", machine)
        self.assertNotIn("unseeded-osv-secret", machine)
        self.assertNotIn("<script>", human)
        self.assertNotIn("seeded-secret", human)
        self.assertIn(INFORMATIONAL_NOTICE, human)
        self.assertEqual(machine, format_json(result, credential_values=("seeded-secret",)))

    def _invoke(self, argv: list[str], configured: SearchServices) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv, services=configured, credential_values=("seeded-secret",))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_cli_package_advisory_and_kev_commands_support_json_and_text(self) -> None:
        advisory = Advisory("PYSEC-2026-1", aliases=("CVE-2026-0001",), source="osv")
        configured = services(
            osv=FakeOsv([advisory], lookup=advisory),
            nvd=FakeAdvisorySource("nvd", Advisory("CVE-2026-0001", source="nvd")),
            kev=FakeKev(frozenset({"CVE-2026-0001"})),
        )
        cases = (
            (["package", "--ecosystem", "PyPI", "--name", "demo", "--version", "1.0.0",
              "--format", "json"], '"kind": "package"'),
            (["advisory", "--id", "CVE-2026-0001", "--format", "text"],
             "CVE-2026-0001"),
            (["kev", "--id", "CVE-2026-0001", "--format", "text"],
             "KEV membership: present"),
        )
        for argv, expected in cases:
            with self.subTest(argv=argv):
                code, stdout, stderr = self._invoke(list(argv), configured)
                self.assertEqual(code, 0)
                self.assertNotEqual(code, 1)
                self.assertIn(expected, stdout)
                self.assertEqual(stderr, "")

    def test_cli_empty_unavailable_and_invalid_have_stable_non_policy_exits(self) -> None:
        empty_code, empty_output, _ = self._invoke(
            ["package", "--ecosystem", "npm", "--name", "safe", "--version", "1.0.0"],
            services(),
        )
        unavailable_code, unavailable_output, _ = self._invoke(
            ["kev", "--id", "CVE-2026-0001", "--format", "json"],
            services(kev=FakeKev(state=SourceState.UNAVAILABLE)),
        )
        invalid_code, _invalid_output, invalid_error = self._invoke(
            ["package", "--ecosystem", "PyPI", "--name", "demo"], services(),
        )

        self.assertEqual(empty_code, 0)
        self.assertIn("No matching records", empty_output)
        self.assertEqual(unavailable_code, 2)
        self.assertIn('"status": "unavailable"', unavailable_output)
        self.assertEqual(invalid_code, 3)
        self.assertIn("invalid invocation", invalid_error.lower())
        self.assertNotIn(1, (empty_code, unavailable_code, invalid_code))

    def test_cli_parser_errors_redact_configured_and_structural_credentials(self) -> None:
        for hostile in ("seeded-secret", 'password="synthetic password secret"'):
            with self.subTest(hostile=hostile):
                code, stdout, stderr = self._invoke(
                    ["package", "--ecosystem", "PyPI", "--name", "demo",
                     "--version", "1.0", "--format", hostile],
                    services(),
                )
                self.assertEqual(code, 3)
                self.assertEqual(stdout, "")
                self.assertNotIn("seeded-secret", stderr)
                self.assertNotIn("synthetic password secret", stderr)
                self.assertIn("[REDACTED]", stderr)


if __name__ == "__main__":
    unittest.main()
