#!/usr/bin/env python3
"""Run a complete dependency-security audit with stable automation semantics.

The command accepts project and evidence paths, never credential values. Optional credential
arguments name environment variables, keeping secrets out of process listings and shell history.
Human output is concise text; JSON output is a summary whose status and exit code match the full
versioned reports. Exit ``0`` means pass or warnings, ``1`` blocked findings, ``2`` unavailable or
incomplete required evidence, and ``3`` invalid invocation. Reports default to
``ROOT/.security/dependency-audit``; main and release modes additionally retain immutable evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import fields
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Mapping, Sequence, TextIO
import unicodedata
from urllib.parse import urlsplit

from dependency_audit.http import (
    HttpResponse, HttpTransport, RetryingHttpClient, StdlibHttpTransport, redact_diagnostic,
)
from dependency_audit.inventory import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS, CommandRunner, run_command,
)
from dependency_audit.models import (
    Advisory, AffectedPackage,
    AuditMode, AuditResult, Decision, InventoryResult, PackageRef, SourceState, SourceStatus,
)
from dependency_audit.policy import Policy
from dependency_audit.runner import AuditConfig, AuditServices, NativeAuditResult, run_audit
from dependency_audit.sources import GithubClient, KevClient, NvdClient, OsvClient, _cvss_score


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_TIMEOUT_SECONDS = 300.0
_MAX_SOURCE_AGE_SECONDS = 604_800.0
_STABLE_ADVISORY_ID = re.compile(r"[A-Z][A-Z0-9._]*-[A-Z0-9][A-Z0-9._-]*")
_SEVERITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class InvalidInvocation(ValueError):
    """Represent argument or local-configuration failures as stable exit ``3`` evidence."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        """Raise instead of terminating so embedding callers receive the documented exit code."""
        raise InvalidInvocation("arguments do not match the documented command; use --help")


class _CredentialTransport:
    """Add host-scoped credentials obtained from the environment at the transport boundary.

    Host checks prevent one source's credential from being forwarded to another source, while the
    wrapped standard-library transport retains the shared byte and timeout limits.
    """

    def __init__(self, wrapped: HttpTransport, github_token: str = "", nvd_api_key: str = "") -> None:
        self.wrapped = wrapped
        self.github_token = github_token
        self.nvd_api_key = nvd_api_key

    def request(self, method: str, url: str, headers: Mapping[str, str], body: bytes | None,
                connect_timeout: float, read_timeout: float, max_bytes: int) -> HttpResponse:
        """Forward one bounded request with only the credential allowed for its exact host."""
        scoped = dict(headers)
        host = (urlsplit(url).hostname or "").lower()
        if host == "api.github.com" and self.github_token:
            scoped["Authorization"] = f"Bearer {self.github_token}"
        if host == "services.nvd.nist.gov" and self.nvd_api_key:
            scoped["apiKey"] = self.nvd_api_key
        return self.wrapped.request(
            method, url, scoped, body, connect_timeout, read_timeout, max_bytes,
        )


def build_parser() -> argparse.ArgumentParser:
    """Build the public command grammar and explain its security-sensitive argument contract."""
    parser = _Parser(
        prog="dependency_security_audit.py",
        description="Audit one exact resolved dependency snapshot and write JSON/Markdown evidence.",
        epilog=(
            "stdout contains one human or JSON summary; invalid invocation diagnostics use stderr. "
            "Reports default to ROOT/.security/dependency-audit; main/release retain immutable "
            "timestamped evidence. Exits: 0 pass/warnings, 1 blocked, 2 unavailable/incomplete, "
            "3 invalid. Credential options accept ENVIRONMENT VARIABLE NAMES, never secret values."
        ),
    )
    parser.add_argument("--root", required=True, help="project root directory")
    parser.add_argument("--mode", required=True, choices=tuple(item.value for item in AuditMode))
    parser.add_argument("--sbom", help="optional readable CycloneDX JSON file")
    parser.add_argument("--reachability", help="optional readable reachability JSON file")
    parser.add_argument("--policy", help="optional strict-policy JSON file")
    parser.add_argument("--output", help="report directory; defaults under the project root")
    parser.add_argument("--baseline-fingerprint", help="change-mode comparison fingerprint")
    parser.add_argument("--revision", default="", help="project revision recorded in evidence")
    parser.add_argument("--connect-timeout", type=float, default=5.0, metavar="SECONDS")
    parser.add_argument("--read-timeout", type=float, default=15.0, metavar="SECONDS")
    parser.add_argument("--source-max-age", type=float, default=3600.0, metavar="SECONDS",
                        help="freshness window, positive and at most 604800 seconds")
    parser.add_argument("--github-token-env", metavar="ENV_NAME",
                        help="environment-variable name containing a GitHub token; never the token")
    parser.add_argument("--nvd-api-key-env", metavar="ENV_NAME",
                        help="environment-variable name containing an NVD API key; never the key")
    parser.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    services: AuditServices | None = None,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Validate, run, report, and summarize one audit without accepting secrets on argv.

    Args:
        argv: Arguments after the executable name; omission reads ``sys.argv``.
        services: Optional injected effects for deterministic offline use. Omission creates bounded
            production source clients and the reviewed inventory/report services.
        environ: Environment used to resolve explicitly named credentials.
        stdout: Destination for one human or JSON summary.
        stderr: Destination for sanitized invalid-invocation diagnostics.

    Returns:
        Stable exit ``0`` for pass/warnings, ``1`` for blocked, ``2`` for unavailable/incomplete,
        or ``3`` for invalid input. Full evidence is written before a non-invalid result returns.
    """
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    environment = os.environ if environ is None else environ
    try:
        arguments = build_parser().parse_args(argv)
        settings = _validate(arguments, environment)
    except InvalidInvocation as error:
        print(f"Invalid invocation: {redact_diagnostic(error)}", file=errors)
        return 3

    configured = services or _default_services(
        settings["credentials"], settings["github_token"], settings["nvd_api_key"],
        arguments.connect_timeout, arguments.read_timeout, settings["root"],
    )
    config = AuditConfig(
        root=settings["root"], mode=AuditMode(arguments.mode),
        baseline_fingerprint=arguments.baseline_fingerprint,
        sbom_path=settings["sbom"], reachability_path=settings["reachability"],
        output_dir=settings["output"], project_revision=arguments.revision,
        policy=settings["policy"], source_max_age_seconds=arguments.source_max_age,
        credential_values=settings["credentials"],
    )
    before_reports = _report_snapshot(settings["output"])
    result = run_audit(config, configured)
    current_reports = _current_report_paths(result, settings["output"], before_reports)
    rendered = (_json_summary(result, current_reports, settings["credentials"])
                if arguments.format == "json"
                else _human_summary(result, current_reports, settings["credentials"]))
    print(rendered, end="", file=output)
    return result.exit_code if result.exit_code in {0, 1, 2, 3} else 2


