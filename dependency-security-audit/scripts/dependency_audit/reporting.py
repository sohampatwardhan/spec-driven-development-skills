"""Render and durably persist dependency-audit evidence.

JSON is the canonical versioned record; the Markdown view is generated from the same
``AuditResult`` and uses explicit text labels so security meaning never depends on color.
Remote text is inert data: it is redacted, stripped of controls, and Markdown/HTML escaped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from .models import AuditMode, AuditResult, Decision, DecisionRecord, Finding, GateStatus


_CREDENTIAL_PATTERN = re.compile(
    r"""(?ix)
    (?<![\w-])(?P<key_quote>["']?)
    (?P<key>
        (?:proxy-)?authorization
        | api[_-]?key
        | access[_-]?token
        | refresh[_-]?token
        | token
        | password
        | secret
    )
    (?P=key_quote)\s*[:=]\s*(?:(?:bearer|basic)\s+)?
    (?:
        \[REDACTED\]
        | "(?:\\.|[^"\\\r\n])*"
        | '(?:\\.|[^'\\\r\n])*'
        | [^\s,;}\]]+
    )
    """
)
_URL_USERINFO_PATTERN = re.compile(r"(?i)\b(https?://)[^/\s@]+@")
_MARKDOWN_CONTROL = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")


@dataclass(frozen=True)
class ReportPaths:
    """Name the evidence files produced by a successful report write.

    Timestamped paths are absent in change mode because only main and release runs carry the
    immutable retention contract.
    """

    latest_json: Path
    latest_markdown: Path
    evidence_json: Path | None = None
    evidence_markdown: Path | None = None


class ReportWriteError(RuntimeError):
    """Report a sanitized persistence failure without presenting incomplete output as success."""

    def __init__(self, diagnostic: str) -> None:
        super().__init__(diagnostic)
        self.diagnostic = diagnostic


def render_json(
    result: AuditResult,
    *,
    credential_values: Iterable[str] = (),
) -> str:
    """Serialize one audit as canonical, schema-versioned, redacted JSON evidence.

    Source order and other set-like collections are normalized so equivalent evidence produces
    byte-stable output. Configured credential values supplement structural secret redaction;
    blank values are ignored to avoid replacing every string boundary.

    Args:
        result: Completed audit evidence to serialize.
        credential_values: Exact sensitive values that must be removed from output.

    Returns:
        UTF-8 JSON text ending in one newline.
    """

    payload = result.to_dict()
    # AuditResult canonicalizes findings, but decisions are a positional companion collection.
    # Sort the pairs together here so machine readers cannot associate a decision with the wrong
    # package merely because the controller supplied findings in a different order.
    ordered_pairs, unmatched_findings, unmatched_decisions = _ordered_evidence(result)
    payload["findings"] = (
        [finding.to_dict() for finding, _ in ordered_pairs]
        + [finding.to_dict() for finding in unmatched_findings]
    )
    payload["decisions"] = (
        [decision.to_dict() for _, decision in ordered_pairs]
        + [decision.to_dict() for decision in unmatched_decisions]
    )
    payload = _redact_value(payload, credential_values)
    _canonicalize_payload(payload)
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def render_markdown(
    result: AuditResult,
    *,
    credential_values: Iterable[str] = (),
    json_name: str = "latest.json",
    evidence_json_name: str | None = None,
) -> str:
    """Render a human-readable security report from the canonical audit object.

    The report groups decisions into blocks, warnings, and retained exclusions; names missing
    evidence directly; and provides ordinary links that remain understandable in text-only
    readers. Advisory text is displayed only after redaction and escaping, preventing remote
    Markdown, HTML, and control characters from changing report structure.

    Args:
        result: The same completed audit object used for machine-readable JSON.
        credential_values: Exact sensitive values that must be removed from the report.
        json_name: Relative machine-readable evidence link for this Markdown file.
        evidence_json_name: Optional relative immutable-evidence link for main/release reports.

    Returns:
        Markdown text ending in one newline.
    """

    secrets = tuple(item for item in credential_values if item)
    pairs, unmatched_findings, unmatched_decisions = _ordered_evidence(result)
    blocks = [pair for pair in pairs if pair[1].decision is Decision.BLOCK]
    warnings = [pair for pair in pairs if pair[1].decision is Decision.WARN]
    excluded = [pair for pair in pairs if pair[1].decision is Decision.EXCLUDED]
    lines = [
        "# Dependency Security Audit",
        "",
        f"**Result:** {_status_label(result.gate_status)}",
        "",
        "## Audit context",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Mode | {_md(result.mode.value, secrets)} |",
        f"| Completed | {_md(result.timestamp, secrets)} |",
        f"| Project revision | {_md(result.project_revision or 'not recorded', secrets)} |",
        f"| Inventory fingerprint | {_md(result.inventory.fingerprint or 'not available', secrets)} |",
        f"| Inventory completeness | {'complete' if result.inventory.complete else 'incomplete'} |",
        f"| Stable exit code | {result.exit_code} |",
        "",
        "## Report links",
        "",
        f"- [Machine-readable JSON]({_safe_relative_link(json_name)})",
    ]
    if evidence_json_name:
        lines.append(
            f"- [Immutable JSON evidence]({_safe_relative_link(evidence_json_name)})"
        )
    lines.extend(["", "## Source availability", ""])
    if result.sources:
        lines.extend(["| Source | State | Provenance | Diagnostic |", "|---|---|---|---|"])
        for source in sorted(result.sources, key=lambda item: (
            item.source.casefold(), item.state.value, item.attempted_at,
            item.provenance, item.diagnostic,
        )):
            provenance = _safe_url(source.provenance, secrets)
            provenance_cell = (
                f"[source]({provenance})" if provenance else _md(source.provenance or "not recorded", secrets)
            )
            lines.append(
                f"| {_md(source.source, secrets)} | {_md(source.state.value, secrets)} | "
                f"{provenance_cell} | {_md(source.diagnostic or '—', secrets)} |"
            )
    else:
        lines.append("No source attempts were recorded; this report does not establish a clean audit.")

    lines.extend([
        "",
        "## Inventory",
        "",
        f"Resolved packages: **{len(result.inventory.packages)}**.",
    ])
    if result.inventory.incomplete_reasons:
        lines.extend(["", "Incomplete evidence:"])
        lines.extend(
            f"- {_md(reason, secrets)}" for reason in sorted(set(result.inventory.incomplete_reasons))
        )

    _append_findings(lines, "Blocking findings", blocks, secrets)
    _append_findings(lines, "Warnings", warnings, secrets)
    _append_findings(lines, "Excluded findings", excluded, secrets)
    _append_unclassified(lines, unmatched_findings, secrets)
    _append_unmatched_decisions(lines, unmatched_decisions, secrets)

    lines.extend(["", "## Remediation and acceptance", ""])
    actionable = [pair for pair in pairs if pair[1].decision is not Decision.EXCLUDED]
    unmatched_actionable = [
        decision for decision in unmatched_decisions
        if decision.decision is not Decision.EXCLUDED
    ]
    if not actionable and not unmatched_actionable:
        lines.append("No remediation or risk acceptance is recorded because there are no actionable findings.")
    for finding, decision in actionable:
        label = f"{finding.package.name} / {finding.advisory.id}"
        lines.append(f"- **{_md(label, secrets)}:** {_md(decision.mitigation or 'No mitigation recorded.', secrets)}")
        if decision.risk_acceptance:
            lines.append(f"  Risk acceptance: {_md(decision.risk_acceptance, secrets)}")
        elif decision.decision is Decision.WARN:
            lines.append("  Risk acceptance: not recorded.")
    for index, decision in enumerate(unmatched_actionable, start=1):
        lines.append(
            f"- **Unmatched decision {index}:** "
            f"{_md(decision.mitigation or 'No mitigation recorded.', secrets)}"
        )
        lines.append(
            f"  Risk acceptance: {_md(decision.risk_acceptance or 'not recorded.', secrets)}"
        )

    return "\n".join(lines).rstrip() + "\n"


def write_reports(
    result: AuditResult,
    output_dir: Path,
    *,
    credential_values: Iterable[str] = (),
) -> ReportPaths:
    """Atomically refresh latest reports and retain immutable delivery evidence.

    Each file is fully written and synchronized in the target directory before its atomic rename.
    Existing timestamped evidence is never replaced. An identical repeated timestamp reuses the
    retained artifact; conflicting content fails closed before latest reports change. Temporary
    siblings are cleaned after failures, and diagnostics are redacted for safe CLI/report use.

    Args:
        result: Completed evidence used for both JSON and Markdown outputs.
        output_dir: Destination directory, normally ``.security/dependency-audit``.
        credential_values: Exact sensitive values to redact from content and failure diagnostics.

    Returns:
        Paths to refreshed latest output and, for main/release, retained timestamped evidence.

    Raises:
        ReportWriteError: If the directory or any output cannot be durably written. The exception
            never claims audit success and exposes only a sanitized bounded diagnostic.
    """

    output_dir = Path(output_dir)
    secrets = tuple(item for item in credential_values if item)
    latest_json = output_dir / "latest.json"
    latest_markdown = output_dir / "latest.md"
    evidence_json: Path | None = None
    evidence_markdown: Path | None = None
    created_evidence: list[Path] = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_text = render_json(result, credential_values=secrets)
        evidence_stem: str | None = None
        if result.mode in (AuditMode.MAIN, AuditMode.RELEASE):
            evidence_stem = f"audit-{_timestamp_slug(result.timestamp)}"
            evidence_json = output_dir / f"{evidence_stem}.json"
            evidence_markdown = output_dir / f"{evidence_stem}.md"
        markdown_text = render_markdown(
            result,
            credential_values=secrets,
            json_name=latest_json.name,
            evidence_json_name=evidence_json.name if evidence_json else None,
        )

        if evidence_json and evidence_markdown:
            retained_markdown_text = render_markdown(
                result,
                credential_values=secrets,
                json_name=evidence_json.name,
            )
            if _create_immutable(evidence_json, json_text):
                created_evidence.append(evidence_json)
            if _create_immutable(evidence_markdown, retained_markdown_text):
                created_evidence.append(evidence_markdown)
        _atomic_replace_many(((latest_json, json_text), (latest_markdown, markdown_text)))
        return ReportPaths(latest_json, latest_markdown, evidence_json, evidence_markdown)
    except (OSError, ValueError, ReportWriteError) as error:
        for path in reversed(created_evidence):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if isinstance(error, ReportWriteError):
            raise
        diagnostic = _sanitize_text(str(error), secrets)[:400]
        raise ReportWriteError(f"Reports could not be written: {diagnostic}") from error


def _canonicalize_payload(payload: dict[str, Any]) -> None:
    for finding in payload.get("findings", []):
        finding["reachability_evidence"] = sorted(set(finding.get("reachability_evidence", [])))
    for decision in payload.get("decisions", []):
        decision["reason_codes"] = sorted(set(decision.get("reason_codes", [])))
    payload["sources"] = sorted(
        payload.get("sources", []), key=_source_item_key
    )
    inventory = payload.get("inventory", {})
    inventory["statuses"] = sorted(
        inventory.get("statuses", []),
        key=_source_item_key,
    )


def _canonical_item_key(item: Mapping[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _source_item_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("source", "")).casefold(),
        str(item.get("state", "")),
        _canonical_item_key(item),
    )


def _redact_value(value: Any, credential_values: Iterable[str]) -> Any:
    secrets = tuple(item for item in credential_values if item)
    if isinstance(value, str):
        return _sanitize_text(value, secrets, preserve_newlines=True)
    if isinstance(value, Mapping):
        return {str(key): _redact_value(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    return value


def _sanitize_text(
    value: str,
    secrets: Iterable[str],
    *,
    preserve_newlines: bool = False,
) -> str:
    text = value
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = _URL_USERINFO_PATTERN.sub(r"\1[REDACTED]@", text)
    text = _CREDENTIAL_PATTERN.sub(lambda match: f"{match.group('key')}: [REDACTED]", text)
    clean: list[str] = []
    for character in text:
        if preserve_newlines and character in "\n\t":
            clean.append(character)
        elif unicodedata.category(character).startswith("C"):
            clean.append(" ")
        else:
            clean.append(character)
    return "".join(clean)


def _md(value: str, secrets: Iterable[str]) -> str:
    sanitized = _sanitize_text(str(value), secrets).replace("\n", " ").replace("\r", " ")
    escaped_html = html.escape(sanitized, quote=True)
    escaped = _MARKDOWN_CONTROL.sub(r"\\\1", escaped_html)
    # Keep the fixed redaction marker legible to human reviewers; its literal content is trusted.
    return escaped.replace(r"\[REDACTED\]", "[REDACTED]")


def _safe_url(value: str, secrets: Iterable[str]) -> str | None:
    sanitized = _sanitize_text(value, secrets)
    if "[REDACTED]" in sanitized or any(character in sanitized for character in '<>"\'\\'):
        return None
    try:
        parts = urlsplit(sanitized)
    except ValueError:
        return None
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    sensitive_keys = {
        "api_key", "apikey", "access_token", "refresh_token", "token", "password", "secret",
    }
    if any(key.casefold() in sensitive_keys for key, _ in parse_qsl(parts.query, keep_blank_values=True)):
        return None
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        quote(parts.path, safe="/%:@-._~!$&+,;="),
        quote(parts.query, safe="=&%:@/?-._~!$+,;"),
        quote(parts.fragment, safe="-._~!$&+,;=:@/?"),
    ))


def _safe_relative_link(value: str) -> str:
    return Path(value).name.replace("(", "%28").replace(")", "%29")


def _ordered_evidence(
    result: AuditResult,
) -> tuple[list[tuple[Finding, DecisionRecord]], list[Finding], list[DecisionRecord]]:
    pair_count = min(len(result.findings), len(result.decisions))
    pairs = sorted(
        zip(result.findings[:pair_count], result.decisions[:pair_count]),
        key=lambda pair: (
            pair[0].package.purl,
            pair[0].advisory.id,
            _canonical_item_key(pair[0].to_dict()),
            _canonical_item_key(pair[1].to_dict()),
        ),
    )
    unmatched_findings = sorted(
        result.findings[pair_count:], key=lambda item: (item.package.purl, item.advisory.id)
    )
    return pairs, unmatched_findings, list(result.decisions[pair_count:])


def _append_findings(
    lines: list[str],
    title: str,
    pairs: list[tuple[Finding, DecisionRecord]],
    secrets: Iterable[str],
) -> None:
    lines.extend(["", f"## {title} ({len(pairs)})", ""])
    if not pairs:
        lines.append("None.")
        return
    for finding, decision in pairs:
        advisory = finding.advisory
        package = finding.package
        lines.extend([
            f"### {_md(package.name, secrets)} — {_md(advisory.id, secrets)}",
            "",
            f"- Package: {_md(package.purl, secrets)}",
            f"- Installed version: {_md(package.version, secrets)}",
            f"- Severity: {_md(advisory.severity, secrets)}",
            f"- Dependency scope: {_md(package.scope.value, secrets)}",
            f"- KEV status: {'present in CISA KEV' if finding.kev else 'not identified in CISA KEV'}",
            f"- Reachability: {_md(finding.reachability.value, secrets)}",
            f"- Decision reasons: {_md(', '.join(sorted(decision.reason_codes)) or 'not recorded', secrets)}",
            f"- Fixed versions: {_md(', '.join(sorted(advisory.fixed_versions)) or 'none identified', secrets)}",
        ])
        if advisory.details:
            lines.append(f"- Advisory summary: {_md(advisory.details, secrets)}")
        for index, reference in enumerate(sorted(set(advisory.references)), start=1):
            safe_reference = _safe_url(reference, secrets)
            if safe_reference:
                lines.append(f"- [Advisory evidence {index}]({safe_reference})")
        for evidence in sorted(set(finding.reachability_evidence)):
            lines.append(f"- Reachability evidence: {_md(evidence, secrets)}")


def _append_unclassified(
    lines: list[str], findings: list[Finding], secrets: Iterable[str]
) -> None:
    lines.extend(["", f"## Unclassified findings ({len(findings)})", ""])
    if not findings:
        lines.append("None.")
        return
    lines.append(
        "These findings have no policy decision; treat the audit as incomplete until they are classified."
    )
    for finding in findings:
        lines.append(
            f"- {_md(finding.package.purl, secrets)} — {_md(finding.advisory.id, secrets)} "
            f"({_md(finding.advisory.severity, secrets)})"
        )


def _append_unmatched_decisions(
    lines: list[str], decisions: list[DecisionRecord], secrets: Iterable[str]
) -> None:
    lines.extend(["", f"## Unmatched decisions ({len(decisions)})", ""])
    if not decisions:
        lines.append("None.")
        return
    lines.append(
        "These policy decisions have no corresponding finding; treat the audit as incomplete "
        "until their evidence is restored."
    )
    for index, decision in enumerate(decisions, start=1):
        lines.extend([
            f"- Decision {index}: {_md(decision.decision.value, secrets)}",
            f"  Reasons: {_md(', '.join(sorted(set(decision.reason_codes))) or 'not recorded', secrets)}",
            f"  Mitigation: {_md(decision.mitigation or 'not recorded', secrets)}",
            f"  Risk acceptance: {_md(decision.risk_acceptance or 'not recorded', secrets)}",
        ])


def _status_label(status: GateStatus) -> str:
    return {
        GateStatus.PASS: "PASS — complete audit with no blocking findings or warnings",
        GateStatus.WARNINGS: "WARNINGS — review required; this is not a clean audit",
        GateStatus.BLOCKED: "BLOCKED — one or more findings prevent delivery",
        GateStatus.UNAVAILABLE: "UNAVAILABLE — required evidence is incomplete",
        GateStatus.INVALID: "INVALID — the audit invocation or local configuration is invalid",
    }[status]


def _timestamp_slug(value: str) -> str:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("audit timestamp must include a timezone")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _atomic_replace_many(outputs: Iterable[tuple[Path, str]]) -> None:
    staged: list[tuple[Path, Path]] = []
    backups: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for target, text in outputs:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=target.parent,
                prefix=f".{target.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, target))
            if target.exists():
                with tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=f".{target.name}.backup.",
                    suffix=".tmp", delete=True,
                ) as reservation:
                    backup = Path(reservation.name)
                os.link(target, backup)
                backups[target] = backup
        for temporary, target in staged:
            os.replace(temporary, target)
            replaced.append(target)
        staged.clear()
    except BaseException:
        for target in reversed(replaced):
            backup = backups.get(target)
            if backup is not None:
                os.replace(backup, target)
                backups.pop(target, None)
            else:
                try:
                    target.unlink()
                except FileNotFoundError:
                    pass
        raise
    finally:
        for temporary, _ in staged:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        for backup in backups.values():
            try:
                backup.unlink()
            except FileNotFoundError:
                pass


def _create_immutable(target: Path, text: str) -> bool:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target.parent,
            prefix=f".{target.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.read_text(encoding="utf-8") != text:
                raise ReportWriteError(
                    f"Reports could not be written: immutable evidence already exists at {target.name}"
                )
            return False
        return True
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
