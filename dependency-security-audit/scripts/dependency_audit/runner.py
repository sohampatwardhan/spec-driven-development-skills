"""Orchestrate one dependency audit without weakening partial security evidence.

The runner owns sequencing and mode semantics, while inventory, network, reachability, native
audit, and report implementations remain injected. This boundary keeps offline tests complete and
prevents an unavailable enrichment source from erasing authoritative OSV findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import math
from numbers import Real
from pathlib import Path
import re
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import unquote, urlsplit

from .http import redact_diagnostic
from .inventory import collect_inventory
from .models import (
    Advisory, AdvisoryEnrichment, AffectedPackage, AuditMode, AuditResult, Decision,
    DecisionRecord, Finding, GateStatus, InventoryResult, PackageRef, Reachability,
    SourceState, SourceStatus, utc_now,
)
from .policy import (
    FixedVersionSelection, Policy, classify_finding, gate_result,
    select_lowest_common_fixed_version,
)
from .reachability import ReachabilityResult, load_reachability
from .reporting import ReportPaths, write_reports
from .sources import SourceResult, correlate_advisories


class OsvService(Protocol):
    """Provide current package-aware OSV results for exact resolved packages.

    Returning normalized value and status together lets the runner retain valid advisories when a
    later request is partial instead of converting an evidence gap into an empty result.
    """

    def query(self, packages: Sequence[PackageRef]) -> SourceResult[list[Advisory]]:
        """Return normalized OSV advisories and explicit availability for exact packages."""
        ...


class EnrichmentService(Protocol):
    """Add source-scoped metadata without changing authoritative package applicability.

    Enrichment remains optional because secondary-source availability must not erase or broaden
    the exact-package applicability already established by primary evidence.
    """

    def enrich(self, advisory: Advisory, *, package: PackageRef | None = None) -> SourceResult[Advisory]:
        """Return supplemental evidence without replacing primary package applicability."""
        ...


class KevService(Protocol):
    """Provide one current normalized KEV catalog snapshot for an audit run.

    Fetching once and matching locally gives every finding the same catalog timestamp and avoids
    order-dependent policy decisions within a single run.
    """

    def fetch_ids(self) -> SourceResult[frozenset[str]]:
        """Return the current normalized KEV identifiers with source availability."""
        ...


@dataclass(frozen=True)
class NativeAuditResult:
    """Return applicable native-audit advisories and explicit source availability.

    Native adapters supplement OSV and are required only when they report themselves applicable;
    an empty result therefore means no installed applicable audit rather than a hidden success.
    """

    advisories: tuple[Advisory, ...] = ()
    statuses: tuple[SourceStatus, ...] = ()


@dataclass(frozen=True)
class RiskAcceptance:
    """Record reviewable mitigation and approval text for one release finding.

    Both fields are intentionally free text because policy checks presence while reports preserve
    the human owner, impact, review date, and approval detail supplied by the project.
    """

    mitigation: str
    approval: str


@dataclass(frozen=True)
class RemediationEvidence:
    """Describe the evidence required before declaring a dependency remediation complete.

    Current Context7 guidance is mandatory for a released target. Major upgrades and replacements
    additionally require explicit approval, and any resolution change requires relevant project
    tests plus a post-change dependency audit. Keeping these booleans as evidence inputs prevents
    a recommendation from being mistaken for a completed change.
    """

    target_version: str
    context7_evidence: str = ""
    major_upgrade: bool = False
    replacement: bool = False
    explicit_approval: str = ""
    resolution_changed: bool = True
    project_tests_passed: bool = False
    post_change_audit_passed: bool = False


def remediation_preconditions(
    evidence: RemediationEvidence,
    *,
    current_version: str | None = None,
    authoritative_target: str | None = None,
    inferred_major_upgrade: bool = False,
    major_upgrade_unresolved: bool = False,
    major_evaluation_failed: bool = False,
) -> tuple[str, ...]:
    """Return unmet safeguards for a proposed remediation.

    The result is empty only when the proposed target equals the authoritative safe selection and
    current library guidance, approvals for disruptive changes, and re-verification after inferred
    resolution changes are all present. Caller-supplied booleans can strengthen these safeguards
    but cannot weaken facts inferred by the runner from the installed and target versions.
    """

    gaps: list[str] = []
    if authoritative_target is not None and evidence.target_version != authoritative_target:
        gaps.append(f"target must equal authoritative safe version {authoritative_target}")
    if not evidence.context7_evidence.strip():
        gaps.append("current Context7 migration, API, and configuration evidence is required")
    resolution_changed = (evidence.resolution_changed or (
        current_version is not None and evidence.target_version != current_version
    ))
    major_upgrade = evidence.major_upgrade or inferred_major_upgrade
    if major_evaluation_failed:
        gaps.append("major-version evaluation failed; approval scope remains unresolved")
    if (major_upgrade or major_upgrade_unresolved or evidence.replacement) and not evidence.explicit_approval.strip():
        gaps.append("explicit approval is required for a major upgrade or replacement")
    if resolution_changed and not evidence.project_tests_passed:
        gaps.append("relevant project tests must pass after the resolution change")
    if resolution_changed and not evidence.post_change_audit_passed:
        gaps.append("a fresh post-change dependency audit must pass")
    return tuple(gaps)


@dataclass(frozen=True)
class AuditConfig:
    """Configure one audit event and its evidence/acceptance boundaries.

    ``baseline_fingerprint`` suppresses a full change-mode scan only when it exactly matches the
    newly collected resolved inventory. Main and release modes always query fresh sources.
    Acceptance and remediation mappings use ``<package-purl>|<advisory-id>`` keys, with advisory ID
    fallback accepted for project-wide release records.
    """

    root: Path
    mode: AuditMode
    baseline_fingerprint: str | None = None
    sbom_path: Path | None = None
    reachability_path: Path | None = None
    output_dir: Path | None = None
    project_revision: str = ""
    policy: Policy = field(default_factory=Policy)
    release_acceptances: Mapping[str, RiskAcceptance] = field(default_factory=dict)
    remediations: Mapping[str, RemediationEvidence] = field(default_factory=dict)
    source_max_age_seconds: float = 3600.0
    credential_values: tuple[str, ...] = ()


InventoryCollector = Callable[[Path, Path | None], InventoryResult]
NativeAuditRunner = Callable[[InventoryResult], NativeAuditResult]
ReachabilityLoader = Callable[[Path | None], ReachabilityResult]
ReportWriter = Callable[..., ReportPaths]
SafeVersionPredicate = Callable[[Finding, str], bool]
VersionKey = Callable[[str], object]
MajorUpgradePredicate = Callable[[PackageRef, str], bool | None]


def _no_native_audits(_inventory: InventoryResult) -> NativeAuditResult:
    return NativeAuditResult()


@dataclass(frozen=True)
class AuditServices:
    """Inject every effectful audit service behind a narrow normalized contract.

    Required inventory, OSV, and KEV services are explicit constructor arguments. GitHub, NVD,
    native audits, reachability, clocks, and report persistence are replaceable so tests never
    need a live network, subprocess, wall clock, or durable output directory. Ecosystem-aware
    safe-range, ordering, and major-upgrade callbacks keep generic orchestration from guessing at
    version semantics it cannot safely interpret. A missing or indeterminate major-upgrade result
    requires conservative approval; callback exceptions become reportable source gaps rather than
    aborting the audit.
    """

    osv: OsvService
    kev: KevService
    inventory: InventoryCollector = collect_inventory
    github: EnrichmentService | None = None
    nvd: EnrichmentService | None = None
    native_audits: NativeAuditRunner = _no_native_audits
    reachability: ReachabilityLoader = load_reachability
    reports: ReportWriter = write_reports
    now: Callable[[], str] = utc_now
    is_safe_version: SafeVersionPredicate | None = None
    version_key: VersionKey | None = None
    is_major_upgrade: MajorUpgradePredicate | None = None


def run_audit(config: AuditConfig, services: AuditServices) -> AuditResult:
    """Run one mode-aware audit and write reports from all verified evidence.

    Change mode skips remote work only for an exact baseline fingerprint match; otherwise all
    modes collect inventory, OSV, applicable native audits, secondary enrichment, KEV, optional
    reachability, policy decisions, and reports. Main/release require fresh complete inventory,
    OSV, KEV, and every applicable native audit. Secondary failures remain visible but do not
    erase findings or make delivery unavailable. Aggregate unavailable status precedes known
    blocks, followed by warnings and pass. Report failure itself returns unavailable because an
    unwritten result cannot satisfy the evidence contract.

    Args:
        config: Project event, local evidence paths, policy, freshness, and acceptance inputs.
        services: Injected normalized services; production and fake implementations share the
            same failure-preserving contract.

    Returns:
        The complete audit evidence with stable aggregate status and exit code. Invalid local
        configuration returns ``invalid`` without invoking remote services.
    """

    invalid = _invalid_config(config)
    if invalid:
        return AuditResult(mode=config.mode if isinstance(config.mode, AuditMode) else AuditMode.CHANGE,
                           project_revision=config.project_revision, gate_status=GateStatus.INVALID,
                           exit_code=3, sources=[SourceStatus("configuration", SourceState.UNAVAILABLE,
                                                             diagnostic=invalid)])

    try:
        started_at = services.now()
        _parse_timestamp(started_at)
    except Exception as error:
        result = AuditResult(mode=config.mode, timestamp=utc_now(),
                             project_revision=config.project_revision,
                             gate_status=GateStatus.UNAVAILABLE, exit_code=2,
                             sources=[SourceStatus(
                                 "clock", SourceState.UNAVAILABLE,
                                 diagnostic=f"audit clock failed: {redact_diagnostic(error, config.credential_values)}",
                             )])
        _write_unavailable_result(result, config, services)
        return result
    try:
        inventory = services.inventory(Path(config.root), config.sbom_path)
    except Exception as error:  # Service boundaries must convert failures into durable evidence.
        inventory = InventoryResult(complete=False,
                                    statuses=[SourceStatus("inventory", SourceState.UNAVAILABLE,
                                                           attempted_at=started_at,
                                                           diagnostic=f"inventory failed: {redact_diagnostic(error, config.credential_values)}")],
                                    incomplete_reasons=["inventory service failed"])
    inventory.statuses = [_fresh_status(item, started_at, config.source_max_age_seconds)
                          for item in inventory.statuses]
    if not inventory.complete:
        inventory.statuses.append(SourceStatus(
            "inventory-completeness", SourceState.PARTIAL, attempted_at=started_at,
            diagnostic="resolved dependency inventory is incomplete",
        ))
    result = AuditResult(mode=config.mode, timestamp=started_at, project_revision=config.project_revision,
                         inventory=inventory)

    if (config.mode is AuditMode.CHANGE and inventory.complete
            and config.baseline_fingerprint is not None
            and inventory.fingerprint == config.baseline_fingerprint):
        _finish_and_write(result, config, services, required_sources=())
        return result

    try:
        osv_result = services.osv.query(tuple(inventory.packages))
    except Exception as error:
        osv_result = SourceResult([], SourceStatus("osv", SourceState.UNAVAILABLE,
                                                   attempted_at=started_at,
                                                   diagnostic=f"OSV query failed: {redact_diagnostic(error, config.credential_values)}"))
    osv_status = _fresh_status(osv_result.status, started_at, config.source_max_age_seconds)
    result.sources.append(osv_status)

    try:
        native = services.native_audits(inventory)
    except Exception as error:
        native = NativeAuditResult(statuses=(SourceStatus("native-audit", SourceState.UNAVAILABLE,
                                                          attempted_at=started_at,
                                                          diagnostic=f"native audit failed: {redact_diagnostic(error, config.credential_values)}"),))
    native_statuses = tuple(_fresh_status(item, started_at, config.source_max_age_seconds)
                            for item in native.statuses)
    native_statuses = _native_consistency_statuses(native, native_statuses, started_at)
    result.sources.extend(native_statuses)

    try:
        kev_result = services.kev.fetch_ids()
    except Exception as error:
        kev_result = SourceResult(frozenset(), SourceStatus("kev", SourceState.UNAVAILABLE,
                                                            attempted_at=started_at,
                                                            diagnostic=f"KEV query failed: {redact_diagnostic(error, config.credential_values)}"))
    kev_status = _fresh_status(kev_result.status, started_at, config.source_max_age_seconds)
    result.sources.append(kev_status)
    kev_ids = kev_result.value or frozenset()

    try:
        reachability = services.reachability(config.reachability_path)
    except Exception as error:
        reachability = ReachabilityResult(diagnostics=(
            f"reachability loading failed: {redact_diagnostic(error, config.credential_values)}",),
                                          default_state=Reachability.UNKNOWN,
                                          available=False, complete=False)
    if config.reachability_path is not None:
        reachability_state = (SourceState.OK if reachability.available and reachability.complete else
                              SourceState.PARTIAL if reachability.available else SourceState.UNAVAILABLE)
        result.sources.append(SourceStatus("reachability", reachability_state, attempted_at=started_at,
                                           diagnostic="; ".join(reachability.diagnostics)))

    primary_advisories = [*osv_result.value, *native.advisories]
    result.findings, enrichment_statuses = _build_findings(
        inventory.packages, primary_advisories, kev_ids, reachability, services,
        config.credential_values,
    )
    result.sources.extend(_fresh_status(item, started_at, config.source_max_age_seconds)
                          for item in enrichment_statuses)
    result.decisions, remediation_statuses = _decisions(
        result.findings, config, services, started_at,
    )
    result.sources.extend(remediation_statuses)

    required_sources = (osv_status, kev_status, *remediation_statuses, *(
        item for item in native_statuses if item.state is not SourceState.NOT_APPLICABLE
    ))
    _finish_and_write(result, config, services, required_sources=required_sources)
    return result


def _invalid_config(config: AuditConfig) -> str:
    if not isinstance(config.mode, AuditMode):
        return "audit mode is invalid"
    maximum_age = config.source_max_age_seconds
    try:
        valid_maximum_age = (not isinstance(maximum_age, bool)
                             and isinstance(maximum_age, Real)
                             and math.isfinite(float(maximum_age))
                             and maximum_age > 0)
    except (OverflowError, TypeError, ValueError):
        valid_maximum_age = False
    if not valid_maximum_age:
        return "source freshness window must be a finite positive number"
    if not Path(config.root).is_dir():
        return "project root is not a directory"
    return ""


def _write_unavailable_result(
    result: AuditResult, config: AuditConfig, services: AuditServices,
) -> None:
    """Persist an early operational failure while preserving unavailable precedence."""
    try:
        services.reports(result, config.output_dir or Path(config.root) / ".security" / "dependency-audit",
                         credential_values=config.credential_values)
    except Exception as error:
        result.sources.append(SourceStatus(
            "reporting", SourceState.UNAVAILABLE,
            diagnostic=redact_diagnostic(error, config.credential_values),
        ))


def _native_consistency_statuses(
    native: NativeAuditResult,
    statuses: tuple[SourceStatus, ...],
    attempted_at: str,
) -> tuple[SourceStatus, ...]:
    """Fail closed when native advisory evidence contradicts adapter applicability evidence."""
    contradictions: dict[str, list[str]] = {}
    states_by_source: dict[str, set[SourceState]] = {}
    for status in statuses:
        states_by_source.setdefault(status.source, set()).add(status.state)
    for source, states in states_by_source.items():
        if len(states) > 1:
            contradictions.setdefault(source, []).append(
                "native audit reported contradictory states for one source"
            )
    for advisory in native.advisories:
        advisory_sources = tuple(filter(None, advisory.source.split(";"))) or ("native-audit",)
        for source in advisory_sources:
            matching = states_by_source.get(source, set())
            if not matching or not matching.issubset({SourceState.OK, SourceState.PARTIAL}):
                contradictions.setdefault(source, []).append(
                    f"native advisory from {source} lacked a matching OK or PARTIAL source status"
                )
    if not contradictions:
        return statuses
    synthesized = tuple(SourceStatus(
        f"{source}-consistency", SourceState.PARTIAL, attempted_at=attempted_at,
        diagnostic="; ".join(sorted(set(diagnostics))),
    ) for source, diagnostics in sorted(contradictions.items()))
    return (*statuses, *synthesized)


def _finish_and_write(
    result: AuditResult,
    config: AuditConfig,
    services: AuditServices,
    *,
    required_sources: Sequence[SourceStatus],
) -> None:
    gate_view = replace(result)
    gate_view.sources = list(result.sources if result.mode is AuditMode.CHANGE else required_sources)
    aggregate = gate_result(gate_view)
    result.gate_status, result.exit_code = aggregate.status, aggregate.exit_code
    try:
        services.reports(result, config.output_dir or Path(config.root) / ".security" / "dependency-audit",
                         credential_values=config.credential_values)
    except Exception as error:
        result.sources.append(SourceStatus("reporting", SourceState.UNAVAILABLE,
                                           diagnostic=redact_diagnostic(error, config.credential_values)))
        result.gate_status, result.exit_code = GateStatus.UNAVAILABLE, 2


def _build_findings(
    packages: Sequence[PackageRef],
    advisories: Sequence[Advisory],
    kev_ids: frozenset[str],
    reachability: ReachabilityResult,
    services: AuditServices,
    credential_values: tuple[str, ...],
) -> tuple[list[Finding], list[SourceStatus]]:
    findings: list[Finding] = []
    statuses: list[SourceStatus] = []
    for package in sorted(packages, key=lambda item: (item.purl, item.ecosystem, item.name, item.version)):
        correlated = correlate_advisories(advisories, package=package)
        for advisory in (
            _preserve_native_package_evidence(item, advisories, package) for item in correlated
        ):
            if not _advisory_applies(advisory, package, len(packages)):
                continue
            authoritative_ids = _stable_ids(advisory)
            kev = bool(authoritative_ids & {item.upper() for item in kev_ids})
            enriched = advisory
            for source, client in (("github", services.github), ("nvd", services.nvd)):
                if client is None:
                    continue
                try:
                    response = client.enrich(enriched, package=package)
                except Exception as error:
                    statuses.append(SourceStatus(source, SourceState.UNAVAILABLE,
                                                 diagnostic=f"{source} enrichment failed: "
                                                            f"{redact_diagnostic(error, credential_values)}"))
                    continue
                if response.value is not None:
                    merged = _merge_secondary_enrichment(enriched, response.value, source)
                    if merged is None:
                        statuses.append(SourceStatus(
                            source, SourceState.PARTIAL,
                            attempted_at=response.status.attempted_at,
                            provenance=response.status.provenance,
                            diagnostic="secondary advisory identity did not overlap authoritative stable IDs",
                        ))
                        continue
                    enriched = merged
                statuses.append(response.status)
            assessment = reachability.lookup(package.purl, enriched.id)
            findings.append(Finding(package=package, advisory=enriched,
                                    kev=kev, reachability=assessment.state,
                                    reachability_evidence=assessment.evidence))
    unique = {(item.package.purl, item.advisory.id): item for item in findings}
    return [unique[key] for key in sorted(unique)], statuses


_SEVERITY_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_STABLE_ID = re.compile(r"[A-Z][A-Z0-9._]*-[A-Z0-9][A-Z0-9._-]*")


def _stable_ids(advisory: Advisory) -> set[str]:
    return {
        normalized for value in (advisory.id, *advisory.aliases)
        if isinstance(value, str)
        and (normalized := value.strip().upper())
        and _STABLE_ID.fullmatch(normalized)
    }


def _merge_secondary_enrichment(
    primary: Advisory, secondary: Advisory, expected_source: str,
) -> Advisory | None:
    """Merge supplemental source evidence without replacing authoritative advisory identity.

    A stable-ID overlap proves the response belongs to the requested correlation component. Only
    validated aliases, references, and source-scoped enrichments are added; canonical identity,
    provenance, applicability, withdrawal, and fixes remain primary-owned. Severity may increase
    within the closed vocabulary but can never be downgraded by secondary data.
    """
    if not (_stable_ids(primary) & _stable_ids(secondary)):
        return None
    aliases = {
        *primary.aliases,
        *(value.strip().upper() for value in (secondary.id, *secondary.aliases)
          if isinstance(value, str) and _STABLE_ID.fullmatch(value.strip().upper())),
    }
    aliases = {value for value in aliases if value.upper() != primary.id.upper()}
    references = {
        *primary.references,
        *(value for value in secondary.references if _valid_reference(value)),
    }
    enrichments = {
        *primary.enrichments,
        *(item for item in secondary.enrichments
          if _valid_enrichment(item, expected_source)),
    }
    severity = max(
        (value for value in (primary.severity, secondary.severity,
                             *(item.severity for item in enrichments))
         if value in _SEVERITY_RANK),
        key=_SEVERITY_RANK.__getitem__,
        default="unknown",
    )
    detail_parts = tuple(dict.fromkeys(
        value for value in (primary.details, secondary.details)
        if isinstance(value, str) and value.strip()
    ))
    return replace(
        primary,
        aliases=tuple(sorted(aliases)),
        severity=severity,
        references=tuple(sorted(references)),
        details="\n\n".join(detail_parts),
        enrichments=tuple(sorted(enrichments, key=lambda item: (
            item.source, item.severity, item.cvss_scores, item.cvss_vectors,
            item.epss_scores, item.vulnerable_functions, item.details,
        ))),
    )


def _valid_reference(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.username is None


def _valid_enrichment(item: AdvisoryEnrichment, expected_source: str) -> bool:
    return (
        isinstance(item, AdvisoryEnrichment)
        and item.source == expected_source
        and item.severity in _SEVERITY_RANK
        and all(_valid_score(score, 10) for score in item.cvss_scores)
        and all(_valid_score(score, 1) for score in item.epss_scores)
        and all(isinstance(value, str) for value in (
            *item.cvss_vectors, *item.vulnerable_functions,
        ))
        and isinstance(item.details, str)
    )


def _valid_score(value: object, maximum: float) -> bool:
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value)) and 0 <= value <= maximum
    except (OverflowError, TypeError, ValueError):
        return False


def _preserve_native_package_evidence(
    correlated: Advisory,
    originals: Sequence[Advisory],
    package: PackageRef,
) -> Advisory:
    """Fill missing OSV fix/range fields from correlated exact-package native evidence.

    Stable identifier/alias membership selects the deterministic correlation component. OSV's
    exact-package projection remains authoritative for every populated field; native adapters may
    supply only a missing fix or range field, and secondary sources never participate here.
    """
    identifiers = {correlated.id, *correlated.aliases}
    native = sorted(
        (item for item in originals
         if not _is_osv_source(item.source)
         and identifiers.intersection((item.id, *item.aliases))),
        key=lambda item: (item.id, item.aliases, item.source),
    )
    native_fixes: set[str] = set()
    native_ranges: set[str] = set()
    for advisory in native:
        matches = tuple(
            affected for affected in advisory.affected_packages
            if _affected_matches(affected, package)
        )
        for affected in matches:
            native_fixes.update(affected.fixed_versions)
            native_ranges.update(
                f"{event.kind.value}:{event.value}"
                for range_item in affected.ranges for event in range_item.events
            )
    return replace(
        correlated,
        fixed_versions=(correlated.fixed_versions or tuple(sorted(native_fixes))),
        affected_ranges=(correlated.affected_ranges or tuple(sorted(native_ranges))),
    )


def _is_osv_source(source: str) -> bool:
    return "osv" in source.split(";")


def _advisory_applies(advisory: Advisory, package: PackageRef, package_count: int) -> bool:
    if advisory.affected_packages:
        return any(_affected_matches(item, package) for item in advisory.affected_packages)
    return package_count == 1


def _affected_matches(affected: AffectedPackage, package: PackageRef) -> bool:
    if affected.purl:
        affected_identity, affected_version = _purl_parts(affected.purl)
        package_identity, package_version = _purl_parts(package.purl)
        return (_purl_key(affected_identity) == _purl_key(package_identity)
                and (affected_version is None or affected_version == package.version)
                and (package_version is None or package_version == package.version))
    ecosystem = _ecosystem_key(affected.ecosystem)
    return ecosystem == _ecosystem_key(package.ecosystem) and _name_key(
        ecosystem, affected.name) == _name_key(ecosystem, package.name)


def _purl_parts(purl: str) -> tuple[str, str | None]:
    core = purl.split("?", 1)[0].split("#", 1)[0]
    identity, separator, version = core.rpartition("@")
    return (unquote(identity), unquote(version)) if separator else (unquote(core), None)


def _purl_key(identity: str) -> tuple[str, str]:
    if not identity.casefold().startswith("pkg:") or "/" not in identity:
        return "", identity
    ecosystem, name = identity[4:].split("/", 1)
    canonical = _ecosystem_key(ecosystem)
    return canonical, _name_key(canonical, name)


def _ecosystem_key(ecosystem: str) -> str:
    return {"pip": "pypi", "pypi": "pypi", "rust": "crates.io", "cargo": "crates.io",
            "crates.io": "crates.io", "go": "go", "golang": "go"}.get(
                ecosystem.casefold(), ecosystem.casefold())


def _name_key(ecosystem: str, name: str) -> str:
    if ecosystem == "pypi":
        return re.sub(r"[-_.]+", "-", name).casefold()
    if ecosystem in {"go", "maven"}:
        return name
    return name.casefold()


def _decisions(
    findings: Sequence[Finding], config: AuditConfig, services: AuditServices, attempted_at: str,
) -> tuple[list[DecisionRecord], list[SourceStatus]]:
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.package.purl, []).append(finding)
    selections: dict[str, FixedVersionSelection] = {}
    statuses: list[SourceStatus] = []
    for purl, items in grouped.items():
        try:
            selections[purl] = select_lowest_common_fixed_version(
                items,
                is_safe_version=services.is_safe_version,
                version_key=services.version_key,
            )
        except Exception as error:
            unresolved = tuple(sorted({item.advisory.id for item in items}))
            selections[purl] = FixedVersionSelection(None, unresolved)
            statuses.append(SourceStatus(
                "remediation-version-evaluation", SourceState.PARTIAL,
                attempted_at=attempted_at,
                diagnostic="safe-version evaluation failed: " + redact_diagnostic(
                    error, config.credential_values,
                ),
            ))
    decisions: list[DecisionRecord] = []
    for finding in findings:
        decision = classify_finding(finding, config.policy)
        key = f"{finding.package.purl}|{finding.advisory.id}"
        acceptance = config.release_acceptances.get(key) or config.release_acceptances.get(finding.advisory.id)
        mitigation = acceptance.mitigation if acceptance else ""
        approval = acceptance.approval if acceptance else ""
        selection = selections[finding.package.purl]
        recommendation = selection.version
        remediation = config.remediations.get(key) or config.remediations.get(finding.package.purl)
        if decision.decision is not Decision.EXCLUDED and not mitigation:
            if recommendation is None:
                if selection.unresolved:
                    mitigation = "No common authoritative safe version; unresolved advisories: " + ", ".join(
                        selection.unresolved)
            elif remediation is None:
                mitigation = (f"Authoritative safe candidate {recommendation}; current Context7 evidence is "
                              "required before implementation, followed by relevant project tests and a fresh "
                              "dependency audit.")
            else:
                version_changed = finding.package.version != remediation.target_version
                inferred_major = False
                major_unresolved = version_changed and services.is_major_upgrade is None
                major_evaluation_failed = False
                if version_changed and services.is_major_upgrade is not None:
                    try:
                        major_result = services.is_major_upgrade(
                            finding.package, remediation.target_version,
                        )
                        if isinstance(major_result, bool):
                            inferred_major = major_result
                        else:
                            major_unresolved = True
                    except Exception as error:
                        major_unresolved = True
                        major_evaluation_failed = True
                        statuses.append(SourceStatus(
                            "remediation-version-evaluation", SourceState.PARTIAL,
                            attempted_at=attempted_at,
                            diagnostic="major-version evaluation failed: " + redact_diagnostic(
                                error, config.credential_values,
                            ),
                        ))
                gaps = remediation_preconditions(
                    remediation,
                    current_version=finding.package.version,
                    authoritative_target=recommendation,
                    inferred_major_upgrade=inferred_major,
                    major_upgrade_unresolved=major_unresolved,
                    major_evaluation_failed=major_evaluation_failed,
                )
                mitigation = (f"Target {remediation.target_version}; " +
                              ("remediation evidence complete" if not gaps else "pending: " + "; ".join(gaps)))
        decisions.append(DecisionRecord(decision.decision, decision.reason_codes, mitigation, approval))
    return decisions, statuses


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _fresh_status(status: SourceStatus, now: str, max_age_seconds: float) -> SourceStatus:
    if status.state is SourceState.NOT_APPLICABLE:
        return status
    try:
        attempted = _parse_timestamp(status.attempted_at)
        current = _parse_timestamp(now)
        age_seconds = (current - attempted).total_seconds()
        stale = age_seconds > max_age_seconds or age_seconds < -300
    except (TypeError, ValueError, OverflowError):
        stale = True
    if not stale:
        return status
    diagnostic = "; ".join(filter(None, (status.diagnostic, "source evidence is stale or has an invalid timestamp")))
    stale_state = (SourceState.UNAVAILABLE if status.state is SourceState.UNAVAILABLE
                   else SourceState.PARTIAL)
    return SourceStatus(status.source, stale_state, attempted_at=status.attempted_at,
                        provenance=status.provenance, diagnostic=diagnostic)
