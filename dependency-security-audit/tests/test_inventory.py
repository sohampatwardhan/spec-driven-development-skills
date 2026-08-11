"""Focused contracts for exact inventory adapters and native command evidence."""

from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.inventory import (  # noqa: E402
    CommandResult,
    collect_inventory,
    fingerprint_inventory,
    parse_cargo_metadata,
    parse_cyclonedx,
    parse_go_list,
    parse_npm_list,
    parse_pip_inspect,
    run_command,
)
from dependency_audit.models import DependencyScope, SourceState  # noqa: E402


FIXTURES = Path(__file__).with_name("fixtures")


def load_fixture(name: str) -> object:
    """Load a checked-in machine-readable package-manager response."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class InventoryAdapterTests(unittest.TestCase):
    """Verify parsers retain only exact, reproducible resolved dependency facts."""

    def test_npm_preserves_direct_transitive_and_scope(self) -> None:
        result = parse_npm_list(load_fixture("npm-list.json"))

        packages = {package.name: package for package in result.packages}
        self.assertTrue(result.complete)
        self.assertTrue(packages["direct-runtime"].direct)
        self.assertEqual(packages["direct-runtime"].scope, DependencyScope.RUNTIME)
        self.assertFalse(packages["nested"].direct)
        self.assertEqual(packages["direct-dev"].scope, DependencyScope.DEVELOPMENT)
        self.assertIn((packages["direct-runtime"].purl, packages["nested"].purl), result.dependencies)

    def test_pip_cargo_and_go_parse_exact_graphs(self) -> None:
        pip = parse_pip_inspect(load_fixture("pip-inspect.json"))
        cargo = parse_cargo_metadata(load_fixture("cargo-metadata.json"))
        go = parse_go_list(
            (FIXTURES / "go-list.jsonl").read_text(encoding="utf-8"),
            "example.com/app example.com/direct@v1.2.3\nexample.com/direct@v1.2.3 example.com/transitive@v2.0.0\n",
        )

        self.assertFalse(pip.complete)  # pip metadata requirements are not resolved graph evidence.
        self.assertEqual({package.scope for package in pip.packages}, {DependencyScope.UNKNOWN})
        self.assertTrue(any(package.direct for package in pip.packages))
        self.assertTrue(cargo.complete)
        self.assertTrue(any(package.scope is DependencyScope.DEVELOPMENT for package in cargo.packages))
        self.assertTrue(go.complete)
        self.assertTrue(any(package.direct for package in go.packages))
        self.assertEqual(len(go.dependencies), 1)

    def test_cyclonedx_builds_edges_and_rejects_unresolved_refs(self) -> None:
        result = parse_cyclonedx(load_fixture("cyclonedx.json"))

        self.assertTrue(result.complete)
        self.assertEqual(len(result.dependencies), 1)
        self.assertEqual(result.packages[0].scope, DependencyScope.RUNTIME)
        packages = {package.name: package for package in result.packages}
        self.assertTrue(packages["requests"].direct)
        self.assertFalse(packages["urllib3"].direct)

        invalid = parse_cyclonedx({"components": [{"name": "missing-version", "purl": "pkg:pypi/x@1"}]})
        self.assertFalse(invalid.complete)
        self.assertTrue(invalid.incomplete_reasons)

        unresolved = parse_cyclonedx({
            "bomFormat": "CycloneDX", "specVersion": "1.7",
            "components": [{"name": "known", "version": "1.0", "purl": "pkg:pypi/known@1.0", "bom-ref": "known"}],
            "dependencies": [{"ref": "known", "dependsOn": ["not-in-components"]}],
        })
        self.assertFalse(unresolved.complete)
        self.assertTrue(any("unknown target" in reason for reason in unresolved.incomplete_reasons))

    def test_cyclonedx_requires_document_identity_and_complete_graph_nodes(self) -> None:
        component = {
            "name": "known", "version": "1.0", "purl": "pkg:pypi/known@1.0",
            "bom-ref": "known",
        }
        for payload in (
            {"specVersion": "1.7", "components": [component], "dependencies": []},
            {"bomFormat": "CycloneDX", "components": [component], "dependencies": []},
            {"bomFormat": "CycloneDX", "specVersion": "9.9", "components": [component], "dependencies": []},
        ):
            with self.subTest(payload=payload):
                self.assertFalse(parse_cyclonedx(payload).complete)

        omitted = parse_cyclonedx({
            "bomFormat": "CycloneDX", "specVersion": "1.7",
            "components": [component], "dependencies": [],
        })
        self.assertFalse(omitted.complete)
        self.assertTrue(any("omits bom-ref" in reason for reason in omitted.incomplete_reasons))

        duplicate = parse_cyclonedx({
            "bomFormat": "CycloneDX", "specVersion": "1.7",
            "components": [component, dict(component)],
            "dependencies": [{"ref": "known", "dependsOn": []}],
        })
        self.assertFalse(duplicate.complete)
        self.assertTrue(any("ambiguous" in reason for reason in duplicate.incomplete_reasons))

    def test_duplicate_purls_are_deduplicated_and_fingerprint_is_canonical(self) -> None:
        first = parse_npm_list(load_fixture("npm-list.json"))
        duplicate = parse_npm_list({
            "dependencies": {
                "direct-runtime": {"version": "1.0.0", "dev": False},
                "direct-runtime-copy": {"version": "1.0.0", "dev": False, "name": "direct-runtime"},
            }
        })

        self.assertEqual(len(duplicate.packages), 1)
        self.assertEqual(first.fingerprint, fingerprint_inventory(first.packages, first.dependencies))
        self.assertEqual(first.fingerprint, fingerprint_inventory(list(reversed(first.packages)), list(reversed(first.dependencies))))

    def test_collect_inventory_marks_command_failures_partial(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "package-lock.json").write_text("{}", encoding="utf-8")

            def failed_runner(argv: tuple[str, ...], cwd: Path, timeout: float) -> CommandResult:
                self.assertIsInstance(argv, tuple)
                self.assertEqual(cwd, root)
                self.assertGreater(timeout, 0)
                return CommandResult(argv=argv, returncode=1, stdout="", stderr="native failed")

            result = collect_inventory(root, runner=failed_runner)

        self.assertFalse(result.complete)
        self.assertTrue(any(status.state is SourceState.PARTIAL for status in result.statuses))
        self.assertTrue(any("npm" in reason for reason in result.incomplete_reasons))

    def test_rejects_locator_branch_and_path_versions(self) -> None:
        for version in ("file:../local", "https://example.test/pkg.tgz", "git+https://example.test/pkg.git", "main", "release-tag", "../local"):
            with self.subTest(version=version):
                result = parse_npm_list({"dependencies": {"unsafe": {"version": version}}})
                self.assertFalse(result.complete)
                self.assertTrue(result.incomplete_reasons)

    def test_cargo_requires_unambiguous_root_and_package_ids(self) -> None:
        payload = load_fixture("cargo-metadata.json")
        assert isinstance(payload, dict)
        payload["resolve"]["root"] = "missing-root"
        bad_root = parse_cargo_metadata(payload)
        self.assertFalse(bad_root.complete)
        self.assertTrue(any("root" in reason for reason in bad_root.incomplete_reasons))

        payload = load_fixture("cargo-metadata.json")
        assert isinstance(payload, dict)
        payload["resolve"]["nodes"][0]["deps"][0]["pkg"] = "missing-package"
        bad_id = parse_cargo_metadata(payload)
        self.assertFalse(bad_id.complete)
        self.assertTrue(any("unresolved" in reason or "unknown" in reason for reason in bad_id.incomplete_reasons))

    def test_go_requires_and_joins_exact_module_graph(self) -> None:
        listing = (FIXTURES / "go-list.jsonl").read_text(encoding="utf-8")
        absent = parse_go_list(listing)
        self.assertFalse(absent.complete)
        self.assertTrue(any("graph" in reason for reason in absent.incomplete_reasons))

        invalid = parse_go_list(listing, "example.com/app example.com/missing@v1.0.0\n")
        self.assertFalse(invalid.complete)
        self.assertTrue(any("unknown" in reason for reason in invalid.incomplete_reasons))

    def test_go_remote_replace_uses_effective_package_identity(self) -> None:
        listing = "\n".join((
            '{"Path":"example.com/app","Main":true}',
            '{"Path":"example.com/original","Version":"v1.0.0","Replace":{"Path":"example.com/fork","Version":"v1.2.3"}}',
            '{"Path":"example.com/leaf","Version":"v2.0.0","Indirect":true}',
        ))
        graph = "\n".join((
            "example.com/app example.com/original@v1.0.0",
            "example.com/original@v1.0.0 example.com/leaf@v2.0.0",
        ))

        result = parse_go_list(listing, graph)

        self.assertTrue(result.complete)
        packages = {package.name: package for package in result.packages}
        self.assertEqual(packages["example.com/fork"].version, "v1.2.3")
        self.assertEqual(packages["example.com/fork"].purl, "pkg:golang/example.com/fork@v1.2.3")
        self.assertIn((packages["example.com/fork"].purl, packages["example.com/leaf"].purl), result.dependencies)

        local = parse_go_list(
            listing.replace('"example.com/fork"', '"../fork"'), graph,
        )
        self.assertFalse(local.complete)
        self.assertTrue(any("replacement" in reason for reason in local.incomplete_reasons))

    def test_collect_go_runs_bounded_list_and_graph_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
            calls: list[tuple[str, ...]] = []

            def go_runner(argv: tuple[str, ...], cwd: Path, timeout: float) -> CommandResult:
                calls.append(argv)
                self.assertEqual(cwd, root)
                self.assertGreater(timeout, 0)
                if argv[:3] == ("go", "list", "-m"):
                    return CommandResult(argv, 0, (FIXTURES / "go-list.jsonl").read_text(encoding="utf-8"))
                return CommandResult(argv, 0, "example.com/app example.com/direct@v1.2.3\nexample.com/direct@v1.2.3 example.com/transitive@v2.0.0\n")

            result = collect_inventory(root, runner=go_runner)

        self.assertTrue(result.complete)
        self.assertIn(("go", "list", "-m", "-json", "all"), calls)
        self.assertIn(("go", "mod", "graph"), calls)

    def test_collect_refuses_ambient_pip_and_reports_all_source_states(self) -> None:
        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
            ambient = collect_inventory(root)
        self.assertFalse(ambient.complete)
        self.assertTrue(any(status.source == "pip-inspect" and status.state is SourceState.PARTIAL for status in ambient.statuses))

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            missing = collect_inventory(root)
        self.assertTrue(any(status.state is SourceState.NOT_APPLICABLE for status in missing.statuses))

        with tempfile.TemporaryDirectory() as raw_root:
            root = Path(raw_root)
            (root / "package-lock.json").write_text("{}", encoding="utf-8")

            def unavailable(argv: tuple[str, ...], cwd: Path, timeout: float) -> CommandResult:
                raise FileNotFoundError(argv[0])

            result = collect_inventory(root, runner=unavailable)
        self.assertTrue(any(status.state is SourceState.UNAVAILABLE for status in result.statuses))

        successful = parse_npm_list(load_fixture("npm-list.json"))
        self.assertTrue(any(status.state is SourceState.OK for status in successful.statuses))

    def test_runner_timeout_and_shell_safety_are_explicit(self) -> None:
        class FakeProcess:
            stdout = io.BytesIO(b"{}")
            stderr = io.BytesIO(b"")
            returncode = 0

            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def terminate(self) -> None:
                self.returncode = -15

            def kill(self) -> None:
                self.returncode = -9

        with patch("dependency_audit.inventory.subprocess.Popen", return_value=FakeProcess()) as native:
            result = run_command(("safe", "argument;still-data"), Path("."), timeout=1.0)
        self.assertEqual(result.argv, ("safe", "argument;still-data"))
        self.assertFalse(native.call_args.kwargs["shell"])
        self.assertEqual(native.call_args.kwargs["stdout"], subprocess.PIPE)

        result = run_command((sys.executable, "-c", "import time; time.sleep(2)"), Path("."), timeout=0.01)
        self.assertEqual(result.returncode, 124)

    def test_runner_terminates_flooding_command_at_output_limit(self) -> None:
        result = run_command(
            (sys.executable, "-c", "import sys; sys.stdout.write('x' * 1100000)"),
            Path("."),
            timeout=2.0,
        )

        self.assertEqual(result.returncode, 125)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 1_000_000)
        self.assertIn("output exceeded", result.stderr)


if __name__ == "__main__":
    unittest.main()
