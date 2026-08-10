# Tasks: Dependency Security Audit

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Requirements](01_requirements.md) · [Design](02_design.md) · [Tasks](03_tasks.md) · [Execution](04_execution.md)
<!-- spec-nav:end -->

> [!WARNING]
> Execute dependency stages in order. Run tasks concurrently only when each is marked
> `parallel-safe`, its owned files are disjoint, and isolated worktrees or equivalent isolation
> are available. Stop at every checkpoint for human review.

## Execution Model

The task graph deliberately freezes shared domain models first. Policy, inventory, source clients,
reachability, and reporting can then proceed concurrently because they own separate files and run
tests without bytecode output. Orchestration begins only after all five contracts pass. The
machine-readable graph is produced from this document with `spec-check.py --format json`; no
duplicate JSON or YAML task list is maintained.

- [x] 1. Establish the shared skill and domain contract
  - [x] 1.1 Scaffold the skill package and implement versioned domain models
    - Initialize the canonical `dependency-security-audit` Agent Skill without generated example
      content, using a Python 3.11+ standard-library runtime.
    - Define modes, scopes, reachability, source states, findings, decisions, aggregate results,
      schema versioning, deterministic serialization, stable status values, and the normalized
      `AdvisorySearchResult` from the design.
    - Preserve each advisory's affected packages independently, including exact package identity,
      explicit versions, typed ranges, ordered events, and package-specific fixes; retain only an
      exact-package projection in finding-level compatibility fields.
    - Retain source-scoped enrichment evidence for normalized severity, CVSS, EPSS, vulnerable
      functions, and descriptive context without allowing it to replace OSV applicability.
    - Add round-trip tests proving every result is JSON-compatible and canonical ordering is stable.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/SKILL.md`, `/Users/soham/.agents/skills/dependency-security-audit/agents/openai.yaml`, `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/__init__.py`, `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/models.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_models.py`
    - **Depends on:** none
    - **Stage:** 1
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document the public enums, dataclasses, schema compatibility contract, and why source availability is distinct from vulnerability outcome.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_models.py' -v`; review public documentation against the approved design.
    - **Risk:** medium; these models are the shared interface, so rollback is removal of the unintegrated new skill before downstream tasks begin.
    - **Delegation:** controller
    - _Requirements: 2.4, 7.1, 7.4, 7.5, 10.6_

