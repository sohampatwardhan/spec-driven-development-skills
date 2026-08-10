"""Regression tests for spec dependency-security evidence contracts."""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILLS_ROOT = SKILL_DIR.parent
SCRIPT = SKILL_DIR / "scripts" / "spec-check.py"
SPEC = importlib.util.spec_from_file_location("spec_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
spec_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spec_check)


DESIGN = """# Design: Example

## Current Technology Evidence

No evolving technology behavior applies.

## Dependency Security Evidence

No material third-party runtime dependency is selected.
"""


def task(
    files: str,
    details: str,
    title: str = "Implement behavior",
    *,
    resolution: str = "none",
    delivery: str = "none",
    metadata: bool = True,
    checked: bool = False,
) -> str:
    """Build one canonical leaf contract for checker tests."""
    dependency_fields = ""
    if metadata:
        dependency_fields = (
            f"    - **Dependency resolution:** {resolution}\n"
            f"    - **Dependency delivery:** {delivery}\n"
        )
    mark = "x" if checked else " "
    return f"""- [ ] 1. Group
  - [{mark}] 1.1 {title}
    - {details}
    - **Files:** {files}
{dependency_fields}    - **Depends on:** none
    - **Stage:** 1
    - **Interfaces:** Consumes: approved design contract; Produces: `run()` behavior in {files}
    - **Documentation:** no public surface
    - **Verification:** Review documentation and tests.
    - **Estimated effort:** 15-30 minutes
    - **Risk:** low; lockfile rollback is atomic.
    - **Delegation:** sequential subagent
    - _Requirements: 1.1_
"""


RESOLUTION_LINKS = ", ".join(
    f"[{path}](../../{path})" for path in (
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb",
        "pyproject.toml", "uv.lock", "requirements-dev.in", "requirements-dev.txt",
        "requirements-dev.lock", "packages/app/package.json", "packages/excluded/package.json",
        "Cargo.lock", "crates/app/Cargo.toml", "crates/excluded/Cargo.toml",
    )
)
SECURE_DETAILS = f"""
Context: the selected dependency API and remediation evidence are recorded for human review.
- **Context7 evidence:** state=pending | identity=/org/library | version=1.2.3 | decision=use documented API
- **Pre-change dependency audit:** state=pending | command=dependency-security-audit change | expected_json=.security/dependency-audit/pre.json | expected_markdown=.security/dependency-audit/pre.md | review=pending
- **Resolution edit:** state=pending | expected_files=package.json, package-lock.json, pnpm-lock.yaml, yarn.lock, bun.lock, bun.lockb, pyproject.toml, uv.lock, requirements-dev.in, requirements-dev.txt, requirements-dev.lock, packages/app/package.json, packages/excluded/package.json, Cargo.lock, crates/app/Cargo.toml, crates/excluded/Cargo.toml
- **Project tests:** state=pending | expected_evidence=test-results.txt
- **Post-change dependency audit:** state=pending | command=dependency-security-audit change | expected_json=.security/dependency-audit/post.json | expected_markdown=.security/dependency-audit/post.md | review=pending
"""

GATE_DETAILS = """
Delivery summary: current dependency evidence supports the recorded release decision.
- **Dependency delivery evidence:** state=pending | mode=release | expected_json=.security/dependency-audit/release.json | expected_markdown=.security/dependency-audit/release.md
"""
COMPLETED_GATE_DETAILS = """
Delivery summary: current dependency evidence supports the recorded release decision.
- **Dependency delivery evidence:** state=completed | mode=release | timestamp=2026-08-08T12:00:00Z | revision=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa | JSON=[release.json](../../.security/dependency-audit/release.json) | Markdown=[release.md](../../.security/dependency-audit/release.md) | review=completed | result=pass | exit=0 | decision=ship | warnings_reviewed=false | clean=true
"""


def audit_result_json(
    mode: str, timestamp: str, revision: str, fingerprint: str,
    *, status: str = "pass", exit_code: int = 0,
) -> dict[str, object]:
    """Build an actual AuditResult 1.0 JSON shape for evidence-correlation tests."""

    return {
        "schema_version": "1.0",
        "mode": mode,
        "timestamp": timestamp,
        "project_revision": revision,
        "inventory": {
            "packages": [],
            "dependencies": [],
            "fingerprint": fingerprint,
            "complete": True,
            "statuses": [],
            "incomplete_reasons": [],
        },
        "sources": [],
        "findings": [],
        "decisions": [],
        "gate_status": status,
        "exit_code": exit_code,
    }


