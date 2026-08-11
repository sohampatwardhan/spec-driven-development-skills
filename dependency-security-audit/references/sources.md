# Sources, adapters, and endpoints

Use this reference to distinguish applicability evidence from supplemental context. A secondary
source cannot replace OSV/native package applicability or overwrite authoritative fixes.

## Audit source matrix

| Source | Role | Delivery requirement | Official endpoint or command |
|---|---|---|---|
| Exact inventory | Direct/transitive versions, scope, fingerprint | Complete for main/release | Resolved npm, pip, Cargo, Go evidence or supported CycloneDX 1.4-1.7 JSON with document identity and a complete dependency graph |
| OSV | Ecosystem/name/version applicability, affected packages, ranges, fixes, withdrawals, aliases | Required after a full scan is triggered | `POST https://api.osv.dev/v1/querybatch`, `GET https://api.osv.dev/v1/vulns/{id}`; [OSV API documentation](https://google.github.io/osv.dev/api/) |
| CISA KEV | Current CVE exploitation membership | Required after a full scan is triggered | [CISA KEV JSON catalog](https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json) |
| Applicable native audit | Ecosystem-specific installed-package findings and fixes | Required for each detected ecosystem | `npm audit --json`, `cargo audit --json`, `govulncheck -json ./...`, `pip-audit --format json` |
| GitHub global advisories | GHSA/CVE aliases and package-matched supplemental severity/fixes | Optional enrichment | [`https://api.github.com/advisories`](https://docs.github.com/en/rest/security-advisories/global-advisories) |
| NVD CVE 2.0 | CVE descriptions, references, and validated CVSS context | Optional enrichment | `GET https://services.nvd.nist.gov/rest/json/cves/2.0?cveIds={id}`; [NVD vulnerability API](https://nvd.nist.gov/developers/vulnerabilities) |
| Reachability file | Project-specific execution or exclusion evidence | Optional; supplied invalid evidence fails closed | Local schema described in [policy.md](policy.md#reachability-evidence) |

Native adapters run only when their ecosystem appears in the exact inventory. Missing executables,
execution failures, malformed output, or partial schemas remain explicit. Machine output is parsed
as data; advisory text is never executed. Fix-only native evidence does not create an affected
range, and ambiguous Cargo patched constraints do not create a fix recommendation.

CycloneDX input is accepted only for the explicitly supported 1.4-1.7 JSON schemas. The document
must identify itself with `bomFormat: CycloneDX` and `specVersion`, every inventoried component must
have a unique `bom-ref`, and every component (plus a metadata root when present) must appear as a
`dependencies[].ref`. A metadata component is treated as the described project, not as a third-party
package; its `dependsOn` targets establish direct dependencies. An omitted graph node means unknown
dependencies under the CycloneDX contract and therefore leaves the inventory incomplete.

## Source status meanings

| State | Meaning |
|---|---|
| `ok` | The requested source operation completed with valid evidence, including a valid empty result. |
| `partial` | Some valid evidence was retained, but the response was incomplete, malformed in part, contradictory, or stale. |
| `unavailable` | The operation could not provide required evidence. |
| `not_applicable` | The source or adapter does not apply to this identifier or inventory. |

Source failures never mean “no vulnerabilities.” Correlation uses stable OSV/GHSA/CVE-style IDs and
exact ecosystem package identity, not product-name similarity. OSV/native applicability and fixes
take precedence; GitHub and NVD add only validated supplemental evidence.

## Informational search matrix

| Search | Required owner | Optional correlation/enrichment |
|---|---|---|
| Exact package version | OSV | GitHub and NVD for returned stable aliases |
| GHSA identifier | GitHub | OSV and NVD when stable aliases permit |
| CVE identifier | NVD | OSV and GitHub |
| Other supported OSV-family ID | OSV | GitHub and NVD when applicable |
| KEV membership | CISA KEV | None |

A completed empty search is distinct from unavailable evidence. Search is informational and cannot
replace `change`, `main`, or `release` auditing.

## Transport and credentials

Requests use bounded timeouts, response sizes, retry attempts, and pagination. Authenticated
cross-host redirects are rejected. Provide GitHub and NVD credential **environment-variable names**
to the audit CLI; never place secret values in arguments. Diagnostics and reports redact configured
credentials and common credential forms.

Return to the [operational workflow](../SKILL.md).