- [x] 2. Implement independent audit components
  - [x] 2.1 Implement the monotonic policy and remediation engine
    - Encode the exact withdrawn, KEV, no-fix, scope, reachability, severity, and stricter-project-
      policy precedence with stable reason codes.
    - Compute the lowest released version satisfying all authoritative safe ranges; preserve
      unresolved findings and enforce release mitigation plus risk-acceptance fields.
    - Test every decision-table combination, aggregate precedence, and all stable exit statuses.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/policy.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_policy.py`
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `classify_finding`, `gate_result`, effective-policy monotonicity, fixed-version selection, and the rationale for rule order.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_policy.py' -v`; review the decision table and API documentation.
    - **Risk:** high; a precedence error can weaken a security gate, so rollback is limited to reverting this isolated module before orchestration integration.
    - **Delegation:** parallel-safe
    - _Requirements: 3.3, 3.6, 3.7, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 6.1, 6.2_

  - [x] 2.2 Implement exact inventory and native-audit adapters
    - Parse exact direct and transitive resolution evidence for npm, pip, Cargo, Go, and the
      documented CycloneDX JSON component/dependency subset.
    - Preserve runtime, development, and unknown scopes; reject missing or non-exact versions;
      build dependency edges and the canonical SHA-256 inventory fingerprint.
    - Detect applicable native audit commands, invoke argument arrays without shell expansion,
      and distinguish missing, failed, partial, and successful adapters.
    - Add minimal fixture tests for each adapter, incomplete inventory, duplicate package URLs,
      deterministic fingerprints, and command failures.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/inventory.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_inventory.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/npm-list.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/pip-inspect.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cargo-metadata.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/go-list.jsonl`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cyclonedx.json`
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `collect_inventory`, adapter selection, completeness semantics, scope preservation, native-command safety, and fingerprint inputs.
    - **Verification:** Consult the design's CycloneDX Context7 evidence and repeat it if the supported schema changes; run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_inventory.py' -v`; review public documentation.
    - **Risk:** high; false completeness could produce false assurance, so unsupported or ambiguous evidence must remain incomplete and adapters can be rolled back independently.
    - **Delegation:** parallel-safe
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 8.1, 8.2_

  - [x] 2.3 Implement bounded HTTP and vulnerability-source clients
    - Build an injectable standard-library HTTP client with timeouts, response limits, bounded
      transient retries, pagination limits, API-version headers, and credential redaction.
    - Implement OSV batch queries using either a versioned package URL or a separate exact version,
      then paginate and retrieve complete advisory records before affected-range matching.
    - Correlate stable OSV, GHSA, and CVE aliases independent of input order; union every OSV
      affected-package record without pooling ranges or fixes across packages; retain withdrawn
      provenance; support direct OSV/GHSA/CVE lookup; implement independent current KEV lookup plus
      exact-package GitHub and NVD enrichment.
    - Test all clients with hostile and partial fake responses, source disagreement, redaction,
      retries, pagination, fixed/no-fix records, and deduplication.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/http.py`, `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/sources.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_sources.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/osv-querybatch.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/osv-advisory.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/github-advisory.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/nvd-cve.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cisa-kev.json`
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document transport trust boundaries, `OsvClient`, `GithubClient`, `NvdClient`, `KevClient`, required versus enrichment sources, retry bounds, and alias-correlation rules.
    - **Verification:** Consult the design's OSV and GitHub Context7 evidence and repeat a query if API behavior or version changes; run `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_sources.py' -v`; review public documentation and seeded-secret redaction.
    - **Risk:** high; remote ambiguity and source outages must never erase findings, so every source returns explicit status and the clients remain replaceable behind their interfaces.
    - **Delegation:** parallel-safe
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 2.4 Implement evidence-based reachability loading
    - Parse annotations keyed by package URL and advisory ID with state, method, evidence links,
      producer, and timestamp.
    - Reject unsupported `unreachable` claims, preserve direct/runtime/configuration evidence for
      `reachable`, and use `unknown` or `not_assessed` when exclusion is not proven.
    - Test valid, absent, malformed, conflicting, and evidence-free annotations.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/reachability.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_reachability.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/reachability.json`
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `load_reachability`, the annotation key/schema, accepted proof states, and why absence of a direct import cannot prove exclusion.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_reachability.py' -v`; review evidence validation and public documentation.
    - **Risk:** high; an unsupported unreachable state could weaken enforcement, so invalid annotations fail closed to unknown and the loader can be removed without changing source matching.
    - **Delegation:** parallel-safe
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 2.5 Implement atomic JSON and human-readable Markdown reporting
    - Serialize schema-versioned results and derive Markdown from the same object with source
      availability, inventory, blocks, warnings, remediation, acceptance, and linked evidence.
    - Escape hostile Markdown/HTML/control characters, redact seeded secrets, atomically replace
      latest reports, and retain timestamped main/release evidence.
    - Test schema compatibility, matching counts, deterministic ordering, inaccessible output,
      interrupted replacement, report links, and text-only status meaning.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/reporting.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_reporting.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/expected-report.md`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/expected-report.json`
    - **Depends on:** 1.1
    - **Stage:** 2
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `write_reports`, output schema/version policy, atomicity guarantees, retention behavior, escaping, redaction, and accessibility rationale.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_reporting.py' -v`; compare JSON and Markdown golden results and review documentation.
    - **Risk:** medium; partial or unsafe evidence undermines auditability, so failures return unavailable and rollback removes only newly generated reports and this isolated writer.
    - **Delegation:** parallel-safe
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 8.4, 8.5_

- [x] 3. Checkpoint — independent contracts are stable
  - Confirm tasks 2.1–2.5 pass independently, their public contracts agree with the shared models,
    and no parallel task owns or mutates another task's files before orchestration begins.

