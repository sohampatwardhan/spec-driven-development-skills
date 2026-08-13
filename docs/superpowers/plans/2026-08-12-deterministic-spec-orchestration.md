# Deterministic Spec Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`[ ]`) syntax for tracking.

**Goal:** Make spec-driven planning and execution deterministic, low-token, autonomous across safe concurrent waves, and concise for human readers.

**Architecture:** Keep `04_tasks.json` as immutable task-plan facts and make `05_execution.json` the authoritative event ledger plus generated task-status projection. Extend the existing sidecar validator, Orca bridge, and Mermaid renderer to consume those shared facts; generated Markdown is a compact projection with an input-digest manifest.

**Tech Stack:** Python standard library, JSON Schema subset validation, Mermaid/ELK, Orca CLI,
PyYAML (existing model-router dependency), pytest (development-only test dependency).

## Global Constraints

- No new runtime dependency.
- Run tests through the project-local `.venv`; `pytest` is development-only, while `PyYAML` is
  required by the existing model-router. Neither may be introduced as a hidden dependency.
- A provider safety block is never bypassed by prompt rewriting or unapproved routing.
- Next-wave dispatch requires a verified integration checkpoint and clean scoped commit.
- Generated visual status must include text/icon and color.
- Preserve legacy sidecars unless explicitly migrated.

---

### Task 1: Execution schema and deterministic status projection

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `spec-driven/contracts/schemas/04_tasks.schema.json`
- Modify: `spec-driven/contracts/schemas/05_execution.schema.json`
- Modify: `spec-driven/scripts/spec-check.py`
- Test: `spec-driven/tests/test_sidecars.py`

**Interfaces:**
- Consumes: `04_tasks.json.tasks`, `05_execution.json.task_attempts`, execution gates.
- Produces: `05_execution.json.task_status[]` and validated `concurrency.waves[]`.

- [x] **Step 1: Add failing schema and projection tests** for pending, running, failed, done, and blocked task IDs plus invalid status transitions.
- [x] **Step 2: Extend the schemas** with `task_status`, `checkpoint_commits`, task ownership/components, wave dispatch profile, and provider constraints.
- [x] **Step 3: Implement pure projection functions** in `spec-check.py` that derive current status and waves from parsed payloads without reparsing files.
- [x] **Step 4: Validate ownership collisions, blocked dependencies, and an attempted next wave without a verified checkpoint.**
- [x] **Step 5: Run** `python3 -m pytest spec-driven/tests/test_sidecars.py spec-driven/tests/test_spec_check.py`.
- [ ] **Step 6: Commit** schema and validator changes.

### Task 2: Provider-aware Orca scheduling and autonomous checkpoints

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `spec-driven/contracts/agent_profiles.json`
- Modify: `spec-driven/contracts/schemas/agent_profiles.schema.json`
- Modify: `spec-driven/scripts/spec-orca.py`
- Test: `spec-driven/tests/test_spec_orca.py`

**Interfaces:**
- Consumes: computed ready wave, agent profile, provider constraints, task ownership.
- Produces: bounded worker prompts, dispatch plans, provider-policy outcomes, and checkpoint receipts.

- [ ] **Step 1: Add failing tests** for provider-incompatible dispatch, prompt manifest bounds, scoped ownership, stable task-ID integration order, and a failed checkpoint blocking the next wave.
- [ ] **Step 2: Add profile fields** for sandbox/permission settings, supported safety classifications, real-time safeguard behavior, and verified defensive-use state.
- [ ] **Step 3: Replace broad prompt assembly** with a deterministic task manifest containing only declared files, interfaces, dependencies, verification, and required citations.
- [ ] **Step 4: Add dispatch filtering** that treats provider policy blocks as non-retryable, preserves evidence, and only chooses another profile under the same authorized classification.
- [ ] **Step 5: Add checkpoint commands** that verify scoped changed paths, integrate in task-ID order, record commit/evidence, and prevent next-wave dispatch otherwise.
- [ ] **Step 6: Run** `python3 -m pytest spec-driven/tests/test_spec_orca.py spec-driven/tests/test_model_routing.py`.
- [ ] **Step 7: Commit** scheduling and checkpoint changes.

### Task 3: Compact, digest-driven generated task views

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `spec-driven/scripts/render-gantt.py`
- Modify: `spec-driven/contracts/schemas/05_execution.schema.json`
- Test: `spec-driven/tests/test_render_gantt.py`

**Interfaces:**
- Consumes: `04_tasks.json` plus `05_execution.json.task_status` and attempt data.
- Produces: a single generated Task Views region in `04_tasks.md` and one Gantt in `05_execution.md`.

