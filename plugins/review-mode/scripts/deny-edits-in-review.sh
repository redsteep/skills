#!/usr/bin/env bash
# PreToolUse(Edit|Write|NotebookEdit): no edits inside a worktree under review.
#
# Scoped to that worktree on purpose — the user reviews one branch while other
# sessions keep working in theirs. The file's own worktree is resolved through git,
# not by path prefix: linked worktrees often live inside the main checkout
# (`.worktrees/x`), and a prefix test would freeze all of them whenever the main
# checkout is under review.
#
# This layer only removes the dedicated edit tools. Files can be edited through
# Bash as well, which this does not see; `review-drift-check.sh` on Stop is the
# backstop that cannot be bypassed.
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
[[ -n "$state" ]] || exit 0

payload=$(cat)
file=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // ""' <<<"$payload" 2>/dev/null) || exit 0
[[ -n "$file" ]] || exit 0

wt=$(toplevel_of "$file") || exit 0
[[ -n "$wt" ]] || exit 0
marker=$(marker_for_worktree "$wt") || exit 0
branch=$(jq -r '.branch // ""' "$marker" 2>/dev/null)

jq -n --arg b "$branch" --arg f "$file" --arg s "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/review-mode.sh" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: ("Review mode on branch \($b): edits wait while the user reads the PR. Instead of editing \($f), queue the request with `\"\($s)\" add -b \($b) \"<the user'"'"'s wording> — path/file:line — <what you will do>\"` and answer the question if there was one. Runs (tests, queries, the running app) are allowed: answering questions is the point. Leave only on the user'"'"'s go-ahead, with /review-mode done.")
  }
}'
