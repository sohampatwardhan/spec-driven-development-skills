"""Offline end-to-end tests for the standalone dependency-audit command contract."""

from __future__ import annotations

from dataclasses import replace
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dependency_security_audit as cli  # noqa: E402
from dependency_audit.http import HttpResponse, RetryingHttpClient  # noqa: E402
from dependency_audit.inventory import CommandResult  # noqa: E402
from dependency_audit.models import (  # noqa: E402
    AuditMode, DependencyScope, InventoryResult, PackageRef, SourceState, SourceStatus,
)
from dependency_audit.runner import AuditServices  # noqa: E402
from dependency_audit.sources import KevClient, OsvClient, SourceResult  # noqa: E402


FIXTURE_PROJECT = Path(__file__).parent / "fixtures" / "project"


class FakeTransport:
    """Serve deterministic OSV/KEV payloads and expose request bounds for assertions."""

    def __init__(self, *, severity: str | None = None, fail_osv: bool = False,
                 secret: str = "") -> None:
        self.severity = severity
        self.fail_osv = fail_osv
        self.secret = secret
        self.requests = []

    def request(self, method, url, headers, body, connect_timeout, read_timeout, max_bytes):
        self.requests.append((method, url, dict(headers), connect_timeout, read_timeout, max_bytes))
        if "api.osv.dev" in url and self.fail_osv:
            raise TimeoutError(f"\x1b[31mauthorization={self.secret or 'unavailable'}")
        if url.endswith("/querybatch"):
            result = {} if self.severity is None else {"vulns": [{"id": "OSV-ONE"}]}
            return self._json({"results": [result]})
        if "/vulns/OSV-ONE" in url:
            return self._json({
                "id": "OSV-ONE",
                "aliases": ["CVE-2025-0001"],
                "database_specific": {"severity": self.severity},
                "affected": [{
                    "package": {"ecosystem": "PyPI", "name": "demo", "purl": "pkg:pypi/demo"},
                    "ranges": [{"type": "ECOSYSTEM", "events": [
                        {"introduced": "0"}, {"fixed": "1.0.1"},
                    ]}],
                }],
            })
        if "known_exploited_vulnerabilities" in url:
            return self._json({"vulnerabilities": []})
        raise AssertionError(f"unexpected offline URL: {url}")

    @staticmethod
    def _json(payload):
        return HttpResponse(200, {}, json.dumps(payload).encode("utf-8"))


class CaptureTransport:
    """Capture credential headers without performing a network request."""

    def __init__(self) -> None:
        self.headers = {}

    def request(self, method, url, headers, body, connect_timeout, read_timeout, max_bytes):
        self.headers[url] = dict(headers)
        return HttpResponse(200, {}, b"{}")


