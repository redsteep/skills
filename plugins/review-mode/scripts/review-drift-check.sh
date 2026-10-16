#!/usr/bin/env bash
# Stop: edits made during review mode anyway are caught here.
#
# Compares each reviewed worktree against the snapshot taken on entry, so it does
# not care whether the edit came through Edit, Write or Bash. One report per
# distinct drift, or `decision: block` would repeat every turn.
set -uo pipefail

payload=$(cat)
# The model is already continuing because of a Stop hook: do not loop.
[[ "$(jq -r '.stop_hook_active // false' <<<"$payload" 2>/dev/null)" == "true" ]] && exit 0

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
[[ -n "$state" ]] || exit 0

report=""
while IFS= read -r marker; do
  wt=$(jq -r '.worktree' "$marker")
  branch=$(jq -r '.branch // ""' "$marker")
  now=$(git -C "$wt" status --porcelain 2>/dev/null)
  snap=$(jq -r '.snapshot // ""' "$marker")
  [[ "$now" != "$snap" ]] || continue
  drift=$(comm -13 <(printf '%s\n' "$snap" | sort) <(printf '%s\n' "$now" | sort) | sed '/^$/d')
  [[ -n "$drift" ]] || continue
  stamps="$(dirname "$marker")/drift"; mkdir -p "$stamps" 2>/dev/null || continue
  key=$(printf '%s' "$drift" | sha1sum | cut -c1-16)
  [[ -e "$stamps/$key" ]] && continue
  : > "$stamps/$key"
  report+="branch $branch ($wt):"$'\n'"$drift"$'\n'
done < <(live_markers)
[[ -n "$report" ]] || exit 0

jq -n --arg d "$report" --arg s "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/review-mode.sh" '{
  decision: "block",
  reason: ("Review mode is on, but a reviewed tree changed since it was entered:\n\($d)\nThe user has not released these edits yet. Either revert them and queue them with `\"\($s)\" add -b <branch> \"…\"`, or say in one line why they were needed now (e.g. answering a question required a run). Do not keep editing.")
}'
