# Task 2.1 Brief: Policy and Remediation Engine

Implement only task 2.1 from the approved task plan.

## Contract

- Own only `/Users/soham/.agents/skills/dependency-security-audit/scripts/dependency_audit/policy.py`
  and `/Users/soham/.agents/skills/dependency-security-audit/tests/test_policy.py`.
- Use the existing versioned models without modifying them.
- Follow RED → GREEN → REFACTOR → DOCUMENT → VERIFY.
- Encode exact withdrawn, KEV, no-fix, development-only, proven-unreachable, severity, and stricter
  policy precedence with stable reason codes.
- Implement lowest common authoritative fixed-version selection and release no-fix acceptance.
- Verify requirements 3.3, 3.6, 3.7, 4.1–4.8, 6.1, and 6.2.
- Do not edit the task checklist, state, ledger, or any other task files.

## Verification

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s /Users/soham/.agents/skills/dependency-security-audit/tests -p 'test_policy.py' -v`

Public functions and policy types require Python docstrings explaining contract and rationale.
