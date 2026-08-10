# Dependency Security Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a portable `dependency-security-audit` skill that inventories resolved dependencies, checks authoritative vulnerability sources, enforces the approved policy, produces JSON and Markdown evidence, and integrates with the spec family.

**Architecture:** A Python-standard-library scanner normalizes package inventories and advisory records behind typed dataclasses. Independent inventory, source-client, and policy modules feed one orchestration/reporting CLI; a concise Agent Skill explains when to run each mode and how Context7 and reachability evidence affect remediation. The spec family invokes the new skill when dependencies change and at main/release gates.

**Tech Stack:** Python 3.11+ standard library, `unittest`, OSV API, GitHub Advisory REST API, NVD CVE API 2.0, CISA KEV JSON, Agent Skills Markdown/YAML

## Global Constraints

- Use the skill name `dependency-security-audit`; do not collide with the broad `cso` skill.
- Support `change`, `main`, and `release` modes with exit codes `0`, `1`, `2`, and `3` exactly as specified.
- Block every CISA KEV match and applicable high/critical runtime findings with reachable, unknown, or unassessed reachability.
- Warn for medium/low, non-KEV development-only, proven-unreachable, and non-KEV no-fix findings.
- Never treat unavailable sources, incomplete inventories, withdrawn records, or unknown reachability as a clean scan.
- Use OSV for package/version matching; use GitHub and NVD only for enrichment; require a current KEV check in main/release modes.
- Use Context7 before recommending or applying a fixed library version.
- Keep the skill portable and dependency-free at runtime; tests may use only Python's standard library.
- Write human-readable Markdown and versioned JSON under `.security/dependency-audit/`.
- Do not auto-apply major upgrades, dependency replacements, or risk acceptance.
- The current workspace and global skill directory are not Git repositories; do not fabricate commit steps or claims.

---

### Task 1: Scaffold the skill and define stable domain models

- [ ] **Task status:** Complete and reviewed

**Depends on:** none
**Stage:** 1

**Files:**
- Create: `/Users/soham/.agents/skills/dependency-security-audit/SKILL.md`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/agents/openai.yaml`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/__init__.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/models.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_models.py`

**Interfaces:**
- Consumes: approved design specification and Python 3.11+
- Produces: `AuditMode`, `DependencyScope`, `Reachability`, `Decision`, `SourceState`, `PackageRef`, `Advisory`, `Finding`, `SourceStatus`, `InventoryResult`, and `AuditResult`

- [ ] **Step 1: Initialize the new skill with scripts and references directories**

Run:

```bash
python3 /Users/soham/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  dependency-security-audit \
  --path /Users/soham/.agents/skills \
  --resources scripts,references \
  --interface 'display_name=Dependency Security Audit' \
  --interface 'short_description=Audit dependency vulnerabilities and fixes' \
  --interface 'default_prompt=Audit this project dependency snapshot using the appropriate change, main, or release policy.'
```

Expected: the skill directory, `SKILL.md`, and `agents/openai.yaml` exist without example placeholders.

- [ ] **Step 2: Write failing model round-trip tests**

Create tests that construct a package and advisory, serialize an `AuditResult` through `to_dict()`, and assert enum values and nested records are plain JSON-compatible values:

```python
def test_audit_result_to_dict_is_json_serializable(self):
    package = PackageRef(
        ecosystem="PyPI", name="example", version="1.2.3",
        purl="pkg:pypi/example@1.2.3", direct=True,
        scope=DependencyScope.RUNTIME,
    )
    advisory = Advisory(
        id="GHSA-aaaa-bbbb-cccc", aliases=("CVE-2026-0001",),
        severity="high", withdrawn=False, fixed_versions=("1.2.4",),
        references=("https://example.invalid/advisory",),
    )
    result = AuditResult.empty(AuditMode.CHANGE)
    result.findings.append(Finding(package=package, advisory=advisory))
    encoded = result.to_dict()
    json.dumps(encoded)
    self.assertEqual(encoded["mode"], "change")
```