- [ ] **Step 1: Write failing renderer tests** for two collapsibles in task views, input-digest manifest, one Gantt only, idempotent replacement, and status agreement across views.
- [ ] **Step 2: Generate the ELK dependency flowchart and Kanban from the same task/status payload.**
- [ ] **Step 3: Move Kanban injection from `05_execution.md` to `04_tasks.md` under Task Views; keep the Gantt as the only execution diagram.**
- [ ] **Step 4: Add canonical digest comparison and debounce-aware no-op behavior so unchanged inputs do not rewrite Markdown.**
- [ ] **Step 5: Run** `python3 -m pytest spec-driven/tests/test_render_gantt.py`.
- [ ] **Step 6: Commit** renderer changes.

### Task 4: JSON-first validation, binding manifests, and compact readiness

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `spec-driven/scripts/spec-check.py`
- Modify: `spec-driven/scripts/spec-nav.py`
- Modify: `spec-driven/contracts/spec-family.yaml`
- Test: `spec-driven/tests/test_sidecars.py`, `spec-driven/tests/test_nav_linkify.py`

**Interfaces:**
- Consumes: parsed sidecars and generated-region manifest.
- Produces: one-pass validation, compact ready result, and region freshness errors.

- [ ] **Step 1: Add failing tests** for manifest freshness, legacy passthrough, compact readiness output, and single-parse validation reuse.
- [ ] **Step 2: Replace circular binding behavior** with canonical source digest manifests for generated regions.
- [ ] **Step 3: Add `--validate-json` and compact `--ready` output that share parsed payloads with traceability and scheduling checks.**
- [ ] **Step 4: Update the family contract** with schema validation, task-view manifest, and status-projection declarations.
- [ ] **Step 5: Run** `python3 -m pytest spec-driven/tests/test_sidecars.py spec-driven/tests/test_nav_linkify.py`.
- [ ] **Step 6: Commit** validator and contract changes.

### Task 5: Skill guidance, templates, and invocation/update policy

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `spec-driven/references/artifacts.md`
- Modify: `spec-driven/references/orca-orchestration.md`
- Modify: `spec-driven/references/agent-cli-flags.md`
- Modify: `spec-driven/SKILL.md`, `spec-tasks/SKILL.md`, `spec-execute/SKILL.md`
- Modify: `spec-discovery/SKILL.md`, `spec-requirements/SKILL.md`, `spec-design/SKILL.md`, `spec-audit/SKILL.md`, `spec-finish/SKILL.md`

**Interfaces:**
- Consumes: new validator, scheduler, renderer, agent profiles.
- Produces: consistent JSON-first workflows, autonomous checkpoint behavior, and concise human artifacts.

- [ ] **Step 1: Replace Markdown-first instructions** with sidecar → validate → render → bind instructions, stating authored versus computed fields.
- [ ] **Step 2: Update templates** to use Task Views collapsibles and one execution Gantt; remove delivery-schedule Gantt and duplicate status prose.
- [ ] **Step 3: Document wave autonomy** and exception-only human gates, scoped commits, provider safety constraints, and the full/lightweight/direct invocation rubric.
- [ ] **Step 4: Add publication manifest and invocation-time safe-update guidance**: verify digest, lock, atomic replacement, fallback to installed version, preserve local changes.
- [ ] **Step 5: Run targeted documentation consistency checks** with `rg` for obsolete Markdown-first, duplicate Gantt, and manual per-task render instructions.
- [ ] **Step 6: Commit** skill and reference changes.

### Task 6: Migrate the Orca spec and complete acceptance verification

- [ ] **Task status:** Complete and reviewed

**Files:**
- Modify: `.specs/orca-agent-orchestration/04_tasks.md`
- Modify: `.specs/orca-agent-orchestration/05_execution.md`
- Modify: `.specs/orca-agent-orchestration/sidecars/04_tasks.json`
- Modify: `.specs/orca-agent-orchestration/sidecars/05_execution.json`
- Test: `spec-driven/tests/`

- [ ] **Step 1: Regenerate task and execution sidecars** with the new canonical task-status and generated-view format.
- [ ] **Step 2: Generate the Task Views region and the single execution Gantt; verify no duplicate generated diagrams remain.**
- [ ] **Step 3: Run** `python3 spec-driven/scripts/spec-check.py .specs/orca-agent-orchestration --validate-json` and `--check-only`.
- [ ] **Step 4: Run** `python3 -m pytest spec-driven/tests/`.
- [ ] **Step 5: Verify acceptance:** every visual matches its source, status/waves agree, and an unverified checkpoint cannot advance execution.
- [ ] **Step 6: Commit** migration and verification evidence.
