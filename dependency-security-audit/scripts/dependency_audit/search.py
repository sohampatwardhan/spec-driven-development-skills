"""Reusable informational advisory search over normalized source clients.

Search deliberately does not collect a project inventory or apply delivery policy. A completed
lookup, including an explicit no-match, therefore answers an investigation question rather than
asserting that a project is safe. Required-source gaps remain unavailable instead of becoming
false empty results.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping, Protocol

from .http import RetryingHttpClient
from .inventory import _is_exact_version as _inventory_exact_version
from .models import (
    Advisory,
    AdvisorySearchResult,
    DependencyScope,
    PackageRef,
    SearchKind,
    SearchStatus,
    SourceState,
    SourceStatus,
)
from .sources import (
    GithubClient,
    KevClient,
    NvdClient,
    OsvClient,
    SourceResult,
    correlate_advisories,
)


INFORMATIONAL_NOTICE = (
    "Informational advisory search only; this is not a project audit or delivery decision."
)
_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$", re.IGNORECASE)
_GHSA = re.compile(r"^GHSA-[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+$", re.IGNORECASE)
_STABLE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$", re.IGNORECASE)
_FLOATING_VERSION = re.compile(r"(?:^|[._-])[xX](?:$|[._-])")
_URL_USERINFO = re.compile(r"(?i)\b(https?://)[^/\s@]+@")
_CREDENTIAL = re.compile(
    r"""(?ix)
    (?<![\w-])(?P<quote>["']?)
    (?P<key>(?:proxy-)?authorization|api[_-]?key|access[_-]?token|
        refresh[_-]?token|token|password|secret)
    (?P=quote)\s*[:=]\s*(?:(?:bearer|basic)\s+)?
    (?:\[REDACTED\]|"(?:\\.|[^"\\\r\n])*"|'(?:\\.|[^'\\\r\n])*'|[^\s,;}\]]+)
    """
)


class OsvSearchService(Protocol):
    """Provide exact package queries and stable-identifier OSV lookup."""

    def query(self, packages: Iterable[PackageRef]) -> SourceResult[list[Advisory]]:
        """Return normalized OSV matches for exact package identities."""
        ...

    def lookup(self, identifier: str, *, package: PackageRef | None = None
               ) -> SourceResult[Advisory | None]:
        """Return one OSV record by stable identifier, optionally projected to a package."""
        ...


class AdvisoryLookupService(Protocol):
    """Provide secondary identifier lookup and package-aware enrichment."""

    def lookup(self, identifier: str) -> SourceResult[Advisory | None]:
        """Return a secondary advisory matching the supplied stable identifier."""
        ...

    def enrich(self, advisory: Advisory, *, package: PackageRef | None = None
               ) -> SourceResult[Advisory]:
        """Return package-scoped supplemental metadata for a primary advisory."""
        ...


class KevSearchService(Protocol):
    """Provide one current normalized KEV catalog snapshot."""

    def fetch_ids(self) -> SourceResult[frozenset[str]]:
        """Return current KEV identifiers for informational membership lookup."""
        ...


@dataclass(frozen=True)
class SearchServices:
    """Inject normalized source boundaries so search is reusable and offline-testable.

    OSV is required for package and OSV-family searches because it owns exact applicability.
    GHSA, CVE, and KEV searches require their corresponding owning source; optional secondary
    failures remain visible without erasing completed authoritative evidence.
    """

    osv: OsvSearchService
    github: AdvisoryLookupService | None = None
    nvd: AdvisoryLookupService | None = None
    kev: KevSearchService | None = None


def default_services(*, credential_values: Iterable[str] = ()) -> SearchServices:
    """Construct bounded production clients with source-specific response limits."""

    secrets = tuple(item for item in credential_values if item)
    http = RetryingHttpClient(secrets=secrets)
    kev_http = RetryingHttpClient(max_bytes=5_000_000, secrets=secrets)
    return SearchServices(
        osv=OsvClient(http), github=GithubClient(http), nvd=NvdClient(http),
        kev=KevClient(kev_http),
    )


def search_package(
    ecosystem: str,
    name: str,
    version: str,
    services: SearchServices,
) -> AdvisorySearchResult:
    """Search advisories for one exact package version without collecting an inventory.

    OSV completion is required because only its ecosystem-aware query establishes version
    applicability. GitHub and NVD may enrich records, but their failure cannot convert verified
    OSV findings into an empty result.

    Args:
        ecosystem: OSV ecosystem label for the resolved package.
        name: Exact package name in that ecosystem.
        version: One resolved version, never a constraint or range.
        services: Injected normalized source clients.

    Returns:
        A normalized complete, unavailable, or invalid informational result. No return value is
        an enforcement decision.
    """

    query = {"ecosystem": ecosystem.strip(), "name": name.strip(), "version": version.strip()}
    if (
        not query["ecosystem"]
        or not query["name"]
        or not _is_exact_version(query["version"], query["ecosystem"])
    ):
        return _invalid(SearchKind.PACKAGE, query, "ecosystem, name, and one exact version are required")
    package = PackageRef(
        ecosystem=query["ecosystem"], name=query["name"], version=query["version"],
        purl="", scope=DependencyScope.UNKNOWN,
    )
    try:
        primary = services.osv.query([package])
    except Exception as error:
        primary = SourceResult([], _failed_status("osv", error))
    statuses = [primary.status]
    advisories = list(primary.value)
    for source, enrichment in (("github", services.github), ("nvd", services.nvd)):
        if enrichment is None:
            continue
        enriched: list[Advisory] = []
        for advisory in advisories:
            try:
                response = enrichment.enrich(advisory, package=package)
            except Exception as error:
                response = SourceResult(advisory, _failed_status(source, error))
            statuses.append(response.status)
            enriched.append(response.value)
        advisories = enriched
    correlated = correlate_advisories(advisories, package=package)
    if primary.status.state is not SourceState.OK:
        return _unavailable(SearchKind.PACKAGE, query, correlated, statuses)
    return AdvisorySearchResult.completed(
        SearchKind.PACKAGE, query, advisories=correlated, sources=statuses,
    )


def search_advisory(identifier: str, services: SearchServices) -> AdvisorySearchResult:
    """Look up and correlate one OSV-family, GHSA, or CVE stable identifier.

    The identifier's owning source is required: GitHub for GHSA, NVD for CVE, and OSV for other
    supported OSV-family IDs. Applicable optional clients are queried for stable aliases and
    enrichment, then records are correlated without name-similarity matching.
    """

    normalized = identifier.strip().upper()
    query = {"id": normalized}
    if not _STABLE_ID.fullmatch(normalized):
        return _invalid(SearchKind.ADVISORY, query, "a stable OSV, GHSA, or CVE identifier is required")

    calls: list[tuple[str, object | None]] = [("osv", services.osv)]
    required = "osv"
    if _GHSA.fullmatch(normalized):
        required = "github"
        calls.append(("github", services.github))
    elif _CVE.fullmatch(normalized):
        required = "nvd"
        calls.extend((("github", services.github), ("nvd", services.nvd)))

    records: list[Advisory] = []
    statuses: list[SourceStatus] = []
    required_status: SourceStatus | None = None
    called: set[str] = set()
    for source, service in calls:
        if service is None:
            if source == required:
                required_status = SourceStatus(
                    source, SourceState.UNAVAILABLE,
                    diagnostic=f"required {source} source is not configured",
                )
                statuses.append(required_status)
            continue
        called.add(source)
        try:
            response = (
                service.lookup(normalized, package=None) if source == "osv"
                else service.lookup(normalized)
            )
        except Exception as error:
            response = SourceResult(None, _failed_status(source, error))
        statuses.append(response.status)
        if source == required:
            required_status = response.status
        if response.value is not None:
            records.append(response.value)

    # Follow stable aliases discovered in normalized records. This lets an OSV lookup carrying a
    # CVE alias reuse GitHub/NVD and lets a GHSA lookup carrying a CVE reach NVD, without any
    # name-similarity matching or speculative request.
    identifiers = _record_identifiers(records)
    ghsa = next((item for item in identifiers if _GHSA.fullmatch(item)), None)
    cve = next((item for item in identifiers if _CVE.fullmatch(item)), None)
    if services.github is not None and "github" not in called and (ghsa or cve):
        response = _lookup_optional("github", services.github, ghsa or cve or normalized)
        statuses.append(response.status)
        if response.value is not None:
            records.append(response.value)
            identifiers = _record_identifiers(records)
            cve = next((item for item in identifiers if _CVE.fullmatch(item)), cve)
    if services.nvd is not None and "nvd" not in called and cve:
        response = _lookup_optional("nvd", services.nvd, cve)
        statuses.append(response.status)
        if response.value is not None:
            records.append(response.value)

    correlated = correlate_advisories(records)
    if required_status is None or required_status.state is not SourceState.OK:
        return _unavailable(SearchKind.ADVISORY, query, correlated, statuses)
    return AdvisorySearchResult.completed(
        SearchKind.ADVISORY, query, advisories=correlated, sources=statuses,
    )


def search_kev(identifier: str, services: SearchServices) -> AdvisorySearchResult:
    """Report membership in the current KEV catalog without implying project exposure.

    Absence is trustworthy only when the whole required KEV fetch completes. Partial or
    unavailable catalogs therefore return unavailable with unknown membership, never absence.
    """

    normalized = identifier.strip().upper()
    query = {"id": normalized}
    if not _CVE.fullmatch(normalized):
        return _invalid(SearchKind.KEV, query, "KEV lookup requires a CVE identifier")
    if services.kev is None:
        status = SourceStatus(
            "kev", SourceState.UNAVAILABLE, diagnostic="required KEV source is not configured",
        )
        return _unavailable(SearchKind.KEV, query, [], [status])
    try:
        response = services.kev.fetch_ids()
    except Exception as error:
        response = SourceResult(frozenset(), _failed_status("kev", error))
    if response.status.state is not SourceState.OK:
        return AdvisorySearchResult(
            kind=SearchKind.KEV, query=query, sources=[response.status], kev_member=None,
            status=SearchStatus.UNAVAILABLE, exit_code=2,
        )
    return AdvisorySearchResult.completed(
        SearchKind.KEV, query, kev_member=normalized in response.value,
        sources=[response.status],
    )


def format_json(
    result: AdvisorySearchResult,
    *,
    credential_values: Iterable[str] = (),
) -> str:
    """Return deterministic redacted JSON with explicit informational scope."""

    payload = _sanitize_value(result.to_dict(), credential_values)
    payload["sources"] = sorted(
        payload.get("sources", []),
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False),
    )
    payload["informational_only"] = True
    payload["notice"] = INFORMATIONAL_NOTICE
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def format_text(
    result: AdvisorySearchResult,
    *,
    credential_values: Iterable[str] = (),
) -> str:
    """Return concise text whose status meaning is understandable without color.

    Remote descriptions are intentionally omitted from this concise view; identifiers and source
    diagnostics are escaped and redacted, so embedded instructions remain inert data.
    """

    secrets = tuple(item for item in credential_values if item)
    lines = [
        INFORMATIONAL_NOTICE,
        f"Search: {result.kind.value}",
        f"Status: {result.status.value}",
    ]
    if result.kind is SearchKind.KEV:
        membership = "unknown" if result.kev_member is None else (
            "present" if result.kev_member else "absent"
        )
        lines.append(f"KEV membership: {membership}")
    if result.empty and result.status is SearchStatus.COMPLETE:
        lines.append("No matching records.")
    for advisory in sorted(result.advisories, key=lambda item: item.id):
        aliases = ", ".join(sorted(advisory.aliases)) or "none"
        lines.append(
            f"Advisory: {_plain(advisory.id, secrets)} | aliases: {_plain(aliases, secrets)} | "
            f"severity: {_plain(advisory.severity, secrets)}"
        )
    for status in sorted(result.sources, key=lambda item: (item.source.casefold(), item.state.value)):
        diagnostic = f" | {_plain(status.diagnostic, secrets)}" if status.diagnostic else ""
        lines.append(
            f"Source: {_plain(status.source, secrets)} | {status.state.value}{diagnostic}"
        )
    return "\n".join(lines) + "\n"


def sanitize_diagnostic(value: object, credential_values: Iterable[str] = ()) -> str:
    """Return bounded redacted text safe for parser and validation stderr.

    CLI argument errors echo hostile user input before source clients exist. Applying the same
    structural and configured-value protections here prevents that local boundary from bypassing
    the output redaction contract.
    """

    return _sanitize_text(str(value), credential_values)[:512]


def _invalid(kind: SearchKind, query: Mapping[str, str], diagnostic: str
             ) -> AdvisorySearchResult:
    return AdvisorySearchResult(
        kind=kind, query=dict(query), status=SearchStatus.INVALID, exit_code=3,
        sources=[SourceStatus("validation", SourceState.NOT_APPLICABLE, diagnostic=diagnostic)],
    )


def _unavailable(kind: SearchKind, query: Mapping[str, str], advisories: list[Advisory],
                 statuses: list[SourceStatus]) -> AdvisorySearchResult:
    return AdvisorySearchResult(
        kind=kind, query=dict(query), advisories=list(advisories), sources=list(statuses),
        status=SearchStatus.UNAVAILABLE, exit_code=2,
    )


def _is_exact_version(version: str, ecosystem: str) -> bool:
    """Apply inventory-equivalent resolved-version rules for the selected ecosystem.

    The inventory validator owns locator, branch, range, whitespace, and ecosystem-specific
    SemVer/Go contracts. Search adds an explicit floating-segment rejection because generic
    ecosystems may otherwise parse labels such as ``1.x`` as opaque release text.
    """

    normalized = ecosystem.strip().casefold()
    inventory_ecosystem = {
        "crates.io": "cargo",
        "rust": "cargo",
        "go": "golang",
    }.get(normalized, normalized)
    return (
        not _FLOATING_VERSION.search(version)
        and _inventory_exact_version(version, inventory_ecosystem)
    )


def _failed_status(source: str, error: object) -> SourceStatus:
    return SourceStatus(
        source, SourceState.UNAVAILABLE,
        diagnostic=f"{source} search failed: {_sanitize_text(str(error), ())}",
    )


def _lookup_optional(
    source: str, service: AdvisoryLookupService, identifier: str
) -> SourceResult[Advisory | None]:
    try:
        return service.lookup(identifier)
    except Exception as error:
        return SourceResult(None, _failed_status(source, error))


def _record_identifiers(records: Iterable[Advisory]) -> list[str]:
    return sorted({
        identifier.strip().upper()
        for advisory in records
        for identifier in (advisory.id, *advisory.aliases)
        if identifier.strip()
    })


def _sanitize_value(value: Any, secrets: Iterable[str]) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value, secrets, preserve_newlines=True)
    if isinstance(value, Mapping):
        return {str(key): _sanitize_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, secrets) for item in value]
    return value


def _sanitize_text(value: str, secrets: Iterable[str], *, preserve_newlines: bool = False) -> str:
    text = value
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = _URL_USERINFO.sub(r"\1[REDACTED]@", text)
    text = _CREDENTIAL.sub(lambda match: f"{match.group('key')}: [REDACTED]", text)
    clean: list[str] = []
    for character in text:
        if preserve_newlines and character in "\n\t":
            clean.append(character)
        elif unicodedata.category(character).startswith("C"):
            clean.append(" ")
        else:
            clean.append(character)
    return "".join(clean)


def _plain(value: str, secrets: Iterable[str]) -> str:
    sanitized = _sanitize_text(str(value), secrets).replace("\n", " ").replace("\r", " ")
    return html.escape(sanitized, quote=True)