def _validate(arguments: argparse.Namespace, environment: Mapping[str, str]) -> dict[str, object]:
    root = Path(arguments.root).expanduser().resolve()
    if not root.is_dir():
        raise InvalidInvocation("--root must name an existing directory")
    for name in ("connect_timeout", "read_timeout", "source_max_age"):
        value = getattr(arguments, name)
        maximum = _MAX_SOURCE_AGE_SECONDS if name == "source_max_age" else _MAX_TIMEOUT_SECONDS
        if not math.isfinite(value) or value <= 0 or value > maximum:
            raise InvalidInvocation(f"--{name.replace('_', '-')} must be a finite positive bounded number")
    sbom = _optional_file(arguments.sbom, "--sbom")
    reachability = _optional_file(arguments.reachability, "--reachability")
    policy_path = _optional_file(arguments.policy, "--policy")
    output = Path(arguments.output).expanduser().resolve() if arguments.output else (
        root / ".security" / "dependency-audit"
    )
    if output.exists() and not output.is_dir():
        raise InvalidInvocation("--output must name a directory, not a file")
    credentials: list[str] = []
    resolved: dict[str, str] = {}
    for option, key in ((arguments.github_token_env, "github_token"),
                        (arguments.nvd_api_key_env, "nvd_api_key")):
        if option is not None and not _ENV_NAME.fullmatch(option):
            raise InvalidInvocation("credential options accept environment-variable names only")
        value = environment.get(option, "") if option else ""
        resolved[key] = value
        if value:
            credentials.append(value)
    return {
        "root": root, "sbom": sbom, "reachability": reachability,
        "policy": _load_policy(policy_path), "output": output,
        "credentials": tuple(credentials), **resolved,
    }


