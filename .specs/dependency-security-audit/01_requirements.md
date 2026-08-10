# Requirements: Dependency Security Audit

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Requirements](01_requirements.md) · [Design](02_design.md) · [Tasks](03_tasks.md) · [Execution](04_execution.md)
<!-- spec-nav:end -->

## Introduction

The Dependency Security Audit provides a focused, repeatable safety gate for third-party libraries.
It verifies resolved dependency versions against current vulnerability intelligence, distinguishes
blocking risks from warnings, identifies authoritative fixes, and records evidence that humans and
automation can review later.

The feature complements broad security reviews rather than replacing them. Its approved background
is captured in the [exploratory design](../../docs/superpowers/specs/2026-08-08-dependency-security-audit-design.md).

> [!IMPORTANT]
> Approval gate: approve these requirements before work begins on [the design](02_design.md).

## Definitions

- **Runtime dependency:** third-party code included in or required by the delivered application.
- **Development-only dependency:** third-party code used only to build, test, document, or analyze the application.
- **Resolved dependency snapshot:** the exact direct and transitive package versions selected for a project revision.
- **Known Exploited Vulnerability (KEV):** a CVE listed by the U.S. Cybersecurity and Infrastructure Security Agency as actively exploited.
- **Reachability:** evidence describing whether the vulnerable behavior can execute in the delivered application.

## Assumptions

- Protected-main and release environments can access the required vulnerability intelligence services.
- A project can provide a resolved lockfile, package-manager inventory, or software bill of materials.
- Project policy may make warning and blocking thresholds stricter, but cannot downgrade a KEV finding.

## Requirements

### Requirement 1: Context-sensitive audit modes

**User Story:** As a maintainer, I want audit depth to match the delivery event, so that routine dependency work remains efficient while shared and released code receives a complete check.

#### Acceptance Criteria

1. **R1.1** WHEN a dependency is added, removed, upgraded, downgraded, or re-resolved, THE Dependency_Auditor SHALL evaluate the changed dependency snapshot in change mode.
2. **R1.2** WHEN a revision is proposed for protected-main integration, THE Dependency_Auditor SHALL evaluate the complete resolved dependency snapshot using current vulnerability intelligence.
3. **R1.3** WHEN a revision is prepared for release, THE Dependency_Auditor SHALL perform a fresh complete evaluation without reusing an earlier vulnerability decision.
4. **R1.4** WHILE an ordinary feature-branch commit does not change the resolved dependency snapshot, THE Dependency_Auditor SHALL NOT require a complete audit.

### Requirement 2: Exact dependency inventory

**User Story:** As a security reviewer, I want findings tied to exact resolved packages, so that advisory matching and remediation decisions are reproducible.

#### Acceptance Criteria

1. **R2.1** WHEN an audit starts, THE Dependency_Auditor SHALL inventory exact direct and transitive package versions from the project's resolved dependency evidence.
2. **R2.2** WHERE dependency-scope metadata is available, THE Dependency_Auditor SHALL classify each package as runtime or development-only.
3. **R2.3** IF any package version cannot be resolved exactly, THEN THE Dependency_Auditor SHALL identify the inventory as incomplete rather than reporting a clean result.
4. **R2.4** WHEN two audits use identical resolved dependency evidence, THE Dependency_Auditor SHALL produce the same inventory fingerprint.

### Requirement 3: Current vulnerability intelligence

**User Story:** As a maintainer, I want package-aware vulnerability results from authoritative sources, so that I do not rely on stale documentation or imprecise product-name matching.

#### Acceptance Criteria

1. **R3.1** WHEN an exact package version is evaluated, THE Dependency_Auditor SHALL match it against current ecosystem-aware affected-version records.
2. **R3.2** WHEN advisory sources use different identifiers for the same vulnerability, THE Dependency_Auditor SHALL return one finding containing the correlated OSV, GHSA, and CVE aliases.
3. **R3.3** WHEN an advisory has been withdrawn, THE Dependency_Auditor SHALL exclude it from blocking and warning counts.
4. **R3.4** WHEN an advisory has been withdrawn, THE Dependency_Auditor SHALL retain its source provenance.
5. **R3.5** WHEN a finding has a CVE alias, THE Dependency_Auditor SHALL determine whether that CVE appears in the current CISA KEV catalog.
6. **R3.6** WHEN an authoritative affected range identifies a released fix, THE Dependency_Auditor SHALL report the applicable fixed version.
7. **R3.7** IF no authoritative fixed version or upstream patch exists, THEN THE Dependency_Auditor SHALL label the finding as no-fix rather than inferring safety from a newer release.

### Requirement 4: Deterministic enforcement policy

