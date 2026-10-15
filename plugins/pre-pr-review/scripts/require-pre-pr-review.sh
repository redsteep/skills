#!/usr/bin/env bash
# PreToolUse(Bash): deny `gh pr create` until the branch has passed pre-pr-review.
# The agent (or a human) opts through by prefixing the command with REVIEWED=1.
cmd=$(jq -r '.tool_input.command // ""')

# gh in command position: start of line or after ; & | ( , optionally behind VAR=value prefixes.
invocation='(^|[;&|(])[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+pr[[:space:]]+create'
grep -qE "$invocation" <<<"$cmd" || exit 0
grep -qE '(^|[[:space:];&|(])REVIEWED=1([[:space:]]|$)' <<<"$cmd" && exit 0

jq -n '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: "PR blocked: run the pre-pr-review skill on this branch first. Once every gate has passed, rerun the same command prefixed with REVIEWED=1 (e.g. `REVIEWED=1 gh pr create ...`). The same prefix is the opt-out for docs-only changes, trivial fixes and dependency bumps — say which in the PR body."
  }
}'
