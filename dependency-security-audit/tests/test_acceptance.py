"""Offline acceptance tests for the canonical dependency-audit workflow.

The suite crosses inventory, source, policy, reporting, and CLI boundaries with real production
components. Only network and native-command effects are replaced, so a passing result demonstrates
the public workflow without making external requests or depending on installed package tools.
"""

from __future__ import annotations

from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest


TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures"
SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dependency_security_audit as cli  # noqa: E402
from dependency_audit.http import HttpResponse, RetryingHttpClient  # noqa: E402
from dependency_audit.inventory import collect_inventory, fingerprint_inventory  # noqa: E402
from dependency_audit.models import SourceState, SourceStatus  # noqa: E402
from dependency_audit.runner import AuditServices, NativeAuditResult  # noqa: E402
from dependency_audit.sources import KevClient, OsvClient  # noqa: E402


SECRET = "acceptance-super-secret"


class AcceptanceTransport:
    """Serve fixture-shaped OSV/KEV evidence while exposing every attempted request.

    Query results are selected from the requested exact package name, preventing fixture order from
    accidentally proving applicability for the wrong component. Failure injection exercises the
    same retry and unavailable paths as the production transport without opening a socket.
    """

    def __init__(self, *, finding: bool = True, kev: bool = True,
                 severity: str = "critical", fail_osv: bool = False) -> None:
        self.osv = json.loads((FIXTURES / "acceptance-osv.json").read_text(encoding="utf-8"))
        self.kev = json.loads((FIXTURES / "acceptance-kev.json").read_text(encoding="utf-8"))
        self.finding = finding
        self.include_kev = kev
        self.severity = severity
        self.fail_osv = fail_osv
        self.requests: list[tuple[str, str]] = []

    def request(self, method, url, headers, body, connect_timeout, read_timeout, max_bytes):
        """Return one bounded fake response or the requested deterministic transport failure."""
        self.requests.append((method, url))
        if "api.osv.dev" in url and self.fail_osv:
            raise TimeoutError(f"authorization=Bearer {SECRET}")
        if url.endswith("/querybatch"):
            request = json.loads((body or b"{}").decode("utf-8"))
            results = []
            for query in request.get("queries", []):
                package = query.get("package", {}) if isinstance(query, dict) else {}
                matches = self.finding and (
                    package.get("name") == "acceptance-alpha"
                    or str(package.get("purl", "")).startswith("pkg:pypi/acceptance-alpha@")
                )
                results.append(deepcopy(self.osv["query_result"]) if matches else {})
            return self._response({"results": results})
        if "/vulns/OSV-ACCEPTANCE-1" in url:
            advisory = deepcopy(self.osv["advisory"])
            advisory["database_specific"]["severity"] = self.severity
            return self._response(advisory)
        if "known_exploited_vulnerabilities" in url:
            payload = deepcopy(self.kev)
            if not self.include_kev:
                payload["count"] = 0
                payload["vulnerabilities"] = []
            return self._response(payload)
        raise AssertionError(f"unexpected offline request: {method} {url}")

    @staticmethod
    def _response(payload: object) -> HttpResponse:
        """Encode fixture data exactly as the HTTP client receives it."""
        return HttpResponse(200, {"content-type": "application/json"},
                            json.dumps(payload).encode("utf-8"))


