#!/usr/bin/env python3
"""Opt-in live smoke test for the dependency-security source adapters.

Run with::

    PYTHONDONTWRITEBYTECODE=1 python3 tests/live_smoke.py

The command requires DNS and outbound HTTPS access to ``api.osv.dev`` and ``www.cisa.gov``.
It requires no credentials, keeps all response data in memory, and prints only the UTC date plus
sanitized source states. Assertions cover stable schemas and identifier/package relationships;
they deliberately avoid advisory counts, severity text, descriptions, and catalog timestamps.

This check supplements rather than replaces the deterministic offline suite: remote availability
and upstream data can change independently of this repository, while fixtures make regressions
repeatable and suitable for required CI.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import NoReturn


TESTS = Path(__file__).resolve().parent
SCRIPTS = TESTS.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.http import RetryingHttpClient, redact_diagnostic  # noqa: E402
from dependency_audit.models import Advisory, PackageRef, SourceState  # noqa: E402
from dependency_audit.sources import KevClient, OsvClient  # noqa: E402


TARGET_ID = "GHSA-9HJG-9R4M-MVJ7"
TARGET_LOOKUP_ID = "GHSA-9hjg-9r4m-mvj7"
TARGET_ALIAS = "CVE-2024-47081"
VULNERABLE = PackageRef(
    ecosystem="PyPI",
    name="requests",
    version="2.31.0",
    purl="pkg:pypi/requests@2.31.0",
)
FIXED = PackageRef(
    ecosystem="PyPI",
    name="requests",
    version="2.32.4",
    purl="pkg:pypi/requests@2.32.4",
)
_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$")


class _SmokeFailure(RuntimeError):
    """Represent an explicit source or stable-contract failure."""


def _safe(value: object) -> str:
    """Make one bounded diagnostic inert before writing it to the terminal."""
    redacted = redact_diagnostic(value)
    return " ".join("".join(character if character >= " " else " " for character in redacted).split())


def _fail(message: str) -> NoReturn:
    """Stop at the first violated smoke-test contract with a concise diagnostic."""
    raise _SmokeFailure(message)


def _identifiers(advisory: Advisory) -> frozenset[str]:
    """Return normalized stable identifiers without exposing advisory prose."""
    return frozenset(value.strip().upper() for value in (advisory.id, *advisory.aliases) if value.strip())


def _observe(result: object, statuses: dict[str, str], operation: str) -> None:
    """Record a source state and reject anything short of a complete live response."""
    status = result.status  # type: ignore[attr-defined]
    source = _safe(status.source) or "unknown"
    statuses[source] = status.state.value
    if status.state is not SourceState.OK:
        detail = _safe(status.diagnostic) or status.state.value
        _fail(f"{operation} did not complete: {detail}")


def _exercise_sources(statuses: dict[str, str]) -> None:
    """Exercise current OSV and KEV endpoints using only durable relationship assertions."""
    http = RetryingHttpClient()
    osv = OsvClient(http)

    vulnerable = osv.query((VULNERABLE,))
    _observe(vulnerable, statuses, "OSV vulnerable-version query")
    vulnerable_records = [
        advisory for advisory in vulnerable.value if TARGET_ID in _identifiers(advisory)
    ]
    if not vulnerable_records:
        _fail("OSV vulnerable-version query omitted the expected stable advisory identity")

    fixed = osv.query((FIXED,))
    _observe(fixed, statuses, "OSV fixed-version query")
    if any(TARGET_ID in _identifiers(advisory) for advisory in fixed.value):
        _fail("OSV fixed-version query still returned the target advisory")

    complete = osv.lookup(TARGET_LOOKUP_ID)
    _observe(complete, statuses, "OSV complete-record lookup")
    advisory = complete.value
    if advisory is None or advisory.id.strip().upper() != TARGET_ID:
        _fail("OSV complete-record lookup returned a mismatched identity")
    if TARGET_ALIAS not in _identifiers(advisory):
        _fail("OSV complete record omitted the expected stable CVE alias")
    matching_packages = [
        affected
        for affected in advisory.affected_packages
        if affected.ecosystem == "PyPI" and affected.name == "requests"
    ]
    if not matching_packages:
        _fail("OSV complete record omitted package-scoped requests evidence")
    if not any(FIXED.version in affected.fixed_versions for affected in matching_packages):
        _fail("OSV complete record omitted the package-scoped fixed-version transition")
    if not (_identifiers(vulnerable_records[0]) & _identifiers(advisory)):
        _fail("OSV query and complete record do not share a stable advisory identity")

    # The complete public catalog is currently larger than the general advisory-response bound;
    # retain a finite source-specific ceiling so the live check exercises the whole feed.
    kev = KevClient(RetryingHttpClient(max_bytes=5_000_000)).fetch_ids()
    _observe(kev, statuses, "KEV catalog fetch")
    if not isinstance(kev.value, frozenset):
        _fail("KEV catalog did not normalize to an immutable identifier set")
    if any(not _CVE.fullmatch(identifier) for identifier in kev.value):
        _fail("KEV catalog contained a non-CVE normalized identifier")


def main() -> int:
    """Run the supplementary live checks and return zero only for complete stable evidence.

    The JSON summary intentionally excludes live records, counts, timestamps, and remote prose so
    operators can retain terminal output without turning it into an unsanitized response cache.
    """
    statuses: dict[str, str] = {}
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        _exercise_sources(statuses)
    except Exception as error:  # A smoke script must convert transport surprises into explicit failure.
        print(json.dumps({
            "date": today,
            "result": "fail",
            "sources": [{"source": source, "state": statuses[source]} for source in sorted(statuses)],
            "diagnostic": _safe(error) or "unexpected live smoke failure",
        }, sort_keys=True))
        return 1
    print(json.dumps({
        "date": today,
        "result": "pass",
        "sources": [{"source": source, "state": statuses[source]} for source in sorted(statuses)],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
