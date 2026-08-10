#!/usr/bin/env bash
# spec-execute checklist guard  —  Claude Code PostToolUse hook (Edit|Write|MultiEdit).
#
# Nudges you to keep 04_tasks.md honest: if you edit a SOURCE file while a
# `.specs/**/04_tasks.md` still has unchecked REQUIRED items, it reminds you to mark
# the completed task `[x]` (and roll up its parent) before moving on.
#
# Mechanism: reads the hook's JSON from stdin, and on drift exits 2 with a message
# on stderr — for PostToolUse, exit 2 surfaces that message back to Claude. On
# anything not worth flagging it exits 0 (silent). It NEVER blocks or reverts an edit.
#
# Wire it up with the `update-config` skill (see spec-hooks/SKILL.md). Non-fatal by
# design: any internal error exits 0 so it can't wedge your workflow.
set -uo pipefail

input="$(cat 2>/dev/null || true)"
[ -z "$input" ] && exit 0

# --- extract file_path + cwd from the hook payload (stdlib python, no deps) ------
read -r fp cwd < <(printf '%s' "$input" | python3 -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    print(" "); sys.exit(0)
ti = d.get("tool_input", {}) or {}
fp = ti.get("file_path", "") or ""
cwd = d.get("cwd", "") or ""
# emit as a single line: <fp>\t<cwd>
print(fp + "\t" + cwd)
' | awk -F'\t' '{print $1, $2}') || exit 0

[ -z "${fp:-}" ] && exit 0

# Don't flag edits to the spec artifacts themselves (that IS updating the checklist).
case "$fp" in
  */.specs/*) exit 0 ;;
  */04_tasks.md) exit 0 ;;
esac

# Only nudge for source-like files (keeps the hook quiet on docs/config churn).
case "$fp" in
  *.py|*.js|*.ts|*.tsx|*.jsx|*.go|*.rs|*.java|*.rb|*.c|*.cc|*.cpp|*.h|*.hpp|*.cs|*.php|*.swift|*.kt|*.scala|*.sh) ;;
  *) exit 0 ;;
esac

root="${cwd:-$PWD}"
[ -d "$root/.specs" ] || exit 0

# Any 04_tasks.md under .specs with an unchecked REQUIRED item? `- [ ] ` (trailing
# space) matches required tasks; optional `- [ ]*` has no trailing space, so it's
# correctly ignored.
pending="$(grep -rlE '^[[:space:]]*- \[ \] ' "$root/.specs" --include=04_tasks.md 2>/dev/null || true)"
[ -z "$pending" ] && exit 0

{
  echo "spec-execute guard: you edited a source file"
  echo "  $fp"
  echo "while a task list still has unchecked required items:"
  printf '  - %s\n' $pending
  echo "If this edit completed a task, mark it [x] in 04_tasks.md (and roll up its parent)"
  echo "BEFORE starting the next task — one task at a time, never batch. (spec-execute)"
} >&2
exit 2