class CliTests(unittest.TestCase):
    """Verify modes, validation, reports, redaction, policy, summaries, and exits."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(FIXTURE_PROJECT, self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def inventory(self, root, sbom, *, complete=True):
        line = (Path(root) / "requirements.lock").read_text(encoding="utf-8").splitlines()[-1]
        name, version = line.split("==")
        package = PackageRef("PyPI", name, version, f"pkg:pypi/{name}@{version}", True,
                             DependencyScope.RUNTIME)
        return InventoryResult(
            packages=[package], fingerprint="fixture-fingerprint", complete=complete,
            statuses=[SourceStatus("fixture-inventory", SourceState.OK)],
            incomplete_reasons=[] if complete else ["fixture incomplete"],
        )

    @staticmethod
    def native_inventory(source):
        ecosystem, name, version, purl = {
            "npm-audit": ("npm", "demo", "1.0.0", "pkg:npm/demo@1.0.0"),
            "cargo-audit": ("crates.io", "demo", "1.0.0", "pkg:cargo/demo@1.0.0"),
            "govulncheck": ("Go", "example.com/demo", "v1.0.0", "pkg:golang/example.com/demo@v1.0.0"),
            "pip-audit": ("PyPI", "demo", "1.0.0", "pkg:pypi/demo@1.0.0"),
        }[source]
        package = PackageRef(ecosystem, name, version, purl, True, DependencyScope.RUNTIME)
        return InventoryResult(packages=[package], fingerprint=f"{source}-fingerprint", complete=True,
                               statuses=[SourceStatus("fixture-inventory", SourceState.OK)])

    @staticmethod
    def native_payload(source, kind):
        clean = {
            "npm-audit": {"auditReportVersion": 2, "vulnerabilities": {}},
            "cargo-audit": {"vulnerabilities": {"found": False, "count": 0, "list": []}},
            "govulncheck": {"config": {"protocol_version": "v1"}},
            "pip-audit": [{"name": "demo", "version": "1.0.0", "vulns": []}],
        }
        if kind == "clean":
            value = clean[source]
            return json.dumps(value) + ("\n" if source == "govulncheck" else "")
        finding = {
            "npm-audit": {
                "auditReportVersion": 2,
                "vulnerabilities": {"demo": {
                    "name": "demo", "severity": "high",
                    "via": [{"source": 101, "name": "demo", "severity": "high",
                             "title": "inert npm text", "url": "https://example.test/GHSA-1111-2222-3333"}],
                    "fixAvailable": {"name": "demo", "version": "1.0.1"},
                }},
            },
            "cargo-audit": {
                "vulnerabilities": {"found": True, "count": 1, "list": [{
                    "advisory": {"id": "RUSTSEC-2026-0001", "severity": "critical",
                                 "title": "inert cargo text", "url": "https://example.test/rustsec"},
                    "versions": {"patched": [">= 1.0.1"], "unaffected": []},
                    "package": {"name": "demo", "version": "1.0.0"},
                }]},
            },
            "pip-audit": [{
                "name": "demo", "version": "1.0.0", "vulns": [{
                    "id": "PYSEC-2026-1", "aliases": ["CVE-2026-0001"],
                    "severity": "high", "fix_versions": ["1.0.1"],
                    "description": "inert pip text",
                }],
            }],
        }
        if source == "govulncheck":
            events = [
                {"osv": {"id": "GO-2026-0001", "aliases": ["CVE-2026-0002"],
                         "summary": "inert go text", "database_specific": {"severity": "high"}}},
                {"finding": {"osv": "GO-2026-0001", "fixed_version": "v1.0.1",
                             "trace": [{"module": "example.com/demo", "version": "v1.0.0"}]}},
            ]
            return "\n".join(json.dumps(event) for event in events) + "\n"
        return json.dumps(finding[source])

    def services(self, *, severity=None, fail_osv=False, secret="", complete=True):
        transport = FakeTransport(severity=severity, fail_osv=fail_osv, secret=secret)
        http = RetryingHttpClient(transport, sleeper=lambda delay: None, secrets=(secret,))
        services = AuditServices(
            inventory=lambda root, sbom: self.inventory(root, sbom, complete=complete),
            osv=OsvClient(http), kev=KevClient(http),
        )
        return services, transport

    def invoke(self, mode, services, *, output=None, extra=(), format="json", environ=None):
        stdout, stderr = StringIO(), StringIO()
        destination = output or (Path(self.temp.name) / f"reports-{mode}")
        argv = ["--root", str(self.root), "--mode", mode, "--output", str(destination),
                "--format", format, *extra]
        code = cli.main(argv, services=services, environ=environ or {}, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue(), destination

    def test_change_main_and_release_are_offline_and_write_required_evidence(self) -> None:
        for mode in ("change", "main", "release"):
            with self.subTest(mode=mode):
                services, transport = self.services()
                code, stdout, stderr, output = self.invoke(mode, services)
                summary = json.loads(stdout)

                self.assertEqual(code, 0)
                self.assertEqual(summary["status"], "pass")
                self.assertEqual(stderr, "")
                self.assertTrue((output / "latest.json").is_file())
                self.assertTrue((output / "latest.md").is_file())
                retained = list(output.glob("audit-*.json"))
                self.assertEqual(len(retained), 0 if mode == "change" else 1)
                retained_markdown = list(output.glob("audit-*.md"))
                self.assertEqual(len(retained_markdown), 0 if mode == "change" else 1)
                self.assertTrue(any("api.osv.dev" in request[1] for request in transport.requests))
                self.assertTrue(any("known_exploited_vulnerabilities" in request[1]
                                    for request in transport.requests))

    def test_pass_warning_block_unavailable_and_incomplete_exits_are_distinct(self) -> None:
        cases = (
            (None, False, True, "pass", 0),
            ("medium", False, True, "warnings", 0),
            ("high", False, True, "blocked", 1),
            (None, True, True, "unavailable", 2),
            (None, False, False, "unavailable", 2),
        )
        for index, (severity, fail, complete, expected_status, expected_code) in enumerate(cases):
            with self.subTest(status=expected_status, index=index):
                services, _transport = self.services(
                    severity=severity, fail_osv=fail, complete=complete,
                )
                code, stdout, _stderr, _output = self.invoke(
                    "main", services, output=Path(self.temp.name) / f"status-{index}",
                )
                self.assertEqual(code, expected_code)
                self.assertEqual(json.loads(stdout)["status"], expected_status)

    def test_policy_file_has_same_decision_in_summary_and_canonical_report(self) -> None:
        policy = Path(self.temp.name) / "policy.json"
        policy.write_text(json.dumps({"block_severities": ["medium"]}), encoding="utf-8")
        services, _transport = self.services(severity="medium")

        code, stdout, _stderr, output = self.invoke(
            "main", services, extra=("--policy", str(policy)),
        )
        summary = json.loads(stdout)
        report = json.loads((output / "latest.json").read_text(encoding="utf-8"))

        self.assertEqual((code, summary["status"]), (1, "blocked"))
        self.assertEqual(report["gate_status"], summary["status"])
        self.assertEqual(report["exit_code"], summary["exit_code"])
        self.assertEqual(report["decisions"][0]["decision"], "block")

    def test_human_summary_is_concise_and_warning_is_not_labeled_clean(self) -> None:
        services, _transport = self.services(severity="medium")
        code, stdout, stderr, _output = self.invoke("change", services, format="human")

        self.assertEqual(code, 0)
        self.assertIn("Dependency audit: WARNINGS", stdout)
        self.assertIn("Reports:", stdout)
        self.assertNotIn("clean", stdout.lower())
        self.assertEqual(stderr, "")

    def test_paths_timeouts_policy_and_environment_names_validate_as_exit_three(self) -> None:
        existing_file = self.root / "requirements.lock"
        malformed_policy = Path(self.temp.name) / "bad-policy.json"
        malformed_policy.write_text('{"unknown": true}', encoding="utf-8")
        cases = (
            ("--root", str(self.root / "missing")),
            ("--sbom", str(self.root / "missing.json")),
            ("--reachability", str(self.root / "missing-reach.json")),
            ("--policy", str(malformed_policy)),
            ("--output", str(existing_file)),
            ("--connect-timeout", "nan"),
            ("--read-timeout", "0"),
            ("--source-max-age", "inf"),
            ("--source-max-age", "604801"),
            ("--github-token-env", "actual-secret-value!"),
            ("--nvd-api-key-env", "BAD-NAME"),
        )
        for index, extra in enumerate(cases):
            with self.subTest(option=extra[0]):
                services, _transport = self.services()
                root_args = [] if extra[0] == "--root" else ["--root", str(self.root)]
                stdout, stderr = StringIO(), StringIO()
                code = cli.main(
                    [*root_args, "--mode", "main", *extra], services=services,
                    environ={}, stdout=stdout, stderr=stderr,
                )
                self.assertEqual(code, 3)
                self.assertEqual(stdout.getvalue(), "")
                self.assertIn("Invalid invocation:", stderr.getvalue())

        services, _transport = self.services()
        code, _stdout, _stderr, _output = self.invoke(
            "main", services, extra=("--source-max-age", "86400"),
        )
        self.assertEqual(code, 0)

    def test_unknown_credential_like_argument_is_rejected_without_echoing_its_value(self) -> None:
        secret = "accidental-argv-secret"
        stdout, stderr = StringIO(), StringIO()
        services, _transport = self.services()
        code = cli.main(
            ["--root", str(self.root), "--mode", "main", "--github-token", secret],
            services=services, environ={}, stdout=stdout, stderr=stderr,
        )

        self.assertEqual(code, 3)
        self.assertNotIn(secret, stderr.getvalue())

    def test_report_failure_is_unavailable_and_summary_does_not_claim_paths(self) -> None:
        services, _transport = self.services()

        def fail_reports(*args, **kwargs):
            raise OSError("write failed")

        failed_services = replace(services, reports=fail_reports)
        code, stdout, _stderr, _output = self.invoke("main", failed_services, format="human")

        self.assertEqual(code, 2)
        self.assertIn("Reports: unavailable", stdout)

    def test_credential_value_comes_only_from_environment_and_is_redacted_everywhere(self) -> None:
        secret = "seeded-super-secret"
        services, _transport = self.services(fail_osv=True, secret=secret)
        code, stdout, _stderr, output = self.invoke(
            "main", services, extra=("--github-token-env", "AUDIT_GITHUB_TOKEN"),
            environ={"AUDIT_GITHUB_TOKEN": secret},
        )

        self.assertEqual(code, 2)
        self.assertNotIn(secret, stdout)
        self.assertNotIn("\x1b", stdout)
        self.assertNotIn(secret, (output / "latest.json").read_text(encoding="utf-8"))
        self.assertNotIn(secret, (output / "latest.md").read_text(encoding="utf-8"))

    def test_all_dynamic_summary_fields_and_paths_are_sanitized(self) -> None:
        secret = "summary-secret"
        services, _transport = self.services()
        original_inventory = services.inventory

        def hostile_inventory(root, sbom):
            value = original_inventory(root, sbom)
            value.fingerprint = f"fingerprint-{secret}\x1b"
            value.statuses = [SourceStatus(f"source-{secret}\x1b", SourceState.OK)]
            return value

        hostile_services = replace(services, inventory=hostile_inventory)
        output = Path(self.temp.name) / f"reports-{secret}\x1b"
        code, stdout, _stderr, _output = self.invoke(
            "change", hostile_services, output=output,
            extra=("--github-token-env", "TOKEN_NAME"), environ={"TOKEN_NAME": secret},
        )

        self.assertEqual(code, 0)
        self.assertNotIn(secret, stdout)
        self.assertNotIn("\x1b", stdout)

    def test_stale_latest_files_never_appear_as_current_after_report_failure(self) -> None:
        for format in ("json", "human"):
            with self.subTest(format=format):
                output = Path(self.temp.name) / f"stale-{format}"
                output.mkdir()
                (output / "latest.json").write_text("stale-json", encoding="utf-8")
                (output / "latest.md").write_text("stale-markdown", encoding="utf-8")
                services, _transport = self.services()

                def fail_reports(*args, **kwargs):
                    raise OSError("write failed")

                code, stdout, _stderr, _output = self.invoke(
                    "main", replace(services, reports=fail_reports), output=output, format=format,
                )
                self.assertEqual(code, 2)
                if format == "json":
                    self.assertEqual(json.loads(stdout)["reports"],
                                     {"json": None, "markdown": None})
                else:
                    self.assertIn("Reports: unavailable", stdout)
                self.assertEqual((output / "latest.json").read_text(encoding="utf-8"), "stale-json")

    def test_stale_required_source_cannot_be_revived_by_maximum_allowed_age(self) -> None:
        class StaleOsv:
            def query(self, packages):
                return SourceResult([], SourceStatus(
                    "osv", SourceState.OK, attempted_at="2020-01-01T00:00:00Z",
                ))

        services, _transport = self.services()
        code, stdout, _stderr, _output = self.invoke(
            "main", replace(services, osv=StaleOsv()),
            extra=("--source-max-age", "604800"),
        )

        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["status"], "unavailable")

    def test_optional_evidence_files_require_read_permission_bits_and_openability(self) -> None:
        for option in ("--sbom", "--reachability", "--policy"):
            with self.subTest(option=option):
                path = Path(self.temp.name) / f"unreadable-{option[2:]}.json"
                path.write_text("{}", encoding="utf-8")
                path.chmod(0)
                try:
                    services, _transport = self.services()
                    stdout, stderr = StringIO(), StringIO()
                    code = cli.main(
                        ["--root", str(self.root), "--mode", "main", option, str(path)],
                        services=services, environ={}, stdout=stdout, stderr=stderr,
                    )
                    self.assertEqual(code, 3)
                    self.assertIn("must be readable", stderr.getvalue())
                finally:
                    path.chmod(0o600)

    def test_default_service_bounds_and_host_scoped_environment_credentials(self) -> None:
        commands = []

        def command_runner(argv, cwd, timeout):
            commands.append(argv)
            return CommandResult(tuple(argv), 0, "[]")

        services = cli._default_services(
            ("gh-secret", "nvd-secret"), "gh-secret", "nvd-secret", 2.5, 4.5,
            self.root, command_runner,
        )
        self.assertEqual(services.osv.http.connect_timeout, 2.5)
        self.assertEqual(services.osv.http.read_timeout, 4.5)
        native = services.native_audits(self.inventory(self.root, None))
        states = {item.source: item.state for item in native.statuses}
        self.assertEqual(states["pip-audit"], SourceState.OK)
        self.assertEqual(states["npm-audit"], SourceState.NOT_APPLICABLE)
        self.assertEqual(commands, [("pip-audit", "--format", "json")])

        missing = cli._default_services(
            (), "", "", 2.5, 4.5, self.root,
            lambda argv, cwd, timeout: (_ for _ in ()).throw(FileNotFoundError()),
        ).native_audits(self.inventory(self.root, None))
        self.assertEqual(next(item.state for item in missing.statuses
                              if item.source == "pip-audit"), SourceState.UNAVAILABLE)

        partial = cli._default_services(
            (), "", "", 2.5, 4.5, self.root,
            lambda argv, cwd, timeout: CommandResult(tuple(argv), 1, "{}", "findings present"),
        ).native_audits(self.inventory(self.root, None))
        self.assertEqual(next(item.state for item in partial.statuses
                              if item.source == "pip-audit"), SourceState.PARTIAL)

    def test_default_applicable_native_tool_gap_prevents_main_from_passing(self) -> None:
        default = cli._default_services(
            (), "", "", 2.5, 4.5, self.root,
            lambda argv, cwd, timeout: (_ for _ in ()).throw(FileNotFoundError()),
        )
        offline, _transport = self.services()
        wired = replace(
            default, inventory=offline.inventory, osv=offline.osv, kev=offline.kev,
            github=None, nvd=None,
        )

        code, stdout, _stderr, _output = self.invoke("main", wired)

        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["status"], "unavailable")

    def test_native_machine_adapters_distinguish_clean_findings_malformed_and_failure(self) -> None:
        commands = {item[0]: item[2] for item in cli._NATIVE_AUDITS}
        findings_exit = {"npm-audit": 1, "cargo-audit": 1, "govulncheck": 0, "pip-audit": 1}
        identities = {
            "npm-audit": ("NPM-101", ("GHSA-1111-2222-3333",), "high"),
            "cargo-audit": ("RUSTSEC-2026-0001", (), "critical"),
            "govulncheck": ("GO-2026-0001", ("CVE-2026-0002",), "high"),
            "pip-audit": ("PYSEC-2026-1", ("CVE-2026-0001",), "high"),
        }
        for source in commands:
            inventory = self.native_inventory(source)
            for kind, expected in (("clean", SourceState.OK), ("finding", SourceState.OK),
                                   ("malformed", SourceState.PARTIAL), ("failure", SourceState.UNAVAILABLE)):
                with self.subTest(source=source, kind=kind):
                    def runner(argv, cwd, timeout, *, selected=source, case=kind):
                        self.assertEqual(tuple(argv), commands[selected])
                        if case == "failure":
                            return CommandResult(tuple(argv), 2, "", "execution failed")
                        if case == "malformed":
                            return CommandResult(tuple(argv), 0, "not-json")
                        code = findings_exit[selected] if case == "finding" else 0
                        return CommandResult(tuple(argv), code, self.native_payload(selected, case))

                    result = cli._run_native_audits(inventory, self.root, runner)
                    state = next(item.state for item in result.statuses if item.source == source)
                    self.assertEqual(state, expected)
                    self.assertEqual(bool(result.advisories), kind == "finding")
                    if kind == "finding":
                        advisory = result.advisories[0]
                        package = inventory.packages[0]
                        self.assertEqual((advisory.id, advisory.aliases, advisory.severity),
                                         identities[source])
                        self.assertEqual(advisory.source, source)
                        self.assertTrue(advisory.fixed_versions)
                        self.assertEqual(advisory.affected_ranges, ())
                        self.assertEqual(len(advisory.affected_packages), 1)
                        self.assertEqual(advisory.affected_packages[0].purl, package.purl)
                        self.assertEqual(advisory.affected_packages[0].versions, (package.version,))
                        self.assertEqual(advisory.affected_packages[0].ranges, ())
                        self.assertIn("inert", advisory.details)

    def test_cargo_patched_or_branches_never_recommend_an_older_safe_line(self) -> None:
        inventory = self.native_inventory("cargo-audit")
        installed = inventory.packages[0]
        inventory.packages = [PackageRef(
            installed.ecosystem, installed.name, "0.9.0", "pkg:cargo/demo@0.9.0", True,
            DependencyScope.RUNTIME,
        )]
        payload = json.loads(self.native_payload("cargo-audit", "finding"))
        payload["vulnerabilities"]["list"][0]["package"]["version"] = "0.9.0"
        payload["vulnerabilities"]["list"][0]["versions"]["patched"] = [
            ">=0.8.4,<0.9.0", ">=0.9.1",
        ]

        advisories, malformed = cli._parse_native_output(
            "cargo-audit", json.dumps(payload), inventory.packages,
        )

        self.assertFalse(malformed)
        self.assertEqual(advisories[0].fixed_versions, ("0.9.1",))
        self.assertNotIn("0.8.4", advisories[0].fixed_versions)
        self.assertEqual(advisories[0].affected_ranges, ())
        self.assertEqual(advisories[0].affected_packages[0].ranges, ())
        self.assertIn(">=0.8.4,<0.9.0", advisories[0].details)
        self.assertIn(">=0.9.1", advisories[0].details)

        payload["vulnerabilities"]["list"][0]["versions"]["patched"] = [">0.9.0"]
        ambiguous, malformed = cli._parse_native_output(
            "cargo-audit", json.dumps(payload), inventory.packages,
        )
        self.assertTrue(malformed)
        self.assertEqual(ambiguous[0].fixed_versions, ())
        self.assertIn(">0.9.0", ambiguous[0].details)

    def test_each_native_adapter_retains_exact_fixed_runtime_finding_into_policy(self) -> None:
        commands = {item[0]: item[2] for item in cli._NATIVE_AUDITS}
        findings_exit = {"npm-audit": 1, "cargo-audit": 1, "govulncheck": 0, "pip-audit": 1}
        for index, source in enumerate(commands):
            with self.subTest(source=source):
                inventory = self.native_inventory(source)

                def runner(argv, cwd, timeout, *, selected=source):
                    return CommandResult(tuple(argv), findings_exit[selected],
                                         self.native_payload(selected, "finding"))

                services, _transport = self.services()
                wired = replace(
                    services, inventory=lambda root, sbom, value=inventory: value,
                    native_audits=lambda value, selected=source: cli._run_native_audits(
                        value, self.root, runner,
                    ),
                )
                code, stdout, _stderr, output = self.invoke(
                    "main", wired, output=Path(self.temp.name) / f"native-{index}",
                )
                report = json.loads((output / "latest.json").read_text(encoding="utf-8"))

                self.assertEqual(code, 1)
                self.assertEqual(json.loads(stdout)["status"], "blocked")
                self.assertEqual(report["findings"][0]["advisory"]["source"], source)
                self.assertTrue(report["findings"][0]["advisory"]["fixed_versions"])
                self.assertEqual(report["decisions"][0]["decision"], "block")

        capture = CaptureTransport()
        transport = cli._CredentialTransport(capture, "gh-secret", "nvd-secret")
        for url in ("https://api.github.com/advisories", "https://services.nvd.nist.gov/x",
                    "https://api.osv.dev/v1/querybatch"):
            transport.request("GET", url, {}, None, 1, 1, 100)
        self.assertEqual(capture.headers["https://api.github.com/advisories"]["Authorization"],
                         "Bearer gh-secret")
        self.assertEqual(capture.headers["https://services.nvd.nist.gov/x"]["apiKey"], "nvd-secret")
        self.assertNotIn("Authorization", capture.headers["https://api.osv.dev/v1/querybatch"])
        self.assertNotIn("apiKey", capture.headers["https://api.osv.dev/v1/querybatch"])

    def test_help_documents_outputs_credentials_and_exit_contract(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "dependency_security_audit.py"), "--help"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("--github-token-env", completed.stdout)
        self.assertIn("--nvd-api-key-env", completed.stdout)
        self.assertIn("--format", completed.stdout)
        self.assertIn("stdout contains one human or JSON summary", completed.stdout)
        self.assertIn("Exits: 0 pass/warnings, 1 blocked, 2 unavailable/incomplete, 3 invalid",
                      completed.stdout.replace("\n", " "))


if __name__ == "__main__":
    unittest.main()
