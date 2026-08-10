"""Load reviewable reachability evidence without inferring safe exclusion.

Annotations are keyed by ``<package-purl>|<advisory-id>`` and use the states
``reachable``, ``unreachable``, ``unknown``, or ``not_assessed``. Reachable proof methods are
``direct_call``, ``runtime_loading``, ``enabled_configuration``, ``execution_trace``, and
``dynamic_analysis``; unreachable proof methods are ``delivered_artifact_exclusion``,
``call_graph_exclusion``, and ``configuration_exclusion``. Every reachable or unreachable
claim must link concrete evidence. Absence of a direct import never proves exclusion because an
indirect call, dynamic load, or enabled configuration can still execute the vulnerable surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Mapping

from .models import Reachability


_REACHABLE_METHODS = frozenset({
    "direct_call",
    "runtime_loading",
    "enabled_configuration",
    "execution_trace",
    "dynamic_analysis",
})
_UNREACHABLE_METHODS = frozenset({
    "delivered_artifact_exclusion",
    "call_graph_exclusion",
    "configuration_exclusion",
})
_MAX_INPUT_BYTES = 1024 * 1024
_SCHEMA_VERSION = re.compile(r"^(?P<major>0|[1-9][0-9]*)(?:\.[0-9]+)*$")


class _JsonObject(list[tuple[str, object]]):
    """Distinguish decoded JSON objects from arrays until duplicate checks finish."""


def _materialize_json(value: object) -> tuple[object, bool]:
    """Convert pair-preserving JSON objects while detecting every duplicate key."""

    duplicate = False
    if isinstance(value, _JsonObject):
        result: dict[str, object] = {}
        seen: set[str] = set()
        for key, child in value:
            converted, nested_duplicate = _materialize_json(child)
            duplicate = duplicate or nested_duplicate or key in seen
            seen.add(key)
            result[key] = converted
        return result, duplicate
    if isinstance(value, list):
        result_list: list[object] = []
        for child in value:
            converted, nested_duplicate = _materialize_json(child)
            duplicate = duplicate or nested_duplicate
            result_list.append(converted)
        return result_list, duplicate
    return value, False


def _supported_schema_version(value: object) -> bool:
    """Accept compatible schema minors while rejecting ambiguous version text."""

    if not isinstance(value, str):
        return False
    match = _SCHEMA_VERSION.fullmatch(value)
    return bool(match and match.group("major") == "1")


@dataclass(frozen=True)
class ReachabilityAssessment:
    """Describe the evidence-backed state for one exact package/advisory pair.

    Methods, evidence references, producers, and timestamps remain attached to the
    result so a reviewer can evaluate how the state was established. Empty metadata
    is intentional for missing or rejected annotations: it prevents unsupported
    claims from being presented as evidence.
    """

    state: Reachability
    methods: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    producers: tuple[str, ...] = ()
    timestamps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReachabilityResult:
    """Contain normalized assessments and validation diagnostics for one input.

    ``available`` means at least the requested evidence input could be interpreted;
    ``complete`` additionally means every annotation was valid. Missing annotations
    resolve to ``default_state`` so an absent optional file remains ``not_assessed``,
    while a corrupt supplied file fails closed to ``unknown``. Compatible schema minor
    versions and unknown fields are tolerated; duplicate JSON keys reject the whole input
    before parser overwrite behavior can discard stronger evidence.
    """

    assessments: Mapping[str, ReachabilityAssessment] = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    available: bool = True
    complete: bool = True
    default_state: Reachability = Reachability.NOT_ASSESSED

    def lookup(self, purl: str, advisory_id: str) -> ReachabilityAssessment:
        """Return evidence for an exact package/advisory key.

        Args:
            purl: Exact package URL, including the resolved version when available.
            advisory_id: Stable advisory identifier used by the normalized finding.

        Returns:
            The recorded assessment, or a metadata-free assessment using the input's
            conservative default when that exact pair has no annotation.
        """

        return self.assessments.get(
            f"{purl}|{advisory_id}", ReachabilityAssessment(self.default_state)
        )


def _safe_label(value: object) -> str:
    """Bound diagnostic identifiers and remove control characters."""

    text = "".join(character if character.isprintable() else "?" for character in str(value))
    return text[:200]


def _valid_timestamp(value: object) -> bool:
    """Return whether a timestamp is an ISO-8601 value with an explicit timezone."""

    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _invalid_assessment() -> ReachabilityAssessment:
    """Create the fail-closed value used for rejected annotation claims."""

    return ReachabilityAssessment(Reachability.UNKNOWN)


def _parse_candidate(
    key: str, raw: object
) -> tuple[ReachabilityAssessment, str | None, bool]:
    """Validate one producer record and retain only evidence relevant to its state."""

    if not isinstance(raw, Mapping):
        return _invalid_assessment(), f"{_safe_label(key)}: annotation must be an object", False

    status = raw.get("status")
    method = raw.get("method")
    evidence = raw.get("evidence")
    producer = raw.get("producer")
    timestamp = raw.get("timestamp")

    try:
        state = Reachability(status)
    except (TypeError, ValueError):
        return _invalid_assessment(), f"{_safe_label(key)}: unsupported reachability status", False

    if not isinstance(method, str) or not method.strip():
        return _invalid_assessment(), f"{_safe_label(key)}: method is required", False
    if (
        not isinstance(evidence, list)
        or any(not isinstance(item, str) or not item.strip() for item in evidence)
    ):
        return _invalid_assessment(), f"{_safe_label(key)}: evidence must be a string list", False
    if not isinstance(producer, str) or not producer.strip():
        return _invalid_assessment(), f"{_safe_label(key)}: producer is required", False
    if not _valid_timestamp(timestamp):
        return _invalid_assessment(), f"{_safe_label(key)}: timestamp must include a timezone", False

    method = method.strip()
    normalized_evidence = tuple(sorted(set(item.strip() for item in evidence)))
    metadata = {
        "methods": (method,),
        "evidence": normalized_evidence,
        "producers": (producer.strip(),),
        "timestamps": (timestamp,),
    }

    if state is Reachability.REACHABLE:
        if method not in _REACHABLE_METHODS or not normalized_evidence:
            return (
                _invalid_assessment(),
                f"{_safe_label(key)}: reachable claim lacks accepted execution evidence",
                False,
            )
        return ReachabilityAssessment(state, **metadata), None, True

    if state is Reachability.UNREACHABLE:
        if method not in _UNREACHABLE_METHODS or not normalized_evidence:
            return (
                _invalid_assessment(),
                f"{_safe_label(key)}: unreachable claim lacks concrete exclusion evidence",
                False,
            )
        return ReachabilityAssessment(state, **metadata), None, True

    return ReachabilityAssessment(state, **metadata), None, True


def _merge_assessments(
    key: str,
    candidates: list[tuple[ReachabilityAssessment, bool]],
) -> tuple[ReachabilityAssessment, str | None]:
    """Resolve multiple producer claims without discarding direct execution evidence."""

    valid = [assessment for assessment, accepted in candidates if accepted]
    invalid_present = any(not accepted for _, accepted in candidates)
    reachable = [item for item in valid if item.state is Reachability.REACHABLE]
    states = {item.state for item in valid}

    if reachable:
        conflict = invalid_present or states != {Reachability.REACHABLE}
        return _combine(Reachability.REACHABLE, reachable), (
            f"{_safe_label(key)}: conflicting annotations; reachable evidence retained"
            if conflict else None
        )

    if invalid_present:
        return _invalid_assessment(), f"{_safe_label(key)}: invalid annotation prevents exclusion"
    if not valid:
        return _invalid_assessment(), f"{_safe_label(key)}: annotation list is empty"
    if len(states) != 1:
        return _invalid_assessment(), f"{_safe_label(key)}: conflicting annotations resolve to unknown"

    state = next(iter(states))
    return _combine(state, valid), None


def _combine(
    state: Reachability, assessments: list[ReachabilityAssessment]
) -> ReachabilityAssessment:
    """Combine agreeing producer evidence into deterministic review fields."""

    return ReachabilityAssessment(
        state=state,
        methods=tuple(sorted({item for value in assessments for item in value.methods})),
        evidence=tuple(sorted({item for value in assessments for item in value.evidence})),
        producers=tuple(sorted({item for value in assessments for item in value.producers})),
        timestamps=tuple(sorted({item for value in assessments for item in value.timestamps})),
    )


def load_reachability(path: Path | None) -> ReachabilityResult:
    """Load structured reachability annotations from an optional JSON file.

    The document must be at most 1 MiB, use schema major version ``1``, and contain an
    ``annotations`` object keyed by ``<package-purl>|<advisory-id>``. Accepted states are
    ``reachable``, ``unreachable``, ``unknown``, and ``not_assessed``. Reachable methods are
    ``direct_call``, ``runtime_loading``, ``enabled_configuration``, ``execution_trace``, and
    ``dynamic_analysis``; unreachable methods are ``delivered_artifact_exclusion``,
    ``call_graph_exclusion``, and ``configuration_exclusion``. A key may contain one annotation
    or a list of independent producer annotations. Valid reachable evidence wins a conflict
    because observed execution cannot be negated by static analysis. A missing direct import is
    only ``unknown``: indirect calls, dynamic loading, and configuration-driven paths may still
    execute the vulnerable surface. All other conflicts resolve to ``unknown``. The size and
    nesting limits keep untrusted evidence from exhausting the audit process.

    Args:
        path: Annotation document, or ``None`` when no reachability assessment was supplied.

    Returns:
        Normalized assessments, bounded validation diagnostics, and availability/completeness
        flags. File and schema errors do not raise; they return an unavailable result whose
        missing keys resolve to ``unknown``.
    """

    if path is None:
        return ReachabilityResult()

    try:
        with path.open("rb") as stream:
            raw_document = stream.read(_MAX_INPUT_BYTES + 1)
    except OSError:
        return ReachabilityResult(
            diagnostics=("reachability evidence file is unreadable or invalid JSON",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    if len(raw_document) > _MAX_INPUT_BYTES:
        return ReachabilityResult(
            diagnostics=("reachability evidence file exceeds 1 MiB limit",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    try:
        decoded = json.loads(
            raw_document.decode("utf-8"), object_pairs_hook=_JsonObject
        )
    except (UnicodeError, json.JSONDecodeError):
        return ReachabilityResult(
            diagnostics=("reachability evidence file is unreadable or invalid JSON",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )
    except RecursionError:
        return ReachabilityResult(
            diagnostics=("reachability evidence exceeds nesting limit",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    try:
        document, has_duplicate = _materialize_json(decoded)
    except RecursionError:
        return ReachabilityResult(
            diagnostics=("reachability evidence exceeds nesting limit",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )
    if has_duplicate:
        return ReachabilityResult(
            diagnostics=("duplicate JSON object key rejected",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    if not isinstance(document, Mapping):
        return ReachabilityResult(
            diagnostics=("reachability document must be an object",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )
    if not _supported_schema_version(document.get("schema_version")):
        return ReachabilityResult(
            diagnostics=("unsupported reachability schema version",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    raw_annotations = document.get("annotations")
    if not isinstance(raw_annotations, Mapping):
        return ReachabilityResult(
            diagnostics=("reachability annotations must be an object",),
            available=False,
            complete=False,
            default_state=Reachability.UNKNOWN,
        )

    assessments: dict[str, ReachabilityAssessment] = {}
    diagnostics: list[str] = []
    accepted_keys = 0

    for raw_key, raw_value in raw_annotations.items():
        key = str(raw_key)
        purl, separator, advisory_id = key.rpartition("|")
        if not separator or not purl.startswith("pkg:") or not advisory_id.strip():
            diagnostics.append(f"{_safe_label(key)}: invalid annotation key")
            continue

        records = raw_value if isinstance(raw_value, list) else [raw_value]
        parsed: list[tuple[ReachabilityAssessment, bool]] = []
        for record in records:
            assessment, diagnostic, accepted = _parse_candidate(key, record)
            parsed.append((assessment, accepted))
            if diagnostic:
                diagnostics.append(diagnostic)

        assessment, conflict_diagnostic = _merge_assessments(key, parsed)
        assessments[key] = assessment
        accepted_keys += 1
        if conflict_diagnostic:
            diagnostics.append(conflict_diagnostic)

    complete = not diagnostics
    available = not raw_annotations or accepted_keys > 0
    return ReachabilityResult(
        assessments=assessments,
        diagnostics=tuple(diagnostics),
        available=available,
        complete=complete,
        default_state=Reachability.NOT_ASSESSED,
    )
