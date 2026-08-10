"""Versioned evidence models shared by auditing and advisory search.

The models contain no network or policy behavior. Keeping serialization at this boundary
deterministic lets reports, fixtures, and automation compare evidence without Python internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0"


class AuditMode(str, Enum):
    """Select the freshness and completeness contract for an audit run."""
    CHANGE = "change"
    MAIN = "main"
    RELEASE = "release"


class DependencyScope(str, Enum):
    """Describe whether a resolved package can affect the delivered runtime."""
    RUNTIME = "runtime"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"


class Reachability(str, Enum):
    """Represent evidence about execution of the advisory's vulnerable surface."""
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"


class Decision(str, Enum):
    """Represent the policy outcome for one normalized finding."""
    EXCLUDED = "excluded"
    WARN = "warn"
    BLOCK = "block"


class GateStatus(str, Enum):
    """Represent aggregate results without conflating warnings and missing evidence."""
    PASS = "pass"
    WARNINGS = "warnings"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class SourceState(str, Enum):
    """Describe whether an evidence source completed its responsibility."""
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class SearchKind(str, Enum):
    """Identify a reusable advisory-search operation."""
    PACKAGE = "package"
    ADVISORY = "advisory"
    KEV = "kev"


class SearchStatus(str, Enum):
    """Distinguish completed search from source failure or invalid input."""
    COMPLETE = "complete"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class AffectedEventKind(str, Enum):
    """Name an OSV-compatible transition in an ordered affected range."""
    INTRODUCED = "introduced"
    FIXED = "fixed"
    LAST_AFFECTED = "last_affected"
    LIMIT = "limit"


