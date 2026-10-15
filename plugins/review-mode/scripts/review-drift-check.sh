#!/usr/bin/env bash
# Stop: edits made during review mode anyway are caught here.
#
# Compares the reviewed worktree against the snapshot taken on entry, so it does
# not care whether the edit came through Edit, Write or Bash. One report per
# distinct drift, or `decision: block` would repeat every turn.
set -uo pipefail

payload=$(cat)
# The model is already continuing because of a Stop hook: do not loop.
[[ "$(jq -r '.stop_hook_active // false' <<<"$payload" 2>/dev/null)" == "true" ]] && exit 0

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
[[ -n "$state" && -f "$marker" ]] || exit 0

wt=$(jq -r '.worktree // ""' "$marker" 2>/dev/null)
branch=$(jq -r '.branch // ""' "$marker" 2>/dev/null)
[[ -n "$wt" && -d "$wt" ]] || exit 0

now=$(git -C "$wt" status --porcelain 2>/dev/null)
snap=$(jq -r '.snapshot // ""' "$marker" 2>/dev/null)
[[ "$now" != "$snap" ]] || exit 0
drift=$(comm -13 <(printf '%s\n' "$snap" | sort) <(printf '%s\n' "$now" | sort) | sed '/^$/d')
[[ -n "$drift" ]] || exit 0

stamps="$state/drift"; mkdir -p "$stamps" 2>/dev/null || exit 0
key=$(printf '%s' "$drift" | sha1sum | cut -c1-16)
[[ -e "$stamps/$key" ]] && exit 0
: > "$stamps/$key"

jq -n --arg b "$branch" --arg d "$drift" --arg s "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/review-mode.sh" '{
  decision: "block",
  reason: ("Review mode on branch \($b), but the tree changed since it was entered:\n\($d)\n\nThe user has not released these edits yet. Either revert them and queue them with `\"\($s)\" add \"…\"`, or say in one line why they were needed now (e.g. answering a question required a run). Do not keep editing.")
}'
