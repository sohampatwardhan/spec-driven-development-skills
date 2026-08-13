---
name: spec-finish
description: Use after every required spec task and final review pass, when deciding how to integrate, preserve, or deliver the completed implementation.
version: 1.0.0
---

# Spec Finish (Phase 6)

Verify the final tree, then let the user choose integration. Never assume merge, push, deployment, cleanup, or discard intent.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-execute`](../spec-execute/SKILL.md) ·
[`spec-verification`](../spec-verification/SKILL.md) ·
[`spec-debugging`](../spec-debugging/SKILL.md)

## Workflow

1. Invoke `spec-verification`; run the full available test/build suite and the final requirement checklist on the current revision. Stop on any unexplained failure.
2. Confirm final independent whole-change review has no unresolved load-bearing finding. Record deferred minor findings.
3. Detect current branch, base branch, worktree ownership, dirty state, and remote. Never finish directly on protected `main`/`master` without explicit consent.
4. Present applicable choices:
   - merge locally into the confirmed base and re-run verification on the merged tree;
   - push and create a PR against the confirmed base;
   - keep the branch/worktree unchanged.
5. Execute only the selected choice. A rejected push or merge conflict triggers investigation; never force-push or discard implicitly.
6. Clean up only a worktree and branch created for this spec, and only after a verified local merge. Preserve the worktree for PR iteration.
7. Discard only after the user explicitly confirms the exact branch, commits, and worktree to delete.
8. Record the integration decision and URL/commit where applicable in `05_execution.md` and `00_state.md`.

Deployment is a separate, explicitly authorized workflow. Completion of a spec does not authorize production access or release.
