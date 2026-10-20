#!/usr/bin/env bash
# Review mode: while the user reads a PR, answers and runs are allowed, edits are not.
#
# There is no mode registry in Claude Code, so a mode is a state file plus hooks
# that read it. This script owns the state; `deny-edits-in-review.sh` and
# `review-drift-check.sh` read it. Each reviewed branch has its own marker and
# queue, so review of one branch neither freezes edits in the other worktrees
# running in parallel nor replaces another branch's review.
#
#   review-mode.sh on [worktree]            marker + queue, snapshot of the tree
#   review-mode.sh add [-b branch] "<line>" append one request to that branch's queue
#   review-mode.sh off | done [-b branch]   drop the marker, print the queue
#   review-mode.sh status                   every review that is on
#
# Without -b, a command means the review of the current worktree, else the only
# one that is on; with several on and none here, it lists them and asks for -b.
#
# The queue sits under .git/, which Claude Code guards against the Edit/Write
# tools — so requests are queued through `add`, one Bash call that can be
# allowlisted, rather than by editing the file.
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
[[ -n "$state" ]] || { echo "not a git repo: $project"; exit 1; }
mkdir -p "$state"

cmd="${1:-status}"; shift || true
branch_opt=""
if [[ "${1:-}" == "-b" ]]; then branch_opt="${2:-}"; shift 2 || shift; fi

case "$cmd" in
on)
  wt="${1:-}"
  if [[ -z "$wt" ]]; then
    # Linked worktrees on a branch; the first entry is the main checkout, which
    # is skipped whatever its branch is called.
    mapfile -t cands < <(git -C "$project" worktree list --porcelain | awk '/^worktree /{n++; w=$2} /^branch /{if (n > 1) print w}')
    if [[ ${#cands[@]} -eq 1 ]]; then
      wt="${cands[0]}"
    else
      echo "pass the worktree explicitly; candidates:"; printf '  %s\n' "${cands[@]:-none}"; exit 1
    fi
  fi
  [[ -d "$wt" ]] || { echo "no such worktree: $wt"; exit 1; }
  wt=$(git -C "$wt" rev-parse --show-toplevel) || { echo "not a git worktree: $wt"; exit 1; }
  branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD) || { echo "detached HEAD in $wt"; exit 1; }
  # Nothing is reviewed on the default branch: a PR is opened from a feature branch.
  default=$(git -C "$wt" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null); default="${default#origin/}"
  [[ "$branch" == "${default:-main}" ]] && { echo "$wt is on $branch, the default branch — nothing to review there"; exit 1; }
  dir=$(state_dir_for_branch "$branch"); mkdir -p "$dir"
  head=$(git -C "$wt" rev-parse HEAD)
  jq -n --arg w "$wt" --arg b "$branch" --arg h "$head" --arg s "$(git -C "$wt" status --porcelain)" \
     --arg t "$(date -Is)" '{worktree:$w, branch:$b, head:$h, snapshot:$s, started:$t}' > "$dir/marker.json"
  [[ -f "$dir/queue.md" ]] || printf '# Review queue — %s\n\nFilled in during the review. One line per request:\n`- [ ] <your wording> — path/file:line — <what I will do>`\n\n' "$branch" > "$dir/queue.md"
  echo "review mode ON — $branch ($wt)"
  echo "queue: $dir/queue.md"
  ;;
add)
  line="$*"
  [[ -n "$line" ]] || { echo "usage: review-mode.sh add [-b branch] \"<wording> — path/file:line — <what you will do>\""; exit 1; }
  marker=$(resolve_marker "$branch_opt") || exit 1
  queue="$(dirname "$marker")/queue.md"
  [[ "$line" == "- [ ] "* ]] || line="- [ ] $line"
  printf '%s\n' "$line" >> "$queue"
  echo "queued for $(jq -r .branch "$marker"): $line"
  ;;
off|done)
  marker=$(resolve_marker "$branch_opt") || exit 1
  queue="$(dirname "$marker")/queue.md"
  branch=$(jq -r .branch "$marker")
  # The commit the queue was raised against: an eval case's `before` for each item a reviewer missed.
  before=$(git -C "$(jq -r .worktree "$marker")" rev-parse --short HEAD 2>/dev/null) || before=""
  rm -f "$marker"
  # grep -c prints 0 AND exits 1 on no match, so `|| echo 0` would yield "0\n0".
  n=$(grep -c '^- \[ \]' "$queue" 2>/dev/null) || true
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  echo "review mode OFF — $branch; $n item(s) queued in $queue"
  if [[ "$n" -gt 0 ]]; then
    grep '^- \[ \]' "$queue"
    # Leaving hands the whole queue over for one iteration, so the next pass starts
    # empty; the list is kept beside it for reference, not shown again.
    applied="$(dirname "$queue")/applied-$(date +%Y%m%dT%H%M%S).md"
    { [[ -n "$before" ]] && echo "<!-- before: $before -->"; cat "$queue"; } > "$applied" && rm -f "$queue"
    echo "queue moved to $applied${before:+ (raised against $before)}"
    echo "after applying: offer an eval case for each item a reviewer should have caught (before: ${before:-HEAD now}), run pre-pr-review over the branch, then 'review-mode.sh on <worktree>' for the next pass"
  fi
  ;;
status)
  mapfile -t all < <(live_markers)
  [[ ${#all[@]} -gt 0 ]] || echo "OFF"
  for m in "${all[@]}"; do
    jq -r '"ON — \(.branch) at \(.head[0:7]), since \(.started)\nworktree: \(.worktree)"' "$m"
    echo "queue: $(dirname "$m")/queue.md"
  done
  # 0.2.x kept one marker and one queue for the whole repo.
  if [[ -f "$state/queue.md" ]]; then echo "legacy shared queue (before per-branch state): $state/queue.md"; fi
  ;;
*) echo "usage: review-mode.sh on [worktree] | add [-b branch] \"<line>\" | done [-b branch] | status"; exit 1;;
esac
