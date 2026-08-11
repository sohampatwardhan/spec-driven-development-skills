---
name: spec-execute
description: Use when implementing an approved 04_tasks.md in spec-driven development — run a risk-scaled preflight, execute required tasks by dependency stage, verify requirements, honor checkpoints, and preserve resumable evidence. Triggers on "implement the tasks", "execute the spec", "start building", or after 04_tasks.md is approved.
---

# Spec Execute (Phase 5)

Implement `04_tasks.md` task-by-task with a self-contained TDD loop, verifying each task
against the requirement criteria it cites and checking it off. Use the governing `spec-*`
phase conventions, `code-documenting`, and `context7-mcp` when technology evidence is relevant.

> [!WARNING]
> Execute every required dependency stage in order unless the user explicitly scopes a subset.
> Within the active stage, run tasks concurrently only through the guarded parallel-wave process.
> Persist each verified checkmark immediately. Run continuously through every ready task up to
> the next `Checkpoint` group — invoking this skill on an approved task list is itself sufficient
> authorization to proceed between checkpoints. Do not pause for interim confirmation, an
> incremental sign-off, or a "does this look right so far?" check; that belongs to discipline-heavy
> review workflows this family doesn't depend on. `Checkpoint` groups and the delegated-approval
> exceptions below remain the real stops.

**Core principle:** Complete the full approved task list by default, stage by stage, with one
task contract per implementer. Use parallel waves only for ready tasks proven safe to isolate;
otherwise execute sequentially. Test and review every task against its `_Requirements:_` before
checking it off. A task is done only when its cited criteria are demonstrably met — not when the
code "looks right". Treat explicit user authorization to execute all tasks as approval to
continue through checkpoints. Before implementation, reuse a current passing audit or run a
risk-scaled self-hardening preflight, then autonomously approve safe, behavior-preserving
improvements so execution does not pause for routine planning repairs.
Record exact execution and task-attempt start/stop times as durable evidence, and maintain a
validated Mermaid Gantt derived from those records.

## Related Skills

[`spec-driven`](../spec-driven/SKILL.md) · [`spec-tasks`](../spec-tasks/SKILL.md) ·
[`spec-debugging`](../spec-debugging/SKILL.md) ·
[`spec-verification`](../spec-verification/SKILL.md) · [`spec-finish`](../spec-finish/SKILL.md) ·
[`plan-harden`](../plan-harden/SKILL.md) · [`code-documenting`](../code-documenting/SKILL.md) ·
[`mermaid`](../mermaid/SKILL.md) · [`context7-mcp`](../context7-mcp/SKILL.md) ·
[`dependency-security-audit`](../dependency-security-audit/SKILL.md) ·
[`codebase-memory-reference`](../codebase-memory-reference/SKILL.md)

**REQUIRED first:** work from the project-local `.specs/<feature-slug>/`; read `00_state.md`,
`04_tasks.md`, and `05_execution.md` (create the ledger from the active `spec-driven` template if
absent). Require Discovery, Requirements, Design, and Tasks to be approved. Load only the cited
EARS criteria and directly relevant design sections for the active task. Read the discovery
boundary or steering sections only when preflight, ambiguity, or a cross-cutting risk requires
them; do not preload every artifact into execution context. Immediately
open an execution-run timing record as defined below, then run the Autonomous self-hardening
preflight. Run
`scripts/spec-nav.py <spec-dir> --write`, and run
`scripts/spec-check.py <spec-dir> --ready --format json`; do not execute if it fails — this
includes a stale `04_tasks.json`/`05_execution.json` sidecar (regenerate with `--emit-json` and
rerun `--ready` rather than treating it as a routine warning). Use the
returned `execution.active_stage`, `ready`, `parallel_candidates`, and `blocked` fields to schedule
work, or read the equivalent `concurrency` object persisted in `04_tasks.json` (its `waves` field
is not in the ephemeral `--format json` output). An audit is optional:
run `--require-audit` only when the user or project policy requires an audit. Follow dependency
stage order and the guarded parallel-wave rules below.

Before implementation, capture the repository's relevant full test/build baseline and record the
commands, revision, exit status, and any pre-existing failures. Create a dedicated feature branch
and isolated worktree from the confirmed base by default, including sequential/controller work.
Proceed in the current checkout only when isolation is unavailable or the user explicitly opts out;
record the reason, branch, base commit, and dirty state. If that checkout is `main` or `master`,
do not make implementation edits without the user's explicit consent to work on that protected
branch; isolation being unavailable is not consent. Never mix task edits into unrelated user
changes, and never create an isolated worktree from an uncommitted approximation of the base.

## Autonomous self-hardening preflight

Before the first implementation edit, compute a deterministic SHA-256 digest over
`01_discovery.md` through `04_tasks.md`. If `00_state.md` records a passing `spec-audit` for that
exact digest, reuse it and do not launch `plan-harden`. Otherwise classify a depth
(`quick`/`medium`/`thorough`) against
[delegation.md](../spec-driven/references/delegation.md)'s criteria and resolve its fan-out with
`scripts/fanout.py --depth <depth>` from the `spec-driven` skill directory — never hard-code a
reviewer count or tier here.

Invoke `plan-harden` once with the resolved reviewer count and tier. Record the depth, resolved
fan-out, and artifact digest in `05_execution.md`. Repeat hardening only when implementation
evidence materially invalidates the plan; do not ask its post-review feedback questions during
execution.