def _optional_file(value: str | None, option: str) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise InvalidInvocation(f"{option} must name an existing regular file")
    try:
        if path.stat().st_mode & 0o444 == 0:
            raise PermissionError("file mode has no read bit")
        with path.open("rb") as handle:
            handle.read(1)
    except OSError as error:
        raise InvalidInvocation(f"{option} must be readable") from error
    return path


def _load_policy(path: Path | None) -> Policy:
    if path is None:
        return Policy()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InvalidInvocation(f"--policy is not valid readable JSON: {error}") from error
    allowed = {item.name for item in fields(Policy)}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise InvalidInvocation("--policy must be an object containing only supported policy fields")
    boolean_fields = allowed - {"block_severities"}
    if any(not isinstance(payload.get(name, False), bool) for name in boolean_fields):
        raise InvalidInvocation("policy promotion fields must be booleans")
    severities = payload.get("block_severities", [])
    if (not isinstance(severities, list) or any(
            not isinstance(value, str) or value.lower() not in {"unknown", "low", "medium", "high", "critical"}
            for value in severities)):
        raise InvalidInvocation("policy block_severities must be a list of normalized severities")
    return Policy(**{**payload, "block_severities": tuple(severities)})


def _default_services(
    credentials: tuple[str, ...], github_token: str, nvd_api_key: str,
    connect_timeout: float, read_timeout: float, root: Path,
    command_runner: CommandRunner = run_command,
) -> AuditServices:
    transport = _CredentialTransport(StdlibHttpTransport(), github_token, nvd_api_key)
    http = RetryingHttpClient(
        transport, connect_timeout=connect_timeout, read_timeout=read_timeout,
        secrets=credentials,
    )
    kev_http = RetryingHttpClient(
        transport, connect_timeout=connect_timeout, read_timeout=read_timeout,
        max_bytes=5_000_000, secrets=credentials,
    )
    return AuditServices(
        osv=OsvClient(http), kev=KevClient(kev_http),
        github=GithubClient(http), nvd=NvdClient(http),
        native_audits=lambda inventory: _run_native_audits(
            inventory, root, command_runner,
        ),
    )


_NATIVE_AUDITS = (
    ("npm-audit", frozenset({"npm"}), ("npm", "audit", "--json"),
     frozenset({0, 1}), frozenset({1})),
    ("cargo-audit", frozenset({"crates.io", "cargo", "rust"}),
     ("cargo", "audit", "--json"), frozenset({0, 1}), frozenset({1})),
    ("govulncheck", frozenset({"go", "golang"}),
     ("govulncheck", "-json", "./..."), frozenset({0}), frozenset()),
    ("pip-audit", frozenset({"pypi", "pip"}),
     ("pip-audit", "--format", "json"), frozenset({0, 1}), frozenset({1})),
)


def _run_native_audits(
    inventory: InventoryResult, root: Path, command_runner: CommandRunner,
) -> NativeAuditResult:
    """Run applicable installed native auditors through the bounded no-shell command adapter.

    Every supported adapter emits a state, including explicit non-applicability. A missing tool or
    undocumented/malformed results cannot become a clean main/release audit. Each adapter's
    documented exit contract is interpreted separately because govulncheck JSON deliberately exits
    zero even when its machine stream contains findings.
    """
    ecosystems = {
        package.ecosystem.casefold() for package in getattr(inventory, "packages", ())
    }
    statuses: list[SourceStatus] = []
    advisories: list[Advisory] = []
    for source, supported, argv, documented_exits, findings_exits in _NATIVE_AUDITS:
        if not ecosystems.intersection(supported):
            statuses.append(SourceStatus(source, SourceState.NOT_APPLICABLE,
                                         diagnostic="ecosystem not present"))
            continue
        try:
            result = command_runner(argv, root, DEFAULT_COMMAND_TIMEOUT_SECONDS)
        except FileNotFoundError:
            statuses.append(SourceStatus(source, SourceState.UNAVAILABLE,
                                         diagnostic="native audit executable not found"))
            continue
        except (OSError, ValueError) as error:
            statuses.append(SourceStatus(source, SourceState.UNAVAILABLE,
                                         diagnostic=f"native audit failed: {error}"))
            continue
        if result.returncode not in documented_exits:
            statuses.append(SourceStatus(
                source, SourceState.UNAVAILABLE,
                diagnostic=(result.stderr.strip() or
                            f"native audit execution failed with exit {result.returncode}")[:400],
            ))
            continue
        parsed, malformed = _parse_native_output(source, result.stdout, inventory.packages)
        advisories.extend(parsed)
        exit_signals_findings = result.returncode in findings_exits
        contradiction = bool(findings_exits) and (exit_signals_findings != bool(parsed))
        state = SourceState.PARTIAL if malformed or contradiction else SourceState.OK
        reasons = []
        if malformed:
            reasons.append("native audit returned malformed or incomplete machine evidence")
        if contradiction:
            reasons.append("native audit exit did not agree with parsed finding presence")
        diagnostic = "; ".join(reasons)
        statuses.append(SourceStatus(source, state, diagnostic=diagnostic))
    unique = {(item.source, item.id, item.affected_packages): item for item in advisories}
    ordered = tuple(unique[key] for key in sorted(unique, key=lambda item: (item[0], item[1], repr(item[2]))))
    return NativeAuditResult(advisories=ordered, statuses=tuple(statuses))