def utc_now() -> str:
    """Return a timezone-explicit UTC timestamp suitable for durable evidence."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    """Convert model values to plain, deterministically ordered JSON values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, _Serializable):
        return value.to_dict()
    if is_dataclass(value):
        return {item.name: _json_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    return value


class _Serializable:
    """Provide explicit plain-data serialization for public evidence models."""
    def to_dict(self) -> dict[str, Any]:
        """Return JSON-compatible fields while preserving declared schema names."""
        return {item.name: _json_value(getattr(self, item.name)) for item in fields(self)}


@dataclass(frozen=True)
class PackageRef(_Serializable):
    """Identify one exact resolved package and its delivery relevance.

    Exact versions are mandatory because advisory ranges cannot safely use floating constraints.
    """
    ecosystem: str
    name: str
    version: str
    purl: str
    direct: bool = False
    scope: DependencyScope = DependencyScope.UNKNOWN
    bom_ref: str | None = None


@dataclass(frozen=True)
class AffectedEvent(_Serializable):
    """Preserve one range transition and its source-defined ordering.

    Event order is meaningful: a record may contain multiple introduced/fixed intervals, so
    callers must not sort or flatten events while deciding whether a version is affected.
    """
    kind: AffectedEventKind
    value: str


@dataclass(frozen=True)
class AffectedRange(_Serializable):
    """Retain a typed affected range without reducing it to display text."""
    type: str
    events: tuple[AffectedEvent, ...] = ()
    repo: str | None = None


@dataclass(frozen=True)
class AffectedPackage(_Serializable):
    """Keep affected evidence scoped to exactly one package identity.

    Fixes and ranges must remain attached to this identity so a multi-package advisory cannot
    accidentally recommend one package's fixed version for another package.
    """
    ecosystem: str
    name: str
    purl: str | None = None
    versions: tuple[str, ...] = ()
    ranges: tuple[AffectedRange, ...] = ()
    fixed_versions: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Canonicalize set-like values while preserving each range's event order."""
        encoded = super().to_dict()
        encoded["versions"] = sorted(set(encoded["versions"]))
        encoded["fixed_versions"] = sorted(set(encoded["fixed_versions"]))
        encoded["ranges"] = sorted(
            encoded["ranges"],
            key=lambda item: (
                item["type"], item["repo"] or "",
                tuple((event["kind"], event["value"]) for event in item["events"]),
            ),
        )
        return encoded


@dataclass(frozen=True)
class AdvisoryEnrichment(_Serializable):
    """Retain secondary-source evidence without changing OSV applicability.

    Values stay source-scoped so disagreement remains reviewable. Source clients normalize the
    policy-facing severity separately and must not treat these metrics as affected-version proof.
    """
    source: str
    severity: str = "unknown"
    cvss_scores: tuple[float, ...] = ()
    cvss_vectors: tuple[str, ...] = ()
    epss_scores: tuple[float, ...] = ()
    vulnerable_functions: tuple[str, ...] = ()
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Canonicalize source evidence whose input ordering has no meaning."""
        encoded = super().to_dict()
        for key in ("cvss_scores", "cvss_vectors", "epss_scores", "vulnerable_functions"):
            encoded[key] = sorted(set(encoded[key]))
        return encoded


@dataclass(frozen=True)
class Advisory(_Serializable):
    """Normalize a vulnerability record without pooling multi-package evidence.

    ``affected_packages`` is the complete source evidence. The flat ``fixed_versions`` and
    ``affected_ranges`` fields are retained as a compatibility projection only: source clients
    may populate them for the exact package bound to a finding, never by combining packages.
    """
    id: str
    aliases: tuple[str, ...] = ()
    severity: str = "unknown"
    withdrawn: bool = False
    fixed_versions: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    affected_ranges: tuple[str, ...] = ()
    modified: str | None = None
    details: str = ""
    source: str = ""
    affected_packages: tuple[AffectedPackage, ...] = ()
    enrichments: tuple[AdvisoryEnrichment, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize set-like fields canonically for stable evidence comparisons."""
        encoded = super().to_dict()
        for key in ("aliases", "fixed_versions", "references", "affected_ranges"):
            encoded[key] = sorted(set(encoded[key]))
        encoded["affected_packages"] = sorted(
            encoded["affected_packages"],
            key=lambda item: (
                item["ecosystem"].casefold(), item["ecosystem"],
                item["name"].casefold(), item["name"], item["purl"] or "",
            ),
        )
        encoded["enrichments"] = sorted(
            encoded["enrichments"],
            key=lambda item: (
                item["source"].casefold(), item["severity"], tuple(item["cvss_scores"]),
                tuple(item["cvss_vectors"]), tuple(item["epss_scores"]),
                tuple(item["vulnerable_functions"]), item["details"],
            ),
        )
        return encoded


@dataclass(frozen=True)
class SourceStatus(_Serializable):
    """Record a source attempt so missing evidence cannot appear clean."""
    source: str
    state: SourceState
    attempted_at: str = field(default_factory=utc_now)
    provenance: str = ""
    diagnostic: str = ""


@dataclass
class InventoryResult(_Serializable):
    """Capture an exact package graph and whether it is policy-complete."""
    packages: list[PackageRef] = field(default_factory=list)
    dependencies: list[tuple[str, str]] = field(default_factory=list)
    fingerprint: str = ""
    complete: bool = False
    statuses: list[SourceStatus] = field(default_factory=list)
    incomplete_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize packages and graph edges in canonical order."""
        encoded = super().to_dict()
        encoded["packages"] = sorted(encoded["packages"], key=lambda item: (
            item["ecosystem"], item["name"], item["version"], item["purl"]
        ))
        encoded["dependencies"] = sorted(encoded["dependencies"])
        encoded["incomplete_reasons"] = sorted(set(encoded["incomplete_reasons"]))
        return encoded


@dataclass(frozen=True)
class Finding(_Serializable):
    """Bind a present package to advisory and policy evidence."""
    package: PackageRef
    advisory: Advisory
    kev: bool = False
    reachability: Reachability = Reachability.NOT_ASSESSED
    reachability_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecisionRecord(_Serializable):
    """Explain a deterministic finding decision with stable reason codes."""
    decision: Decision
    reason_codes: tuple[str, ...]
    mitigation: str = ""
    risk_acceptance: str = ""


@dataclass
class AuditResult(_Serializable):
    """Represent the complete versioned evidence of one audit invocation."""
    mode: AuditMode
    timestamp: str = field(default_factory=utc_now)
    project_revision: str = ""
    inventory: InventoryResult = field(default_factory=InventoryResult)
    sources: list[SourceStatus] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    decisions: list[DecisionRecord] = field(default_factory=list)
    gate_status: GateStatus = GateStatus.PASS
    exit_code: int = 0
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def empty(cls, mode: AuditMode) -> "AuditResult":
        """Create an unclassified result for services to populate."""
        return cls(mode=mode)

    def to_dict(self) -> dict[str, Any]:
        """Serialize findings deterministically with versioned evidence."""
        encoded = super().to_dict()
        encoded["findings"] = sorted(encoded["findings"], key=lambda item: (
            item["package"]["purl"], item["advisory"]["id"]
        ))
        return encoded


@dataclass
class AdvisorySearchResult(_Serializable):
    """Represent an informational query without implying project safety."""
    kind: SearchKind
    query: dict[str, str]
    sources: list[SourceStatus] = field(default_factory=list)
    advisories: list[Advisory] = field(default_factory=list)
    kev_member: bool | None = None
    status: SearchStatus = SearchStatus.COMPLETE
    exit_code: int = 0
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def completed(
        cls,
        kind: SearchKind,
        query: Mapping[str, str],
        advisories: list[Advisory] | None = None,
        kev_member: bool | None = None,
        sources: list[SourceStatus] | None = None,
    ) -> "AdvisorySearchResult":
        """Create a successful search, including an explicit no-match result."""
        return cls(kind=kind, query=dict(query), advisories=list(advisories or ()),
                   kev_member=kev_member, sources=list(sources or ()))

    @property
    def empty(self) -> bool:
        """Return true only for a completed query that produced no match.

        Unavailable and invalid queries have no trustworthy match result, so labeling either
        ``empty`` would conflate missing evidence with a verified zero-result search.
        """
        return (
            self.status is SearchStatus.COMPLETE
            and not self.advisories
            and self.kev_member is not True
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize query/results canonically and expose explicit emptiness."""
        encoded = super().to_dict()
        encoded["advisories"] = sorted(encoded["advisories"], key=lambda item: item["id"])
        encoded["empty"] = self.empty
        return encoded