Treat the user's request to execute an approved spec as delegated authority to apply and approve
hardening updates that stay within the already approved requirements and product behavior:

1. Merge and deduplicate findings. Apply every high-confidence CERTAIN P0/P1 fix to
   `04_tasks.md` and, when needed for internal consistency, `03_design.md`. P2 fixes may be applied
   when low-risk and clearly useful; do not expand scope merely because an improvement is possible.
2. Convert UNCERTAIN findings into bounded verification steps, task acceptance evidence, or
   checkpoint checks. Never turn an uncertain assumption into approved behavior.
3. Preserve every approved EARS criterion, user-visible behavior, security boundary, public
   contract, budget, and explicit non-goal. Requirements may receive link, identifier, or formatting
   repairs only; do not substantively rewrite `02_requirements.md` under delegated authority.
4. After edits, independently review the targeted artifact diff against all cited requirements,
   regenerate navigation, and run `spec-check.py <spec-dir> --ready --format json`. Repair
   deterministic artifact errors and rerun the check. One targeted hardening re-review is enough;
   do not create an unbounded review loop.
5. If the review and checker pass, retain or restore the affected gates as `approved` in
   `00_state.md` and record that the update was self-hardened and approved by `spec-execute` under
   delegated authority. Once `05_execution.md` is available, summarize the changes and evidence
   there before the first implementation edit; continue without asking the user to approve routine
   plan repairs.

Delegated approval does **not** cover a new or changed requirement, changed user-visible behavior,
scope expansion, weakened test/security/performance constraints, destructive or irreversible
operations, credential or production access, unresolved reviewer disagreement, or a choice among
multiple materially different product/architecture options. For those cases, preserve the proposed
diff separately when useful, leave the affected gate unapproved, and ask one concise blocking
question containing the recommendation and tradeoff. This is the exception path, not the default.

## Autonomous task-list repair

The delegated authority above is not a one-time preflight grant; it applies for the life of the
run whenever a task's own contract — not its requirement or design — turns out wrong once you
start implementing it: the wrong file scope, a missing or incorrect `Depends on`, an
unimplementable `Interfaces` contract, or a task that's the wrong size. Repair `04_tasks.md` in
place (and `03_design.md` only for a purely internal-consistency correction), independently
review the diff at the fan-out resolved for the task's depth, regenerate `04_tasks.json` with
`--emit-json` in the same step, rerun `spec-check.py`, retain or restore the affected gates as
`approved`, record the repair in `05_execution.md`, and continue — do not stop to ask permission
for a routine contract repair.

A defect gets at most the fan-out's `self_repair_rounds` in place (see
[delegation.md](../spec-driven/references/delegation.md)). Exhausting that budget is not a request
for the user's permission to keep trying — it is the trigger to reclassify the defect once more: a
mechanical contract defect (wrong scope, wrong dependency, wrong size) gets one further rewrite
under the same delegated authority and continues; a defect that conflicts with an approved
requirement or design decision, or would cross the delegated-approval boundary above, is the one
case that actually stops — return to the owning `spec-*` phase for re-approval.

## Failure discipline

Any unexpected build, test, integration, review, or runtime failure invokes `spec-debugging`
before a corrective edit. Preserve the failing evidence and keep the task unchecked. Do not stack
speculative fixes, weaken assertions, or redefine expected behavior to obtain green output.
After the root-cause fix, invoke `spec-verification` against the task contract and affected
regression suite. Pre-existing baseline failures remain explicit and cannot be claimed as fixed or
ignored merely because they preceded execution.

**Current technology rule:** Before implementing or reviewing a task whose
correctness depends on an evolving library, framework, SDK, API, CLI, or cloud
service, read the design's Current Technology Evidence. Use `context7-mcp` to
re-resolve and query current official documentation when the installed version,
requested capability, or configuration question is not already covered. Record
the source and result in the task report before marking the task complete.

**Dependency security rule:** Stop when either canonical resolution/delivery field is absent. When
either is not `none`, load and enforce
[dependency-evidence.md](../spec-driven/references/dependency-evidence.md). Do not mark a task done
or cross a delivery gate unless its canonical evidence records satisfy that policy. These focused
checks do not replace broad security/authorization review.

**Graph-assisted implementation rule:** For brownfield tasks, when `codebase-memory-mcp` has a
current index, invoke `codebase-memory-reference` and use `search_graph`, `trace_path`, and
targeted snippets to confirm the task's symbols, callers, dependencies, data flow, and likely
blast radius before editing. After implementation, use change-impact analysis when the installed
server exposes it. Graph evidence supplements the diff, tests, and requirement verification; it
never makes a task complete by itself. Fall back to direct repository discovery when needed.

## Execution state and recovery

