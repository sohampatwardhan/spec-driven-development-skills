---
name: spec-requirements
description: Use when writing or refining a feature's requirements for spec-driven development — capturing user stories with EARS acceptance criteria in 02_requirements.md (phase 2). Triggers on "write requirements", "EARS", "acceptance criteria", "user stories", or after discovery is approved.
---

# Spec Requirements (Phase 2)

Turn a feature idea into `02_requirements.md`: numbered requirements, each a **user story**
plus **EARS** acceptance criteria that are individually testable.

> [!IMPORTANT]
> `02_requirements.md` is the phase-2 approval gate. Do not begin
> `03_design.md` until the user approves the requirements.

**Core principle:** Requirements say *what* the system must do and how you'd verify it —
never *how* it's built (that's design). If a criterion isn't observably testable, rewrite it.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-discovery`](../spec-discovery/SKILL.md) ·
[`spec-design`](../spec-design/SKILL.md) · [`spec-steering`](../spec-steering/SKILL.md) ·
[`mermaid`](../mermaid/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md)

**REQUIRED:** Resolve the active `spec-driven` skill directory and follow its `references/ears.md`
and `references/artifacts.md`; never assume a tool-specific home-directory path.
Read the feature's approved `01_discovery.md` and require the Discovery gate in `00_state.md` to
be `approved`. If `.specs/steering/` exists, read it first for context. A legacy feature without
discovery must migrate through `spec-discovery`; requirements drafting is not a substitute.

## Workflow

1. **Translate the approved discovery.** Confirm the chosen direction, scope, non-goals, users,
   and success measures. Ask one focused question only when an observable requirement remains
   ambiguous. For a brownfield feature, use `codebase-memory-reference` and
   graph discovery when available to check existing capabilities and integration constraints,
   but keep the resulting requirements behavioral and implementation-agnostic. Don't over-elicit
   — enough to write clear requirements.
2. **Draft requirements.** Group into numbered requirements, each with:
   - a **User Story**: `As a <role>, I want <capability>, so that <benefit>.`
   - **Acceptance Criteria** in EARS, numbered (R<n>.1, R<n>.2, …).
3. **Cover the unhappy paths.** Add `IF <unwanted condition>, THEN THE <actor> SHALL …`
   criteria for errors and edge cases — these are where under-specification bites.
4. **Identify evolving-technology constraints.** If the feature's user-visible behavior
   depends on a library, framework, SDK, API, CLI, or cloud service that can change, record
   the capability or compatibility constraint without prescribing an implementation. Defer
   current-document research to `spec-design`.
