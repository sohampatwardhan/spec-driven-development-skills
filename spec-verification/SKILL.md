---
name: spec-verification
description: Use before marking a spec task complete, advancing a stage, reporting success, committing completion, or handing implemented work to integration.
version: 1.0.0
---

# Spec Verification

Evidence precedes every completion claim.

## Related Skills

[`spec-execute`](../spec-execute/SKILL.md) ·
[`spec-debugging`](../spec-debugging/SKILL.md) · [`spec-finish`](../spec-finish/SKILL.md)

## Gate

1. Identify the exact command or observable check that proves the claim.
2. Run it fresh against the current tree; read the complete relevant output and exit status.
3. Verify the cited EARS criteria, task `Verification` contract, documentation contract, and changed-file scope independently.
4. Run the appropriate affected regression suite; the final gate runs the full available suite.
5. Compare with the recorded baseline. Pre-existing failures remain explicit and cannot be called green.
6. Record command, result, revision/diff, and criterion verdict in `05_execution.md` or the task report.
7. Only then check the task, advance the stage, commit completion, or state success.

A subagent report, diff existence, stale command output, partial suite, lint-only result, or “should pass” is not verification. When evidence disagrees with the intended claim, report the actual state and invoke `spec-debugging` for unexpected failures.