`04_tasks.md` is the user-facing checklist; `05_execution.md` is the durable evidence ledger.
Write both for a human resuming the project: summarize outcomes and evidence, explain blockers and
decisions, link to detailed task artifacts when useful, and do not paste raw command/tool output.
Record material verification outcomes, commits/diffs, approvals, failures, and recovery decisions;
omit tool-call narration, agent choreography, generation/validation commentary, timestamps other
than the required execution timing records below, and process metadata that does not help a human
evaluate or resume the implementation.
Hyperlink every referenced project path once it exists, including paths that were inline code in
`04_tasks.md` when originally planned. Refresh navigation after creating a numbered artifact.
Whenever `04_tasks.md` or `05_execution.md` changes, regenerate its `04_tasks.json`/
`05_execution.json` sidecar in the same step with `scripts/spec-check.py <spec-dir> --emit-json`
from the `spec-driven` skill directory — never hand-maintain either; see Checklist discipline
below for the checkbox case and Execution timing and Gantt below for the timing-ledger case.
Before editing, record the current branch/worktree, dirty-tree state, and base commit. Create
`execution/` and retain task-local `task-<id>-brief.md`, `task-<id>-report.md`, and
`task-<id>-review.md` evidence when delegation is used. After each verified task, update the
ledger with stage/wave membership, worktree/branch, verification, reviewer, integration commit/diff,
and checkpoint status before choosing another.

### Execution timing and Gantt (required)

Use the operating system clock, never a model-estimated time. Capture UTC in
`YYYY-MM-DDTHH:mm:ssZ` format (for example, `date -u +"%Y-%m-%dT%H:%M:%SZ"`). Keep two structured
Markdown tables under `## Execution Timing` in `05_execution.md`; preserve their exact headings so
future automation can parse them:

```markdown
### Run Intervals
| Run ID | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|

### Task Attempt Intervals
| Run ID | Stage/Wave | Task | Attempt | Started UTC | Stopped UTC | Elapsed Seconds | Outcome |
|---|---|---|---:|---|---|---:|---|
```

Timing rules:

0. Maintain exactly one `### Run Intervals` table and one `### Task Attempt Intervals` table.
   Append or update rows inside those canonical tables; never create replacement copies elsewhere
   in the ledger. Maintain at most one `### Execution Gantt` section, and regenerate it by replacing
   that section in place rather than appending another chart.

1. After identifying the spec directory and creating/reading `05_execution.md`, append a unique
   `run-YYYYMMDDTHHMMSSZ` row (add `-NN` if that ID already exists) with the observed start time,
   `Stopped UTC` and `Elapsed Seconds` set to `pending`, and outcome `active`. This includes
   self-hardening and preflight time.
2. Immediately before work begins on each leaf task attempt, append its row with the observed start
   time and `pending` stop/elapsed fields. Attempts are 1-based per task and must not overwrite
   earlier failed, blocked, or interrupted attempts. In parallel waves, the controller records each
   agent's actual reported start/stop timestamps rather than dispatch or collection time.
3. Immediately after an attempt verifies, fails, or blocks, observe the stop time and close that
   row with non-negative elapsed whole seconds and outcome `verified`, `failed`, or `blocked`.
4. Before every intentional return from the skill, including completion, checkpoint pause, user
   stop, preflight/check failure, or blocker, observe the stop time and close all controlled open
   rows. Close the run as `complete`, `checkpoint`, `stopped`, `failed`, or `blocked`.
5. Never invent a missing stop time. On resume, if a prior run or attempt is still `active`, close
   it as `interrupted` with `Stopped UTC` and `Elapsed Seconds` set to `unknown`, record the newly
   observed resume time in a new run, and continue reconciliation. Historical closed rows are
   immutable except to correct a demonstrated transcription error.