class DependencySecurityCheckerTests(unittest.TestCase):
    """Verify designs and dependency-changing tasks expose complete human evidence."""

    def test_canonical_artifact_sequence_starts_discovery_at_01(self) -> None:
        self.assertEqual(
            (
                ("State", "00_state.md"),
                ("Discovery", "01_discovery.md"),
                ("Requirements", "02_requirements.md"),
                ("Design", "03_design.md"),
                ("Tasks", "04_tasks.md"),
                ("Execution", "05_execution.md"),
            ),
            spec_check.NAV_MODULE.ARTIFACTS,
        )

    def test_phase_aware_check_accepts_discovery_and_requirements_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_dir = root / ".specs" / "example"
            spec_dir.mkdir(parents=True)
            (spec_dir / "00_state.md").write_text("# State\n", encoding="utf-8")
            (spec_dir / "01_discovery.md").write_text("# Discovery\n", encoding="utf-8")
            spec_check.NAV_MODULE.update_navigation(spec_dir)
            discovery = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, discovery.returncode, discovery.stdout + discovery.stderr)

            (spec_dir / "02_requirements.md").write_text(
                "# Requirements\n\n**R1.1** THE workflow SHALL retain approved scope.\n",
                encoding="utf-8",
            )
            spec_check.NAV_MODULE.update_navigation(spec_dir)
            requirements = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir)],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, requirements.returncode, requirements.stdout + requirements.stderr)

    def test_execution_artifact_links_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_dir = root / ".specs" / "example"
            spec_dir.mkdir(parents=True)
            (spec_dir / "05_execution.md").write_text(
                "# Execution\n\n[Missing](missing-evidence.txt)\n",
                encoding="utf-8",
            )
            self.assertTrue(any(
                "05_execution.md contains a broken local link" in error
                for error in spec_check.artifact_link_errors(spec_dir)
            ))

    def test_hook_and_templates_use_current_numbering(self) -> None:
        hook = (SKILLS_ROOT / "spec-hooks" / "examples" / "tasks-checkbox-guard.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("04_tasks.md", hook)
        self.assertNotIn("03_tasks.md", hook)

        artifacts = (SKILL_DIR / "references" / "artifacts.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "[Discovery](01_discovery.md) · [State](00_state.md)",
            artifacts,
        )

    def test_complete_dependency_change_contract_passes(self) -> None:
        errors = spec_check.dependency_security_errors(
            DESIGN,
            task(
                "package.json, package-lock.json", SECURE_DETAILS, resolution="change"
            ),
        )
        self.assertEqual(errors, [])
        narrative = SECURE_DETAILS + "\nTried and failed to run every step; prose is informational only."
        self.assertEqual([], spec_check.dependency_security_errors(
            DESIGN, task("package.json, package-lock.json", narrative, resolution="change")
        ))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN,
                task("package.json, package-lock.json", SECURE_DETAILS, resolution="change"),
                project_root=root,
            ))
            self.assertFalse((root / ".security/dependency-audit/pre.json").exists())
            self.assertFalse((root / "test-results.txt").exists())
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN,
                task("docs/release.md", GATE_DETAILS, delivery="release"),
                project_root=root,
            ))

    def test_full_ready_check_accepts_pending_nonexistent_expected_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_dir = root / ".specs" / "example"
            spec_dir.mkdir(parents=True)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            artifacts = {
                "01_discovery.md": "# Discovery\n\nApproved approach and scope.\n",
                "00_state.md": "# State\n\n| Phase | Status |\n|---|---|\n| Discovery | approved |\n| Requirements | approved |\n| Design | approved |\n| Tasks | approved |\n",
                "02_requirements.md": "# Requirements\n\n**R1.1** WHEN dependency delivery is planned, THE workflow SHALL require audit evidence.\n",
                "03_design.md": DESIGN + "\n**Validates: Requirement 1.1**\n",
                "04_tasks.md": "# Tasks\n\n" + task(
                    "package.json, package-lock.json",
                    SECURE_DETAILS + GATE_DETAILS,
                    resolution="change",
                    delivery="release",
                ),
                "05_execution.md": """# Execution

## Execution Timing

### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|
| run-20260809T120000Z | 2026-08-09T12:00:00Z | pending | pending | active |

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|
""",
            }
            for name, contents in artifacts.items():
                (spec_dir / name).write_text(contents, encoding="utf-8")
            spec_check.NAV_MODULE.update_navigation(spec_dir)
            result = subprocess.run(
                ["python3", str(SCRIPT), str(spec_dir), "--ready", "--format", "json"],
                check=False, capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(["1.1"], payload["execution"]["ready"])
            for relative in (
                ".security/dependency-audit/pre.json",
                ".security/dependency-audit/post.md",
                ".security/dependency-audit/release.json",
                "test-results.txt",
            ):
                self.assertFalse((root / relative).exists())

    def test_pending_expected_paths_reject_existing_parent_symlink_escapes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, outside = base / "project", base / "outside"
            root.mkdir()
            outside.mkdir()
            (root / ".security").mkdir()
            (root / ".security" / "dependency-audit").symlink_to(
                outside, target_is_directory=True
            )
            report = {
                "expected_json": ".security/dependency-audit/pre.json",
                "expected_markdown": ".security/dependency-audit/pre.md",
            }
            self.assertIsNone(spec_check._expected_report_pair(report, root))

            (root / "escape").symlink_to(outside, target_is_directory=True)
            self.assertIsNone(spec_check._expected_path(
                "escape/package.json", project_root=root
            ))
            self.assertIsNone(spec_check._expected_path(
                "escape/test-results.txt", project_root=root
            ))

    def test_audit_result_v1_recursively_validates_advisory_evidence(self) -> None:
        package = {
            "ecosystem": "PyPI", "name": "demo", "version": "1.0.0",
            "purl": "pkg:pypi/demo@1.0.0", "direct": True, "scope": "runtime",
            "bom_ref": None, "package_extension": True,
        }
        event = {"kind": "introduced", "value": "0", "event_extension": True}
        affected_range = {
            "type": "ECOSYSTEM", "events": [event], "repo": None,
            "range_extension": True,
        }
        affected_package = {
            "ecosystem": "PyPI", "name": "demo", "purl": "pkg:pypi/demo",
            "versions": ["1.0.0"], "ranges": [affected_range],
            "fixed_versions": ["1.0.1"], "affected_extension": True,
        }
        enrichment = {
            "source": "nvd", "severity": "high", "cvss_scores": [8.1],
            "cvss_vectors": ["CVSS:3.1/test"], "epss_scores": [0.4],
            "vulnerable_functions": ["demo.run"], "details": "secondary evidence",
            "enrichment_extension": True,
        }
        advisory = {
            "id": "CVE-2026-0001", "aliases": ["GHSA-test"], "severity": "high",
            "withdrawn": False, "fixed_versions": ["1.0.1"],
            "references": ["https://example.invalid/advisory"],
            "affected_ranges": [">=1,<1.0.1"], "modified": None,
            "details": "advisory details", "source": "osv",
            "affected_packages": [affected_package], "enrichments": [enrichment],
            "advisory_extension": True,
        }
        evidence = audit_result_json(
            "change", "2026-08-08T12:00:00Z", "a" * 40, "b" * 64
        )
        evidence["findings"] = [{
            "package": package, "advisory": advisory, "kev": False,
            "reachability": "reachable", "reachability_evidence": ["src/demo.py:1"],
            "finding_extension": True,
        }]
        evidence["decisions"] = [{
            "decision": "warn", "reason_codes": ["non_blocking_severity"],
            "mitigation": "upgrade", "risk_acceptance": "SEC-1",
            "decision_extension": True,
        }]
        evidence["audit_extension"] = {"future": True}
        self.assertIsNone(spec_check._audit_result_v1(evidence))

        minimal = deepcopy(evidence)
        minimal["findings"][0]["advisory"] = {"id": "CVE-2026-0001"}
        self.assertEqual("invalid Finding collection", spec_check._audit_result_v1(minimal))

        invalid_paths = {
            "advisory id": (("findings", 0, "advisory", "id"), 1),
            "aliases": (("findings", 0, "advisory", "aliases"), "alias"),
            "severity": (("findings", 0, "advisory", "severity"), 1),
            "withdrawn": (("findings", 0, "advisory", "withdrawn"), "false"),
            "fixed versions": (("findings", 0, "advisory", "fixed_versions"), [1]),
            "references": (("findings", 0, "advisory", "references"), [1]),
            "flat affected ranges": (("findings", 0, "advisory", "affected_ranges"), [1]),
            "modified": (("findings", 0, "advisory", "modified"), 1),
            "details": (("findings", 0, "advisory", "details"), 1),
            "source": (("findings", 0, "advisory", "source"), 1),
            "affected packages container": (("findings", 0, "advisory", "affected_packages"), {}),
            "affected ecosystem": (("findings", 0, "advisory", "affected_packages", 0, "ecosystem"), 1),
            "affected name": (("findings", 0, "advisory", "affected_packages", 0, "name"), 1),
            "affected purl": (("findings", 0, "advisory", "affected_packages", 0, "purl"), 1),
            "affected versions": (("findings", 0, "advisory", "affected_packages", 0, "versions"), [1]),
            "affected fixes": (("findings", 0, "advisory", "affected_packages", 0, "fixed_versions"), [1]),
            "ranges container": (("findings", 0, "advisory", "affected_packages", 0, "ranges"), {}),
            "range type": (("findings", 0, "advisory", "affected_packages", 0, "ranges", 0, "type"), 1),
            "range repo": (("findings", 0, "advisory", "affected_packages", 0, "ranges", 0, "repo"), 1),
            "events container": (("findings", 0, "advisory", "affected_packages", 0, "ranges", 0, "events"), {}),
            "event kind": (("findings", 0, "advisory", "affected_packages", 0, "ranges", 0, "events", 0, "kind"), "unknown"),
            "event value": (("findings", 0, "advisory", "affected_packages", 0, "ranges", 0, "events", 0, "value"), 1),
            "enrichments container": (("findings", 0, "advisory", "enrichments"), {}),
            "enrichment source": (("findings", 0, "advisory", "enrichments", 0, "source"), 1),
            "enrichment severity": (("findings", 0, "advisory", "enrichments", 0, "severity"), 1),
            "cvss scores": (("findings", 0, "advisory", "enrichments", 0, "cvss_scores"), ["high"]),
            "cvss vectors": (("findings", 0, "advisory", "enrichments", 0, "cvss_vectors"), [1]),
            "epss scores": (("findings", 0, "advisory", "enrichments", 0, "epss_scores"), [True]),
            "functions": (("findings", 0, "advisory", "enrichments", 0, "vulnerable_functions"), [1]),
            "enrichment details": (("findings", 0, "advisory", "enrichments", 0, "details"), 1),
        }
        for label, (path, invalid_value) in invalid_paths.items():
            candidate = deepcopy(evidence)
            target = candidate
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = invalid_value
            with self.subTest(nested_field=label):
                self.assertEqual(
                    "invalid Finding collection", spec_check._audit_result_v1(candidate)
                )

    def test_design_requires_adjacent_dependency_security_evidence(self) -> None:
        design = "# Design\n\n## Current Technology Evidence\n\nNone.\n"
        errors = spec_check.dependency_security_errors(
            design, task("src/app.py", "Implement behavior.", title="Implement behavior"),
        )
        self.assertIn("03_design.md must contain Dependency Security Evidence", errors)

        separated = DESIGN.replace(
            "## Dependency Security Evidence",
            "## Unrelated Design Section\n\nContent.\n\n## Dependency Security Evidence",
        )
        self.assertIn(
            "Dependency Security Evidence must be adjacent to Current Technology Evidence",
            spec_check.dependency_security_errors(
                separated, task("src/app.py", "Implement behavior.", title="Implement behavior")
            ),
        )

    def test_design_ignores_fenced_headings_and_rejects_empty_or_incomplete_evidence(self) -> None:
        fenced_only = """# Design

```markdown
## Current Technology Evidence
Fake.
## Dependency Security Evidence
Fake.
```
"""
        errors = spec_check.dependency_security_errors(
            fenced_only, task("src/app.py", "Implement behavior.")
        )
        self.assertTrue(any("must contain Current" in error for error in errors))
        self.assertTrue(any("must contain Dependency" in error for error in errors))

        empty = """# Design

## Current Technology Evidence

## Dependency Security Evidence

"""
        errors = spec_check.dependency_security_errors(
            empty, task("src/app.py", "Implement behavior.")
        )
        self.assertTrue(any("Current Technology Evidence must contain" in error for error in errors))
        self.assertTrue(any("Dependency Security Evidence must contain" in error for error in errors))

        material = """# Design

## Current Technology Evidence

Consulted Context7 using identity `/org/library`; selected version `1.2.3`; decision: use the documented API.

## Dependency Security Evidence

| Dependency / resolved version | Mode | Evidence | Result and decision |
|---|---|---|---|
| library@1.2.3 | change | [JSON](../../.security/dependency-audit/latest.json) · [Markdown](../../.security/dependency-audit/latest.md) | explicitly reviewed warnings, not clean; decision: remediate before merge |
"""
        self.assertEqual(
            [],
            spec_check.dependency_security_errors(
                material, task("src/app.py", "Implement behavior.")
            ),
        )
        no_breaking = material.replace(
            "Consulted Context7 using identity `/org/library`",
            "Consulted Context7 using identity `/org/library` and confirmed no breaking changes",
        )
        self.assertEqual(
            [],
            spec_check.dependency_security_errors(
                no_breaking, task("src/app.py", "Implement behavior.")
            ),
        )
        for fragment in ("library@1.2.3", "change", "latest.json", "decision"):
            incomplete = material.replace(fragment, "omitted")
            with self.subTest(fragment=fragment):
                self.assertTrue(
                    any("lacks material fields" in error for error in
                        spec_check.dependency_security_errors(
                            incomplete, task("src/app.py", "Implement behavior.")
                        ))
                )

        technology_cases = {
            "source": material.replace(
                "Consulted Context7 using identity `/org/library`", "Documentation checked"
            ),
            "version": material.replace("selected version `1.2.3`", "selected version omitted"),
            "decision": material.replace(
                "decision: use the documented API", "selection rationale omitted"
            ),
            "not consulted": material.replace("Consulted Context7", "Context7 was not consulted"),
            "No Context7": material.replace("Consulted Context7", "No Context7 was consulted"),
            "No Context7 evidence": material.replace(
                "Consulted Context7 using identity `/org/library`", "No Context7 evidence"
            ),
            "avoided": material.replace("Consulted Context7", "Avoided consulting Context7"),
            "declined": material.replace("Consulted Context7", "Declined to consult Context7"),
            "refused": material.replace("Consulted Context7", "Refused to consult Context7"),
            "omitted": material.replace("Consulted Context7", "Omitted consulting Context7"),
            "failed": material.replace("Consulted Context7", "Failed to consult Context7"),
            "skipped": material.replace("Consulted Context7", "Skipped consulting Context7"),
        }
        for label, incomplete in technology_cases.items():
            with self.subTest(current_technology_field=label):
                self.assertTrue(any(
                    "Current Technology Evidence lacks material fields" in error for error in
                    spec_check.dependency_security_errors(
                        incomplete, task("src/app.py", "Implement behavior.")
                    )
                ))

        blocked = material.replace(
            "explicitly reviewed warnings, not clean",
            "blocked",
        )
        self.assertTrue(any(
            "cannot ship" in error for error in
            spec_check.dependency_security_errors(
                blocked, task("src/app.py", "Implement behavior.")
            )
        ))
        for label, unsafe in (
            ("unreviewed warnings", material.replace("explicitly reviewed warnings", "warnings")),
            ("clean warnings", material.replace("not clean", "clean")),
            (
                "negated warning review",
                material.replace("explicitly reviewed warnings", "not reviewed warnings"),
            ),
        ):
            with self.subTest(material_status=label):
                self.assertTrue(any(
                    "Dependency Security Evidence lacks material fields" in error for error in
                    spec_check.dependency_security_errors(
                        unsafe, task("src/app.py", "Implement behavior.")
                    )
                ))

    def test_dependency_change_requires_owned_resolution_and_full_evidence_sequence(self) -> None:
        errors = spec_check.dependency_security_errors(
            DESIGN,
            task(
                "src/app.py", "Update the package.", title="Update dependency",
                resolution="change",
            ),
        )
        self.assertTrue(any("must own" in error for error in errors))
        self.assertTrue(any("canonical structured evidence" in error for error in errors))

    def test_lockfile_named_test_fixture_does_not_create_a_resolution_change(self) -> None:
        errors = spec_check.dependency_security_errors(
            DESIGN,
            task(
                "tests/fixtures/project/requirements.lock",
                "Add an offline fixture and verify parsing.",
                title="Add parser fixture",
            ),
        )
        self.assertEqual(errors, [])

    def test_canonical_metadata_is_required_parsed_and_keeps_earliest_none_ready(self) -> None:
        missing = task("src/app.py", "Implement behavior.", metadata=False)
        parsed, errors = spec_check.task_dependency_graph(missing)
        self.assertTrue(any("Dependency resolution" in error for error in errors))
        self.assertTrue(any("Dependency delivery" in error for error in errors))
        output = io.StringIO()
        with redirect_stdout(output):
            result = spec_check.emit_result(
                "json", Path("/project/.specs/example"), {"1.1"}, parsed, [], errors
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(1, result)
        self.assertFalse(payload["ok"])
        self.assertEqual([], payload["execution"]["ready"])

        tasks, errors = spec_check.task_dependency_graph(
            task("src/app.py", "Implement behavior.", title="Dependency-first bootstrap")
        )
        self.assertEqual([], errors)
        self.assertEqual("none", tasks[0]["dependency_resolution"])
        self.assertEqual("none", tasks[0]["dependency_delivery"])
        self.assertEqual(1, tasks[0]["computed_stage"])

    def test_task_contract_requires_documentation_verification_and_risk(self) -> None:
        complete = task("src/app.py", "Implement behavior.")
        for field in ("Documentation", "Verification", "Risk"):
            with self.subTest(field=field):
                missing = re.sub(
                    rf"(?mi)^\s*-\s+\*\*{field}:\*\*.*\n",
                    "",
                    complete,
                )
                _, errors = spec_check.task_dependency_graph(missing)
                self.assertIn(
                    f"task 1.1 must declare exactly one {field} field",
                    errors,
                )

    def test_task_contract_requires_traceability_effort_and_interfaces(self) -> None:
        complete = task("src/app.py", "Implement behavior.")
        cases = {
            "Requirements": r"(?mi)^\s*-\s+_Requirements:.*\n",
            "Estimated effort": r"(?mi)^\s*-\s+\*\*Estimated effort:\*\*.*\n",
            "Interfaces": r"(?mi)^\s*-\s+\*\*Interfaces:\*\*.*\n",
        }
        for field, pattern in cases.items():
            with self.subTest(field=field):
                missing = re.sub(pattern, "", complete)
                _, errors = spec_check.task_dependency_graph(missing)
                self.assertIn(
                    f"task 1.1 must declare exactly one {field} field",
                    errors,
                )

    def test_task_contract_rejects_unbounded_effort_and_implicit_interfaces(self) -> None:
        complete = task("src/app.py", "Implement behavior.")
        for estimate in ("soon", "15 minutes to forever", "15 minutes+"):
            with self.subTest(estimate=estimate):
                unbounded = complete.replace("15-30 minutes", estimate)
                _, effort_errors = spec_check.task_dependency_graph(unbounded)
                self.assertTrue(any("bounded duration" in error for error in effort_errors))

        implicit = complete.replace(
            "Consumes: approved design contract; Produces: `run()` behavior in src/app.py",
            "Implement the design",
        )
        _, interface_errors = spec_check.task_dependency_graph(implicit)
        self.assertTrue(any("Consumes and Produces" in error for error in interface_errors))

    def test_requirements_reject_non_ears_acceptance_criteria(self) -> None:
        valid = """# Requirements

### Requirement 1: Behavior

**User Story:** As a user, I want a result, so that I can continue.

#### Acceptance Criteria

1. **R1.1** WHEN input arrives, THE Processor SHALL emit a result.
2. **R1.2** IF input is invalid, THEN THE Processor SHALL emit an error.
"""
        self.assertEqual([], spec_check.requirements_contract_errors(valid))

        invalid = valid.replace(
            "WHEN input arrives, THE Processor SHALL emit a result.",
            "The processor should handle input robustly.",
        )
        errors = spec_check.requirements_contract_errors(invalid)
        self.assertTrue(any("R1.1 is not valid EARS" in error for error in errors))

    def test_task_structure_rejects_checked_parent_with_required_child_open(self) -> None:
        tasks = task("src/app.py", "Implement behavior.").replace("- [ ] 1. Group", "- [x] 1. Group")
        errors = spec_check.task_structure_errors(tasks)
        self.assertTrue(any("parent task 1 is checked" in error for error in errors))

    def test_task_structure_validates_checkpoint_syntax(self) -> None:
        tasks = task("src/app.py", "Implement behavior.") + "\n- [ ] Checkpoint maybe review\n"
        errors = spec_check.task_structure_errors(tasks)
        self.assertTrue(any("malformed checkpoint" in error for error in errors))

    def test_execution_timing_requires_canonical_tables_and_closed_values(self) -> None:
        missing = "# Execution Ledger: Example\n\nPending.\n"
        self.assertTrue(spec_check.execution_timing_errors(missing, require_timing=True))

        valid = """# Execution Ledger: Example

## Execution Timing

### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|
| run-20260809T120000Z | 2026-08-09T12:00:00Z | 2026-08-09T12:00:03Z | 3 | complete |

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|
| run-20260809T120000Z | 1/serial | 1.1 | 1 | 2026-08-09T12:00:00Z | 2026-08-09T12:00:03Z | 3 | verified |

### Execution Gantt

```mermaid
gantt
    dateFormat YYYY-MM-DDTHH:mm:ss
    axisFormat %m-%d %H:%M
    section Execution Runs
    complete (3s) :2026-08-09T12:00:00, 3s
```
"""
        self.assertEqual([], spec_check.execution_timing_errors(valid, require_timing=True))

    def test_resolution_metadata_drives_bump_pin_and_exact_manifest_lock_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "package-lock.json").write_text("{}", encoding="utf-8")
            for title in ("Bump runtime package", "Pin dependency", "Dependency-first update"):
                with self.subTest(title=title):
                    complete = task(
                        "package.json, package-lock.json", SECURE_DETAILS,
                        title=title, resolution="change",
                    )
                    self.assertEqual(
                        [],
                        spec_check.dependency_security_errors(
                            DESIGN, complete, project_root=root
                        ),
                    )

            missing_lock = task(
                "package.json", SECURE_DETAILS, title="Pin dependency", resolution="change"
            )
            self.assertTrue(any(
                "package-lock.json" in error for error in
                spec_check.dependency_security_errors(
                    DESIGN, missing_lock, project_root=root
                )
            ))

            title_only = task("src/app.py", "Bump a display label.", title="Bump package label")
            self.assertEqual(
                [], spec_check.dependency_security_errors(DESIGN, title_only, project_root=root)
            )
            neutral = task("src/app.py", "Update a display label.", title="Render package label")
            self.assertEqual(
                [], spec_check.dependency_security_errors(DESIGN, neutral, project_root=root)
            )

    def test_documentation_examples_and_fixtures_are_not_project_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in (
                "docs/package.json", "examples/Cargo.lock", "tests/fixtures/requirements.lock"
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
                with self.subTest(relative=relative):
                    self.assertEqual(
                        [],
                        spec_check.dependency_security_errors(
                            DESIGN, task(relative, "Update documentation evidence."), project_root=root
                        ),
                    )

    def test_requirements_variants_require_all_existing_shared_stem_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("requirements-dev.in", "requirements-dev.txt", "requirements-dev.lock"):
                (root / name).write_text("dependency==1.2.3", encoding="utf-8")
            incomplete = task(
                "requirements-dev.in", SECURE_DETAILS, resolution="change"
            )
            errors = spec_check.dependency_security_errors(
                DESIGN, incomplete, project_root=root
            )
            self.assertTrue(any("requirements-dev.txt" in error for error in errors))
            self.assertTrue(any("requirements-dev.lock" in error for error in errors))
            complete = task(
                "requirements-dev.in, requirements-dev.txt, requirements-dev.lock",
                SECURE_DETAILS,
                resolution="change",
            )
            self.assertEqual(
                [], spec_check.dependency_security_errors(DESIGN, complete, project_root=root)
            )

    def test_registry_pairs_uv_and_bun_locks_with_their_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("pyproject.toml", "uv.lock", "package.json", "bun.lock", "bun.lockb"):
                (root / name).write_text("resolution", encoding="utf-8")
            for owned, expected in (
                ("uv.lock", "pyproject.toml"),
                ("package.json, bun.lock", "bun.lockb"),
            ):
                with self.subTest(owned=owned):
                    errors = spec_check.dependency_security_errors(
                        DESIGN,
                        task(owned, SECURE_DETAILS, resolution="change"),
                        project_root=root,
                    )
                    self.assertTrue(any(expected in error for error in errors))

            complete = task(
                "pyproject.toml, uv.lock, package.json, bun.lock, bun.lockb",
                SECURE_DETAILS,
                resolution="change",
            )
            self.assertEqual(
                [], spec_check.dependency_security_errors(DESIGN, complete, project_root=root)
            )

    def test_nested_workspace_manifests_require_nearest_ancestor_lock(self) -> None:
        javascript_cases = (
            ("npm", "package-lock.json", True),
            ("pnpm", "pnpm-lock.yaml", False),
            ("yarn", "yarn.lock", True),
            ("bun", "bun.lock", True),
            ("bun binary", "bun.lockb", True),
        )
        for label, lock_name, package_declares_workspace in javascript_cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                nested = root / "packages" / "app" / "package.json"
                nested.parent.mkdir(parents=True)
                nested.write_text('{"name":"app"}', encoding="utf-8")
                root_package = '{"workspaces":["packages/*"]}' if package_declares_workspace else '{}'
                (root / "package.json").write_text(root_package, encoding="utf-8")
                if label == "pnpm":
                    (root / "pnpm-workspace.yaml").write_text(
                        "packages:\n  - 'packages/*'\n", encoding="utf-8"
                    )
                (root / lock_name).write_text("lock", encoding="utf-8")
                incomplete = task(
                    "packages/app/package.json", SECURE_DETAILS, resolution="change"
                )
                errors = spec_check.dependency_security_errors(
                    DESIGN, incomplete, project_root=root
                )
                self.assertTrue(any(lock_name in error for error in errors))
                complete = task(
                    f"packages/app/package.json, {lock_name}",
                    SECURE_DETAILS,
                    resolution="change",
                )
                self.assertEqual(
                    [], spec_check.dependency_security_errors(DESIGN, complete, project_root=root)
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "crates" / "app" / "Cargo.toml"
            nested.parent.mkdir(parents=True)
            nested.write_text('[package]\nname="app"\nversion="1.0.0"\n', encoding="utf-8")
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/*"]\n', encoding="utf-8"
            )
            (root / "Cargo.lock").write_text("lock", encoding="utf-8")
            incomplete = task("crates/app/Cargo.toml", SECURE_DETAILS, resolution="change")
            self.assertTrue(any(
                "Cargo.lock" in error for error in
                spec_check.dependency_security_errors(DESIGN, incomplete, project_root=root)
            ))
            complete = task(
                "crates/app/Cargo.toml, Cargo.lock", SECURE_DETAILS, resolution="change"
            )
            self.assertEqual(
                [], spec_check.dependency_security_errors(DESIGN, complete, project_root=root)
            )

    def test_workspace_exclusions_do_not_claim_ancestor_locks(self) -> None:
        for lock_name in ("package-lock.json", "yarn.lock", "bun.lock", "bun.lockb"):
            with self.subTest(package_workspace_lock=lock_name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                nested = root / "packages" / "excluded" / "package.json"
                nested.parent.mkdir(parents=True)
                nested.write_text('{"name":"excluded"}', encoding="utf-8")
                (root / "package.json").write_text(
                    '{"workspaces":["packages/*","!packages/excluded"]}',
                    encoding="utf-8",
                )
                (root / lock_name).write_text("lock", encoding="utf-8")
                self.assertEqual([], spec_check.dependency_security_errors(
                    DESIGN,
                    task("packages/excluded/package.json", SECURE_DETAILS, resolution="change"),
                    project_root=root,
                ))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "packages" / "excluded" / "package.json"
            nested.parent.mkdir(parents=True)
            nested.write_text('{"name":"excluded"}', encoding="utf-8")
            (root / "package.json").write_text('{}', encoding="utf-8")
            (root / "pnpm-lock.yaml").write_text("lock", encoding="utf-8")
            workspace = root / "pnpm-workspace.yaml"
            workspace.write_text(
                "packages:\n  - 'packages/*'\n  - '!packages/excluded'\n",
                encoding="utf-8",
            )
            nested_only = task(
                "packages/excluded/package.json", SECURE_DETAILS, resolution="change"
            )
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, nested_only, project_root=root
            ))
            workspace.write_text(
                "packages:\n  - 'packages/*'\n  - '!packages/excluded'\n  - 'packages/excluded'\n",
                encoding="utf-8",
            )
            self.assertTrue(any(
                "pnpm-lock.yaml" in error for error in
                spec_check.dependency_security_errors(DESIGN, nested_only, project_root=root)
            ))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "crates" / "excluded" / "Cargo.toml"
            nested.parent.mkdir(parents=True)
            nested.write_text('[package]\nname="excluded"\nversion="1.0.0"\n', encoding="utf-8")
            (root / "Cargo.toml").write_text(
                '[workspace]\nmembers=["crates/*"]\nexclude=["crates/excluded"]\n',
                encoding="utf-8",
            )
            (root / "Cargo.lock").write_text("lock", encoding="utf-8")
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN,
                task("crates/excluded/Cargo.toml", SECURE_DETAILS, resolution="change"),
                project_root=root,
            ))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "packages" / "app" / "package.json"
            nested.parent.mkdir(parents=True)
            nested.write_text('{"name":"app"}', encoding="utf-8")
            (root / "package.json").write_text(
                '{"workspaces":["packages/*","!../packages/*"]}', encoding="utf-8"
            )
            (root / "package-lock.json").write_text("lock", encoding="utf-8")
            self.assertTrue(any(
                "package-lock.json" in error for error in
                spec_check.dependency_security_errors(
                    DESIGN,
                    task("packages/app/package.json", SECURE_DETAILS, resolution="change"),
                    project_root=root,
                )
            ))

    def test_resolution_none_rejects_owned_files_and_change_clauses(self) -> None:
        for files, details in (
            ("package.json", "Implement behavior."),
            ("src/app.py", "Upgrade the dependency version."),
            ("src/app.py", "Pin the library."),
            ("src/app.py", "Bump the runtime package version."),
            ("src/app.py", "Regenerate the lockfile."),
            ("src/app.py", "Edit the manifest."),
        ):
            with self.subTest(files=files, details=details):
                errors = spec_check.dependency_security_errors(
                    DESIGN, task(files, details)
                )
                self.assertTrue(any("contradicts Dependency resolution: none" in error for error in errors))

    def test_resolution_none_allows_negated_historical_documentation_and_ui_copy(self) -> None:
        probes = (
            "Do not upgrade the dependency.",
            "The dependency was previously upgraded.",
            "We upgraded the dependency in the prior release.",
            "Last release upgraded the dependency.",
            "Two releases ago we upgraded the dependency.",
            "Document how to upgrade the dependency.",
            "Bump the library documentation version.",
            "Upgrade package documentation.",
            "Upgrade documentation for dependency.",
            "Update documentation for dependency version.",
            "Render the Upgrade dependency UI label text.",
        )
        for details in probes:
            with self.subTest(details=details):
                self.assertEqual(
                    [],
                    spec_check.dependency_security_errors(
                        DESIGN, task("src/app.py", details)
                    ),
                )

    def test_resolution_change_predicate_stays_attached_to_its_object_across_conjunctions(self) -> None:
        contradictions = (
            "Upgrade the dependency because the prior version was vulnerable.",
            "Update UI copy and upgrade the dependency.",
            "Document the API and bump the dependency version.",
            "Review the audit result and pin the package version.",
        )
        for details in contradictions:
            with self.subTest(details=details):
                self.assertTrue(any(
                    "contradicts Dependency resolution: none" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("src/app.py", details)
                    )
                ))
        historical_then_ui = (
            "The prior release upgraded the dependency; this task updates UI copy only."
        )
        self.assertEqual(
            [],
            spec_check.dependency_security_errors(
                DESIGN, task("src/app.py", historical_then_ui)
            ),
        )

    @unittest.skip("superseded by closed structured change-evidence record validation")
    def test_change_evidence_sequence_rejects_reversal_one_audit_plain_links_and_missing_review(self) -> None:
        cases = {
            "reversed": SECURE_DETAILS.replace(
                "Update dependency resolution. Run relevant project tests.",
                "Run relevant project tests. Update dependency resolution.",
            ),
            "one audit": SECURE_DETAILS.split("Run a fresh post-change", 1)[0],
            "plain links": SECURE_DETAILS.replace(
                "[latest.json](../../.security/dependency-audit/latest.json)", "`latest.json`"
            ),
            "missing review": SECURE_DETAILS.replace("then review", "then inspect"),
            "skip Context7": SECURE_DETAILS.replace(
                "Consult Current Technology Evidence with Context7.", "Skip Context7."
            ),
            "no Context7": SECURE_DETAILS.replace(
                "Consult Current Technology Evidence with Context7.", "No Context7 was consulted."
            ),
            "negated pre audit": SECURE_DETAILS.replace("Run a pre-change", "Do not run a pre-change"),
            "never pre audit": SECURE_DETAILS.replace("Run a pre-change", "Never run a pre-change"),
            "failed repeatedly pre audit": SECURE_DETAILS.replace(
                "Run a pre-change",
                "Failed repeatedly despite extensive documented operational safety concerns to run a pre-change",
            ),
            "attempted pre audit": SECURE_DETAILS.replace(
                "Run a pre-change",
                "Attempted repeatedly and unsuccessfully despite extensive operational constraints to run a pre-change",
            ),
            "tried despite pre audit": SECURE_DETAILS.replace(
                "Run a pre-change",
                "Tried, despite extensive documented recovery work, to run a pre-change",
            ),
            "missing pre report": SECURE_DETAILS.replace("then review [latest.json]", "then review missing [latest.json]", 1),
            "negated edit": SECURE_DETAILS.replace("Update dependency resolution", "Do not update dependency resolution"),
            "skipped tests": SECURE_DETAILS.replace("Run relevant project tests", "Skip relevant project tests"),
            "unable to run tests": SECURE_DETAILS.replace(
                "Run relevant project tests",
                "Was unable after several documented repeated environmental validation failures to run relevant project tests",
            ),
            "tried to run tests": SECURE_DETAILS.replace(
                "Run relevant project tests",
                "Tried repeatedly and unsuccessfully through many documented recovery procedures to run relevant project tests",
            ),
            "effort to run tests": SECURE_DETAILS.replace(
                "Run relevant project tests",
                "Made a sustained documented engineering effort to run relevant project tests",
            ),
            "implicit post audit": SECURE_DETAILS.replace(
                "post-change dependency-security-audit", "post-change audit"
            ),
            "negated post audit": SECURE_DETAILS.replace(
                "Run a fresh post-change", "Do not run a fresh post-change"
            ),
            "declined post audit": SECURE_DETAILS.replace(
                "Run a fresh post-change",
                "Declined for exceptionally strict documented release safety policy reasons to run a fresh post-change",
            ),
            "unsuccessful post audit attempt": SECURE_DETAILS.replace(
                "Run a fresh post-change",
                "Made an unsuccessful extensively documented recovery attempt to run a fresh post-change",
            ),
            "endeavored post audit": SECURE_DETAILS.replace(
                "Run a fresh post-change",
                "Endeavored through extensive documented recovery work to run a fresh post-change",
            ),
            "pre audit failed suffix": SECURE_DETAILS.replace(
                "change mode, then review", "change mode failed, then review", 1
            ),
            "pre audit contrast failure": SECURE_DETAILS.replace(
                "change mode, then review", "change mode, but it failed, then review", 1
            ),
            "post audit incomplete suffix": SECURE_DETAILS.rsplit(
                "change mode, then review", 1
            )[0] + "change mode was not completed, then review" + SECURE_DETAILS.rsplit(
                "change mode, then review", 1
            )[1],
            "post audit ultimate failure": SECURE_DETAILS.rsplit(
                "change mode, then review", 1
            )[0] + "change mode ultimately failed, then review" + SECURE_DETAILS.rsplit(
                "change mode, then review", 1
            )[1],
            "tests attempted suffix": SECURE_DETAILS.replace(
                "Run relevant project tests.",
                "Run relevant project tests was merely attempted.",
            ),
            "tests operational noun then failure": SECURE_DETAILS.replace(
                "Run relevant project tests.",
                "Run relevant project tests covering failed requests, but it ultimately failed.",
            ),
            "stale post reports": SECURE_DETAILS.rsplit("then review", 1)[0]
                + "then review stale [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
            "outdated post reports": SECURE_DETAILS.rsplit("then review", 1)[0]
                + "then review outdated [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
            "pre review different sentence": SECURE_DETAILS.replace(
                "then review [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                "then review the project logo. The reports are "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                1,
            ),
            "post review different sentence": SECURE_DETAILS.rsplit("then review", 1)[0]
                + "then review the project logo. The reports are "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
            "pre review wrong object": SECURE_DETAILS.replace(
                "then review [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                "then review the logo and archive links "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                1,
            ),
            "unable pre review": SECURE_DETAILS.replace(
                "then review [latest.json]",
                "then Was unable after repeated documented evidence access failures to review [latest.json]",
                1,
            ),
            "attempted pre review": SECURE_DETAILS.replace(
                "then review [latest.json]",
                "then Attempted repeatedly and unsuccessfully despite many recovery steps to review [latest.json]",
                1,
            ),
            "pre review failed after links": SECURE_DETAILS.replace(
                "[latest.md](../../.security/dependency-audit/latest.md). Update dependency resolution.",
                "[latest.md](../../.security/dependency-audit/latest.md), but review failed. Update dependency resolution.",
                1,
            ),
            "sought pre review": SECURE_DETAILS.replace(
                "then review [latest.json]",
                "then Sought through extensive documented recovery work to review [latest.json]",
                1,
            ),
            "post review wrong object": SECURE_DETAILS.rsplit("then review", 1)[0]
                + "then review the logo and archive links "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
        }
        for label, details in cases.items():
            with self.subTest(label=label):
                errors = spec_check.dependency_security_errors(
                    DESIGN,
                    task("package.json", details, resolution="change"),
                )
                self.assertTrue(any("dependency-changing task" in error for error in errors))

        for label, governor in (
            ("pre except", "except"),
            ("pre excluding", "excluding"),
            ("pre rather than", "rather than"),
            ("pre but not", "but not"),
        ):
            details = SECURE_DETAILS.replace(
                "then review [latest.json]",
                f"then review the audit reports {governor} [latest.json]",
                1,
            )
            with self.subTest(label=label):
                self.assertTrue(any(
                    "dependency-changing task" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("package.json", details, resolution="change")
                    )
                ))

        for label, governor in (
            ("post other than", "other than"),
            ("post instead of", "instead of"),
            ("post apart from", "apart from"),
            ("post save for", "save for"),
        ):
            prefix, suffix = SECURE_DETAILS.rsplit("then review [latest.json]", 1)
            details = prefix + f"then review the audit reports {governor} [latest.json]" + suffix
            with self.subTest(label=label):
                self.assertTrue(any(
                    "dependency-changing task" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("package.json", details, resolution="change")
                    )
                ))

    def test_structured_change_evidence_is_mandatory_and_exact(self) -> None:
        replacements = {
            "missing Context7": ("- **Context7 evidence:**", "- **Narrative Context7:**"),
            "Context7 incomplete": ("**Context7 evidence:** state=pending", "**Context7 evidence:** state=attempted"),
            "Context7 identity": ("identity=/org/library", "identity=library"),
            "Context7 version": ("version=1.2.3", "version=latest"),
            "Context7 decision": ("decision=use documented API", "decision="),
            "pre status": ("**Pre-change dependency audit:** state=pending", "**Pre-change dependency audit:** state=attempted"),
            "pre command": ("command=dependency-security-audit change", "command=generic audit"),
            "pre JSON": ("expected_json=.security/dependency-audit/pre.json", "expected_json=../pre.json"),
            "pre review": ("expected_markdown=.security/dependency-audit/pre.md | review=pending", "expected_markdown=.security/dependency-audit/pre.md | review=attempted"),
            "edit status": ("**Resolution edit:** state=pending", "**Resolution edit:** state=attempted"),
            "edit files": ("expected_files=package.json, package-lock.json", "expected_files=README.md"),
            "tests status": ("**Project tests:** state=pending", "**Project tests:** state=failed"),
            "tests evidence": ("expected_evidence=test-results.txt", "expected_evidence=../results.txt"),
            "post status": ("**Post-change dependency audit:** state=pending", "**Post-change dependency audit:** state=attempted"),
            "post command": ("**Post-change dependency audit:** state=pending | command=dependency-security-audit change", "**Post-change dependency audit:** state=pending | command=dependency-security-audit main"),
            "post review": ("expected_markdown=.security/dependency-audit/post.md | review=pending", "expected_markdown=.security/dependency-audit/post.md | review=failed"),
            "same reports": ("expected_json=.security/dependency-audit/post.json", "expected_json=.security/dependency-audit/pre.json"),
        }
        for label, (old, new) in replacements.items():
            with self.subTest(label=label):
                details = SECURE_DETAILS.replace(old, new)
                self.assertTrue(any(
                    "dependency-changing task" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("package.json, package-lock.json", details, resolution="change")
                    )
                ))
        prose_claims = (
            "Consulted Context7 and ran, reviewed, edited, tested, and re-audited everything successfully.",
            "Tried, despite extensive recovery work, to run and review every audit.",
            "Made a sustained effort to test the project and verify the reports.",
            "Endeavored to complete the dependency change and post-change audit.",
            "Sought to review both reports and document the result.",
            "The run failed, was not completed, and was merely attempted.",
            "After consulting Context7, next and finally we ran the checks.",
        )
        for prose_only in prose_claims:
            with self.subTest(prose_only=prose_only):
                self.assertTrue(any("canonical structured evidence" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("package.json, package-lock.json", prose_only, resolution="change")
                    )
                ))

    def test_delivery_checkpoints_require_fresh_mode_specific_evidence(self) -> None:
        incomplete = task("docs/release.md", "Review readiness.", delivery="release")
        errors = spec_check.dependency_security_errors(DESIGN, incomplete)
        self.assertTrue(any("delivery gate 1.1" in error for error in errors))

        complete = task(
            "docs/release.md", GATE_DETAILS, title="Publish artifacts", delivery="release"
        )
        self.assertEqual([], spec_check.dependency_security_errors(DESIGN, complete))
        named_reports = task(
            "docs/release.md",
            GATE_DETAILS.replace("Review [latest", "Review the audit reports: [latest"),
            delivery="release",
        )
        self.assertEqual([], spec_check.dependency_security_errors(DESIGN, named_reports))
        main_gate = task(
            "docs/release.md",
            GATE_DETAILS.replace("mode=release", "mode=main"),
            title="Integrate artifacts",
            delivery="main",
        )
        self.assertEqual([], spec_check.dependency_security_errors(DESIGN, main_gate))
        for decision_action in (
            "Make the final delivery decision",
            "Review the explicit release decision",
            "Document the dependency security delivery decision",
        ):
            with self.subTest(decision_action=decision_action):
                details = GATE_DETAILS.replace("Record the delivery decision", decision_action)
                self.assertEqual([], spec_check.dependency_security_errors(
                    DESIGN, task("docs/release.md", details, delivery="release")
                ))

    @unittest.skip("superseded by closed structured delivery-evidence record validation")
    def test_delivery_metadata_rejects_stale_missing_timestamp_false_clean_and_ship_blocks(self) -> None:
        cases = {
            "stale": GATE_DETAILS + " Stale evidence may satisfy the gate and ship.",
            "missing timestamp": GATE_DETAILS.replace("; verify its timestamp", ""),
            "false clean": GATE_DETAILS.replace("Warnings are not clean", "Warnings are clean"),
            "ship block": GATE_DETAILS.replace(
                "cannot ship or satisfy the gate", "can ship and satisfy the gate"
            ),
            "implicit warning review": GATE_DETAILS.replace("explicitly reviewed", "reviewed"),
            "negated run": GATE_DETAILS.replace("Run a fresh", "Do not run a fresh"),
            "declined audit run": GATE_DETAILS.replace(
                "Run a fresh",
                "Declined for exceptionally strict documented delivery safety policy reasons to run a fresh",
            ),
            "tried audit run": GATE_DETAILS.replace(
                "Run a fresh",
                "Tried repeatedly and unsuccessfully despite extensive recovery procedures to run a fresh",
            ),
            "effort audit run": GATE_DETAILS.replace(
                "Run a fresh",
                "Made a sustained documented release effort to run a fresh",
            ),
            "audit failed suffix": GATE_DETAILS.replace(
                "release mode;", "release mode failed;"
            ),
            "audit contrast failure": GATE_DETAILS.replace(
                "release mode;", "release mode, but it failed;"
            ),
            "negated timestamp": GATE_DETAILS.replace("verify its timestamp", "do not verify its timestamp"),
            "unable timestamp": GATE_DETAILS.replace(
                "verify its timestamp",
                "was unable after repeated documented evidence access failures to verify its timestamp",
            ),
            "timestamp attempt": GATE_DETAILS.replace(
                "verify its timestamp",
                "made an unsuccessful extensively documented evidence recovery attempt to verify its timestamp",
            ),
            "sought timestamp": GATE_DETAILS.replace(
                "verify its timestamp",
                "sought through extensive documented evidence recovery work to verify its timestamp",
            ),
            "timestamp incomplete suffix": GATE_DETAILS.replace(
                "verify its timestamp", "verify its timestamp was not completed"
            ),
            "timestamp reported incomplete": GATE_DETAILS.replace(
                "verify its timestamp", "verify its timestamp was reportedly not completed"
            ),
            "missing report": GATE_DETAILS.replace("Review [latest.json]", "Review missing [latest.json]"),
            "failed report review": GATE_DETAILS.replace(
                "Review [latest.json]",
                "Failed repeatedly despite extensive documented evidence access recovery attempts to review [latest.json]",
            ),
            "attempted report review": GATE_DETAILS.replace(
                "Review [latest.json]",
                "Attempted repeatedly and unsuccessfully despite extensive recovery procedures to review [latest.json]",
            ),
            "endeavored report review": GATE_DETAILS.replace(
                "Review [latest.json]",
                "Endeavored through extensive documented recovery work to review [latest.json]",
            ),
            "review attempted after links": GATE_DETAILS.replace(
                "[latest.md](../../.security/dependency-audit/latest.md). Only pass",
                "[latest.md](../../.security/dependency-audit/latest.md) was merely attempted. Only pass",
            ),
            "review failed after links": GATE_DETAILS.replace(
                "[latest.md](../../.security/dependency-audit/latest.md). Only pass",
                "[latest.md](../../.security/dependency-audit/latest.md), but review failed. Only pass",
            ),
            "missing decision": GATE_DETAILS.replace("Record the delivery decision", "Skip the delivery decision"),
            "refused decision": GATE_DETAILS.replace(
                "Record the delivery decision",
                "Refused for exceptionally strict documented release safety policy reasons to record the delivery decision",
            ),
            "failed documented-attempt decision": GATE_DETAILS.replace(
                "Record the delivery decision",
                "A failed extensively documented attempt to record the delivery decision",
            ),
            "sought decision": GATE_DETAILS.replace(
                "Record the delivery decision",
                "Sought through extensive documented review work to record the delivery decision",
            ),
            "decision attempted suffix": GATE_DETAILS.replace(
                "Record the delivery decision",
                "Record the delivery decision was merely attempted",
            ),
            "decision contrast failure": GATE_DETAILS.replace(
                "Record the delivery decision",
                "Record the delivery decision, but no decision was made",
            ),
            "documented is not decision action": GATE_DETAILS.replace(
                "Record the delivery decision",
                "The delivery decision was documented",
            ),
            "review different sentence": GATE_DETAILS.replace(
                "Review [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                "Review the project logo. The reports are "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
            ),
            "review wrong object": GATE_DETAILS.replace(
                "Review [latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
                "Review the logo and archive links "
                "[latest.json](../../.security/dependency-audit/latest.json) and "
                "[latest.md](../../.security/dependency-audit/latest.md).",
            ),
        }
        for label, details in cases.items():
            with self.subTest(label=label):
                errors = spec_check.dependency_security_errors(
                    DESIGN,
                    task(
                        "docs/release.md", details, title="Publish artifacts", delivery="release"
                    ),
                )
                self.assertTrue(any("delivery gate" in error for error in errors))

        for governor in (
            "except", "excluding", "rather than", "but not",
            "other than", "instead of", "apart from", "save for",
        ):
            details = GATE_DETAILS.replace(
                "Review [latest.json]",
                f"Review the audit reports {governor} [latest.json]",
            )
            with self.subTest(delivery_review_governor=governor):
                self.assertTrue(any(
                    "delivery gate" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("docs/release.md", details, delivery="release")
                    )
                ))

    def test_structured_delivery_evidence_is_fresh_fail_closed_and_exact(self) -> None:
        replacements = {
            "mode": ("mode=release", "mode=main"),
            "timestamp": ("timestamp=2026-08-08T12:00:00Z", "timestamp=yesterday"),
            "timezone": ("timestamp=2026-08-08T12:00:00Z", "timestamp=2026-08-08T12:00:00"),
            "revision": ("revision=" + "a" * 40, "revision=latest"),
            "JSON link": ("JSON=[release.json](../../.security/dependency-audit/release.json)", "JSON=release.json"),
            "Markdown link": ("Markdown=[release.md](../../.security/dependency-audit/release.md)", "Markdown=release.md"),
            "review": ("review=completed", "review=attempted"),
            "exit mapping": ("result=pass | exit=0", "result=pass | exit=1"),
            "blocked": ("result=pass | exit=0", "result=blocked | exit=1"),
            "unavailable": ("result=pass | exit=0", "result=unavailable | exit=2"),
            "invalid": ("result=pass | exit=0", "result=invalid | exit=3"),
            "decision": ("decision=ship", "decision="),
            "unknown key": ("decision=ship", "decision=ship | surprise=true"),
        }
        for label, (old, new) in replacements.items():
            with self.subTest(label=label):
                details = COMPLETED_GATE_DETAILS.replace(old, new)
                self.assertTrue(any("delivery gate" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("docs/release.md", details, delivery="release", checked=True)
                    )
                ))

    def test_checked_change_requires_real_ordered_completed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            security = root / ".security" / "dependency-audit"
            security.mkdir(parents=True)
            for path in (root / "package.json", root / "package-lock.json", root / "test-results.txt", security / "pre.md", security / "post.md"):
                path.write_text("evidence", encoding="utf-8")
            revision = "a" * 40
            pre_fingerprint, post_fingerprint = "1" * 64, "2" * 64
            post_time = datetime.now(timezone.utc).replace(microsecond=0)
            pre_time = post_time - timedelta(hours=1)
            pre_timestamp = pre_time.isoformat().replace("+00:00", "Z")
            post_timestamp = post_time.isoformat().replace("+00:00", "Z")
            for stem, timestamp, fingerprint in (
                ("pre", pre_timestamp, pre_fingerprint),
                ("post", post_timestamp, post_fingerprint),
            ):
                (security / f"{stem}.json").write_text(json.dumps(
                    audit_result_json("change", timestamp, revision, fingerprint)
                ), encoding="utf-8")
            completed = f"""
- **Context7 evidence:** state=completed | identity=/org/library | version=1.2.3 | decision=use documented API
- **Pre-change dependency audit:** state=completed | command=dependency-security-audit change | mode=change | timestamp={pre_timestamp} | project_revision={revision} | inventory_fingerprint={pre_fingerprint} | JSON=[pre.json](../../.security/dependency-audit/pre.json) | Markdown=[pre.md](../../.security/dependency-audit/pre.md) | review=completed | result=pass | exit=0 | decision=proceed | warnings_reviewed=false | clean=true
- **Resolution edit:** state=completed | files=[package.json](../../package.json), [package-lock.json](../../package-lock.json)
- **Project tests:** state=completed | evidence=[test results](../../test-results.txt)
- **Post-change dependency audit:** state=completed | command=dependency-security-audit change | mode=change | timestamp={post_timestamp} | project_revision={revision} | inventory_fingerprint={post_fingerprint} | JSON=[post.json](../../.security/dependency-audit/post.json) | Markdown=[post.md](../../.security/dependency-audit/post.md) | review=completed | result=pass | exit=0 | decision=merge | warnings_reviewed=false | clean=true
"""
            checked_task = lambda details: task(
                "package.json, package-lock.json", details, resolution="change", checked=True
            )
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_task(completed), project_root=root
            ))
            valid_pre_json = (security / "pre.json").read_text(encoding="utf-8")
            wrong_mode = json.loads(valid_pre_json)
            wrong_mode["mode"] = "main"
            (security / "pre.json").write_text(json.dumps(wrong_mode), encoding="utf-8")
            self.assertTrue(spec_check.dependency_security_errors(
                DESIGN, checked_task(completed), project_root=root
            ))
            (security / "pre.json").write_text("{}", encoding="utf-8")
            self.assertTrue(spec_check.dependency_security_errors(
                DESIGN, checked_task(completed), project_root=root
            ))
            (security / "pre.json").write_text(valid_pre_json, encoding="utf-8")
            forward_compatible = json.loads(valid_pre_json)
            forward_compatible["future_extension"] = {"supported_later": True}
            (security / "pre.json").write_text(json.dumps(forward_compatible), encoding="utf-8")
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_task(completed), project_root=root
            ))
            (security / "pre.json").write_text(valid_pre_json, encoding="utf-8")
            valid_post_json = (security / "post.json").read_text(encoding="utf-8")
            timing_cases = {
                "future post": (post_time + timedelta(hours=1), post_time),
                "stale post": (post_time - timedelta(hours=25), post_time - timedelta(hours=26)),
                "sequence over seven days": (post_time, post_time - timedelta(days=8)),
            }
            for label, (case_post, case_pre) in timing_cases.items():
                case_post_text = case_post.isoformat().replace("+00:00", "Z")
                case_pre_text = case_pre.isoformat().replace("+00:00", "Z")
                timed_details = completed.replace(pre_timestamp, "__PRE_TIMESTAMP__", 1)
                timed_details = timed_details.replace(post_timestamp, case_post_text, 1).replace(
                    "__PRE_TIMESTAMP__", case_pre_text, 1
                )
                (security / "pre.json").write_text(json.dumps(
                    audit_result_json("change", case_pre_text, revision, pre_fingerprint)
                ), encoding="utf-8")
                (security / "post.json").write_text(json.dumps(
                    audit_result_json("change", case_post_text, revision, post_fingerprint)
                ), encoding="utf-8")
                with self.subTest(change_timing=label):
                    self.assertTrue(spec_check.dependency_security_errors(
                        DESIGN, checked_task(timed_details), project_root=root
                    ))
            (security / "pre.json").write_text(valid_pre_json, encoding="utf-8")
            (security / "post.json").write_text(valid_post_json, encoding="utf-8")
            context_line, pre_line = completed.splitlines()[1:3]
            reversed_records = completed.replace(
                context_line + "\n" + pre_line, pre_line + "\n" + context_line
            )
            cases = {
                "order": reversed_records,
                "unknown key": completed.replace("decision=use documented API", "decision=use documented API | extra=yes"),
                "blocked audit": completed.replace("result=pass | exit=0 | decision=proceed", "result=blocked | exit=1 | decision=stop", 1),
                "unsafe report": completed.replace("../../.security/dependency-audit/pre.json", "../../../outside.json"),
                "label mismatch": completed.replace("[package.json](../../package.json)", "[wrong.json](../../package.json)"),
                "plain tests": completed.replace("[test results](../../test-results.txt)", "tests passed"),
            }
            for label, details in cases.items():
                with self.subTest(label=label):
                    self.assertTrue(spec_check.dependency_security_errors(
                        DESIGN, checked_task(details), project_root=root
                    ))
            (security / "post.md").unlink()
            self.assertTrue(spec_check.dependency_security_errors(
                DESIGN, checked_task(completed), project_root=root
            ))

    def test_checked_delivery_correlates_real_reports_revision_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            root.mkdir()
            security = root / ".security" / "dependency-audit"
            security.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
            (root / "seed.txt").write_text("seed", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "seed.txt"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "seed"], check=True)
            revision = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True,
            ).stdout.strip()
            timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            completed_gate = COMPLETED_GATE_DETAILS.replace(
                "2026-08-08T12:00:00Z", timestamp
            ).replace("a" * 40, revision)
            evidence = audit_result_json("release", timestamp, revision, "a" * 64)
            (security / "release.json").write_text(json.dumps(evidence), encoding="utf-8")
            (security / "release.md").write_text("# Release dependency evidence", encoding="utf-8")
            checked_gate = lambda details: task(
                "docs/release.md", details, delivery="release", checked=True
            )
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=root
            ))
            valid_delivery_json = (security / "release.json").read_text(encoding="utf-8")
            wrong_mode_json = dict(evidence, mode="main")
            (security / "release.json").write_text(json.dumps(wrong_mode_json), encoding="utf-8")
            self.assertTrue(spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=root
            ))
            (security / "release.json").write_text("{}", encoding="utf-8")
            self.assertTrue(spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=root
            ))
            (security / "release.json").write_text(valid_delivery_json, encoding="utf-8")
            forward_compatible = dict(evidence, future_extension={"accepted": True})
            (security / "release.json").write_text(json.dumps(forward_compatible), encoding="utf-8")
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=root
            ))
            for label, mutation in {
                "unsupported schema": {**evidence, "schema_version": "2.0"},
                "missing required top-level": {key: value for key, value in evidence.items() if key != "sources"},
                "invalid inventory fingerprint": {
                    **evidence, "inventory": {**evidence["inventory"], "fingerprint": "short"},
                },
                "missing inventory field": {
                    **evidence,
                    "inventory": {
                        key: value for key, value in evidence["inventory"].items()
                        if key != "statuses"
                    },
                },
                "invalid source container": {**evidence, "sources": ["not-a-source"]},
                "invalid finding container": {**evidence, "findings": [{"package": {}}]},
                "invalid decision container": {**evidence, "decisions": [{"decision": "warn"}]},
            }.items():
                with self.subTest(json_schema=label):
                    (security / "release.json").write_text(json.dumps(mutation), encoding="utf-8")
                    self.assertTrue(spec_check.dependency_security_errors(
                        DESIGN, checked_gate(completed_gate), project_root=root
                    ))
            (security / "release.json").write_text(valid_delivery_json, encoding="utf-8")
            for label, details in {
                "record timestamp mismatch": completed_gate.replace(timestamp, (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")),
                "record revision mismatch": completed_gate.replace(revision, "d" * 40),
                "different stems": completed_gate.replace("release.md", "other.md"),
                "unsafe JSON": completed_gate.replace("../../.security/dependency-audit/release.json", "../../../release.json"),
                "stale": completed_gate.replace(timestamp, (datetime.now(timezone.utc) - timedelta(hours=25)).replace(microsecond=0).isoformat().replace("+00:00", "Z")),
                "wrong mode": completed_gate.replace("mode=release", "mode=main"),
            }.items():
                with self.subTest(label=label):
                    self.assertTrue(spec_check.dependency_security_errors(
                        DESIGN, checked_gate(details), project_root=root
                    ))
            subprocess.run(["git", "-C", str(root), "pack-refs", "--all"], check=True)
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=root
            ))
            worktree = base / "worktree"
            subprocess.run(
                ["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(worktree), "HEAD"],
                check=True,
            )
            worktree_security = worktree / ".security" / "dependency-audit"
            worktree_security.mkdir(parents=True)
            (worktree_security / "release.json").write_text(json.dumps(evidence), encoding="utf-8")
            (worktree_security / "release.md").write_text(
                "# Release dependency evidence", encoding="utf-8"
            )
            self.assertEqual([], spec_check.dependency_security_errors(
                DESIGN, checked_gate(completed_gate), project_root=worktree
            ))
        warnings = COMPLETED_GATE_DETAILS.replace("result=pass", "result=warnings").replace(
            "warnings_reviewed=false | clean=true", "warnings_reviewed=true | clean=false"
        )
        self.assertEqual([], spec_check.dependency_security_errors(
            DESIGN, task("docs/release.md", warnings, delivery="release", checked=True)
        ))
        for label, details in (
            ("unreviewed warnings", warnings.replace("warnings_reviewed=true", "warnings_reviewed=false")),
            ("false clean", warnings.replace("clean=false", "clean=true")),
            ("prose only", "Ran a fresh release audit, reviewed reports and decided to ship."),
        ):
            with self.subTest(label=label):
                self.assertTrue(any("delivery gate" in error for error in
                    spec_check.dependency_security_errors(
                        DESIGN, task("docs/release.md", details, delivery="release", checked=True)
                    )
                ))

    def test_all_phases_reference_the_focused_skill_and_shared_policy(self) -> None:
        """Every phase delegates dependency-security wording to one canonical policy.

        The full mode/report/status/exit vocabulary used to be duplicated in each phase's
        SKILL.md; it now lives once in dependency-evidence.md (see
        test_dependency_policy_documents_modes_reports_statuses_and_exits below). Each phase
        only needs to name the focused skill and link to that shared policy.
        """
        phase_files = (
            SKILLS_ROOT / "spec-driven" / "SKILL.md",
            SKILLS_ROOT / "spec-design" / "SKILL.md",
            SKILLS_ROOT / "spec-tasks" / "SKILL.md",
            SKILLS_ROOT / "spec-execute" / "SKILL.md",
            SKILLS_ROOT / "spec-audit" / "SKILL.md",
        )
        for path in phase_files:
            with self.subTest(path=path.name, parent=path.parent.name):
                text = path.read_text(encoding="utf-8").casefold()
                self.assertIn("dependency-security-audit", text, f"{path} lacks dependency-security-audit")
                self.assertIn("change", text, f"{path} lacks change")
                self.assertIn(
                    "dependency-evidence.md", text,
                    f"{path} must link to the shared dependency-evidence.md policy",
                )

    def test_dependency_policy_documents_modes_reports_statuses_and_exits(self) -> None:
        """The canonical policy (not each phase) is the single source for the full vocabulary."""
        policy_text = (
            SKILL_DIR / "references" / "dependency-evidence.md"
        ).read_text(encoding="utf-8").casefold()
        artifacts_text = (
            SKILL_DIR / "references" / "artifacts.md"
        ).read_text(encoding="utf-8").casefold()
        for token in (
            "change", "main", "release", "pass", "warnings", "blocked", "unavailable",
            "invalid", "exit `0`", "exits `1`, `2`, and `3`", "broad security",
        ):
            self.assertIn(token, policy_text, f"dependency-evidence.md lacks {token}")
        for token in ("latest.json", "latest.md"):
            self.assertIn(token, artifacts_text, f"artifacts.md lacks {token}")

    def test_artifact_reference_contains_human_evidence_template(self) -> None:
        text = (SKILL_DIR / "references" / "artifacts.md").read_text(encoding="utf-8")
        self.assertIn("## Dependency security evidence", text)
        self.assertIn("## Dependency Security Evidence", text)
        self.assertIn("latest.json", text)
        self.assertIn("latest.md", text)
        self.assertIn("**Dependency resolution:** none / change", text)
        self.assertIn("**Dependency delivery:** none / main / release", text)
        self.assertIn("Exclude non-material process metadata", text)

    def test_published_requirements_template_satisfies_checker_contract(self) -> None:
        text = (SKILL_DIR / "references" / "artifacts.md").read_text(encoding="utf-8")
        match = re.search(
            r"## 02_requirements\.md template\s+```markdown\n(?P<template>.*?)\n```",
            text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(
            [],
            spec_check.requirements_contract_errors(match.group("template")),
        )


if __name__ == "__main__":
    unittest.main()