def _parse_native_output(
    source: str, value: str, packages: Sequence[PackageRef],
) -> tuple[list[Advisory], bool]:
    parser = {
        "npm-audit": _parse_npm_audit,
        "cargo-audit": _parse_cargo_audit,
        "govulncheck": _parse_govulncheck,
        "pip-audit": _parse_pip_audit,
    }[source]
    try:
        if source == "govulncheck":
            payload: object = [json.loads(line) for line in value.splitlines() if line.strip()]
        else:
            payload = json.loads(value)
    except (UnicodeError, json.JSONDecodeError):
        return [], True
    try:
        return parser(payload, packages)
    except (KeyError, TypeError, ValueError):
        return [], True


def _parse_npm_audit(payload: object, packages: Sequence[PackageRef]) -> tuple[list[Advisory], bool]:
    if not isinstance(payload, dict) or not isinstance(payload.get("vulnerabilities"), dict):
        return [], True
    advisories: list[Advisory] = []
    malformed = False
    for key, vulnerability in payload["vulnerabilities"].items():
        if not isinstance(vulnerability, dict):
            malformed = True
            continue
        name = vulnerability.get("name", key)
        package = _find_package(packages, {"npm"}, name, None)
        via = vulnerability.get("via", [])
        if package is None or not isinstance(via, list):
            malformed = True
            continue
        fixes = _npm_fixes(vulnerability.get("fixAvailable"))
        emitted = False
        for row in via:
            if not isinstance(row, dict):
                continue
            fallback = f"NPM-{row['source']}" if isinstance(row.get("source"), (str, int)) else ""
            identifiers = _identifiers(row, fallback)
            if not identifiers:
                malformed = True
                continue
            emitted = True
            advisories.append(_native_advisory(
                "npm-audit", package, identifiers,
                _severity(row.get("severity"), vulnerability.get("severity")), fixes,
                details=row.get("title"), references=(row.get("url"),),
            ))
        if not emitted:
            malformed = True
    return advisories, malformed


def _parse_cargo_audit(payload: object, packages: Sequence[PackageRef]) -> tuple[list[Advisory], bool]:
    if not isinstance(payload, dict) or not isinstance(payload.get("vulnerabilities"), dict):
        return [], True
    rows = payload["vulnerabilities"].get("list")
    if not isinstance(rows, list):
        return [], True
    advisories: list[Advisory] = []
    malformed = False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("advisory"), dict) or not isinstance(row.get("package"), dict):
            malformed = True
            continue
        metadata, installed = row["advisory"], row["package"]
        package = _find_package(packages, {"crates.io", "cargo", "rust"},
                                installed.get("name"), installed.get("version"))
        identifiers = _identifiers(metadata)
        versions = row.get("versions", {})
        patched = versions.get("patched", ()) if isinstance(versions, dict) else ()
        fixes, constraints, ambiguous_fixes = _cargo_fixes(patched, package.version) if package else ((), (), True)
        malformed = malformed or not isinstance(versions, dict) or ambiguous_fixes
        if package is None or not identifiers:
            malformed = True
            continue
        cvss = metadata.get("cvss")
        cvss_severity: object = None
        if isinstance(cvss, str):
            try:
                cvss_severity = _cvss_score(cvss)
            except ValueError:
                malformed = True
        description = metadata.get("description") or metadata.get("title")
        constraint_evidence = (f"Cargo patched constraints (OR): {', '.join(constraints)}"
                               if constraints else "")
        details = "\n".join(value for value in (description, constraint_evidence)
                            if isinstance(value, str) and value)
        advisories.append(_native_advisory(
            "cargo-audit", package, identifiers,
            _severity(metadata.get("severity"), cvss_severity), fixes,
            details=details,
            references=(metadata.get("url"), *(metadata.get("references", ())
                                               if isinstance(metadata.get("references"), list) else ())),
        ))
    return advisories, malformed