Append timing rows deterministically after each attempt. Rebuild the `### Execution Gantt` only
at a checkpoint, an intentional return, or run completion, rather than after every task — but
never hand-transcribe it. Run `scripts/spec-check.py <spec-dir> --emit-json` first so
`05_execution.json` is current, then generate the Gantt from its embedded `gantt` IR object
(`mermaid/reference/ir.md`'s `timeline` family) with `mermaid/scripts/render.py --target gantt`,
and render-validate the exact generated source through `check.sh`/
`validate_and_render_mermaid_diagram` exactly as a hand-authored diagram would be. The sidecar
builder already puts closed run rows in an `Execution Runs` section, groups task attempts by
stage/wave, includes outcome and elapsed time in labels, uses at least `1s` only for rendering a
completed zero-second interval while retaining the exact `0` in the ledger, and omits interrupted
unknown-duration rows from the IR rather than fabricating bars for them — list those below the
diagram in prose instead. The ledger is authoritative; the Gantt is a derived, generated view.
Because `05_execution.md` renders Mermaid natively, retain the validated fenced source without
generating a redundant image unless requested.

### Task Board (execution-only, conditional)

`05_execution.md` may also carry a `### Task Board` kanban as the first thing under `##
Execution Timing` — before `### Run Intervals`, `### Task Attempt Intervals`, and `### Execution
Gantt` — as the quick-glance status view ahead of the detailed timing ledger and timeline.
It groups tasks into Pending/In Progress/Failed/Done columns from the same `04_tasks.json`
and `05_execution.json` sidecars the flowchart reads. This is the one named exception to "do not
add a new Kanban" below: it lives only in `05_execution.md`, and it supplements rather than
replaces or duplicates the required `04_tasks.md` dependency flowchart. Both views must derive
task status identically — `scripts/render-gantt.py`'s `derive_task_statuses` is the single source
both builders call — so they can never disagree. Mermaid kanban has no render-validated per-card
`style`/`classDef` mechanism (confirmed by direct render-validation: `style <id> fill:...` is
misparsed as a bogus extra column, and `:::class` is a parse error), so `build_kanban_board_from_tasks_data`
prefixes each card with a colored-circle emoji (⚪🟠🔴🟢) matching the flowchart's
pending/in_progress/failed/done palette instead of a literal fill/stroke color. The `mermaid`
skill has no `kanban` diagram family in its IR yet either, so this board is hand-authored
deterministically instead of routing through `mermaid/scripts/render.py`; still render-validate
the exact generated source before saving it, exactly as any other diagram. Regenerate it at the
same cadence as the Execution
Gantt: `scripts/render-gantt.py <spec-dir> --write` emits both together, and `--flowchart-only`
(used by the per-task-update sync step below) leaves both the Gantt and the Task Board unchanged.

### Task flowchart synchronization (required when present)

Treat the task checklist and execution ledger as authoritative and their JSON sidecars as the
only inputs to the existing `## Stage and Dependency Overview` flowchart. After every task-state,
attempt-state, or checklist update:

1. Update the existing Markdown row/checkmark first; never add a replacement table or duplicate
   progress section.
2. Run `scripts/spec-check.py <spec-dir> --emit-json` immediately so both task and execution
   sidecars are current. Never render from a stale sidecar.
3. Run `scripts/render-gantt.py <spec-dir> --write --flowchart-only`. It must replace the one
   existing flowchart in `04_tasks.md` and leave the checkpoint-only Execution Gantt unchanged.
4. Render-validate the exact generated flowchart with the `mermaid` skill, then confirm there is
   exactly one `## Stage and Dependency Overview` heading and one flowchart block.
5. Run `scripts/spec-check.py <spec-dir> --emit-json` once more after injection so the sidecars'
   source hashes include the generated Markdown change. Do not render again in this cycle; finish
   with `spec-check.py <spec-dir> --ready --format json` and require `ok: true`.

Whenever the checkpoint-only Gantt is regenerated, also confirm `05_execution.md` contains exactly
one Run Intervals table, one Task Attempt Intervals table, one Execution Gantt heading/block, and
— when a Task Board is present — exactly one Task Board heading/block.

Use one stable color convention: orange (`in_progress`) for the latest active attempt, red
(`failed`) when the latest attempt failed, green (`done`) only for checked and verified tasks, and
gray (`pending`) for pending, queued, ready, or blocked-by-dependency tasks. Latest attempt state
wins, so an active retry is orange even when an earlier attempt failed. Refresh the flowchart
before every user-visible status update and before every intentional return.

If work resumes after compaction, interruption, or a failed agent, reconcile `00_state.md`,
`04_tasks.md`, `05_execution.md`, the working tree, and git history before resuming. Never
assume an unchecked task is incomplete or a checked task is verified without evidence. A
material spec change outside the delegated self-hardening boundary invalidates the affected
approval gates; stop until the relevant artifacts are re-approved. Behavior-preserving hardening
updates follow the autonomous approval process above. Re-run an audit only when the user or project
policy requests it.

An audit result becomes stale when its reviewed artifacts materially change. If the user applies
audit fixes and re-approves the affected artifacts, execution may continue without a redundant
audit unless the user or project policy asks for another one.

Keep execution timing separate from planned delivery scheduling. The required Execution Gantt shows
observed work intervals only; any forecast Gantt must be separately labeled and must not substitute
for the task ledger or use invented dates.

Do not add a new block, state, or dependency diagram to report progress by default, and do not add
a second Kanban or a second flowchart. The execution-only Task Board above is the sole named
exception, and it must supplement rather than replace the required `04_tasks.md` flowchart. When a
generated task flowchart already exists, keep that single derived view — and the Task Board, when
present — synchronized as required above. Add any other diagram only for exceptional diagnostic
evidence under `spec-debugging`, and apply the shared diagram policy so it cannot become a
competing progress source.

## Context and execution budgets

Every task dispatch uses a bounded context envelope rather than raw artifacts or conversation
history. Include only: task ID and text, cited EARS criteria, directly relevant design excerpts,
owned paths, declared interfaces, verification command, applicable policy references, and the
current diff/evidence needed by the recipient. Prefer links or paths over copied documents. The
recipient returns the structured report below and no transcript:

```yaml
status: pass | fail | blocked | uncertain
task_id: string
capability_tier: economical | balanced | frontier
resolved_model: string
reasoning_level: low | medium | high | extra_high
changed_files: [string]
criteria:
   - id: string
      result: pass | fail | uncertain
      evidence: [string]
verification:
   commands: [string]
   exits: [integer]
findings: [string]
context_requests: [string]
```

Default budgets are 12 tool steps and 20 minutes per delegated task or review. The controller may
raise them once for a recorded high-risk reason. Compact proactively, not reactively: at 60
minutes of active work, after one completed dependency stage, when the active context window is
materially full (do not wait for a forced or degraded compaction late in the window — a
controlled handoff before that point loses no fidelity, one triggered by running out of room
does), or when the host reports context pressure, close current evidence and start a fresh
resumable run with a compact state handoff. This is cheap here specifically because nothing
load-bearing lives only in conversation: `00_state.md`, `04_tasks.md`/`04_tasks.json`,
`05_execution.md`/`05_execution.json`, and `execution/task-*-{brief,report,review}.md` already
hold every fact a resumed run needs. After any compaction or session resume, re-read those files
fresh rather than trusting a carried-over summary of their contents — the same reason a stale
command output is not verification (see `spec-verification`) applies to a stale recollection of
state. Never keep a background or loop session active without pending work.

## Subagent Execution Mode

When subagents are available and the user asks for delegated execution, schedule dependency
waves. Delegate only tasks whose complexity or isolation benefits justify a separate request;
execute small mechanical tasks in the controller. Classify each wave's depth and resolve its
review fan-out per [delegation.md](../spec-driven/references/delegation.md) — a `quick`/`medium`
wave gets one reviewer for the accumulated wave by default; a `thorough` task (public contract,
migration, dependency resolution, or security/privacy boundary) gets its own dedicated,
higher-fan-out review instead of sharing the wave's.

Before each wave:

1. Run `spec-check.py <spec-dir> --ready --format json` and select only ready tasks in
   `execution.active_stage`.
2. Re-check every `parallel_candidate`: its declared files, generated outputs, verification,
   external state, and interfaces must be disjoint from every concurrent task. A shared lockfile,
   migration/schema chain, snapshot, repo-wide formatter, mutable service, or uncertain overlap
   makes the tasks sequential regardless of their label.
3. Create a dedicated branch and worktree for each parallel task from the same stage base. Give
   each subagent only its worktree path and task-owned files. If isolated worktrees are unavailable
   or unsafe, degrade to sequential execution; never allow parallel implementers to edit one
   shared checkout.
4. Limit the wave to available agent capacity. Keep serial/controller tasks out of the wave.

**Codebase-memory-mcp usage is coordinator-only.** Step 2's disjointness check (and any other
graph-informed task-assignment decision) is the coordinator's call to make, via one set of
`search_graph`/`trace_path`/`get_architecture`/`index_repository` calls against the shared base
before dispatch — never something each dispatched worker re-derives for itself. Each worker's
injected task spec already carries the resolved files/interfaces/dependencies it needs (see the
Orca dispatch bridge below); it does not need its own codebase-graph exploration to get oriented.
Letting every dispatched worker's fresh session independently decide to index the same repo is
what causes a same-path indexing stampede (many concurrent `index_repository` runs racing on one
project, saturating CPU) — this is a real failure mode, not a hypothetical one. `auto_index` in
`codebase-memory-mcp`'s config controls whether a session indexes automatically on first graph-tool
use; with it enabled, this stampede can happen even without anyone explicitly calling
`index_repository`, so treat indexing as something only the coordinator triggers deliberately, not
something dispatched workers are ever prompted to do.

