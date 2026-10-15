#!/usr/bin/env bash
# Review mode: while the user reads a PR, answers and runs are allowed, edits are not.
#
# There is no mode registry in Claude Code, so a mode is a state file plus hooks
# that read it. This script owns the state; `deny-edits-in-review.sh` and
# `review-drift-check.sh` read it. The marker names a worktree, so review of one
# branch does not freeze edits in the other worktrees running in parallel.
#
#   review-mode.sh on [worktree]   marker + queue, snapshot of the tree
#   review-mode.sh add "<line>"    append one request to the queue
#   review-mode.sh off | done      drop the marker, print the queue
#   review-mode.sh status          print the marker, or say it is off
#
# The queue sits under .git/, which Claude Code guards against the Edit/Write
# tools — so requests are queued through `add`, one Bash call that can be
# allowlisted, rather than by editing the file.
set -uo pipefail

. "$(dirname "${BASH_SOURCE[0]}")/common.sh"
[[ -n "$state" ]] || { echo "not a git repo: $project"; exit 1; }
mkdir -p "$state"

case "${1:-status}" in
on)
  wt="${2:-}"
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
  head=$(git -C "$wt" rev-parse HEAD)
  jq -n --arg w "$wt" --arg b "$branch" --arg h "$head" --arg s "$(git -C "$wt" status --porcelain)" \
     --arg t "$(date -Is)" '{worktree:$w, branch:$b, head:$h, snapshot:$s, started:$t}' > "$marker"
  [[ -f "$queue" ]] || printf '# Review queue — %s\n\nFilled in during the review. One line per request:\n`- [ ] <your wording> — path/file:line — <what I will do>`\n\n' "$branch" > "$queue"
  echo "review mode ON — $branch ($wt)"
  echo "queue: $queue"
  ;;
add)
  shift
  line="$*"
  [[ -n "$line" ]] || { echo "usage: review-mode.sh add \"<wording> — path/file:line — <what you will do>\""; exit 1; }
  [[ -f "$marker" ]] || echo "note: review mode is off; queued anyway"
  [[ "$line" == "- [ ] "* ]] || line="- [ ] $line"
  printf '%s\n' "$line" >> "$queue"
  echo "queued: $line"
  ;;
off|done)
  [[ -f "$marker" ]] || { echo "review mode was already off"; exit 0; }
  branch=$(jq -r .branch "$marker"); rm -f "$marker"
  # grep -c prints 0 AND exits 1 on no match, so `|| echo 0` would yield "0\n0".
  n=$(grep -c '^- \[ \]' "$queue" 2>/dev/null) || true
  [[ "$n" =~ ^[0-9]+$ ]] || n=0
  echo "review mode OFF — $branch; $n item(s) queued in $queue"
  [[ "$n" -gt 0 ]] && grep '^- \[ \]' "$queue"
  ;;
status)
  if [[ -f "$marker" ]]; then jq -r '"ON — \(.branch) at \(.head[0:7]), since \(.started)\nworktree: \(.worktree)"' "$marker"
  else echo "OFF"; fi
  echo "queue: $queue"
  ;;
*) echo "usage: review-mode.sh on [worktree] | add \"<line>\" | done | status"; exit 1;;
esac