- [x] 4. Integrate audit and advisory-search workflows
  - [x] 4.1 Implement mode selection, orchestration, failure integrity, and remediation workflow
    - Orchestrate inventory, OSV, applicable native audits, enrichment, KEV, reachability, policy,
      and reports without discarding valid partial findings.
    - Implement fingerprint-based change triggers, fresh full main/release modes, required-source
      matrices, aggregate precedence, and release no-fix acceptance handling.
    - Require current Context7 guidance before remediation recommendations and encode explicit
      approval for major upgrades/replacements, relevant project tests, and the post-change audit.
    - Add fake-service integration tests for every mode, required and secondary source failure,
      stale evidence, withdrawn findings, known blocks, warnings, unavailable results, and pass.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/runner.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_runner.py`
    - **Depends on:** 2.1, 2.2, 2.3, 2.4, 2.5
    - **Stage:** 3
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `run_audit`, service injection, mode/source matrix, freshness, partial-evidence behavior, aggregate precedence, and remediation preconditions.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_runner.py' -v`; review public documentation and the complete mode/failure matrix.
    - **Risk:** high; orchestration combines every assurance boundary, so failures stay unavailable, tests use injected services, and rollback reverts this integration without disturbing proven components.
    - **Delegation:** sequential subagent
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.7, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 7.4, 8.1, 8.2, 8.3_

  - [x] 4.2 Implement the reusable advisory-search API and CLI
    - Add programmatic package, advisory-identifier, and KEV lookup functions that reuse the
      normalized source clients without requiring a project root or inventory.
    - Support exact ecosystem/name/version search, OSV/GHSA/CVE correlation, current CVE KEV
      membership, explicit empty results, and required-source unavailable results.
    - Expose `dependency_advisory_search.py` with `package`, `advisory`, and `kev` subcommands plus
      stable JSON and concise text output. Return exit `0` for completed searches including empty
      results, `2` for unavailable required sources, and `3` for invalid invocation; never return
      the audit-policy block exit.
    - Test normalized API results, every command form, aliases, KEV presence/absence, hostile text,
      seeded-secret redaction, empty versus unavailable behavior, and exits `0`, `2`, and `3`.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/search.py`, `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_advisory_search.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_search.py`
    - **Depends on:** 2.3
    - **Stage:** 3
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document `search_package`, `search_advisory`, `search_kev`, the normalized result contract, command syntax, source requirements, empty/unavailable distinction, and informational—not enforcement—semantics.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_search.py' -v`; review `--help`, JSON/text fixtures, exits, redaction, and public documentation.
    - **Risk:** medium; callers could mistake search completion for project safety, so output explicitly states informational scope and rollback removes the independent entry point without changing audit behavior.
    - **Delegation:** parallel-safe
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

- [x] 5. Expose the standalone command contract
  - [x] 5.1 Implement the CLI, stable exits, and end-to-end offline tests
    - Validate root, mode, optional SBOM/reachability/policy/output paths, source timeouts, and
      credential environment-variable names without accepting secret values as arguments.
    - Print concise human or JSON summaries, sanitized diagnostics, and exits `0` for pass/warnings,
      `1` for findings blocked, `2` for unavailable/incomplete evidence, and `3` for invalid use.
    - Exercise standalone change, main, and release runs against a temporary fixture project and
      assert both reports, immutable evidence, exit codes, and policy equivalence.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_security_audit.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/test_cli.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/project/pyproject.toml`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/project/requirements.lock`
    - **Depends on:** 4.1
    - **Stage:** 4
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document command arguments, credential handling, stdout/stderr contract, output locations, status meanings, and why warnings must not be described as clean.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_cli.py' -v`; review `--help`, public module comments, reports, and exits `0`–`3`.
    - **Risk:** high; automation relies on stable status semantics, so rollback removes the unintegrated entry point rather than changing exit meanings after release.
    - **Delegation:** sequential subagent
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 7.1, 7.2, 7.3, 7.4, 7.5, 8.4, 9.9_

