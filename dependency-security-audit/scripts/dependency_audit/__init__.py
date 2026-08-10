"""Dependency vulnerability auditing and advisory-search primitives.

The package keeps source access, policy, and reporting behind explicit models so the
standalone CLIs and spec-driven integrations share one evidence contract.
"""

from .models import (
    Advisory,
    AdvisoryEnrichment,
    AdvisorySearchResult,
    AffectedEvent,
    AffectedEventKind,
    AffectedPackage,
    AffectedRange,
    AuditMode,
    AuditResult,
    Decision,
    DependencyScope,
    Finding,
    GateStatus,
    InventoryResult,
    PackageRef,
    Reachability,
    SearchKind,
    SearchStatus,
    SourceState,
    SourceStatus,
)

__all__ = [
    "Advisory", "AdvisoryEnrichment", "AdvisorySearchResult", "AffectedEvent", "AffectedEventKind",
    "AffectedPackage", "AffectedRange", "AuditMode", "AuditResult", "Decision",
    "DependencyScope", "Finding", "GateStatus", "InventoryResult", "PackageRef",
    "Reachability", "SearchKind", "SearchStatus", "SourceState", "SourceStatus",
]
