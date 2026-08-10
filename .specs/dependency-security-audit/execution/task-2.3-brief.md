# Task 2.3 Brief: Vulnerability Source Clients

Implement only task 2.3 from the approved task plan.

## Contract

- Own only `scripts/dependency_audit/http.py`, `scripts/dependency_audit/sources.py`,
  `tests/test_sources.py`, and the five named source fixtures.
- Use existing models without modification.
- Implement an injectable standard-library HTTP transport with bounded response bytes, connect/read
  timeout, at most three transient attempts, bounded Retry-After, and redacted diagnostics.
- OSV package query must use a versioned purl or ecosystem/name plus separate version, never both;
  paginate each batch result and fetch every unique complete record by ID.
- Normalize affected ranges/events, fixes, withdrawal, aliases, severity, provenance, and stable
  correlation without name-similarity merging.
- Implement direct OSV/GHSA/CVE lookup, current KEV normalization, GitHub API-versioned enrichment,
  and NVD enrichment. Enrichment cannot erase OSV affected-package evidence.
- Treat all remote text as inert data and expose explicit `SourceStatus` on partial/unavailable work.
- Follow RED → GREEN → REFACTOR → DOCUMENT → VERIFY for requirements 3.1–3.7, 8.1–8.5,
  10.1–10.5. Do not edit spec artifacts or other task files.

## Current Technology Evidence

Use the approved design's OSV and GitHub Context7 evidence: querybatch returns IDs/modified values,
full records require separate retrieval, pagination tokens must be exhausted, and GitHub is
secondary enrichment with an explicit API-version header.

## Verification

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_sources.py' -v`

Document all public transport/client methods, source precedence, retry/redaction boundaries, and
why enrichment cannot change primary affected-range truth.