### Orca Multi-Agent Orchestration and Wave Dispatch

When executing with Orca (`orca orchestration`), use [`spec-driven/scripts/spec-orca.py`](../spec-driven/scripts/spec-orca.py) to manage the Run DAG and unattended, supervised launches:

1. **Initialize Orca Run**:
   Run `python3 spec-driven/scripts/spec-orca.py sync .specs/<feature-slug>` to register the task DAG, prerequisite bindings (`--deps`), parent-child hierarchies (`--parent`), and checkpoint decision gates (`gate-create`).
2. **Preview Ready Waves**:
   Run `python3 spec-driven/scripts/spec-orca.py dispatch-ready .specs/<feature-slug> --json`. The generated `04_tasks.json` already contains the model and reasoning decisions produced by `model-router.py`; the bridge preserves them and infers the matching agent unless `--agent` overrides it.
   - Treat each Orca Task's `--spec` as the authoritative worker prompt. The bridge builds it from the task title, files, dependencies, requirement IDs, interfaces, dependency resolution/delivery, delegation, risk, documentation, exact verification, resolved model, and reasoning level, plus a bounded execution/reporting contract.
   - The preview must show `prompt_delivery: orca-task-spec-inject`, the exact `command_argv`, model, and abstract effort. Agent profiles normalize abstract effort to each installed CLI's accepted spelling (for example, `extra_high` becomes Claude/Codex `xhigh` and Agy `high`).
