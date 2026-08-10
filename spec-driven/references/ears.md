# EARS — Easy Approach to Requirements Syntax

EARS makes acceptance criteria unambiguous and testable by constraining each to one of a
few sentence templates. Every criterion has a **trigger/condition** and a **single actor**
that **SHALL** do a **single observable behavior**. Keep one requirement per line.

Use the actual system/component name as the actor (e.g. `THE Label_Assigner SHALL …`),
not a vague "the system", once components are known.

## The five templates

| Kind | Template | Use for |
|---|---|---|
| **Ubiquitous** | `THE <actor> SHALL <behavior>` | Always-true invariants |
| **Event-driven** | `WHEN <trigger>, THE <actor> SHALL <behavior>` | Response to an event |
| **State-driven** | `WHILE <state>, THE <actor> SHALL <behavior>` | Behavior during a mode/state |
| **Unwanted / error** | `IF <unwanted condition>, THEN THE <actor> SHALL <behavior>` | Error handling, edge cases |
| **Optional feature** | `WHERE <feature is included>, THE <actor> SHALL <behavior>` | Behavior gated on an optional feature |

Combine sparingly: `WHILE <state>, WHEN <trigger>, THE <actor> SHALL <behavior>`.

## Rules that keep criteria testable

- **One behavior per criterion.** If you wrote "and", consider splitting.
- **Observable.** The behavior must be verifiable from outside the actor (output, state
  change, message, error). Avoid "handle", "support", "manage" — say what's observable.
- **No solution detail.** Requirements say *what*, not *how* (that's design).
- **Number them** under each requirement so design and tasks can cite them (R2.3 = requirement 2, criterion 3).

## Example

```markdown
### Requirement 2: Duplicate detection

**User Story:** As a maintainer, I want duplicate issues flagged, so that I avoid
triaging the same report twice.

#### Acceptance Criteria

1. WHEN a new issue is created, THE Duplicate_Detector SHALL compare it against open issues.
2. IF a duplicate is found, THEN THE Issue_Manager SHALL post a linking comment and stop further processing.
3. WHILE the repo has more than 5000 open issues, THE Duplicate_Detector SHALL limit comparison to the most recent 5000.
4. WHERE semantic search is enabled, THE Duplicate_Detector SHALL rank candidates by embedding similarity.
```

Criteria above are individually testable: each maps to a check `spec-execute` can verify.
