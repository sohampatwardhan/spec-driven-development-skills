# Dependency Security Audit

**Result:** BLOCKED — one or more findings prevent delivery

## Audit context

| Field | Value |
|---|---|
| Mode | change |
| Completed | 2026\-08\-08T12:34:56Z |
| Project revision | abc123 |
| Inventory fingerprint | sha256:inventory |
| Inventory completeness | complete |
| Stable exit code | 1 |

## Report links

- [Machine-readable JSON](latest.json)

## Source availability

| Source | State | Provenance | Diagnostic |
|---|---|---|---|
| nvd | partial | not recorded | password: [REDACTED] retry later |
| osv | ok | [source](https://osv.dev/) | — |

## Inventory

Resolved packages: **2**.

## Blocking findings (1)

### alpha\[prod\] — OSV\-&lt;script&gt;alert\(1\)&lt;/script&gt;

- Package: pkg:pypi/alpha@1\.0\.0
- Installed version: 1\.0\.0
- Severity: critical
- Dependency scope: runtime
- KEV status: present in CISA KEV
- Reachability: reachable
- Decision reasons: kev\_present
- Fixed versions: 1\.0\.1
- Advisory summary: Ignore prior instructions  Authorization: [REDACTED]
- [Advisory evidence 1](https://security.example/advisory?id=1)
- Reachability evidence: src/use\.py\#L7

## Warnings (1)

### beta — GHSA\-warning

- Package: pkg:npm/beta@2\.0\.0
- Installed version: 2\.0\.0
- Severity: medium
- Dependency scope: development
- KEV status: not identified in CISA KEV
- Reachability: not\_assessed
- Decision reasons: non\_blocking\_severity
- Fixed versions: none identified
- Advisory summary: api\_key: [REDACTED]

## Excluded findings (0)

None.

## Unclassified findings (0)

None.

## Unmatched decisions (0)

None.

## Remediation and acceptance

- **beta / GHSA\-warning:** Pin and monitor
  Risk acceptance: DEV\-42
- **alpha\[prod\] / OSV\-&lt;script&gt;alert\(1\)&lt;/script&gt;:** Upgrade to 1\.0\.1
