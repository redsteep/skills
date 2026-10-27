#!/usr/bin/env bash
# PostToolUse(Bash): a PR has just been opened → turn review mode on.
#
# Mechanical trigger, so it does not depend on the agent noticing the user's
# first remark. From here on edits to that worktree are denied and requests go
# into the queue until the user runs `/review-mode done`.
set -uo pipefail

here="$(dirname "${BASH_SOURCE[0]}")"
. "$here/common.sh"
[[ -n "$state" ]] || exit 0

payload=$(cat)
cmd=$(jq -r '.tool_input.command // ""' <<<"$payload" 2>/dev/null) || exit 0

# `gh pr create` in command position (optionally behind env assignments).
grep -qE '(^|[;&|(])[[:space:]]*([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*[[:space:]]+)*gh[[:space:]]+pr[[:space:]]+create' <<<"$cmd" || exit 0
# ...and it actually produced a PR. The URL is the only success signal that does
# not depend on which field the harness puts the output in.
# Any host, so GitHub Enterprise counts too.
grep -qoE 'https://[^/[:space:]"]+/[^[:space:]"]+/pull/[0-9]+' <<<"$payload" || exit 0
# A draft PR is not up for review yet (unattended runs tend to open drafts).
grep -qE '(^|[[:space:]])--draft([[:space:]]|$)' <<<"$cmd" && exit 0
# Inside a factory worker, review mode is the worker's own move: its triage runs
# `review-mode.sh on <worktree>` when it sends the PR to review. Turning it on here instead would
# deny the worker the edits its own later phases need and hand it the queueing protocol on top of
# its own auto-merge — and since the factory's PR opens with the code (no draft for a spec), this
# hook would fire on every step.
[[ -n "${FACTORY_WORKER:-}" ]] && exit 0

# Which worktree: the last `cd <path>` the command used (plain, chained or in a
# subshell), else the tool's cwd, else let review-mode.sh decide (it refuses
# when the choice is ambiguous).
wt=$(grep -oE '(^|[;&|(])[[:space:]]*cd[[:space:]]+[^[:space:]&;)]+' <<<"$cmd" | tail -1 | awk '{print $NF}')
wt="${wt%\"}"; wt="${wt#\"}"
[[ -z "$wt" ]] && wt=$(jq -r '.cwd // ""' <<<"$payload" 2>/dev/null)

out=$("$here/review-mode.sh" on ${wt:+"$wt"} 2>&1) || exit 0

jq -n --arg o "$out" --arg s "$(cd "$here" && pwd)/review-mode.sh" '{
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: ("Review mode turned on automatically after the PR was created.\n\($o)\n\nProtocol while it is on: answer the user'"'"'s questions at once and in full — runs are allowed (tests, queries, the running app). Do NOT carry out a change request: queue it with `\"\($s)\" add -b <branch> \"<the user'"'"'s wording> — path/file:line — <what you will do>\"` and confirm in one line. Edits to the reviewed worktree are denied by a hook. Leave only on the user'"'"'s go-ahead: /review-mode done (with -b <branch> when several reviews are on), then apply the whole queue in one iteration.")
  }
}'