**User Story:** As a release owner, I want consistent gate decisions, so that exploitable dependency risk cannot be silently accepted or inconsistently classified.

#### Acceptance Criteria

1. **R4.1** WHEN a present dependency matches CISA KEV, THE Dependency_Auditor SHALL block the audit regardless of dependency scope, reachability, or fix availability.
2. **R4.2** WHEN a high or critical runtime finding has an available fix and its reachability is reachable, unknown, or not assessed, THE Dependency_Auditor SHALL block the audit.
3. **R4.3** WHEN a finding is medium or low severity, THE Dependency_Auditor SHALL report a warning unless stricter project policy applies.
4. **R4.4** WHEN a non-KEV finding affects only a development dependency, THE Dependency_Auditor SHALL report a warning unless stricter project policy applies.
5. **R4.5** WHEN a high or critical non-KEV finding is proven unreachable, THE Dependency_Auditor SHALL report a warning containing the reachability evidence.
6. **R4.6** WHEN a non-KEV finding has no available fix, THE Dependency_Auditor SHALL report a warning.
7. **R4.7** WHEN a no-fix warning is included in a release, THE Dependency_Auditor SHALL require documented mitigations and explicit risk acceptance.
8. **R4.8** WHEN project policy is stricter than the default policy, THE Dependency_Auditor SHALL apply the stricter decision.

### Requirement 5: Evidence-based reachability

**User Story:** As a security reviewer, I want reachability claims backed by concrete evidence, so that indirect or configuration-driven vulnerable paths are not incorrectly dismissed.

#### Acceptance Criteria

1. **R5.1** WHEN direct calls, runtime loading, enabled configuration, or equivalent execution evidence reaches a vulnerable surface, THE Dependency_Auditor SHALL classify the finding as reachable.
2. **R5.2** WHEN concrete analysis proves the vulnerable surface is excluded from the delivered application, THE Dependency_Auditor SHALL classify the finding as unreachable.
3. **R5.3** WHEN a finding is classified as unreachable, THE Dependency_Auditor SHALL record the supporting exclusion evidence.
4. **R5.4** IF analysis finds no obvious direct import but cannot prove exclusion, THEN THE Dependency_Auditor SHALL classify reachability as unknown.
5. **R5.5** IF an unreachable classification contains no supporting evidence, THEN THE Dependency_Auditor SHALL reject that classification.

### Requirement 6: Safe remediation guidance

**User Story:** As an implementer, I want vulnerability fixes paired with current library guidance, so that remediation does not introduce avoidable compatibility or configuration errors.

#### Acceptance Criteria

1. **R6.1** WHEN one compatible fixed version resolves all applicable findings, THE Dependency_Auditor SHALL recommend the lowest such version.
2. **R6.2** IF no single version resolves all applicable findings, THEN THE Dependency_Auditor SHALL identify the unresolved findings separately.
3. **R6.3** WHEN remediation uses a released fixed library version, THE audit workflow SHALL obtain current Context7 migration, API, and configuration guidance before recommending implementation changes.
4. **R6.4** IF remediation requires a major-version upgrade or dependency replacement, THEN THE audit workflow SHALL require explicit user approval before applying it.
5. **R6.5** WHEN remediation changes the resolved dependency snapshot, THE audit workflow SHALL require the project's relevant tests before declaring remediation complete.
6. **R6.6** WHEN remediation changes the resolved dependency snapshot, THE audit workflow SHALL require a new dependency audit before declaring remediation complete.

### Requirement 7: Human and machine-readable evidence

**User Story:** As a maintainer, I want durable reports for humans and automation, so that findings, decisions, and release evidence can be reviewed and reproduced.

#### Acceptance Criteria

1. **R7.1** WHEN an audit completes, THE Dependency_Auditor SHALL write versioned JSON containing the mode, timestamp, project revision, inventory fingerprint, source status, packages, findings, decisions, and aggregate result.
2. **R7.2** WHEN an audit completes, THE Dependency_Auditor SHALL write Markdown summarizing source availability, blocking findings, warnings, remediation, risk acceptance, and linked evidence.
3. **R7.3** WHEN main or release mode completes, THE Dependency_Auditor SHALL retain immutable timestamped evidence in addition to the latest report.
4. **R7.4** WHEN an audit has warnings but no blocking findings, THE Dependency_Auditor SHALL distinguish that result from both a clean audit and an unavailable audit.
5. **R7.5** WHEN automation invokes the audit, THE Dependency_Auditor SHALL return distinct stable statuses for success-with-optional-warnings, blocking findings, unavailable or incomplete scanning, and invalid invocation.

### Requirement 8: Failure integrity and secure operation