3. **Dispatch Unattended Workers**:
   Add `--apply` only after reviewing the preview. Use `--task <spec-id>` to select tasks, `--agent codex|claude|agy` to override the inferred agent, and `--worktree new-child` only for a verified checkout conflict. The default is a fresh agent terminal in the current worktree.
   - Orca's `worker-start` accepts model and effort but no raw agent flags. The bridge therefore uses the documented custom-argv path: `terminal create`, `terminal wait --for tui-idle`, then `orchestration dispatch --inject`. The final `--inject` delivers the authoritative Task spec as the agent's initial prompt; do not also pass a positional CLI prompt and accidentally execute the task twice.
   - For a required child checkout, the bridge creates the worktree with `--setup run`, starts the custom-argv agent there, and injects the Task. This path cannot enforce a repository's `wait-for-setup` policy; do not use it for such repositories.
   - Canonical current flags live in [`spec-driven/contracts/agent_profiles.json`](../spec-driven/contracts/agent_profiles.json): Claude `--permission-mode bypassPermissions`, Codex `--ask-for-approval never --sandbox workspace-write` (non-destructive edits run immediately; network/out-of-worktree writes fail closed instead of prompting — never dispatch a worker that can hang on an interactive prompt), and Antigravity's `--dangerously-skip-permissions`. Read-only reviewer/explorer role overrides stay sandboxed (`--permission-mode plan`, `--sandbox read-only`, or equivalent). Treat this file as the single source of truth for flags — do not hand-type a vendor flag from memory in a dispatch; if a flag looks wrong or a CLI rejects it, re-verify the vendor's current syntax (Context7's `/anthropics/claude-code`, `/openai/codex`, or the Antigravity CLI library) before editing the profile, since these flags drift across CLI releases.
4. **Supervised PTY Event Loop**:
   - For TUI agents, wait for idle: `orca terminal wait --terminal <handle> --for tui-idle --timeout-ms 10000`.
   - Listen for worker events: `orca orchestration check --wait --types worker_done,escalation,question --timeout-ms 30000`.
   - When receiving `worker_done`, verify the structured return payload and test changed files against cited requirements. Then close out the worker completely, not just its output: release the terminal via `orca orchestration worker-release --dispatch <dispatch-id>` to end the agent's session, and — once its changes are integrated (merged/cherry-picked into the stage's base branch, or the task is otherwise confirmed no longer needed) — remove any worktree that was created for it via `orca worktree rm --worktree <selector> --force --json`. `worker-release` only ends the session; it does not delete the worktree, so a wave with per-task child worktrees (`--worktree new-child`) leaves them behind unless this step runs. Do not delete a worktree before its changes are integrated. Refresh the execution ledger and Gantt chart via `python3 spec-driven/scripts/render-gantt.py .specs/<feature-slug> --write`.
   - **Nested dispatch**: as a convention enforced by this skill, a worker that itself becomes a coordinator for sub-workers owns this same lifecycle for its own children — end each child's session and remove each child's worktree once integrated, before that worker reports its own `worker_done` upward. Orca stores `--parent` as flat metadata only; it does not track nested coordinators, cascade cleanup, or detect a skipped level. A top-level coordinator cannot recover worktrees a nested worker never reported.
   - **Ambiguous workspace identity**: if Orca reports "Workspace identity is ambiguous across hosts," this is Orca failing to resolve the current workspace to a single project/host-setup record — usually a stale or self-referential paired environment (`orca environment list --json`) whose runtime ID matches a host already resolvable another way. Refreshing projects re-triggers resolution; if it recurs, remove the offending environment (`orca environment rm --environment <selector>`) rather than retrying the same dispatch, since retrying will hit the same ambiguity.

### Capability mapping and reasoning level

Every dispatch gets **two independent values**, resolved together in one call: a **capability
tier** (which model) and a **reasoning level** (how much deliberation that model spends on this
one task). They are not the same axis — a `balanced`-tier implementer at `high` reasoning is a
different, and sometimes better, choice than a `frontier`-tier implementer at `low` reasoning.
Assign both to every subagent; never dispatch with only one resolved.

Let the runtime adapter resolve the tier to an available model. Record the resolved model and the
reasoning level together in the task report; availability and capability matter more than
vendor-specific names. Use the least expensive tier and lowest sufficient reasoning level for the
contract — escalate either independently when the work actually needs it, not by default. For a
task that already has an entry in `04_tasks.json` (regenerated fresh — see Checklist discipline
below), read its `capability_tier`/`resolved_model`/`reasoning_level` directly from that entry;
`spec-tasks` already resolved them deterministically from the task's declared `Task category` and
`Risk` fields, so re-deriving them here would be redundant, not more correct. For a dispatch with
no single owning task ID — a wave-level or escalated reviewer, an ad hoc self-hardening reviewer —
resolve both per
[references/model-routing.md](../spec-driven/references/model-routing.md) directly: classify the
work as one `task_category` (`quick_lookup`, `code_analysis`, `heavy_reasoning`, or `review`), run
`scripts/model-router.py --category <task_category> [--risk <declared_risk>]` from the `spec-driven`
skill directory, and use its `resolved_model` and `reasoning_level` together. Never hard-code a
model name or a reasoning level in a task brief.

| Capability tier | Use for |
|---|---|
| `frontier` | Architecture, high-risk integration, or escalated fixes. |
| `balanced` | Normal multi-file implementation and wave review. |
| `economical` | Small mechanical implementation, evidence extraction, or re-review. |

| Reasoning level | Use for |
|---|---|
| `extra_high` | System-wide, irreversible, security-sensitive, or expensive-to-get-wrong work. |
| `high` | Ambiguous, non-obviously-caused, or meaningfully risky work. |
| `medium` | Ordinary multi-step implementation or debugging. |
| `low` | Explicit, local, easily verified work. |

If the requested tier is unavailable, use the next stronger available tier and record the
substitution. Never invent a model ID, never invent a reasoning level, and never silently omit
either from a report. An explicit user- or project-policy-named model or reasoning level always
overrides the computed default; pass them as `--override`/`--reasoning-override` and record the
override reason in the task report.

### Per-wave subagent loop

1. The controller selects the ready batch from the active stage and records each task's cited
   requirements, contract, worktree, expected files, verification command or observable check,
   artifact paths, and timing-report contract in `execution/task-<id>-brief.md`.
2. Dispatch one implementer only for each delegated batch task with the bounded context envelope,
   isolated worktree, constraints, and its resolved capability tier and reasoning level. Require each to
   complete RED → GREEN → REFACTOR → DOCUMENT → VERIFY, report changed files, evidence,
   recovery-relevant blockers, and actual UTC start/stop timestamps, and stop without changing task
   status. Save its report under `execution/`.
3. As implementers finish, inspect each structured report and confirm its verification. Resolve
   the wave's depth and fan-out with `scripts/fanout.py --depth <depth>` and dispatch that many
   independent reviewers for the accumulated wave using task envelopes, isolated diffs, and
   verification evidence; split out a dedicated, separately fan-out-resolved review only for a
   `thorough` task. Require two verdicts from each reviewer: requirement compliance and task
   quality. Save each review under `execution/`.
