"""Collect exact resolved dependency evidence without treating ambiguity as safety.

The adapters in this module translate package-manager and CycloneDX JSON into the
shared evidence models.  They intentionally leave unsupported scope and graph data
unknown or incomplete: a fabricated development-only classification or exact
version could weaken a delivery gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
from threading import Event, Lock, Thread
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote

from .models import DependencyScope, InventoryResult, PackageRef, SourceState, SourceStatus


DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
_OUTPUT_LIMIT = 1_000_000
_NON_EXACT_VERSION_CHARS = frozenset("<>=~^*|,")
_SEMVER_EXACT = re.compile(r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
_GO_VERSION_EXACT = re.compile(r"^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$")
_SUPPORTED_CYCLONEDX_VERSIONS = frozenset({"1.4", "1.5", "1.6", "1.7"})
_SCOPE_PRECEDENCE = {
    DependencyScope.UNKNOWN: 0,
    DependencyScope.DEVELOPMENT: 1,
    DependencyScope.RUNTIME: 2,
}
_UNKNOWN_REFERENCE = object()


@dataclass(frozen=True)
class CommandResult:
    """Capture a bounded native-command attempt without exposing shell execution.

    The caller receives only the argument vector and bounded diagnostic text so
    adapters can report unavailable or partial evidence without interpreting a
    command failure as an empty dependency graph.
    """

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[tuple[str, ...], Path, float], CommandResult]


def run_command(argv: Sequence[str], cwd: Path, timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> CommandResult:
    """Run one native adapter command with a timeout and no shell expansion.

    ``argv`` is passed directly to the operating system rather than through a
    shell because project paths and package metadata are untrusted input.  The
    timeout and streaming output cap terminate an overproducing adapter before it
    can stall the audit or place unbounded diagnostics in durable evidence.

    Raises:
        ValueError: If the command is empty or the timeout is not positive.
        FileNotFoundError: If the selected executable is not installed.
    """
    command = tuple(str(part) for part in argv)
    if not command:
        raise ValueError("native command must contain an executable")
    if timeout <= 0:
        raise ValueError("native command timeout must be positive")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        shell=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr, exceeded, readers = _capture_command_output(process)
    deadline = time.monotonic() + timeout
    timed_out = False
    while process.poll() is None and not exceeded.is_set():
        if time.monotonic() >= deadline:
            timed_out = True
            _stop_process(process)
            break
        time.sleep(0.005)
    if process.poll() is None:
        try:
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    for reader in readers:
        reader.join()
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()
    if exceeded.is_set():
        return CommandResult(command, 125, _decode_output(stdout), "native command output exceeded the configured limit")
    if timed_out:
        diagnostic = _decode_output(stderr).strip() or "command timed out"
        return CommandResult(command, 124, _decode_output(stdout), diagnostic)
    return CommandResult(command, process.returncode, _decode_output(stdout), _decode_output(stderr))


def parse_npm_list(payload: object) -> InventoryResult:
    """Parse ``npm ls --all --json`` output into an exact dependency graph.

    ``dev: false`` and ``dev: true`` are preserved as runtime and development
    scope respectively.  Missing npm scope metadata remains unknown, because a
    missing field cannot prove that a package is development-only.
    """
    if not isinstance(payload, Mapping):
        return _invalid_result("npm-list", "npm list response must be an object")

    packages: list[PackageRef] = []
    edges: list[tuple[str, str]] = []
    reasons: list[str] = []
    visited: set[tuple[str, str]] = set()

    def visit(name: str, node: object, parent: str | None, direct: bool) -> None:
        if not isinstance(node, Mapping):
            reasons.append(f"npm package {name!r} is not an object")
            return
        package_name = str(node.get("name") or name)
        version = node.get("version")
        if not _is_exact_version(version, "npm"):
            reasons.append(f"npm package {package_name!r} has no exact version")
            return
        version_text = str(version)
        purl = _purl("npm", package_name, version_text)
        scope = _npm_scope(node)
        packages.append(PackageRef("npm", package_name, version_text, purl, direct, scope))
        if parent:
            edges.append((parent, purl))
        key = (purl, parent or "")
        if key in visited:
            return
        visited.add(key)
        children = node.get("dependencies", {})
        if not isinstance(children, Mapping):
            reasons.append(f"npm dependencies for {package_name!r} are not an object")
            return
        for child_name, child in children.items():
            visit(str(child_name), child, purl, False)

    dependencies = payload.get("dependencies", {})
    if not isinstance(dependencies, Mapping):
        reasons.append("npm root dependencies are not an object")
    else:
        for name, node in dependencies.items():
            visit(str(name), node, None, True)
    return _build_result("npm-list", packages, edges, reasons)


def parse_pip_inspect(payload: object) -> InventoryResult:
    """Parse ``pip inspect --local`` data while retaining its unknown scope.

    Pip exposes installed exact versions and requested roots but neither a
    dependable runtime/development classification nor evaluated graph edges.
    Declared requirement strings can carry markers and extras, so they make this
    result incomplete rather than being converted into fabricated edges.
    """
    if not isinstance(payload, Mapping) or not isinstance(payload.get("installed"), list):
        return _invalid_result("pip-inspect", "pip inspect response lacks installed packages")
    packages: list[PackageRef] = []
    reasons: list[str] = []
    for item in payload["installed"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("metadata"), Mapping):
            reasons.append("pip installed entry lacks metadata")
            continue
        metadata = item["metadata"]
        name = metadata.get("name")
        version = metadata.get("version")
        if not isinstance(name, str) or not _is_exact_version(version, "pypi"):
            reasons.append("pip package lacks name or exact version")
            continue
        normalized = _python_name(name)
        version_text = str(version)
        packages.append(PackageRef("PyPI", name, version_text, _purl("pypi", normalized, version_text), bool(item.get("requested")), DependencyScope.UNKNOWN))
        raw_requirements = metadata.get("requires_dist", [])
        if isinstance(raw_requirements, list) and raw_requirements:
            reasons.append("pip inspect declares requirements but does not provide resolved dependency edges")
        elif raw_requirements not in (None, []):
            reasons.append("pip package requirements are not a list")
    return _build_result("pip-inspect", packages, [], reasons)


def parse_cargo_metadata(payload: object) -> InventoryResult:
    """Parse Cargo metadata and retain root dependency kind where it is known.

    Cargo's resolved graph supplies exact transitive packages.  Directness and
    scope come from root ``deps[].pkg`` identifiers and ``dep_kinds`` rather
    than names, so duplicate crate names cannot silently share a classification.
    Runtime wins when one exact package is reachable through both kinds.
    """
    if not isinstance(payload, Mapping) or not isinstance(payload.get("packages"), list):
        return _invalid_result("cargo-metadata", "cargo metadata response lacks packages")
    resolve = payload.get("resolve")
    if not isinstance(resolve, Mapping):
        return _invalid_result("cargo-metadata", "cargo metadata response lacks resolved graph")
    reasons: list[str] = []
    root_id = resolve.get("root")
    package_records: dict[str, Mapping[str, object]] = {}
    for item in payload["packages"]:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            reasons.append("cargo package lacks a stable package id")
            continue
        package_id = item["id"]
        if package_id in package_records:
            reasons.append(f"cargo package id {package_id!r} is ambiguous")
            continue
        package_records[package_id] = item
    if not isinstance(root_id, str) or root_id not in package_records:
        reasons.append("cargo resolve root does not identify a package")
    nodes = resolve.get("nodes")
    node_records: dict[str, Mapping[str, object]] = {}
    if not isinstance(nodes, list):
        reasons.append("cargo resolved nodes are not a list")
    else:
        for node in nodes:
            if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
                reasons.append("cargo resolved node lacks an id")
                continue
            node_id = node["id"]
            if node_id not in package_records:
                reasons.append(f"cargo resolved node references unknown package {node_id!r}")
                continue
            if node_id in node_records:
                reasons.append(f"cargo resolved node id {node_id!r} is ambiguous")
                continue
            node_records[node_id] = node
    root_node = node_records.get(root_id) if isinstance(root_id, str) else None
    if root_node is None:
        reasons.append("cargo resolve root has no resolved node")
    direct_scopes, direct_reasons = _cargo_direct_scopes(root_node, set(package_records))
    reasons.extend(direct_reasons)
    packages: list[PackageRef] = []
    id_to_purl: dict[str, str] = {}
    purl_ids: dict[str, str] = {}
    for package_id, item in package_records.items():
        if package_id == root_id:
            continue
        name = item.get("name")
        version = item.get("version")
        if not isinstance(name, str) or not _is_exact_version(version, "cargo"):
            reasons.append(f"cargo package {package_id!r} lacks name or exact version")
            continue
        version_text = str(version)
        scope = direct_scopes.get(package_id, DependencyScope.UNKNOWN)
        purl = _purl("cargo", name, version_text)
        if purl in purl_ids and purl_ids[purl] != package_id:
            reasons.append(f"cargo package ids {purl_ids[purl]!r} and {package_id!r} collapse to one package URL")
        purl_ids[purl] = package_id
        id_to_purl[package_id] = purl
        packages.append(PackageRef("crates.io", name, version_text, purl, package_id in direct_scopes, scope))
    edges: list[tuple[str, str]] = []
    for parent_id, node in node_records.items():
        child_ids = node.get("dependencies", [])
        if not isinstance(child_ids, list):
            reasons.append(f"cargo dependencies for {parent_id!r} are not a list")
            continue
        for child_id in child_ids:
            if not isinstance(child_id, str) or child_id not in package_records:
                reasons.append(f"cargo graph references unresolved package {child_id!r}")
                continue
            if parent_id in id_to_purl and child_id in id_to_purl:
                edges.append((id_to_purl[parent_id], id_to_purl[child_id]))
    return _build_result("cargo-metadata", packages, edges, reasons)


def parse_go_list(payload: str | object, graph: str | None = None) -> InventoryResult:
    """Parse line-delimited ``go list -m -json all`` module evidence.

    Go's module listing identifies exact modules, while ``go mod graph`` provides
    the edges between them.  A remote ``Replace`` emits its effective path and
    version but retains the original graph reference; local or ambiguous replaces
    are incomplete.  Both sources are required for a complete graph, and scope
    remains unknown because Go module metadata does not encode it.
    """
    if not isinstance(payload, str):
        return _invalid_result("go-list", "go list response must be JSON text")
    try:
        records = _decode_json_stream(payload)
    except json.JSONDecodeError as error:
        return _invalid_result("go-list", f"go list response is invalid JSON: {error.msg}")
    packages: list[PackageRef] = []
    references: dict[str, str | None] = {}
    reasons: list[str] = []
    for record in records:
        if not isinstance(record, Mapping):
            reasons.append("go module record is not an object")
            continue
        if record.get("Main") is True:
            if isinstance(record.get("Path"), str):
                references[record["Path"]] = None
            continue
        name = record.get("Path")
        version = record.get("Version")
        if not isinstance(name, str) or not _is_exact_version(version, "golang"):
            reasons.append("go module lacks path or exact version")
            continue
        effective_name = name
        effective_version = str(version)
        replacement = record.get("Replace")
        if replacement is not None:
            if not isinstance(replacement, Mapping):
                reasons.append(f"go module {name!r} has an ambiguous replacement")
                continue
            replacement_name = replacement.get("Path")
            replacement_version = replacement.get("Version")
            if (
                not isinstance(replacement_name, str)
                or _is_local_go_path(replacement_name)
                or not _is_exact_version(replacement_version, "golang")
                or replacement.get("Replace") is not None
            ):
                reasons.append(f"go module {name!r} has a non-exact or local replacement")
                continue
            effective_name = replacement_name
            effective_version = str(replacement_version)
        purl = _purl("golang", effective_name, effective_version)
        reference = f"{name}@{version}"
        if reference in references:
            reasons.append(f"go module reference {reference!r} is ambiguous")
        references[reference] = purl
        packages.append(PackageRef("Go", effective_name, effective_version, purl, not bool(record.get("Indirect")), DependencyScope.UNKNOWN))
    edges: list[tuple[str, str]] = []
    if graph is None:
        reasons.append("go module graph evidence is missing")
    else:
        graph_nodes: set[str] = set()
        for line in graph.splitlines():
            parts = line.split()
            if len(parts) != 2:
                reasons.append("go module graph contains an invalid edge")
                continue
            source_ref, target_ref = parts
            source = references.get(source_ref, _UNKNOWN_REFERENCE)
            target = references.get(target_ref, _UNKNOWN_REFERENCE)
            if source is _UNKNOWN_REFERENCE or target is _UNKNOWN_REFERENCE:
                reasons.append(f"go module graph references an unknown module: {line!r}")
                continue
            graph_nodes.update((source_ref, target_ref))
            if source is not None and target is not None:
                edges.append((source, target))
        for reference, purl in references.items():
            if purl is not None and reference not in graph_nodes:
                reasons.append(f"go module {reference!r} is absent from the resolved graph")
    return _build_result("go-list", packages, edges, reasons)


def parse_cyclonedx(payload: object) -> InventoryResult:
    """Parse the documented CycloneDX component and dependency JSON subset.

    Components require name, exact version, package URL, and a stable graph
    reference.  Missing versions or dependency references are incomplete because
    an SBOM with an unresolved node cannot reproduce advisory matching.
    """
    if not isinstance(payload, Mapping):
        return _invalid_result("cyclonedx", "CycloneDX response is not an object")
    if payload.get("bomFormat") != "CycloneDX":
        return _invalid_result("cyclonedx", "CycloneDX response lacks bomFormat=CycloneDX")
    if payload.get("specVersion") not in _SUPPORTED_CYCLONEDX_VERSIONS:
        return _invalid_result("cyclonedx", "CycloneDX response has an unsupported specVersion")
    if not isinstance(payload.get("components"), list):
        return _invalid_result("cyclonedx", "CycloneDX response lacks components")
    packages: list[PackageRef] = []
    refs: dict[str, str] = {}
    reasons: list[str] = []
    raw_components = payload["components"]
    for component in raw_components:
        if not isinstance(component, Mapping):
            reasons.append("CycloneDX component is not an object")
            continue
        name = component.get("name")
        version = component.get("version")
        purl = component.get("purl")
        bom_ref = component.get("bom-ref")
        if (
            not isinstance(name, str)
            or not _is_exact_version(version, _purl_type(purl) if isinstance(purl, str) else None)
            or not isinstance(purl, str)
            or _purl_type(purl) is None
            or not _purl_version_matches(purl, str(version))
        ):
            reasons.append("CycloneDX component lacks name, exact version, or matching versioned package URL")
            continue
        if not isinstance(bom_ref, str) or not bom_ref:
            reasons.append(f"CycloneDX component {name!r} lacks bom-ref")
            continue
        ecosystem = _purl_type(purl) or "unknown"
        scope = DependencyScope.RUNTIME if component.get("scope") == "required" else DependencyScope.UNKNOWN
        packages.append(PackageRef(ecosystem, name, str(version), purl, False, scope, bom_ref))
        if bom_ref in refs:
            reasons.append(f"CycloneDX bom-ref {bom_ref!r} is ambiguous")
        refs[bom_ref] = purl
    metadata = payload.get("metadata")
    metadata_component = metadata.get("component") if isinstance(metadata, Mapping) else None
    root_ref = metadata_component.get("bom-ref") if isinstance(metadata_component, Mapping) else None
    if root_ref is not None and (not isinstance(root_ref, str) or not root_ref):
        reasons.append("CycloneDX metadata component has an invalid bom-ref")
        root_ref = None
    if root_ref in refs:
        reasons.append(f"CycloneDX bom-ref {root_ref!r} is ambiguous")

    edges: list[tuple[str, str]] = []
    graph_sources: set[str] = set()
    root_targets: set[str] = set()
    dependencies = payload.get("dependencies", [])
    if not isinstance(dependencies, list):
        reasons.append("CycloneDX dependencies are not a list")
    else:
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                reasons.append("CycloneDX dependency is not an object")
                continue
            source = dependency.get("ref")
            targets = dependency.get("dependsOn", [])
            if not isinstance(source, str) or (source not in refs and source != root_ref):
                reasons.append("CycloneDX dependency references an unknown source")
                continue
            if source in graph_sources:
                reasons.append(f"CycloneDX dependency source {source!r} is ambiguous")
            graph_sources.add(source)
            if not isinstance(targets, list):
                reasons.append(f"CycloneDX dependency targets for {source!r} are not a list")
                continue
            for target in targets:
                if not isinstance(target, str) or target not in refs:
                    reasons.append(f"CycloneDX dependency references an unknown target {target!r}")
                    continue
                if source == root_ref:
                    root_targets.add(refs[target])
                else:
                    edges.append((refs[source], refs[target]))
    expected_sources = set(refs)
    if root_ref is not None:
        expected_sources.add(root_ref)
    for missing in sorted(expected_sources - graph_sources):
        reasons.append(f"CycloneDX dependency graph omits bom-ref {missing!r}")
    result = _build_result("cyclonedx", packages, edges, reasons)
    inbound = {target for _, target in result.dependencies}
    inferred_direct = root_targets if root_ref is not None else {
        package.purl for package in result.packages if package.purl not in inbound
    }
    result.packages = [
        PackageRef(package.ecosystem, package.name, package.version, package.purl,
                   package.purl in inferred_direct, package.scope, package.bom_ref)
        for package in result.packages
    ]
    result.fingerprint = fingerprint_inventory(result.packages, result.dependencies)
    return result


def fingerprint_inventory(packages: Iterable[PackageRef], dependencies: Iterable[tuple[str, str]]) -> str:
    """Return a SHA-256 fingerprint of canonical package, scope, and graph facts.

    The encoding includes directness because it is part of the resolved inventory
    identity.  Sorting makes equivalent evidence produce the same digest despite
    package-manager ordering, while scope and edges prevent a weaker graph from
    sharing a fingerprint with a runtime graph.
    """
    package_rows = {
        (package.purl, package.ecosystem, package.name, package.version, package.direct, package.scope.value)
        for package in packages
    }
    edge_rows = {(source, target) for source, target in dependencies}
    canonical = {
        "packages": [list(row) for row in sorted(package_rows)],
        "dependencies": [list(row) for row in sorted(edge_rows)],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collect_inventory(
    root: Path,
    sbom_path: Path | None = None,
    runner: CommandRunner = run_command,
) -> InventoryResult:
    """Collect supported exact inventory evidence from a project root and optional SBOM.

    Each recognized source records an explicit status.  A missing executable is
    unavailable, a failed command or malformed response is partial, and an
    unrecognized ecosystem is not applicable.  The result is complete only when
    all selected resolved evidence is exact and internally consistent.  Python
    inspection requires a project-local virtual environment, and Go requires
    both its module listing and graph, so ambient tooling cannot become a clean
    project snapshot by accident.
    """
    root = Path(root)
    results: list[InventoryResult] = []
    statuses: list[SourceStatus] = []
    reasons: list[str] = []
    if sbom_path is not None:
        try:
            payload = json.loads(Path(sbom_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            statuses.append(SourceStatus("cyclonedx", SourceState.PARTIAL, diagnostic=f"unable to read SBOM: {error}"))
            reasons.append("CycloneDX SBOM could not be parsed")
        else:
            results.append(parse_cyclonedx(payload))
    adapters = _detected_adapters(root)
    has_go_modules = (root / "go.mod").exists()
    if _has_python_evidence(root) and _project_python(root) is None:
        statuses.append(SourceStatus("pip-inspect", SourceState.PARTIAL, diagnostic="no project-bound Python environment found"))
        reasons.append("pip inspect cannot prove this project's resolved environment")
    if not adapters and not has_go_modules and sbom_path is None:
        statuses.append(SourceStatus("native-adapters", SourceState.NOT_APPLICABLE, diagnostic="no supported resolved evidence found"))
        reasons.append("no supported resolved dependency evidence found")
    for source, argv, parser in adapters:
        try:
            output = runner(argv, root, DEFAULT_COMMAND_TIMEOUT_SECONDS)
        except FileNotFoundError:
            statuses.append(SourceStatus(source, SourceState.UNAVAILABLE, diagnostic="native executable not found"))
            reasons.append(f"{source} native command is unavailable")
            continue
        except (OSError, ValueError) as error:
            statuses.append(SourceStatus(source, SourceState.PARTIAL, diagnostic=f"native command failed: {error}"))
            reasons.append(f"{source} native command failed")
            continue
        if output.returncode != 0:
            statuses.append(SourceStatus(source, SourceState.PARTIAL, diagnostic=_diagnostic(output.stderr, output.returncode)))
            reasons.append(f"{source} native command failed")
            continue
        try:
            payload = output.stdout if source == "go-list" else json.loads(output.stdout)
        except json.JSONDecodeError as error:
            statuses.append(SourceStatus(source, SourceState.PARTIAL, diagnostic=f"invalid JSON: {error.msg}"))
            reasons.append(f"{source} native command returned invalid JSON")
            continue
        results.append(parser(payload))
    if has_go_modules:
        go_output: dict[str, str] = {}
        for source, argv in (
            ("go-list", ("go", "list", "-m", "-json", "all")),
            ("go-graph", ("go", "mod", "graph")),
        ):
            try:
                output = runner(argv, root, DEFAULT_COMMAND_TIMEOUT_SECONDS)
            except FileNotFoundError:
                statuses.append(SourceStatus(source, SourceState.UNAVAILABLE, diagnostic="native executable not found"))
                reasons.append(f"{source} native command is unavailable")
                continue
            except (OSError, ValueError) as error:
                statuses.append(SourceStatus(source, SourceState.PARTIAL, diagnostic=f"native command failed: {error}"))
                reasons.append(f"{source} native command failed")
                continue
            if output.returncode != 0:
                statuses.append(SourceStatus(source, SourceState.PARTIAL, diagnostic=_diagnostic(output.stderr, output.returncode)))
                reasons.append(f"{source} native command failed")
                continue
            go_output[source] = output.stdout
        if "go-list" in go_output:
            go_result = parse_go_list(go_output["go-list"], go_output.get("go-graph"))
            if "go-graph" in go_output:
                go_result.statuses.append(SourceStatus("go-graph", SourceState.OK if go_result.complete else SourceState.PARTIAL))
            results.append(go_result)
    for result in results:
        statuses.extend(result.statuses)
        reasons.extend(result.incomplete_reasons)
    packages = [package for result in results for package in result.packages]
    edges = [edge for result in results for edge in result.dependencies]
    combined = _build_result("inventory", packages, edges, reasons, statuses)
    if not results:
        combined.complete = False
    return combined


def _detected_adapters(root: Path) -> list[tuple[str, tuple[str, ...], Callable[[object], InventoryResult]]]:
    """Select evidence commands only for package-manager files present at ``root``."""
    adapters: list[tuple[str, tuple[str, ...], Callable[[object], InventoryResult]]] = []
    if any((root / name).exists() for name in ("package-lock.json", "npm-shrinkwrap.json")):
        adapters.append(("npm-list", ("npm", "ls", "--all", "--json"), parse_npm_list))
    project_python = _project_python(root)
    if project_python is not None and _has_python_evidence(root):
        adapters.append(("pip-inspect", (str(project_python), "-m", "pip", "inspect", "--local"), parse_pip_inspect))
    if any((root / name).exists() for name in ("Cargo.toml", "Cargo.lock")):
        adapters.append(("cargo-metadata", ("cargo", "metadata", "--format-version", "1"), parse_cargo_metadata))
    return adapters


def _build_result(
    source: str,
    packages: Iterable[PackageRef],
    dependencies: Iterable[tuple[str, str]],
    reasons: Iterable[str] = (),
    statuses: Iterable[SourceStatus] = (),
) -> InventoryResult:
    deduplicated: dict[str, PackageRef] = {}
    for package in packages:
        existing = deduplicated.get(package.purl)
        if existing is None:
            deduplicated[package.purl] = package
            continue
        deduplicated[package.purl] = _merge_package(existing, package)
    known_purls = set(deduplicated)
    edges = sorted(set(dependencies))
    all_reasons = list(reasons)
    for source_purl, target_purl in edges:
        if source_purl not in known_purls or target_purl not in known_purls:
            all_reasons.append(f"dependency edge references an unknown package: {source_purl!r} -> {target_purl!r}")
    complete = not all_reasons
    all_statuses = list(statuses)
    all_statuses.append(SourceStatus(source, SourceState.OK if complete else SourceState.PARTIAL))
    result = InventoryResult(
        packages=sorted(deduplicated.values(), key=lambda package: (package.ecosystem, package.name, package.version, package.purl)),
        dependencies=edges,
        complete=complete,
        statuses=all_statuses,
        incomplete_reasons=sorted(set(all_reasons)),
    )
    result.fingerprint = fingerprint_inventory(result.packages, result.dependencies)
    return result


def _merge_package(left: PackageRef, right: PackageRef) -> PackageRef:
    """Merge repeated package URLs without allowing weaker scope or directness."""
    scope = left.scope if _SCOPE_PRECEDENCE[left.scope] >= _SCOPE_PRECEDENCE[right.scope] else right.scope
    return PackageRef(left.ecosystem, left.name, left.version, left.purl, left.direct or right.direct, scope, left.bom_ref or right.bom_ref)


def _invalid_result(source: str, reason: str) -> InventoryResult:
    """Create incomplete evidence with a visible partial source status."""
    return _build_result(source, (), (), (reason,))


def _is_exact_version(value: object, ecosystem: str | None = None) -> bool:
    """Reject constraints, locators, and branch names rather than inventing releases."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    lowered = value.lower()
    locator_prefixes = ("file:", "path:", "git+", "git:", "git://", "http:", "https:", "ssh:", "github:", "bitbucket:", "./", "../", "/")
    if lowered in {"latest", "unknown", "(devel)", "devel", "main", "master", "head", "next", "stable"}:
        return False
    if lowered.startswith(locator_prefixes) or any(char in value for char in _NON_EXACT_VERSION_CHARS):
        return False
    if any(char.isspace() for char in value) or any(char in value for char in "/:@#\\"):
        return False
    if not re.match(r"^[vV]?\d[0-9A-Za-z.!+_-]*$", value):
        return False
    normalized_ecosystem = (ecosystem or "").lower()
    if normalized_ecosystem in {"npm", "cargo"}:
        return bool(_SEMVER_EXACT.fullmatch(value))
    if normalized_ecosystem in {"golang", "go"}:
        return bool(_GO_VERSION_EXACT.fullmatch(value))
    return True