**User Story:** As a release owner, I want scan failures to fail safely and reports to protect sensitive data, so that missing evidence cannot masquerade as security assurance.

#### Acceptance Criteria

1. **R8.1** IF the required inventory, ecosystem-aware vulnerability query, or current KEV check cannot complete in main or release mode, THEN THE Dependency_Auditor SHALL block delivery as scan unavailable.
2. **R8.2** IF a source query fails in change mode, THEN THE Dependency_Auditor SHALL report a warning naming the unavailable source rather than reporting a clean audit.
3. **R8.3** WHEN a secondary enrichment source fails after required checks succeed, THE Dependency_Auditor SHALL record the failure without discarding otherwise valid findings.
4. **R8.4** WHEN reports or diagnostics are written, THE Dependency_Auditor SHALL exclude credentials and authorization values.
5. **R8.5** WHEN remote advisory text or package metadata is processed, THE Dependency_Auditor SHALL NOT execute embedded instructions.

### Requirement 9: Spec-driven and standalone use

**User Story:** As an agent user, I want the audit available both inside and outside spec-driven projects, so that the same policy protects ad hoc library work and planned feature delivery.

#### Acceptance Criteria

1. **R9.1** WHEN a spec design materially relies on a third-party library, THE spec workflow SHALL record current Context7 evidence for the selected version.
2. **R9.2** WHEN a spec design materially relies on a third-party library, THE spec workflow SHALL record dependency-security evidence for the selected version.
3. **R9.3** WHEN a spec task changes dependency resolution, THE task contract SHALL name the owned manifest or lockfile.
4. **R9.4** WHEN a spec task changes dependency resolution, THE task contract SHALL require Context7 verification for the selected version.
5. **R9.5** WHEN a spec task changes dependency resolution, THE task contract SHALL require change-mode auditing after resolution.
6. **R9.6** WHEN a spec task changes dependency resolution, THE task contract SHALL require review of the generated audit report.
7. **R9.7** WHEN spec execution prepares protected-main integration or release, THE spec workflow SHALL require the corresponding fresh audit mode before delivery.
8. **R9.8** WHEN a spec audit finds missing required dependency-security evidence or an unaccepted blocking result, THE spec workflow SHALL report a defect.
9. **R9.9** WHEN invoked outside a spec-driven project, THE Dependency_Auditor SHALL provide the same inventory, classification, reporting, and exit-status behavior.

### Requirement 10: Reusable advisory search

**User Story:** As a maintainer or security reviewer, I want to query vulnerability records without
running a project audit, so that I can investigate a package version or advisory identifier and
reuse the same normalized source clients.

#### Acceptance Criteria

1. **R10.1** WHEN a caller supplies an ecosystem, package name, and exact version, THE Advisory_Searcher SHALL return normalized matching advisory records without requiring a project inventory.
2. **R10.2** WHEN a caller supplies an OSV, GHSA, or CVE identifier, THE Advisory_Searcher SHALL return the correlated advisory record and its known aliases.
3. **R10.3** WHEN a caller supplies a CVE identifier for KEV lookup, THE Advisory_Searcher SHALL report whether the identifier appears in the current CISA KEV catalog.
4. **R10.4** WHEN a search completes with no matching records, THE Advisory_Searcher SHALL return an explicit empty result rather than reporting a source failure.
5. **R10.5** IF a required remote source cannot complete the requested search, THEN THE Advisory_Searcher SHALL return an unavailable status naming the source rather than an empty result.
6. **R10.6** WHEN a search is invoked, THE Advisory_Searcher SHALL support stable normalized JSON and concise human-readable output while applying the auditor's timeout, retry, redaction, and untrusted-data protections.

## Risk Classification

| Risk | Applicability | Required observable outcome |
|---|---|---|
| Security and supply chain | Primary | Known exploited and applicable high/critical runtime vulnerabilities cannot pass the gate silently. |
| Privacy | Applicable | Credentials and authorization values never appear in reports or diagnostics. |
| Accessibility | Limited | Markdown reports use descriptive headings, text labels, and links understandable without color. |
| Performance | Applicable | Dependency changes use targeted evaluation; complete evaluation is reserved for main and release gates. |
| Observability | Primary | Every source and inventory step records a status and timestamp. |
| Migration and rollback | Applicable | Remediation identifies fixed versions, compatibility guidance, tests, and explicit approval for major changes. |
| Release | Primary | Release evidence is fresh, complete, immutable, and distinguishable from warning or unavailable states. |

## Approval Status

Requirements were approved by the user on 2026-08-08. The user explicitly approved the reusable
advisory-search extension on 2026-08-08. Material revisions require re-approval.