- [x] 6. Document the skill and connect the spec family
  - [x] 6.1 Write operational skill guidance and focused source/policy references
    - Replace scaffold text with concise mode selection, CLI invocation, result interpretation,
      reachability evidence, current Context7 remediation, explicit approval, tests, and re-audit
      instructions.
    - Document the policy/source matrices and official endpoints in focused references, then
      generate accurate OpenAI UI metadata without claiming broad cybersecurity coverage.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/SKILL.md`, `/Users/soham/.agents/skills/dependency-security-audit/agents/openai.yaml`, `/Users/soham/.agents/skills/dependency-security-audit/references/policy.md`, `/Users/soham/.agents/skills/dependency-security-audit/references/sources.md`
    - **Depends on:** 4.2, 5.1
    - **Stage:** 5
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** The skill and references are the public operational documentation; explain contracts and rationale for modes, required evidence, policy, remediation, and status interpretation.
    - **Verification:** Run the skill creator's `quick_validate.py`; inspect frontmatter and generated UI metadata; execute every documented command form against fixtures; review human readability and links.
    - **Risk:** medium; incorrect operational text can misuse a correct tool, so documented commands are executable tests and rollback restores the scaffold until corrected.
    - **Delegation:** parallel-safe
    - _Requirements: 6.3, 6.4, 6.5, 6.6, 7.2, 7.5, 9.9_

  - [x] 6.2 Integrate dependency evidence and gates throughout the spec family
    - Add a human-readable Dependency Security Evidence contract beside Current Technology Evidence
      without narrating tool-generation or validation process.
    - Require design evidence for material libraries; require dependency-changing tasks to own the
      manifest/lockfile and perform Context7, change-mode audit, report review, tests, and re-audit.
    - Require fresh main/release audits at delivery gates and make missing, stale, blocked, or
      falsely clean dependency evidence a spec-audit defect.
    - Extend spec-family checks and fixtures so every phase names the same focused skill, modes,
      report contract, and status semantics while retaining broad security review separately.
    - **Files:** `/Users/soham/.agents/skills/spec-driven/SKILL.md`, `/Users/soham/.agents/skills/spec-driven/references/artifacts.md`, `/Users/soham/.agents/skills/spec-design/SKILL.md`, `/Users/soham/.agents/skills/spec-tasks/SKILL.md`, `/Users/soham/.agents/skills/spec-execute/SKILL.md`, `/Users/soham/.agents/skills/spec-audit/SKILL.md`, `/Users/soham/.agents/skills/spec-driven/scripts/spec-check.py`, `/Users/soham/.agents/skills/spec-driven/tests/test_spec_check.py`
    - **Depends on:** 5.1
    - **Stage:** 5
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document the cross-phase evidence and invocation contract in each affected skill; keep numbered artifacts human-facing and omit irrelevant implementation-process prose.
    - **Verification:** Run the spec-check test suite, skill frontmatter validation, and `rg` consistency checks for skill name, modes, evidence heading, exit meanings, Context7, owned resolution files, and report review; review documentation links.
    - **Risk:** high; inconsistent phase rules could skip or duplicate gates, so all affected skills change together and rollback restores them as one compatibility set.
    - **Delegation:** parallel-safe
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8_

- [x] 7. Checkpoint — standalone and spec contracts agree
  - Confirm the CLI, operational skill, and every spec phase share the same modes, required sources,
    reports, decision meanings, remediation conditions, and fresh delivery gates.

- [x] 8. Validate the complete canonical implementation
  - [x] 8.1 Run deterministic suites, structural validation, and a temporary-project acceptance test
    - Run the full offline suite without bytecode artifacts, compile-only syntax validation, skill
      structure/frontmatter checks, and `spec-check.py` against representative complete specs.
    - Exercise change, main, and release modes in a temporary project with fake transports; verify
      exact inventory, fingerprints, source states, policy decisions, atomic latest reports,
      timestamped evidence, hyperlinks, redaction, hostile data handling, and exits `0`–`3`.
    - Inspect all public modules and skill documentation for contract-and-rationale comments and
      remove generated placeholders or auxiliary documentation not referenced by the skill.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/tests/test_acceptance.py`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/acceptance-osv.json`, `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/acceptance-kev.json`, `/Users/soham/.agents/skills/spec-driven/tests/test_spec_check.py`
    - **Depends on:** 6.1, 6.2
    - **Stage:** 6
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Review all public surfaces produced by earlier tasks; this task adds only test rationale and no new public API.
    - **Verification:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -v`; run spec-check tests and skill validation; review the acceptance reports as a human would.
    - **Risk:** medium; acceptance fixtures must not become stale copies of implementation logic, so they assert public behavior and can be replaced without production migration.
    - **Delegation:** sequential subagent
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.3, 3.1, 3.2, 3.3, 3.5, 4.1, 4.2, 4.6, 5.5, 7.1, 7.2, 7.3, 7.5, 8.1, 8.3, 8.4, 8.5, 9.1, 9.2, 9.5, 9.7, 9.8, 9.9_