def _parse_pip_audit(payload: object, packages: Sequence[PackageRef]) -> tuple[list[Advisory], bool]:
    dependencies = payload.get("dependencies") if isinstance(payload, dict) else payload
    if not isinstance(dependencies, list):
        return [], True
    advisories: list[Advisory] = []
    malformed = False
    for dependency in dependencies:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("vulns"), list):
            malformed = True
            continue
        package = _find_package(packages, {"pypi", "pip"}, dependency.get("name"), dependency.get("version"))
        if package is None:
            malformed = True
            continue
        for row in dependency["vulns"]:
            if not isinstance(row, dict):
                malformed = True
                continue
            identifiers = _identifiers(row)
            if not identifiers:
                malformed = True
                continue
            fixes = _version_values(row.get("fix_versions", ()))
            advisories.append(_native_advisory(
                "pip-audit", package, identifiers, _severity(row.get("severity")), fixes,
                details=row.get("description"), references=(row.get("url"),),
            ))
    return advisories, malformed


def _parse_govulncheck(payload: object, packages: Sequence[PackageRef]) -> tuple[list[Advisory], bool]:
    if not isinstance(payload, list) or any(not isinstance(event, dict) for event in payload):
        return [], True
    metadata: dict[str, dict[str, object]] = {}
    findings: list[dict[str, object]] = []
    malformed = False
    for event in payload:
        if isinstance(event.get("osv"), dict) and isinstance(event["osv"].get("id"), str):
            metadata[event["osv"]["id"].strip().upper()] = event["osv"]
        if isinstance(event.get("finding"), dict):
            findings.append(event["finding"])
    advisories: list[Advisory] = []
    for finding in findings:
        identifier = finding.get("osv")
        trace = finding.get("trace")
        if not isinstance(identifier, str) or not isinstance(trace, list):
            malformed = True
            continue
        frame = next((item for item in trace if isinstance(item, dict)
                      and isinstance(item.get("module"), str)
                      and isinstance(item.get("version"), str)), None)
        package = (_find_package(packages, {"go", "golang"}, frame.get("module"), frame.get("version"))
                   if frame else None)
        record = metadata.get(identifier.strip().upper(), {"id": identifier})
        identifiers = _identifiers(record, identifier)
        if package is None or not identifiers:
            malformed = True
            continue
        fixes = _version_values((finding.get("fixed_version"),))
        database = record.get("database_specific")
        severity = database.get("severity") if isinstance(database, dict) else None
        advisories.append(_native_advisory(
            "govulncheck", package, identifiers, _severity(severity), fixes,
            details=record.get("details") or record.get("summary"),
            references=tuple(item.get("url") for item in record.get("references", ())
                             if isinstance(item, dict)) if isinstance(record.get("references"), list) else (),
        ))
    return advisories, malformed


def _find_package(packages: Sequence[PackageRef], ecosystems: set[str],
                  name: object, version: object) -> PackageRef | None:
    if not isinstance(name, str):
        return None
    normalized_name = re.sub(r"[-_.]+", "-", name).casefold()
    matches = []
    for package in packages:
        if package.ecosystem.casefold() not in ecosystems:
            continue
        package_name = (re.sub(r"[-_.]+", "-", package.name).casefold()
                        if package.ecosystem.casefold() in {"pypi", "pip"}
                        else package.name.casefold() if package.ecosystem.casefold() != "go" else package.name)
        candidate = (normalized_name if package.ecosystem.casefold() in {"pypi", "pip"}
                     else name.casefold() if package.ecosystem.casefold() != "go" else name)
        if package_name == candidate and (version is None or str(version) == package.version):
            matches.append(package)
    return matches[0] if len(matches) == 1 else None


