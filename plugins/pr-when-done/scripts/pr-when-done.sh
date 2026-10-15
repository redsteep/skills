#!/usr/bin/env bash
# Stop: a finished feature branch should not sit there waiting to be asked about.
# When a worktree looks done — clean tree, commits ahead of the default branch,
# no PR — push the model to review and open the PR instead of ending the turn.
#
# Work often happens in worktrees while the hook's cwd is the main checkout, so
# every worktree is examined rather than "the current branch" — but only those
# this session's own tool calls (or the prompts it handed to subagents) named.
# Parallel sessions keep their own worktrees, and nudging this one about them is noise.
#
# Two loop guards, because `decision: block` on Stop re-enters this hook:
#   - stop_hook_active: the model is already continuing because of a Stop hook;
#   - a stamp per branch+HEAD sha: at most one nudge per commit, so a branch
#     mid-feature costs one sentence per commit, not one per turn.
set -uo pipefail

payload=$(cat)
[[ "$(jq -r '.stop_hook_active // false' <<<"$payload" 2>/dev/null)" == "true" ]] && exit 0

repo="${CLAUDE_PROJECT_DIR:-$PWD}"
gitdir=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || exit 0
# Stamps live in the git dir: never committed, shared by every worktree.
stamps="$gitdir/pr-nudge"
mkdir -p "$stamps" 2>/dev/null || exit 0

# The branch PRs target: the remote's default branch (origin/HEAD), else origin/main.
base=$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || base="origin/main"
base_name="${base#origin/}"

# Tool-call inputs only: the transcript also holds this hook's own nudges, which
# name the worktree they are about and would otherwise make it "ours" for good.
transcript=$(jq -r '.transcript_path // empty' <<<"$payload" 2>/dev/null)
[[ -n "$transcript" && -r "$transcript" ]] || exit 0
touched=$(jq -r 'select(.type == "assistant") | .message.content[]?
  | select(.type == "tool_use") | .input | tostring' "$transcript" 2>/dev/null)
[[ -n "$touched" ]] || exit 0

while read -r _ wt; do
  [[ -z "${wt:-}" ]] && continue
  branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null) || continue
  [[ "$branch" == "$base_name" ]] && continue
  # The path must end where it is named: `.worktrees/foo` is not `.worktrees/foo-v2`.
  wt_re=$(sed 's/[][\.*^$/]/\\&/g' <<<"$wt")
  grep -qE "${wt_re}([^A-Za-z0-9_.-]|$)" <<<"$touched" || continue

  # Nothing half-written, and something actually committed. `status --porcelain`
  # rather than `diff --quiet`: an untracked new module or test file is exactly
  # what unfinished work looks like, and diff does not see it. Ignored paths
  # (env files, virtualenvs, scratch dirs) stay invisible here, as they should.
  [[ -z "$(git -C "$wt" status --porcelain 2>/dev/null)" ]] || continue
  ahead=$(git -C "$wt" rev-list --count "$base..HEAD" 2>/dev/null) || continue
  [[ "${ahead:-0}" -ge 1 ]] || continue

  sha=$(git -C "$wt" rev-parse --short HEAD 2>/dev/null) || continue
  stamp="$stamps/${branch//\//_}-${sha}"
  [[ -e "$stamp" ]] && continue

  # Any PR for this branch — open or already merged — means this is not it.
  # A failure here (offline, no auth) must mean silence, never a false nudge.
  prs=$(cd "$wt" && timeout 8 gh pr list --head "$branch" --state all --limit 1 \
        --json number --jq 'length' 2>/dev/null) || continue
  [[ -z "$prs" || "$prs" != "0" ]] && continue

  : > "$stamp"
  jq -n --arg b "$branch" --arg w "$wt" --arg a "$ahead" --arg base "$base" '{
    decision: "block",
    reason: ("Branch \($b) in \($w): clean tree, \($a) commit(s) ahead of \($base), no PR. "
      + "If the implementation is finished, review it (the pre-pr-review skill, if available) and open the PR, without asking for permission. "
      + "If not, say in one line what is left and carry on: this message will not repeat until the next commit.")
  }'
  exit 0
done < <(git -C "$repo" worktree list --porcelain | grep '^worktree ')
exit 0
