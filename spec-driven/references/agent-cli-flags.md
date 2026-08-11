# Reference: Agent CLI Flags for Unattended Orchestration

## Overview

When coding agents are dispatched as background workers in non-interactive PTYs (e.g. via Orca child worktrees or terminal sessions), they must not halt or freeze waiting for interactive user confirmations (such as `[y/n]` prompts to run bash commands, write files, or approve tool calls).

This reference documents the canonical flags for unattended operation across major AI coding agents, as defined in [`contracts/agent_profiles.json`](../contracts/agent_profiles.json).

**These flags drift across CLI releases — do not trust this file (or memory) blind.** Before relying
on a flag here for a dispatch that matters, or before changing `agent_profiles.json`, re-verify it
against the vendor's current docs (Context7 libraries `/anthropics/claude-code`, `/openai/codex`, the
Antigravity CLI library, etc., or the installed binary's own `--help`) the same way the mermaid
skill escalates to live syntax on a stale-cache signal. Every flag below was verified against
current vendor docs on 2026-08-11; re-check before trusting it much later than that.

Prefer the narrowest flag combination that avoids a hang, not the broadest bypass. A sandbox/deny
rule that rejects a risky action outright is safe for an unattended worker (it fails cleanly); an
`ask`/ `untrusted` policy is not (nothing is present to answer the prompt, so it hangs forever).
Full-bypass flags (`--dangerously-skip-permissions`, `bypassPermissions`, `--yolo`) are for workers
already confined to an isolated worktree where the blast radius of a wrong action is small.

---

## Agent CLI Matrix

### 1. Claude Code (`claude`)

Anthropic Claude Code is an agentic terminal tool.

- **Unattended Flag**: `--permission-mode bypassPermissions` (equivalently `--dangerously-skip-permissions`)
  - `--permission-mode auto` does **not** exist — valid modes are `default`/`manual`, `acceptEdits`, `plan`, `bypassPermissions`. Passing `auto` either errors or silently falls back to a prompting mode, which is a direct cause of unattended-worker hangs.
- **Model Flag**: `--model <model-id>` — resolve the current model id/alias live rather than hardcoding one; Anthropic's model lineup changes.
- **Effort Flag**: `--effort <low|medium|high|xhigh>`
- **Non-Interactive Print**: `-p "<prompt>"` / `--print`
- **Read-only role**: `--permission-mode plan` restricts to planning without edits. `--allowedTools`/a CLI tool-allowlist flag was deprecated in favor of the `permissions.allow`/`deny`/`ask` block in `.claude/settings.json` — there is no current CLI flag equivalent; scope a reviewer/explorer role via a settings file in its worktree, not a hand-typed flag.
- **Optional safety net for a bypass-mode implementer**: a short `permissions.deny` list in `.claude/settings.json` for genuinely destructive Bash patterns (e.g. `Bash(rm -rf:*)`, `Bash(git push --force:*)`) fails those closed even under `bypassPermissions`, without reintroducing a hang-prone prompt for everything else.

#### Example Invocations
```bash
# Implementer in isolated worktree
claude --permission-mode bypassPermissions --model <model-id> --effort high

# Read-only reviewer/explorer
claude --permission-mode plan --model <model-id>

# Non-interactive query
claude -p "Explain architecture in src/core.py" --output-format json
```

---

### 2. OpenAI Codex (`codex`)

OpenAI Codex is a CLI agent for terminal workflows. Use the `codex exec` subcommand for scripted/non-interactive automation.

- **Unattended Flag**: `--ask-for-approval never --sandbox workspace-write`
  - `--approve-for-me` does **not** exist — it is not a Codex flag. `--ask-for-approval` accepts `untrusted` (default, escalates most commands), `on-request`/`on-failure`, or `never` (no prompts, ever — required for an unattended worker). Pair `never` with a sandbox mode so risky actions fail closed instead of running unconstrained: `workspace-write` allows edits inside the worktree and blocks network/out-of-worktree writes; `read-only` blocks all edits; `danger-full-access` (or `--dangerously-bypass-approvals-and-sandbox` / `--yolo`, which sets both `never` and `danger-full-access` at once) removes the sandbox entirely and should only be used for a worker already confined to an isolated, disposable worktree.
- **Model Flag**: `--model <model-id>` — resolve live; do not hardcode a specific model string here.
- **Effort Flag**: `-c model_reasoning_effort="<low|medium|high>"` (the general `-c key=value` config-override syntax)
- **Reviewer Sandbox**: `--sandbox read-only --ask-for-approval never`

#### Example Invocations
```bash
# Implementer (edits allowed in-worktree; network/out-of-worktree writes fail closed, never prompts)
codex exec --ask-for-approval never --sandbox workspace-write --model <model-id> -c model_reasoning_effort="medium" "<task>"

# Read-only Reviewer
codex exec --sandbox read-only --ask-for-approval never --model <model-id> "<task>"
```

---

### 3. Google Antigravity CLI (`agy`)

Google Antigravity CLI operates in agentic mode.

- **Unattended Flag**: `--dangerously-skip-permissions` — confirmed current; auto-approves all tool permission requests so nothing can block on a prompt.
- **Softer alternative**: `--mode=accept-edits` auto-approves file read/write/replace operations (including from subagents) while shell commands are still policy-gated — use only when you also want shell commands gated, and verify current behavior before relying on it for a fully unattended worker (a gated-but-not-approved shell call can still hang with no one present to answer it).
- **Model Flag**: `--model <model-id>` — resolve live; Gemini model slugs move fast (the lineup has already moved past `gemini-2.5-pro`).
- **Effort Flag**: `--effort <low|medium|high>`
- **Reviewer Mode**: `--mode=plan --sandbox` (both confirmed current; `--sandbox` is a boolean flag, no value)

#### Example Invocations
```bash
# Implementer
agy -p "<task>" --dangerously-skip-permissions --model <model-id> --effort high
```

---

### 4. Cursor CLI (`cursor-agent`)

Cursor headless CLI agent. **Unverified against current docs** — check before trusting for a dispatch that matters.

- **Unattended Flags**: `--approve-all`, `--headless`
- **Model Flag**: `--model <model-id>` — resolve live; do not hardcode a specific model string.
- **Thinking Flag**: `--thinking-level <low|medium|high>`

#### Example Invocations
```bash
cursor-agent --approve-all --headless --model <model-id>
```

---

### 5. OpenCode / Pi (`opencode`)

**Unverified against current docs** — check before trusting for a dispatch that matters.

- **Unattended Flags**: `--auto-confirm`, `--yes`
- **Model Flag**: `--model <model-id>`
- **Reasoning Flag**: `--reasoning <level>`