- [ ] **Step 3: Run the model test and verify it fails**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_models.py' -v
```

Expected: failure because `dependency_audit.models` and its types do not exist.

- [ ] **Step 4: Implement immutable model types and serialization**

Use `str, Enum` values and dataclasses with explicit serialization:

```python
class AuditMode(str, Enum):
    CHANGE = "change"
    MAIN = "main"
    RELEASE = "release"

class DependencyScope(str, Enum):
    RUNTIME = "runtime"
    DEVELOPMENT = "development"
    UNKNOWN = "unknown"

class Reachability(str, Enum):
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    UNKNOWN = "unknown"
    NOT_ASSESSED = "not_assessed"

class Decision(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"

@dataclass(frozen=True)
class PackageRef:
    ecosystem: str
    name: str
    version: str
    purl: str
    direct: bool
    scope: DependencyScope
```

Implement the remaining dataclasses with `to_dict()` methods; use tuples in immutable advisory data and lists in mutable aggregate results.

- [ ] **Step 5: Run the model tests**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -v
```

Expected: all model tests pass and `json.dumps(result.to_dict())` succeeds.

### Task 2: Implement the enforcement policy

- [ ] **Task status:** Complete and reviewed

**Depends on:** Task 1
**Stage:** 2

**Files:**
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/policy.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_policy.py`

**Interfaces:**
- Consumes: `Finding`, `AuditMode`, `SourceStatus`, and inventory completeness
- Produces: `classify_finding(finding) -> tuple[Decision, str]`, `gate_result(result) -> tuple[Decision, int]`

- [ ] **Step 1: Write the policy decision table as failing parameterized subtests**

Cover KEV before every other rule, withdrawn advisories, no-fix findings, development scope, unreachable evidence, runtime severity, and unknown severity:

Define a test-local `finding()` helper that accepts `kev`, `scope`, `fixes`, `severity`,
`reachability`, and `withdrawn`, then constructs the model objects with safe defaults.

```python
cases = (
    ("kev_dev_no_fix", finding(kev=True, scope="development", fixes=()), "block"),
    ("runtime_high", finding(severity="high", scope="runtime"), "block"),
    ("runtime_high_unreachable", finding(severity="high", reachability="unreachable"), "warn"),
    ("runtime_high_no_fix", finding(severity="high", fixes=()), "warn"),
    ("development_critical", finding(severity="critical", scope="development"), "warn"),
    ("runtime_medium", finding(severity="medium", scope="runtime"), "warn"),
    ("withdrawn", finding(kev=False, withdrawn=True), "pass"),
)
for name, candidate, expected in cases:
    with self.subTest(name=name):
        self.assertEqual(classify_finding(candidate)[0].value, expected)
```

- [ ] **Step 2: Run the policy tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_policy.py' -v
```

Expected: failure because `policy.py` does not exist.

- [ ] **Step 3: Implement ordered classification rules**

Use this exact precedence:

```python
def classify_finding(finding: Finding) -> tuple[Decision, str]:
    if finding.advisory.withdrawn:
        return Decision.PASS, "advisory withdrawn"
    if finding.kev:
        return Decision.BLOCK, "listed in CISA KEV"
    if not finding.advisory.fixed_versions:
        return Decision.WARN, "no released fixed version or upstream patch"
    if finding.package.scope is DependencyScope.DEVELOPMENT:
        return Decision.WARN, "development-only dependency"
    if finding.reachability is Reachability.UNREACHABLE:
        return Decision.WARN, "vulnerable surface proven unreachable"
    if finding.advisory.severity.lower() in {"critical", "high"}:
        return Decision.BLOCK, "high/critical runtime dependency"
    if finding.advisory.severity.lower() in {"medium", "low", "unknown"}:
        return Decision.WARN, "non-blocking severity"
    return Decision.WARN, "unrecognized severity treated conservatively"
```

Implement aggregate precedence as unavailable/incomplete (`exit 2`) before finding decisions in main/release, then blocking findings (`exit 1`), otherwise `exit 0`; invalid invocations remain the CLI's `exit 3`.

- [ ] **Step 4: Run policy tests and verify all modes and exit codes**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_policy.py' -v
```

Expected: all decision-table and aggregate exit-code tests pass.

### Task 3: Implement dependency inventory adapters

- [ ] **Task status:** Complete and reviewed

**Depends on:** Task 1
**Stage:** 2

**Files:**
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/inventory.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/npm-list.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/pip-inspect.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cargo-metadata.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/go-list.jsonl`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cyclonedx.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_inventory.py`

**Interfaces:**
- Consumes: a project root, optional CycloneDX JSON path, and injectable command runner
- Produces: `collect_inventory(root, sbom_path=None, runner=run_command) -> InventoryResult`

- [ ] **Step 1: Write fixture-driven failing tests for normalized inventory**

Test these adapters and canonical ecosystem names:

```python
expected = {
    "npm": ("npm", "left-pad", "1.3.0"),
    "pip": ("PyPI", "requests", "2.32.3"),
    "cargo": ("crates.io", "serde", "1.0.203"),
    "go": ("Go", "golang.org/x/text", "0.16.0"),
    "cyclonedx": ("Maven", "org.example:demo", "2.1.0"),
}
```

Assert deduplication by package URL, exact-version rejection, direct/transitive classification, development/runtime scope, command failures, and incomplete inventory reporting.

- [ ] **Step 2: Run inventory tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_inventory.py' -v
```

Expected: failure because inventory adapters do not exist.

- [ ] **Step 3: Implement command and SBOM adapters**

Implement adapters for:

```python
COMMANDS = {
    "npm": ("npm", "ls", "--all", "--json"),
    "pip": (sys.executable, "-m", "pip", "inspect", "--local"),
    "cargo": ("cargo", "metadata", "--format-version", "1"),
    "go": ("go", "list", "-m", "-json", "all"),
}
```

Parse CycloneDX 1.4–1.6 JSON as the ecosystem-neutral fallback. Normalize package URLs, reject empty or non-exact versions, and record a `SourceStatus` for every attempted adapter. Do not shell-expand commands; pass argument arrays to `subprocess.run`.

- [ ] **Step 4: Implement deterministic inventory fingerprinting**

Sort records by `(ecosystem, name, version, purl)` and hash compact JSON using SHA-256:

```python
payload = json.dumps([package.to_dict() for package in packages], sort_keys=True, separators=(",", ":"))
fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Run inventory tests**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_inventory.py' -v
```

Expected: all adapters normalize exact resolved versions and incomplete inputs remain explicit.

### Task 4: Implement authoritative source clients and advisory normalization

- [ ] **Task status:** Complete and reviewed

**Depends on:** Task 1
**Stage:** 2

**Files:**
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/http.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/sources.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/osv-querybatch.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/osv-advisory.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/github-advisory.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/nvd-cve.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/cisa-kev.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_sources.py`

**Interfaces:**
- Consumes: normalized packages and injectable `HttpClient`
- Produces: `OsvClient.query(packages)`, `GithubClient.enrich(advisory)`, `NvdClient.enrich(advisory)`, `KevClient.fetch_ids()`, and deduplicated `Advisory` records

- [ ] **Step 1: Write failing client tests with a fake HTTP transport**

Use an in-memory transport and assert endpoint, method, request body, bounded retry count, redacted errors, batch pagination, alias deduplication, withdrawn handling, fixed-version extraction, and KEV lookup:

```python
client = OsvClient(http=FakeHttp(responses))
records, status = client.query((package("PyPI", "jinja2", "2.4.1"),))
self.assertEqual(records[0].id, "GHSA-vqj2-4v8m-8vrq")
self.assertIn("CVE-2019-10906", records[0].aliases)
self.assertEqual(records[0].fixed_versions, ("2.10.1",))
```

- [ ] **Step 2: Run source tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_sources.py' -v
```

Expected: failure because HTTP and source clients do not exist.

- [ ] **Step 3: Implement a bounded standard-library HTTP client**

Use `urllib.request`, JSON bytes, a configurable timeout, at most three attempts, and delays of `0.25`, `0.5`, and `1.0` seconds for retryable `429` and `5xx` responses. Honor integer `Retry-After` values up to 30 seconds. Never include `Authorization` values in exception text or reports.

- [ ] **Step 4: Implement OSV batch querying and full-record retrieval**

POST package/version queries to `https://api.osv.dev/v1/querybatch`, follow per-result page tokens, then GET every unique ID from `/v1/vulns/{id}`. Normalize ecosystem ranges and explicit affected versions; collect `fixed` events only as authoritative fixed versions.

- [ ] **Step 5: Implement KEV and optional enrichment clients**

Use:

```python
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
GITHUB_URL = "https://api.github.com/advisories"
NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
```

Index KEV by uppercase `cveID`; query GitHub by GHSA or CVE identifier; query NVD only for CVE aliases. Preserve OSV affected-range decisions when enrichment disagrees or lacks package-ecosystem precision, while recording source provenance.

- [ ] **Step 6: Run source tests**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_sources.py' -v
```

Expected: deterministic fixtures pass without network access.

### Task 5: Build orchestration, reachability annotations, reports, and CLI

- [ ] **Task status:** Complete and reviewed

**Depends on:** Tasks 2, 3, and 4
**Stage:** 3

**Files:**
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/reporting.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/runner.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_security_audit.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/fixtures/reachability.json`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_runner.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_reporting.py`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/tests/test_cli.py`

**Interfaces:**
- Consumes: inventory, normalized advisories, KEV IDs, optional reachability evidence, and audit mode
- Produces: `run_audit(config) -> AuditResult`, `write_reports(result, output_dir)`, and CLI exit codes

- [ ] **Step 1: Write failing end-to-end orchestration tests**

Build fake inventory/source clients and assert:

```python
result = run_audit(AuditConfig(mode=AuditMode.RELEASE, root=fixture_root), services=fakes)
self.assertEqual(result.decision, Decision.BLOCK)
self.assertEqual(result.exit_code, 1)
self.assertEqual(result.findings[0].reachability, Reachability.UNKNOWN)
```

Cover a clean result, warnings, KEV block, runtime-high block, source-unavailable `exit 2`, malformed invocation `exit 3`, and withdrawn advisory exclusion.

- [ ] **Step 2: Write failing report golden tests**

Assert stable JSON keys and Markdown sections: Summary, Source Status, Inventory, Blocking Findings, Warnings, Remediation, Risk Acceptance, and Evidence. Verify advisory URLs are Markdown links and report text escapes untrusted pipes, brackets, control characters, and HTML.

- [ ] **Step 3: Run runner/report/CLI tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -v
```

Expected: failure because orchestration and entrypoint modules do not exist.

- [ ] **Step 4: Implement reachability evidence loading**

Accept a project-local JSON map keyed by `package-purl|advisory-id`:

```json
{
  "pkg:pypi/example@1.2.3|CVE-2026-0001": {
    "state": "unreachable",
    "evidence": ["src/app.py does not include the vulnerable optional parser in the built artifact"]
  }
}
```

Reject `unreachable` entries with an empty evidence list. Default absent entries to `unknown` for runtime dependencies and `not_assessed` for development dependencies.

- [ ] **Step 5: Implement orchestration and completeness rules**

Run inventory, OSV, native audit status, KEV, and optional enrichment in order. Main/release require complete inventory, OSV success, KEV success, and success from applicable installed native audit commands. Change mode records source failures as warnings. Deduplicate findings by the transitive closure of advisory aliases.

- [ ] **Step 6: Implement JSON and Markdown reporting**

Write `latest.json` and `latest.md` atomically using temporary files in the destination directory and `Path.replace()`. For main/release, also write UTC names such as `20260808T150000Z-release.json`. Use `schema_version: "1.0"` and sort packages/findings deterministically.

- [ ] **Step 7: Implement the CLI**

Support:

```text
dependency_security_audit.py ROOT --mode {change,main,release}
  [--sbom PATH] [--reachability PATH] [--output-dir PATH]
  [--github-token-env NAME] [--nvd-api-key-env NAME]
  [--format {text,json}]
```

Read secrets only from named environment variables; never accept them as command-line values. Print a concise summary to stdout and diagnostics to stderr.

- [ ] **Step 8: Run orchestration, report, and CLI tests**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -v
```

Expected: every offline test passes and all exit codes match the design.

### Task 6: Write the operational skill and references

- [ ] **Task status:** Complete and reviewed

**Depends on:** Task 5
**Stage:** 4

**Files:**
- Modify: `/Users/soham/.agents/skills/dependency-security-audit/SKILL.md`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/references/policy.md`
- Create: `/Users/soham/.agents/skills/dependency-security-audit/references/sources.md`
- Modify: `/Users/soham/.agents/skills/dependency-security-audit/agents/openai.yaml`

**Interfaces:**
- Consumes: tested CLI and approved policy
- Produces: concise invocation workflow, mode selection, Context7 remediation rule, reachability procedure, source reference, and UI metadata

- [ ] **Step 1: Replace generated placeholders with concise skill instructions**

Set exact frontmatter:

```yaml
---
name: dependency-security-audit
description: Audit resolved third-party dependencies for known vulnerabilities, CISA KEV exploitation, affected versions, and available fixes. Use when adding or upgrading a library, changing a lockfile, preparing a protected-main merge or release, checking CVEs/GHSAs/OSV advisories, or selecting a patched dependency version.
---
```

The body must select `change`, `main`, or `release`; run the CLI; require `context7-mcp` before remediation upgrades; use `codebase-memory-reference` plus source evidence for reachability when available; explain exit codes; and forbid describing warnings/unavailable scans as clean.

- [ ] **Step 2: Write the policy reference**

Move the complete precedence table, risk-acceptance fields, required-source matrix, reachability evidence standard, and exit-code table into `references/policy.md`. Link it directly from `SKILL.md` and instruct agents to read it before classifying or overriding a finding.

- [ ] **Step 3: Write the source reference**

Document OSV as the version matcher, native audits as independent ecosystem evidence, GitHub/NVD as enrichment, KEV as exploitation elevation, required authentication environment variables, retry semantics, and official URLs in `references/sources.md`.

- [ ] **Step 4: Regenerate and inspect UI metadata**

Run:

```bash
python3 /Users/soham/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  /Users/soham/.agents/skills/dependency-security-audit \
  --interface 'display_name=Dependency Security Audit' \
  --interface 'short_description=Audit dependency vulnerabilities and patched versions' \
  --interface 'default_prompt=Audit this project dependency snapshot and report blocking vulnerabilities, warnings, and safe fixed versions.'
```

Expected: metadata names the focused dependency audit and does not claim general cybersecurity coverage.

### Task 7: Integrate Context7 and vulnerability gates into the spec family

- [ ] **Task status:** Complete and reviewed

**Depends on:** Task 6
**Stage:** 5

**Files:**
- Modify: `/Users/soham/.agents/skills/spec-driven/SKILL.md`
- Modify: `/Users/soham/.agents/skills/spec-driven/references/artifacts.md`
- Modify: `/Users/soham/.agents/skills/spec-design/SKILL.md`
- Modify: `/Users/soham/.agents/skills/spec-tasks/SKILL.md`
- Modify: `/Users/soham/.agents/skills/spec-execute/SKILL.md`
- Modify: `/Users/soham/.agents/skills/spec-audit/SKILL.md`

**Interfaces:**
- Consumes: `dependency-security-audit` mode and report contracts
- Produces: design evidence, dependency-changing task requirements, execution gates, and audit findings

- [ ] **Step 1: Add the Dependency Security Evidence artifact contract**

Add this table after Current Technology Evidence in `references/artifacts.md`:

```markdown
## Dependency Security Evidence

| Package | Resolved version | Scope | Audit mode/date | Result | Fixed version or mitigation |
|---|---:|---|---|---|---|
| [`requests`](https://pypi.org/project/requests/) | `2.32.3` | runtime | change; `2026-08-08T15:00:00Z` | pass; no advisories | no action |
```

Require it whenever a design adds, upgrades, replaces, or materially relies on a third-party library.

- [ ] **Step 2: Update design and task authoring rules**

In `spec-design`, require Context7 plus a change-mode dependency audit for proposed dependency versions. In `spec-tasks`, require dependency-changing tasks to name the manifest/lockfile, run Context7 for the selected fixed/current version, run change mode after resolution, and include the audit report in Verification.

- [ ] **Step 3: Update execution gates**

In `spec-execute`, run change mode after any lockfile mutation, main mode before protected-main integration, and release mode before a release action. Treat exit `1` or `2` as a stop condition in main/release; preserve warnings and risk acceptance in `04_execution.md`.

- [ ] **Step 4: Update audit and router rules**

In `spec-audit`, report missing security evidence, stale dependency snapshots, unaccepted block findings, or a claimed clean result from an unavailable scan. In `spec-driven`, add `dependency-security-audit` as the focused gate and retain `cso` for broad security reviews.

- [ ] **Step 5: Validate link and dependency references**

Run frontmatter checks and use `rg` to confirm every spec phase names the same skill, modes, evidence heading, and exit-code semantics. Ensure links to existing project files use the spec hyperlink convention.

### Task 8: Validate, live-smoke-test, and synchronize

- [ ] **Task status:** Complete and reviewed

**Depends on:** Tasks 1–7
**Stage:** 6

**Files:**
- Test: `/Users/soham/.agents/skills/dependency-security-audit/tests/`
- Validate: `/Users/soham/.agents/skills/dependency-security-audit/`
- Sync: `/Users/soham/.claude/skills/dependency-security-audit/`
- Sync: `/Users/soham/.copilot/skills/dependency-security-audit/`
- Sync: updated `spec-*` skill folders

**Interfaces:**
- Consumes: completed audit and spec skills
- Produces: validated canonical skill plus byte-identical Claude Code and GitHub Copilot copies

- [ ] **Step 1: Run the complete deterministic test suite**

Run:

```bash
python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -v
```

Expected: all fixture-driven tests pass without network access.

- [ ] **Step 2: Run opt-in live smoke tests**

Query one known vulnerable fixture package/version and one known fixed version through OSV, then fetch the current KEV catalog. Assert only stable properties: vulnerable result is nonempty, fixed result does not contain the same advisory, and KEV JSON contains a `vulnerabilities` array. Do not pin counts or current severity text.

- [ ] **Step 3: Validate Python syntax, skill structure, and frontmatter**

Run compile-only syntax checks without leaving `__pycache__`, run the skill creator's `quick_validate.py`, and use the Ruby YAML fallback if PyYAML is unavailable. Reject generated placeholders, auxiliary README files, or stale `agents/openai.yaml` metadata.

- [ ] **Step 4: Run a temporary project end-to-end fixture**

Exercise change, main, and release modes with fake source responses. Verify report creation, atomic overwrite of `latest.*`, immutable main/release evidence, hyperlinks, inventory fingerprint, warnings, blocks, unavailable status, and exit codes `0`–`3`. Remove the fixture afterward.

- [ ] **Step 5: Dry-run and apply cross-agent synchronization**

Use `syncing-agent-skills` with Codex as source and targets `claude-code` and `copilot-cli`. Preview first, then apply the new skill and changed `spec-*` skills with dependency resolution enabled.

- [ ] **Step 6: Verify target copies**

Repeat the sync as a dry run and require every selected skill and dependency to report `up to date`. Report timestamped backups created by the sync tool.

## Final Acceptance

- [ ] The skill inventories exact resolved dependencies or returns an explicit unavailable/incomplete result.
- [ ] OSV matching, advisory enrichment, alias deduplication, KEV elevation, withdrawn records, and fixed versions are fixture-tested.
- [ ] KEV and applicable high/critical runtime findings block; approved warning classes remain warnings.
- [ ] Unknown reachability cannot be mislabeled as unreachable without evidence.
- [ ] Change, main, and release completeness rules and exit codes are deterministic.
- [ ] Markdown and JSON reports are human-readable, machine-readable, linked, redacted, and safe against untrusted advisory text.
- [ ] Context7 is required before recommending dependency remediation versions.
- [ ] The spec family records dependency security evidence and invokes the correct audit mode at each gate.
- [ ] Claude Code and GitHub Copilot copies are byte-for-byte current with the canonical Codex skills.