def _purl(package_type: str, name: str, version: str) -> str:
    """Create a deterministic versioned package URL from already-exact evidence."""
    return f"pkg:{package_type}/{quote(name, safe='/-._~')}@{quote(version, safe='-._~+')}"


def _npm_scope(node: Mapping[str, object]) -> DependencyScope:
    """Map only explicit npm scope flags; absence stays unknown by design."""
    if node.get("dev") is True:
        return DependencyScope.DEVELOPMENT
    if node.get("dev") is False:
        return DependencyScope.RUNTIME
    return DependencyScope.UNKNOWN


def _python_name(name: str) -> str:
    """Normalize the spelling Python packaging uses for dependency matching."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _cargo_direct_scopes(
    root: Mapping[str, object] | None,
    package_ids: set[str],
) -> tuple[dict[str, DependencyScope], list[str]]:
    """Derive root directness by Cargo package ID, never by ambiguous names."""
    if root is None or not isinstance(root.get("deps"), list):
        return {}, ["cargo root node lacks package-id dependency metadata"]
    scopes: dict[str, DependencyScope] = {}
    reasons: list[str] = []
    for dependency in root["deps"]:
        if not isinstance(dependency, Mapping) or not isinstance(dependency.get("pkg"), str):
            reasons.append("cargo root dependency lacks a package id")
            continue
        package_id = dependency["pkg"]
        if package_id not in package_ids:
            reasons.append(f"cargo root dependency references unknown package {package_id!r}")
            continue
        dep_kinds = dependency.get("dep_kinds")
        if not isinstance(dep_kinds, list) or not dep_kinds:
            reasons.append(f"cargo root dependency {package_id!r} lacks dependency kind metadata")
            scopes.setdefault(package_id, DependencyScope.UNKNOWN)
            continue
        scope = DependencyScope.UNKNOWN
        for dep_kind in dep_kinds:
            if not isinstance(dep_kind, Mapping):
                reasons.append(f"cargo dependency kind for {package_id!r} is invalid")
                continue
            candidate = DependencyScope.DEVELOPMENT if dep_kind.get("kind") in {"dev", "build"} else DependencyScope.RUNTIME if dep_kind.get("kind") is None else DependencyScope.UNKNOWN
            if _SCOPE_PRECEDENCE[candidate] > _SCOPE_PRECEDENCE[scope]:
                scope = candidate
        previous = scopes.get(package_id)
        if previous is None or _SCOPE_PRECEDENCE[scope] > _SCOPE_PRECEDENCE[previous]:
            scopes[package_id] = scope
    return scopes, reasons


def _has_python_evidence(root: Path) -> bool:
    """Identify project files that need Python resolution without trusting ambient Python."""
    return any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "requirements.lock", "Pipfile.lock"))


def _project_python(root: Path) -> Path | None:
    """Return a project-local interpreter, the minimum binding for pip inspection."""
    candidates = (
        root / ".venv" / "bin" / "python",
        root / "venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        root / "venv" / "Scripts" / "python.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _decode_json_stream(payload: str) -> list[object]:
    """Decode consecutive JSON objects emitted by Go without line-length assumptions."""
    decoder = json.JSONDecoder()
    records: list[object] = []
    position = 0
    while position < len(payload):
        while position < len(payload) and payload[position].isspace():
            position += 1
        if position == len(payload):
            break
        record, position = decoder.raw_decode(payload, position)
        records.append(record)
    return records


def _purl_type(purl: str) -> str | None:
    """Return a CycloneDX package URL type without attempting full purl validation."""
    match = re.match(r"^pkg:([^/]+)/", purl)
    return match.group(1) if match else None


def _is_local_go_path(path: str) -> bool:
    """Recognize replacement paths that identify local source instead of a release."""
    return path.startswith(("./", "../", "/", "file:")) or path in {".", ".."}


def _purl_version_matches(purl: str, version: str) -> bool:
    """Require CycloneDX package URLs to identify the same exact component version."""
    if "@" not in purl:
        return False
    encoded_version = purl.rsplit("@", 1)[1].split("?", 1)[0].split("#", 1)[0]
    return _is_exact_version(encoded_version, _purl_type(purl)) and encoded_version == quote(version, safe="-._~+")


def _diagnostic(stderr: str, returncode: int) -> str:
    """Keep command diagnostics concise so failure evidence remains reviewable."""
    detail = stderr.strip().replace("\n", " ")[:500]
    return detail or f"native command exited with status {returncode}"


def _capture_command_output(
    process: subprocess.Popen[bytes],
) -> tuple[bytearray, bytearray, Event, tuple[Thread, Thread]]:
    """Start capped stream readers that stop a child before output becomes unbounded."""
    stdout = bytearray()
    stderr = bytearray()
    exceeded = Event()
    lock = Lock()

    def read_stream(stream: Any, captured: bytearray) -> None:
        while True:
            chunk = stream.read(65_536)
            if not chunk:
                return
            with lock:
                remaining = _OUTPUT_LIMIT - len(captured)
                captured.extend(chunk[:max(remaining, 0)])
                overflow = len(chunk) > remaining
            if overflow:
                exceeded.set()
                _stop_process(process)
                return

    if process.stdout is None or process.stderr is None:
        raise RuntimeError("native command pipes were not created")
    readers = (
        Thread(target=read_stream, args=(process.stdout, stdout), daemon=True),
        Thread(target=read_stream, args=(process.stderr, stderr), daemon=True),
    )
    for reader in readers:
        reader.start()
    return stdout, stderr, exceeded, readers


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate a bounded adapter command, tolerating an already-exited child."""
    try:
        process.terminate()
    except ProcessLookupError:
        pass


def _decode_output(value: bytearray) -> str:
    """Decode already-capped command bytes without letting diagnostics raise errors."""
    return bytes(value).decode(errors="replace")