5. **Classify risk.** Identify applicable security, authorization, privacy, accessibility,
   performance, observability, migration, rollout, and rollback concerns. Record observable
   outcomes in requirements; defer implementation choices to design.
   Requirements use no diagram by default. When many externally observable states and legal or
   illegal transitions are materially harder to verify from EARS criteria alone, build a
   `state-machine` IR JSON per [`mermaid/reference/ir.md`](../mermaid/reference/ir.md) whose
   states and transitions are derived exactly from the numbered EARS criteria (one state per
   distinct externally observable lifecycle state named or implied by a trigger/behavior, one
   transition per WHEN/IF-triggered move between them), run
   `mermaid/scripts/render.py <ir-file> --target stateDiagram-v2`, and render-validate the
   generated source through the `mermaid` skill exactly as a hand-authored diagram would be. In
   formal or compliance-heavy work, build a `requirement-links` IR JSON instead — one
   `requirement` element per numbered criterion (its `text` the criterion's behavior, `id` the
   criterion's `R<n>.<m>`), `element`s for the verifying component(s), and `satisfies`/`verifies`
   links between them — render it with `--target requirementDiagram`, and render-validate the same
   way. Do not hand-author either diagram as a fenced ```mermaid block: the diagram is a generated
   view of the same criteria the JSON already captures, never a second hand-typed representation
   that could drift from them. The numbered EARS criteria remain authoritative; omit either view
   when it would duplicate a short list or introduce design detail.
6. **Write and initialize state** in the project-local `.specs/<feature-slug>/` directory:
   `02_requirements.md`, `02_requirements.json`, and `00_state.md` (create `.specs/` and the
   feature folder if absent). Write `02_requirements.md` for a human reviewer: introduce the
   feature plainly, define domain terms, separate assumptions from requirements, and keep approval
   status and open questions visible. Apply the shared artifact content rule: include useful
   domain and approval information, not research, tool, generation, validation, or agent-process
   narration. Regenerate `02_requirements.json` deterministically from the just-written Markdown in
   this same step, every time `02_requirements.md` is written or revised — it is a generated
   sidecar, never hand-maintained, the same "whenever the Markdown updates, the JSON updates too"
   rule this family applies to `04_tasks.json`/`05_execution.json`. See
   [`02_requirements.json` schema](#02_requirementsjson-schema) below for the exact fields and
   parsing logic. A material requirements revision invalidates downstream approvals in
   `00_state.md`. Run `scripts/spec-nav.py <spec-dir> --write` after both Markdown files are
   present so each links to the other. If contextual notes name an existing project file,
   hyperlink its project-relative path.
7. **Self-review:** each criterion is one observable behavior; no solution detail; no "TBD";
   numbering is contiguous so design/tasks can cite it; a human can understand the document
   without reading the originating conversation.
8. **Gate — get approval.** Run `spec-check.py <spec-dir>`, update `00_state.md`, and ask:
   > "Requirements written to `.specs/<slug>/02_requirements.md`. Review and approve, or tell me what to change, before we design."
   Revise in place until approved. **Do not proceed to design until approved.**

## Rules

- Testable or it doesn't ship: avoid "handle", "support", "manage", "robust", "fast" — state
  the observable behavior (and a number/threshold where relevant).
- One behavior per criterion; split on "and".
- Name the actor once components are known (`THE Parser SHALL …`), else a clear stand-in.
- Keep requirements implementation-agnostic; if you're naming files or functions, that's design.
- A requirements diagram may summarize observable behavior or formal traceability, but it may not
   add behavior, implementation structure, or identifiers absent from the numbered EARS criteria.

## `02_requirements.json` schema

[`references/artifacts.md`](../spec-driven/references/artifacts.md) now documents this schema
canonically (added after this section was first written) — the fields below match it exactly;
follow artifacts.md if the two ever diverge in the future.

`02_requirements.json` sits beside `02_requirements.md` in `.specs/<feature-slug>/`. It is parsed,
never authored, from the same numbered EARS criteria the Markdown already contains — reuse
`spec-driven/scripts/spec-check.py`'s existing `cited` and `requirements_contract_errors` parsing
(the `criterion_pattern` that matches `**R<n>.<m>**` lines, and the five EARS sentence forms)
rather than inventing new patterns. This is instructional pseudocode for the extraction, not a
callable script — `spec-check.py` is owned by a different phase's tooling and is not extended here.

**Fields** (matching `04_tasks.json`/`05_execution.json`'s generated-artifact envelope):

```jsonc
{
  "schema_version": 1,
  "generated_from": { "file": "02_requirements.md", "sha256": "<hex>" },
  "requirements": [
    {
      "id": "1",                     // from "### Requirement 1: <name>"
      "user_story": {                // from "**User Story:** As a <role>, I want <capability>, so that <benefit>."
        "role": "maintainer",
        "capability": "duplicate issues flagged",
        "benefit": "I avoid triaging the same report twice"
      },
      "criteria": [
        {
          "id": "1.1",               // canonical "**R<n>.<m>**" id with the "R" stripped, matching
                                      // how design/tasks already cite it (Validates: Requirements
                                      // 1.1 / _Requirements: 1.1_) with no translation layer needed
          "kind": "event",           // unconditional | event | state | unwanted | optional
                                      // (THE.../WHEN.../WHILE.../IF...THEN.../WHERE... respectively)
          "trigger": "a new issue is created",  // empty for "unconditional" (no trigger clause)
          "actor": "Duplicate_Detector",
          "behavior": "compare it against open issues"
        }
      ]
    }
  ]
}
```

Compute `generated_from.sha256` as the SHA-256 hex digest of the exact `02_requirements.md` text,
the same way `spec-check.py`'s `_sha256_text` does for the other two sidecars — this is what lets
a future checker (or `spec-audit`) detect a stale sidecar without re-parsing the Markdown.

**Extraction logic** (same structural pattern as `spec-check.py`'s `criterion_pattern`/
`ears_pattern`, with named groups added to capture trigger/actor/behavior instead of only
validating the sentence):

```python
import hashlib
import re

REQUIREMENT_HEADING = re.compile(r"(?m)^###\s+Requirement\s+(?P<num>\d+):\s*(?P<name>\S.*)$")
# The User Story sentence commonly wraps across lines (see references/ears.md's own example), so
# capture the whole paragraph up to the next blank line first, collapse its whitespace, then match
# the sentence shape — do not anchor "so that ..." to a single physical line.
USER_STORY_LABEL = re.compile(r"(?im)^\*\*User Story:\*\*\s*(?P<rest>.+?)(?=\n\s*\n|\Z)", re.DOTALL)
USER_STORY_BODY = re.compile(
    r"(?is)^As an?\s+(?P<role>.+?),\s+I want\s+(?P<capability>.+?),"
    r"\s+so that\s+(?P<benefit>.+?)\.?\s*$"
)
# Matches only the marker, not the body — identical to spec-check.py's criterion_header in
# requirements_contract_errors. The EARS sentence itself commonly wraps across several physical
# Markdown lines (exactly like the User Story sentence above), so the body is extracted
# separately as the paragraph following this marker, not assumed to fit on one line.
CRITERION_HEADER = re.compile(r"(?m)^\s*(?:\d+\.\s+)?\*\*R(?P<id>\d+\.\d+)\*\*\s*")
# One pattern per EARS kind, same anchors/order as spec-check.py's ears_pattern alternation,
# each with named groups added for trigger/actor/behavior. Names match artifacts.md's canonical
# 02_requirements.json schema exactly (not spec-check.py's internal error-message wording).
KIND_PATTERNS = [
    ("unconditional", r"^THE\s+(?P<actor>.+?)\s+SHALL\s+(?P<behavior>.+)\.?$"),
    ("event",         r"^WHEN\s+(?P<trigger>.+?),\s+THE\s+(?P<actor>.+?)\s+SHALL\s+(?P<behavior>.+)\.?$"),
    ("state",         r"^WHILE\s+(?P<trigger>.+?),\s+(?:WHEN\s+.+?,\s+)?"
                      r"THE\s+(?P<actor>.+?)\s+SHALL\s+(?P<behavior>.+)\.?$"),
    ("unwanted",      r"^IF\s+(?P<trigger>.+?),\s+THEN\s+THE\s+(?P<actor>.+?)\s+SHALL\s+(?P<behavior>.+)\.?$"),
    ("optional",      r"^WHERE\s+(?P<trigger>.+?),\s+THE\s+(?P<actor>.+?)\s+SHALL\s+(?P<behavior>.+)\.?$"),
]

def extract_user_story(section: str) -> dict | None:
    label = USER_STORY_LABEL.search(section)
    if not label:
        return None
    paragraph = re.sub(r"\s+", " ", label["rest"]).strip()
    body = USER_STORY_BODY.fullmatch(paragraph)
    if not body:
        return None
    return {"role": body["role"], "capability": body["capability"], "benefit": body["benefit"]}


def build_requirements_json(markdown_text: str) -> dict:
    requirements = []
    headings = list(REQUIREMENT_HEADING.finditer(markdown_text))
    for index, heading in enumerate(headings):
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown_text)
        section = markdown_text[heading.end():section_end]

        user_story = extract_user_story(section)

        criteria = []
        headers = list(CRITERION_HEADER.finditer(section))
        for index, match in enumerate(headers):
            body_end = headers[index + 1].start() if index + 1 < len(headers) else len(section)
            raw_body = section[match.end():body_end]
            boundary = re.search(r"\n[ \t]*\n|\n[ \t]*#{1,6}\s", raw_body)
            if boundary:
                raw_body = raw_body[:boundary.start()]
            body = re.sub(r"\s+", " ", raw_body).strip()
            for kind, pattern in KIND_PATTERNS:
                found = re.fullmatch(pattern, body)
                if found:
                    groups = found.groupdict()
                    criteria.append({
                        "id": match["id"],          # already "1.1" with no "R" — matches how
                                                     # design/tasks cite it, no translation layer
                        "kind": kind,
                        "trigger": groups.get("trigger") or "",  # "" for "unconditional"
                        "actor": groups["actor"],
                        "behavior": groups["behavior"].rstrip("."),
                    })
                    break
            # An unmatched body means requirements_contract_errors already flagged it —
            # skip it here rather than guessing a kind; fix the Markdown criterion first.

        requirements.append({
            "id": heading["num"],
            "user_story": user_story,
            "criteria": criteria,
        })

    return {
        "schema_version": 1,
        "generated_from": {
            "file": "02_requirements.md",
            "sha256": hashlib.sha256(markdown_text.encode("utf-8")).hexdigest(),
        },
        "requirements": requirements,
    }
```

Run `spec-check.py <spec-dir>` (which calls `requirements_contract_errors`) before generating the
JSON — every criterion must already be a valid canonical EARS sentence, so the extraction never
needs to guess a malformed one. Regenerate the whole file rather than patching it in place;
treating it as an append-only or hand-edited log reintroduces the drift this sidecar exists to
prevent.

## Next

On approval → **`spec-design`**. Do not reopen approach selection silently; a materially different
approach returns to `spec-discovery` and invalidates downstream approvals.

## Red flags — STOP

- "WHEN a user uploads a file, THE system SHALL handle it" → "handle" isn't observable; say what happens.
- Writing design decisions (tech choices, file layout) into requirements → move them to `03_design.md`.
- Skipping the approval gate → requirements must be approved before design.
