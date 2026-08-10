# Reference: Agent CLI Flags for Unattended Orchestration

## Overview

When coding agents are dispatched as background workers in non-interactive PTYs (e.g. via Orca child worktrees or terminal sessions), they must not halt or freeze waiting for interactive user confirmations (such as `[y/n]` prompts to run bash commands, write files, or approve tool calls).

This reference documents the canonical flags for unattended operation across major AI coding agents, as defined in [`contracts/agent_profiles.json`](../contracts/agent_profiles.json).

---

## Agent CLI Matrix

### 1. Claude Code (`claude`)

Anthropic Claude Code is an agentic terminal tool.

- **Unattended Flag**: `--dangerously-skip-permissions` (or `--permission-mode bypassPermissions`)
  - Bypasses interactive prompts for tool execution, bash commands, and file edits.
- **Model Flag**: `--model <model-name>`
- **Effort Flag**: `--effort <low|medium|high>`
- **Non-Interactive Print**: `-p "<prompt>"` / `--print`
- **Reviewer Allowlist**: `--permission-prompt-tool-allowlist View,Read,Grep,Glob,Search` (constrains tools to read-only discovery).

#### Example Invocations
```bash
# Implementer in isolated worktree
claude --dangerously-skip-permissions --model claude-3-7-sonnet --effort high

# Non-interactive query
claude -p "Explain architecture in src/core.py" --output-format json
```

---

### 2. OpenAI Codex (`codex`)

OpenAI Codex is a CLI agent for terminal workflows.

- **Unattended Flags**: `--full-auto`, `-y`
  - Automatically confirms tool execution and shell actions.
- **Model Flag**: `--model <model-name>`
- **Effort Flag**: `-c model_reasoning_effort="<low|medium|high>"`
- **Reviewer Sandbox**: `--sandbox read-only`

#### Example Invocations
```bash
# Implementer
codex --full-auto -y --model o3-mini -c model_reasoning_effort="medium"

# Read-only Reviewer
codex --sandbox read-only --model o3-mini
```

---

### 3. Google Antigravity CLI (`agy`)

Google Antigravity CLI operates in agentic mode.

- **Unattended Flags**: `--yolo`, `--auto-approve`, `--bypass-sandbox`
- **Model Flag**: `--model <model-name>`
- **Thinking Flag**: `--thinking <low|medium|high>`
- **Reviewer Mode**: `--read-only`

#### Example Invocations
```bash
# Implementer
agy --yolo --auto-approve --model gemini-2.5-pro --thinking high
```

---

### 4. Cursor CLI (`cursor-agent`)

Cursor headless CLI agent.

- **Unattended Flags**: `--approve-all`, `--headless`
- **Model Flag**: `--model <model-name>`
- **Thinking Flag**: `--thinking-level <low|medium|high>`

#### Example Invocations
```bash
cursor-agent --approve-all --headless --model claude-3-7-sonnet
```

---

### 5. OpenCode / Pi (`opencode`)

- **Unattended Flags**: `--auto-confirm`, `--yes`
- **Model Flag**: `--model <model-name>`
- **Reasoning Flag**: `--reasoning <level>`