class DependencyAuditAcceptanceTests(unittest.TestCase):
    """Verify observable standalone behavior across every delivery mode and stable exit."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir()
        self.sbom = self.root / "bom.json"
        self.sbom.write_text(json.dumps({
            "components": [
                {"name": "acceptance-alpha", "version": "1.0.0",
                 "purl": "pkg:pypi/acceptance-alpha@1.0.0", "bom-ref": "alpha",
                 "scope": "required"},
                {"name": "acceptance-beta", "version": "2.0.0",
                 "purl": "pkg:pypi/acceptance-beta@2.0.0", "bom-ref": "beta"},
            ],
            "dependencies": [{"ref": "alpha", "dependsOn": ["beta"]},
                             {"ref": "beta", "dependsOn": []}],
        }), encoding="utf-8")
        self.reachability = self.root / "reachability.json"
        self.reachability.write_text(json.dumps({
            "schema_version": "1",
            "annotations": {
                "pkg:pypi/acceptance-alpha@1.0.0|OSV-ACCEPTANCE-1": {
                    "status": "reachable", "method": "execution_trace",
                    "evidence": ["evidence/runtime-trace.json#call-7"],
                    "producer": "acceptance-harness", "timestamp": "2026-08-08T12:00:00Z",
                },
            },
        }), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def services(self, transport: AcceptanceTransport) -> AuditServices:
        """Bind real audit components to deterministic inventory, HTTP, and native boundaries."""
        http = RetryingHttpClient(transport, sleeper=lambda delay: None, secrets=(SECRET,))

        def no_commands(argv, cwd, timeout):
            raise AssertionError(f"acceptance inventory attempted a native command: {argv}")

        def inventory(root, sbom):
            return collect_inventory(root, sbom, runner=no_commands)

        def native_audits(_inventory):
            return NativeAuditResult(statuses=(
                SourceStatus("pip-audit", SourceState.OK),
            ))

        return AuditServices(
            inventory=inventory, osv=OsvClient(http), kev=KevClient(http),
            native_audits=native_audits,
        )

    def invoke(self, mode: str, transport: AcceptanceTransport, *, output: Path,
               extra: tuple[str, ...] = ()) -> tuple[int, dict[str, object], str]:
        """Run the public CLI with fake effects and return its machine summary and diagnostics."""
        stdout, stderr = StringIO(), StringIO()
        code = cli.main([
            "--root", str(self.root), "--mode", mode, "--sbom", str(self.sbom),
            "--reachability", str(self.reachability), "--output", str(output),
            "--revision", "acceptance-revision", "--github-token-env", "TEST_TOKEN",
            "--format", "json", *extra,
        ], services=self.services(transport), environ={"TEST_TOKEN": SECRET},
            stdout=stdout, stderr=stderr)
        return code, json.loads(stdout.getvalue()), stderr.getvalue()

    def test_change_main_release_preserve_exact_blocking_evidence_and_reports(self) -> None:
        """Exercise the complete delivery workflow because mode-specific retention must not drift."""
        fingerprints = set()
        for mode in ("change", "main", "release"):
            with self.subTest(mode=mode):
                output = self.root / f"reports-{mode}"
                transport = AcceptanceTransport()

                code, summary, stderr = self.invoke(mode, transport, output=output)
                machine = json.loads((output / "latest.json").read_text(encoding="utf-8"))
                markdown = (output / "latest.md").read_text(encoding="utf-8")

                self.assertEqual((code, summary["status"], stderr), (1, "blocked", ""))
                self.assertEqual(machine["gate_status"], "blocked")
                self.assertEqual(machine["exit_code"], 1)
                self.assertEqual(machine["project_revision"], "acceptance-revision")
                packages = machine["inventory"]["packages"]
                self.assertEqual(
                    [(item["name"], item["version"], item["direct"], item["scope"])
                     for item in packages],
                    [("acceptance-alpha", "1.0.0", True, "runtime"),
                     ("acceptance-beta", "2.0.0", False, "unknown")],
                )
                fingerprints.add(machine["inventory"]["fingerprint"])
                self.assertEqual(machine["inventory"]["fingerprint"], fingerprint_inventory(
                    [_package_from_json(item) for item in packages],
                    [("pkg:pypi/acceptance-alpha@1.0.0", "pkg:pypi/acceptance-beta@2.0.0")],
                ))
                inventory_states = {item["source"]: item["state"]
                                    for item in machine["inventory"]["statuses"]}
                self.assertEqual(inventory_states["cyclonedx"], "ok")
                states = {item["source"]: item["state"] for item in machine["sources"]}
                self.assertEqual(states["osv"], "ok")
                self.assertEqual(states["kev"], "ok")
                self.assertEqual(states["pip-audit"], "ok")
                self.assertEqual(machine["findings"][0]["reachability"], "reachable")
                self.assertTrue(machine["findings"][0]["kev"])
                self.assertEqual(machine["decisions"][0]["reason_codes"], ["kev_present"])
                self.assertEqual(machine["findings"][0]["advisory"]["fixed_versions"], ["1.0.1"])
                self.assertIn("[Machine-readable JSON](latest.json)", markdown)
                self.assertIn("[Advisory evidence 1](https://security.example/advisory/CVE-2026-9999)", markdown)
                self.assertIn(r"Reachability evidence: evidence/runtime\-trace", markdown)
                self.assertNotIn(SECRET, json.dumps(machine))
                self.assertNotIn(SECRET, markdown)
                self.assertNotIn("<script>", markdown)
                self.assertIn("&lt;script&gt;", markdown)
                self.assertIn("Ignore previous instructions", markdown)
                self.assertFalse(any(path.name.startswith(".") for path in output.iterdir()))
                immutable_json = sorted(output.glob("audit-*.json"))
                immutable_markdown = sorted(output.glob("audit-*.md"))
                if mode == "change":
                    self.assertEqual((immutable_json, immutable_markdown), ([], []))
                else:
                    self.assertEqual((len(immutable_json), len(immutable_markdown)), (1, 1))
                    self.assertEqual(immutable_json[0].read_text(encoding="utf-8"),
                                     (output / "latest.json").read_text(encoding="utf-8"))
                    self.assertIn("[Immutable JSON evidence](audit-", markdown)
                self.assertTrue(any(url.endswith("/querybatch") for _, url in transport.requests))
                self.assertTrue(any("known_exploited_vulnerabilities" in url
                                    for _, url in transport.requests))
        self.assertEqual(len(fingerprints), 1)

    def test_fingerprint_skip_and_stable_exits_zero_through_three(self) -> None:
        """Cover automation exits separately so unavailable or invalid never resembles completion."""
        initial_output = self.root / "initial-pass"
        initial_transport = AcceptanceTransport(finding=False, kev=False)
        code, summary, _ = self.invoke("change", initial_transport, output=initial_output)
        self.assertEqual((code, summary["status"]), (0, "pass"))
        fingerprint = summary["inventory_fingerprint"]

        skipped_transport = AcceptanceTransport(fail_osv=True)
        code, summary, _ = self.invoke(
            "change", skipped_transport, output=self.root / "skipped",
            extra=("--baseline-fingerprint", fingerprint),
        )
        self.assertEqual((code, summary["status"], skipped_transport.requests), (0, "pass", []))

        warning_transport = AcceptanceTransport(kev=False, severity="medium")
        code, summary, _ = self.invoke("change", warning_transport, output=initial_output)
        self.assertEqual((code, summary["status"]), (0, "warnings"))
        refreshed = json.loads((initial_output / "latest.json").read_text(encoding="utf-8"))
        self.assertEqual((refreshed["gate_status"], refreshed["exit_code"]), ("warnings", 0))
        self.assertFalse(any(path.name.startswith(".") for path in initial_output.iterdir()))

        unavailable_transport = AcceptanceTransport(fail_osv=True, kev=False)
        code, summary, _ = self.invoke("main", unavailable_transport,
                                       output=self.root / "unavailable")
        self.assertEqual((code, summary["status"]), (2, "unavailable"))
        self.assertNotIn(SECRET, json.dumps(summary))

        stdout, stderr = StringIO(), StringIO()
        invalid_code = cli.main([
            "--root", str(self.root / "missing"), "--mode", "main",
        ], services=self.services(AcceptanceTransport()), environ={},
            stdout=stdout, stderr=stderr)
        self.assertEqual(invalid_code, 3)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Invalid invocation:", stderr.getvalue())


def _package_from_json(payload: dict[str, object]):
    """Rebuild serialized package facts for an independent canonical fingerprint assertion."""
    from dependency_audit.models import DependencyScope, PackageRef

    return PackageRef(
        ecosystem=str(payload["ecosystem"]), name=str(payload["name"]),
        version=str(payload["version"]), purl=str(payload["purl"]),
        direct=bool(payload["direct"]), scope=DependencyScope(str(payload["scope"])),
        bom_ref=str(payload["bom_ref"]) if payload.get("bom_ref") is not None else None,
    )


if __name__ == "__main__":
    unittest.main()