- [x] 9. Verify current external services without making tests time-sensitive
  - [x] 9.1 Run opt-in OSV and KEV live smoke checks
    - Query one known vulnerable package/version and a known fixed version through OSV, retrieve
      complete records, and fetch the current KEV catalog.
    - Assert only stable structural properties and advisory identity relationships; do not pin
      changing counts, severity prose, or catalog timestamps.
    - Record sanitized source status and date without embedding live responses in the skill.
    - **Files:** `/Users/soham/.agents/skills/dependency-security-audit/tests/live_smoke.py`
    - **Depends on:** 8.1
    - **Stage:** 7
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** Document opt-in invocation, network requirements, stable assertions, and why the live check is supplementary to deterministic fixtures.
    - **Verification:** Run `PYTHONDONTWRITEBYTECODE=1 python3 /Users/soham/.agents/skills/dependency-security-audit/tests/live_smoke.py`; review that output contains no secrets and failures are explicit.
    - **Risk:** medium; external volatility may fail the smoke check, so it never replaces offline acceptance and rollback removes only the supplementary script.
    - **Delegation:** sequential subagent
    - _Requirements: 1.3, 3.1, 3.5, 8.1_

- [x] 10. Synchronize validated skills to supported agents
  - [x] 10.1 Preview, apply, and verify Claude Code and GitHub Copilot synchronization
    - Use `syncing-agent-skills` with the canonical Codex/Agent Skills source and targets Claude
      Code and GitHub Copilot; preview before applying the new audit skill and changed `spec-*`
      family with dependency resolution enabled.
    - Repeat the sync as a dry run and require each selected skill and dependency to be up to date;
      report timestamped backups and remove only obsolete Codex residual backups already identified
      by the sync workflow.
    - **Files:** `/Users/soham/.claude/skills/dependency-security-audit/SKILL.md`, `/Users/soham/.copilot/skills/dependency-security-audit/SKILL.md`, `/Users/soham/.claude/skills/spec-driven/SKILL.md`, `/Users/soham/.claude/skills/spec-design/SKILL.md`, `/Users/soham/.claude/skills/spec-tasks/SKILL.md`, `/Users/soham/.claude/skills/spec-execute/SKILL.md`, `/Users/soham/.claude/skills/spec-audit/SKILL.md`, `/Users/soham/.copilot/skills/spec-driven/SKILL.md`, `/Users/soham/.copilot/skills/spec-design/SKILL.md`, `/Users/soham/.copilot/skills/spec-tasks/SKILL.md`, `/Users/soham/.copilot/skills/spec-execute/SKILL.md`, `/Users/soham/.copilot/skills/spec-audit/SKILL.md`
    - **Depends on:** 9.1
    - **Stage:** 8
    - **Dependency resolution:** none
    - **Dependency delivery:** none
    - **Documentation:** No new public surface; verify synchronized skill documentation and metadata remain byte-identical to the canonical copies.
    - **Verification:** Run the synchronization preview after apply and require all selected skills to report up to date; compare canonical and target files byte-for-byte and review backup/removal evidence.
    - **Risk:** medium; synchronization overwrites target copies, so retain tool-created timestamped backups and restore them if validation differs.
    - **Delegation:** controller
    - _Requirements: 9.7, 9.8, 9.9_

## Approval Status

Tasks, including the package-aware model and source-correlation correction, were approved by the
user on 2026-08-08. Material revisions after approval invalidate audit and execution approval.