def _identifiers(record: Mapping[str, object], fallback: object = "") -> tuple[str, ...]:
    def normalized(value: object) -> str:
        candidate = value.strip().upper() if isinstance(value, str) else ""
        return candidate if _STABLE_ADVISORY_ID.fullmatch(candidate) else ""

    primary = normalized(record.get("id")) or normalized(fallback)
    candidates: list[object] = []
    for key in ("aliases", "cves"):
        value = record.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    for key in ("url", "advisory"):
        value = record.get(key)
        if isinstance(value, str):
            candidates.extend(re.findall(r"[A-Za-z][A-Za-z0-9._]*-[A-Za-z0-9][A-Za-z0-9._-]*", value))
    aliases = sorted({identifier for value in candidates if (identifier := normalized(value))
                      and identifier != primary})
    if not primary and aliases:
        primary, aliases = aliases[0], aliases[1:]
    return (primary, *aliases) if primary else ()


def _severity(*values: object) -> str:
    normalized: list[str] = []
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            score = float(value)
            normalized.append("critical" if score >= 9 else "high" if score >= 7
                              else "medium" if score >= 4 else "low" if score > 0 else "unknown")
        elif isinstance(value, str) and value.strip().casefold() in {*_SEVERITY_RANK, "moderate"}:
            normalized.append("medium" if value.strip().casefold() == "moderate" else value.strip().casefold())
    return max(normalized, key=_SEVERITY_RANK.__getitem__, default="unknown")


def _version_values(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        return ()
    versions: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        match = re.search(r"(?<![A-Za-z0-9])v?\d[0-9A-Za-z.!+_-]*", value.strip())
        if match:
            versions.add(match.group())
    return tuple(sorted(versions))


def _npm_fixes(value: object) -> tuple[str, ...]:
    return _version_values((value.get("version"),)) if isinstance(value, dict) else ()


_CARGO_REQUIREMENT = re.compile(
    r"^(>=|>|<=|<|=|\^|~)?\s*(v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)$"
)


def _cargo_semver(value: str) -> tuple[int, int, int, int, tuple[tuple[int, object], ...]] | None:
    match = re.fullmatch(
        r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z.-]+)?", value.strip(),
    )
    if not match:
        return None
    prerelease: list[tuple[int, object]] = []
    for identifier in (match.group(4) or "").split(".") if match.group(4) else ():
        if identifier.isdigit():
            if len(identifier) > 1 and identifier.startswith("0"):
                return None
            prerelease.append((0, int(identifier)))
        else:
            prerelease.append((1, identifier))
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
            0 if prerelease else 1, tuple(prerelease))


def _cargo_fixes(values: object, installed: str) -> tuple[tuple[str, ...], tuple[str, ...], bool]:
    """Select only proven non-downgrade lower bounds from OR-ed Cargo patched requirements.

    RustSec's ``patched`` entries are independent safe branches, not a pool of version-looking
    tokens. Comparing each branch's inclusive lower bound against the exact installed SemVer avoids
    recommending an older branch; strict or otherwise ambiguous bounds remain evidence only.
    """
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        return (), (), True
    constraints = tuple(value.strip() for value in values if value.strip())
    installed_key = _cargo_semver(installed)
    if installed_key is None:
        return (), constraints, True
    fixes: set[str] = set()
    ambiguous = False
    for branch in constraints:
        terms = [term.strip() for term in branch.split(",") if term.strip()]
        parsed = [_CARGO_REQUIREMENT.fullmatch(term) for term in terms]
        if not terms or any(item is None for item in parsed):
            ambiguous = True
            continue
        lower = [(item.group(1) or "^", item.group(2)) for item in parsed
                 if (item.group(1) or "^") in {">=", "=", "^", "~"}]
        if len(lower) != 1:
            ambiguous = True
            continue
        candidate = lower[0][1]
        candidate_key = _cargo_semver(candidate)
        if candidate_key is None:
            ambiguous = True
            continue
        compatible = True
        for item in parsed:
            operator, bound = item.group(1) or "^", item.group(2)
            bound_key = _cargo_semver(bound)
            if bound_key is None:
                compatible = False
                break
            if operator == ">=" and not candidate_key >= bound_key:
                compatible = False
            elif operator == ">" and not candidate_key > bound_key:
                compatible = False
            elif operator == "<=" and not candidate_key <= bound_key:
                compatible = False
            elif operator == "<" and not candidate_key < bound_key:
                compatible = False
            elif operator in {"=", "^", "~"} and candidate_key < bound_key:
                compatible = False
        if compatible and candidate_key > installed_key:
            fixes.add(candidate)
    return tuple(sorted(fixes, key=lambda value: _cargo_semver(value) or ())), constraints, ambiguous


