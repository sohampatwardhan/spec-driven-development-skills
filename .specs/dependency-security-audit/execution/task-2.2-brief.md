# Task 2.2 Brief: Inventory and Native Audit Adapters

Implement only task 2.2 from the approved task plan.

## Contract

- Own only `scripts/dependency_audit/inventory.py`, `tests/test_inventory.py`, and the five named
  inventory fixtures under the canonical dependency-security-audit skill.
- Use existing models without modifying them.
- Parse exact npm, pip, Cargo, Go, and CycloneDX JSON resolved evidence.
- Preserve direct/transitive dependency identity and runtime/development/unknown scope where the
  evidence supports it; never infer development-only from missing scope.
- Reject missing/non-exact versions, deduplicate by package URL, build dependency edges, and hash a
  canonical package/scope/edge representation.
- Invoke native commands as argument arrays with bounded execution and explicit source status;
  distinguish not applicable, unavailable, partial, and complete evidence.
- Follow RED → GREEN → REFACTOR → DOCUMENT → VERIFY and verify requirements 2.1–2.4, 8.1, 8.2.
- Do not edit models, spec artifacts, or other task files.

## Technology Evidence

The approved design records CycloneDX component `name`, exact `version`, package URL, `bom-ref`, and
dependency `ref`/`dependsOn`. Parse that documented subset with the standard library. Treat absent
exact versions or unresolved graph references as incomplete.

## Verification

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_inventory.py' -v`

Document public adapter/runner/fingerprint contracts and the reasons for conservative completeness.
