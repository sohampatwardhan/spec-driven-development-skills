---
name: dependency-security-audit
description: Audit resolved third-party dependencies for known vulnerabilities, CISA KEV exploitation, affected versions, and available fixes. Use when adding or upgrading a library, changing a lockfile, preparing protected-main integration or release, investigating an OSV/GHSA/CVE record, or selecting a patched dependency version.
version: 1.0.2
---

# Dependency Security Audit

Audit exact resolved dependency snapshots and produce reviewable JSON and Markdown evidence. Use
the advisory search only for investigation; it does not make a project delivery decision.

## Select the operation

| Need | Operation |
|---|---|
| A manifest or lockfile changed | `change` audit after resolving exact versions |
| A revision is entering protected main | Fresh `main` audit of the complete snapshot |
| A revision is being released | Fresh `release` audit; do not reuse a prior decision |
| No resolved-dependency fingerprint changed | No full feature-branch audit; compare with `--baseline-fingerprint` |
| Investigate one package, advisory, or CVE | Informational advisory search |

An incomplete inventory always remains visible. A matching baseline skips the remote change scan
only when the newly collected inventory is complete.

## Run an audit

From this skill directory, run one of these forms:

```bash
python3 scripts/dependency_security_audit.py --root /path/to/project --mode change --baseline-fingerprint PREVIOUS_SHA256 --format human
python3 scripts/dependency_security_audit.py --root /path/to/project --mode main --revision REVISION --format json
python3 scripts/dependency_security_audit.py --root /path/to/project --mode release --revision REVISION --format json
```

Add evidence or stricter policy when available:

```bash
python3 scripts/dependency_security_audit.py --root /path/to/project --mode main --sbom /path/to/bom.json --reachability /path/to/reachability.json --policy /path/to/policy.json --output /path/to/reports --github-token-env GITHUB_TOKEN --nvd-api-key-env NVD_API_KEY --format json
```

Credential options accept environment-variable names, never secret values. Use `--help` for timeout,
freshness, and output options. Reports default to
`PROJECT/.security/dependency-audit/latest.json` and `latest.md`; main and release also retain
timestamped immutable reports.

## Interpret the result

| Exit | Status | Meaning |
|---:|---|---|
| 0 | `pass` | Required evidence completed and no finding needs action. |
| 0 | `warnings` | Review findings or source gaps; never describe this as clean. |
| 1 | `blocked` | At least one finding blocks delivery. |
| 2 | `unavailable` | Required evidence is missing, partial, stale, incomplete, or unwritable. |
| 3 | `invalid` | Invocation or local configuration is invalid. |

Review both reports, including inventory completeness, source states, finding aliases, exact package
identity, KEV, reachability, fixes, decision reasons, and remediation gaps. Valid findings remain in
reports even when another source fails. See [policy and gate interpretation](references/policy.md).

## Supply reachability evidence

Use a schema-major `1` JSON document keyed by `<exact-purl>|<advisory-id>`. Accept an unreachable
claim only with concrete `delivered_artifact_exclusion`, `call_graph_exclusion`, or
`configuration_exclusion` evidence. A missing direct import is not proof: record `unknown` unless
the delivered vulnerable surface is demonstrably excluded. Supplied malformed evidence fails closed
to unknown. See the [reachability contract](references/policy.md#reachability-evidence).

## Remediate

1. Use only the authoritative fixed version selected by the report; do not infer that a newer-looking
   version is safe. Keep unresolved advisories explicit when no common safe version exists.
2. Immediately before proposing implementation changes, use Context7 for the exact library and
   selected version. Record current migration, API, and configuration guidance and its source.
3. Request explicit user approval before a major-version upgrade or dependency replacement. If
   ecosystem-aware major-version evaluation is unavailable, treat approval as unresolved and ask.
4. Update the owned manifest and lockfile, run the project's relevant tests, then run a new `change`
   audit. Run fresh `main` or `release` mode again at the corresponding delivery gate.

The standalone CLI records the resulting audit evidence; approval and test evidence belong in the
delivery workflow. Do not claim remediation complete until Context7 guidance, required approval,
tests, and the post-change audit are all present.

## Search advisory records

```bash
python3 scripts/dependency_advisory_search.py package --ecosystem PyPI --name requests --version 2.31.0 --format json
python3 scripts/dependency_advisory_search.py advisory --id CVE-2024-0001 --format text
python3 scripts/dependency_advisory_search.py kev --id CVE-2024-0001 --format json
```

Search exit `0` includes an explicit empty result, `2` means required evidence was unavailable, and
`3` means invalid input. Search never returns policy-block exit `1`. Read the [source and endpoint
reference](references/sources.md) before interpreting source ownership or enrichment gaps.