4. Queue reviewed branches for serial integration in task-list order; do not wait for unrelated
   agents when the next branch in that order is ready. After each integration, re-run that task's
   verification against the accumulated branch, verify the cited EARS criteria, mark only that
   leaf `[x]`, perform parent roll-up when eligible, and persist `04_tasks.md` plus
   `05_execution.md`, close its timing row, run `--emit-json` so `04_tasks.json`'s
   `checked`/`concurrency` fields are current, and refresh both the validated Execution Gantt and
   — when `04_tasks.md` has one — the Stage and Dependency Overview flowchart (regenerated from
   the fresh sidecar so its node `status` colors match reality) before
   integrating the next task. Do not open the next stage until every required task in the active
   stage is integrated and checked.
5. If review finds a defect, apply one bounded fix round with the same implementer, then one
   fresh implementer at the next higher capability tier if it remains. Do not exceed the wave's
   resolved `self_repair_rounds` in place — see Autonomous task-list repair above for what happens
   when the budget is exhausted; that is a reclassification, not a pause for user authorization.
6. If a finding conflicts with an approved requirement/design/task, or the repair budget leaves a
   load-bearing issue unresolved, stop and return to the relevant `spec-*` approval gate. Do not
   work around it.
7. A blocked or failed task prevents every dependent and prevents the next stage from opening;
   unrelated tasks already running in its wave may finish, pass review, and integrate when still
   safe. Continue through every stage up to the next `Checkpoint` group without pausing for
   interim confirmation; at a checkpoint, stop after the stage has passed review and integration
   and wait for human approval. After all tasks pass, run a final whole-change review only when it
   is not redundant with a current wave review covering the complete accumulated diff; use the
   escalated fan-out only for the conditions delegation.md names.
8. At a protected-main or release checkpoint, confirm the corresponding fresh dependency audit,
   linked JSON/Markdown reports, result semantics, and timestamped main/release evidence before
   continuing. Missing or stale evidence is a failed checkpoint, not a clean result.

Parallelism changes scheduling, not completion semantics: retain one task contract, one isolated
diff, one review, one integration, and one immediate checkmark per task.

## The loop

```
0. Reconcile the state/ledger/checklist and repository state. In local/sequential mode, pick the
   FIRST unchecked [ ] leaf task in the earliest incomplete stage. In delegated mode, use the
   guarded wave scheduler above. Confirm every task in `Depends on` is already `[x]` (skip `[ ]*`
   tasks only if the user opted out of them).
1. Observe and record the task-attempt start time, then announce it (number + summary + which
   requirements it cites).
2. RED   — write the test(s) for this task's behavior; watch them fail.
3. GREEN — write the minimal code to pass; run the tests.
4. REFACTOR — clean up with tests green.
5. DOCUMENT — add documentation comments to the code this task produced, in the project's
   native convention (Javadoc, Doxygen, JSDoc/TSDoc, Swift DocC, rustdoc, …).
   **REQUIRED SUB-SKILL:** invoke code-documenting and follow it. Every new or changed public
   function, method, class, module, and file gets a doc comment stating its contract and the
   *why* — not a restatement of the code. Skip only genuinely trivial private helpers.
6. VERIFY — confirm the task's cited criteria (_Requirements: X.Y_) are actually satisfied
   (run it / check the observable behavior EARS specified) and review the task's Documentation
   contract with `code-documenting`. Invoke `spec-verification` and compare with the recorded
   baseline. Obtain the independent review required by the task or active wave. In local/sequential
   mode, defer ordinary-risk task review to the wave/final accumulated review. If either fails, keep working and invoke
   `spec-debugging` for unexpected failures; do not check off.
7. STOP THE ATTEMPT — observe its stop time, close the task-attempt record, then edit 04_tasks.md, flip this task's
   [ ] → [x], and save. Do this BEFORE starting the next task. Never carry a
   finished-but-unchecked task forward.
8. ROLL UP — if this was the last unchecked required child of a parent, flip the parent
   [ ] → [x] in the same step. A parent is done only when all its required children are.
9. If the NEXT item is a Checkpoint group → stop and wait for the user unless the user explicitly
    authorized execution through checkpoints; otherwise record the checkpoint and continue. Go to 1.
10. When all required boxes are [x] → invoke `spec-verification`, run the full test suite, do a
   final pass over every requirement criterion, and confirm current independent review covers the
   complete accumulated diff (run one only when coverage is missing), then update
   `05_execution.md`, mark Execution `complete` in `00_state.md`,
   observe and record the run stop time, refresh and render-validate the final Execution Gantt
   and the final Stage and Dependency Overview (now fully `done`, when `04_tasks.md` has one),
   then invoke `spec-finish` for the user's integration choice. Do not merge, push, deploy, clean
   up, or discard merely because execution is complete.
```

## Rules

- **Stage order is law.** Execute stages in order. Within a stage, preserve task-list order unless
  the guarded parallel-wave process isolates the tasks.
- **Dependencies are gates.** Never begin a task until every declared prerequisite is `[x]`, and
  never begin a later stage while required work remains in an earlier stage.
- **Tests first.** If a task has no natural test, verify its observable behavior another explicit
  way and say how — never skip verification.