def _native_advisory(source: str, package: PackageRef, identifiers: tuple[str, ...],
                     severity: str, fixes: tuple[str, ...], *, details: object,
                     references: Sequence[object]) -> Advisory:
    affected = AffectedPackage(
        package.ecosystem, package.name, purl=package.purl,
        versions=(package.version,), ranges=(), fixed_versions=fixes,
    )
    valid_references = tuple(sorted({value for value in references
                                     if isinstance(value, str)
                                     and urlsplit(value).scheme in {"http", "https"}
                                     and urlsplit(value).hostname}))
    return Advisory(
        identifiers[0], aliases=identifiers[1:], severity=severity,
        fixed_versions=fixes, references=valid_references,
        affected_ranges=(),
        details=details if isinstance(details, str) else "", source=source,
        affected_packages=(affected,),
    )


def _report_snapshot(output_dir: Path) -> dict[str, tuple[int, int, int] | None]:
    snapshot: dict[str, tuple[int, int, int] | None] = {}
    for name in ("latest.json", "latest.md"):
        try:
            stat = (output_dir / name).stat()
        except OSError:
            snapshot[name] = None
        else:
            snapshot[name] = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    return snapshot


def _current_report_paths(
    result: AuditResult, output_dir: Path,
    before: Mapping[str, tuple[int, int, int] | None],
) -> dict[str, Path | None]:
    if any(item.source == "reporting" and item.state is SourceState.UNAVAILABLE
           for item in result.sources):
        return {"json": None, "markdown": None}
    current: dict[str, Path | None] = {}
    for key, name in (("json", "latest.json"), ("markdown", "latest.md")):
        path = output_dir / name
        try:
            stat = path.stat()
            fingerprint = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except OSError:
            current[key] = None
        else:
            current[key] = path if fingerprint != before.get(name) else None
    if not all(current.values()):
        return {"json": None, "markdown": None}
    return current


def _summary_payload(
    result: AuditResult, report_paths: Mapping[str, Path | None], credentials: tuple[str, ...],
) -> dict[str, object]:
    sources = [*result.inventory.statuses, *result.sources]
    return {
        "status": result.gate_status.value,
        "exit_code": result.exit_code,
        "mode": result.mode.value,
        "inventory_complete": result.inventory.complete,
        "inventory_fingerprint": _safe_text(result.inventory.fingerprint, credentials),
        "findings": len(result.findings),
        "blocked": sum(item.decision is Decision.BLOCK for item in result.decisions),
        "warnings": sum(item.decision is Decision.WARN for item in result.decisions),
        "sources": [{
            "source": _safe_text(item.source, credentials), "state": item.state.value,
            "diagnostic": _safe_text(item.diagnostic, credentials),
        } for item in sources],
        "reports": {
            "json": (_safe_text(str(report_paths["json"]), credentials)
                     if report_paths.get("json") else None),
            "markdown": (_safe_text(str(report_paths["markdown"]), credentials)
                         if report_paths.get("markdown") else None),
        },
    }


def _json_summary(
    result: AuditResult, report_paths: Mapping[str, Path | None], credentials: tuple[str, ...],
) -> str:
    return json.dumps(_summary_payload(result, report_paths, credentials), sort_keys=True) + "\n"


def _safe_text(value: object, credentials: tuple[str, ...]) -> str:
    """Redact credentials and neutralize terminal controls in concise diagnostics."""
    redacted = redact_diagnostic(value, credentials)
    return "".join(" " if unicodedata.category(character) == "Cc" else character
                   for character in redacted)


def _human_summary(
    result: AuditResult, report_paths: Mapping[str, Path | None], credentials: tuple[str, ...],
) -> str:
    payload = _summary_payload(result, report_paths, credentials)
    lines = [
        f"Dependency audit: {result.gate_status.value.upper()} (exit {result.exit_code})",
        f"Mode: {result.mode.value}; findings: {payload['findings']}; blocked: {payload['blocked']}; warnings: {payload['warnings']}",
        (f"Reports: {payload['reports']['json']} and {payload['reports']['markdown']}"
         if payload["reports"]["json"] and payload["reports"]["markdown"]
         else "Reports: unavailable"),
    ]
    gaps = [item for item in payload["sources"] if item["state"] in {"partial", "unavailable"}]
    lines.extend(
        f"Source {item['source']}: {item['state']} - {item['diagnostic'] or 'no diagnostic'}"
        for item in gaps
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