- **Document as you build.** Code isn't done until it's documented for the next developer.
  **REQUIRED SUB-SKILL:** use code-documenting to add native doc comments (contract + *why*) to
  every new/changed public function, class, module, and file before you check the task off.
- **Treat documentation as verification.** A task's documentation contract is a completion
  condition, not polish to defer. Verify it explains the API contract and rationale rather than
  repeating signatures or implementation mechanics.
- **Verify against requirements, not vibes.** The EARS criterion is the acceptance test.
- **Review is independent and fan-out-proportional.** The implementer never supplies the only
   quality verdict. Resolve reviewer count and tier from the task/wave's depth via
   [delegation.md](../spec-driven/references/delegation.md) and `scripts/fanout.py`; do not repeat
   a final review that already covers the complete accumulated diff.
- **Checkpoints are the only routine stop.** Invoking this skill on an approved task list is
  itself authorization to run continuously through every ready task up to the next `Checkpoint`
  group. Nothing else pauses the loop except a delegated-approval-boundary exception or an
  unresolved failure after the repair budget.
- **No interim check-ins.** Between checkpoints, the checklist, timing ledger, and fan-out-resolved
  reviews already defined are the quality gate. Do not add a "here's what I did so far, does this
  look right?" pause — that pattern belongs to discipline-heavy review workflows this family
  doesn't depend on (`spec-driven` is self-contained).
- **Keep the spec live.** If implementation reveals a plan or design defect, repair it under
   Autonomous task-list repair above and continue when the repair qualifies for delegated approval.
   If it changes requirements or crosses an approval boundary, STOP and get human re-approval via
   the relevant phase skill — never silently deviate.
- **Checklist discipline** — see below; it is non-negotiable.
- **Timing is evidence.** Record observed UTC starts and stops at the event boundary. Close the
   current run on every intentional exit, preserve interrupted unknowns, and derive the validated
   Gantt only from ledger rows.

## Checklist discipline (non-negotiable)

The task list is the single source of truth for progress. Keep it honest, in real time.

- **Mark before moving on.** The instant a task is integrated and verified, flip its `[ ]` → `[x]`
  in `04_tasks.md` and save — BEFORE integrating the next task or opening another stage. At any pause,
  the file must reflect reality exactly:
  every finished task checked, every unfinished task unchecked. No exceptions.
- **One completion record at a time, never bulk-check.** A parallel wave may finish together, but
  integrate, verify, and check off each task individually. Do not check a task you have not
  integrated and verified, or update several checkboxes after the fact.
- **Parent roll-up.** A parent task (e.g. `3`) is checked ONLY when every one of its required
  children (`3.1`, `3.2`, …) is `[x]` — check the parent in the same step you check its last
  child. Never check a parent while a required child is still `[ ]`, and never check a child's
  parent as a shortcut for the child.
- **Optional (`[ ]*`) children.** One the user opted to skip does NOT block its parent; if it is
  actually done, check it. A parent whose only remaining child is a skipped optional is complete.
- **Persist to disk.** Edit the `04_tasks.md` file itself, not a mental tally — progress must survive
  across sessions and be visible to the user at a glance.
- **Regenerate the sidecar in the same step.** Immediately after editing `04_tasks.md` — a
  checkbox flip, a parent roll-up, or an Autonomous task-list repair — run `scripts/spec-check.py
  <spec-dir> --emit-json` from the `spec-driven` skill directory before starting the next task.
  `04_tasks.json` is a derived artifact, never hand-maintained; a stale sidecar is a checker
  error at the next `--ready` gate, not a formatting nicety to catch up on later.

## If something's wrong

- Task unimplementable as written → repair it under Autonomous task-list repair above; return to
   `spec-tasks` (or `spec-design`) for human re-approval only when the repair crosses the delegated
   approval boundary.
- Discovered a missing requirement → return to `spec-requirements`; ripple through design/tasks.

## Red flags — STOP

- "I'll check off the task, tests can come later" → tests/verification come before the check.
- "I'll keep going past this checkpoint to save time" → checkpoints are user gates.
- "Close enough to the requirement" → the EARS criterion is pass/fail; make it pass.
- "I'll tweak the design as I go without updating 03_design.md" → update the artifact and follow
   delegated approval or human re-approval according to the boundary above.
- "Let me check in before starting the next task/stage" → between checkpoints that's an
   unnecessary interruption; keep going.
- "I'll ask the user whether to keep fixing this" → reclassify via Autonomous task-list repair
   instead; only a boundary-crossing conflict actually stops.
- "Two fix rounds failed, I'll pause here for permission" → exhausting the repair budget triggers
   reclassification, not a pause; repair the contract or return to the owning gate, don't ask.
- "I'll finish a few tasks then check them all off together" → mark each `[x]` before starting the next.
- "The parent's basically done, I'll check it" → only when every required child is `[x]`.
- "I'll just remember what's done" → persist each checkmark to `04_tasks.md` now; don't rely on memory.
- "I'll document it all at the end" → document each task's code before you check it off (step 5, via code-documenting).
- "The code is self-explanatory, skip the docs" → public API still needs contract + *why*; only trivial private helpers are exempt.
- "I'll add the times after execution" → observe and persist them at start/stop; reconstructed times are not evidence.
- "The Gantt looks plausible" → invoke `mermaid` and render-validate the exact fenced source before saving it as current.
