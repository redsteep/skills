# Sourced by the review-mode scripts: where the mode keeps its state.
#
# State lives in the git common dir, not the working tree: it is never committed,
# needs no .gitignore entry, and every worktree of the repo sees it — a session
# started in the main checkout and one started inside a worktree agree on what is
# under review.
#
# One directory per reviewed branch (`review-mode/<branch>/marker.json` + `queue.md`),
# so parallel reviews in different worktrees neither overwrite each other's marker
# nor mix their queues.

project="${CLAUDE_PROJECT_DIR:-$PWD}"
gitdir=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || gitdir=""
state="${gitdir:+$gitdir/review-mode}"

# A branch name as a directory name: `feature/x` → `feature__x`.
state_dir_for_branch() { printf '%s/%s' "$state" "${1//\//__}"; }

# Every live marker, one path per line. A marker whose worktree is gone is stale
# and skipped, so a forgotten mode never blocks edits forever.
live_markers() {
  local m wt
  for m in "$state"/*/marker.json; do
    [[ -f "$m" ]] || continue
    wt=$(jq -r '.worktree // ""' "$m" 2>/dev/null)
    [[ -n "$wt" && -d "$wt" ]] && printf '%s\n' "$m"
  done
}

# The worktree a path belongs to: the nearest existing directory's toplevel, so a
# file about to be created resolves too. A linked worktree nested inside the main
# checkout resolves to itself, not to the main checkout.
toplevel_of() {
  local d="$1"
  while [[ ! -d "$d" && "$d" != "/" ]]; do d=$(dirname "$d"); done
  git -C "$d" rev-parse --show-toplevel 2>/dev/null
}

# The live marker reviewing worktree $1, if any.
marker_for_worktree() {
  local m
  while IFS= read -r m; do
    [[ "$(jq -r .worktree "$m")" == "$1" ]] && { printf '%s\n' "$m"; return 0; }
  done < <(live_markers)
  return 1
}

# The marker a command means: `-b <branch>` if given, else the one reviewing the
# current worktree, else the only live one. Explains and fails otherwise.
resolve_marker() {
  local branch="$1" m here all
  if [[ -n "$branch" ]]; then
    m="$(state_dir_for_branch "$branch")/marker.json"
    [[ -f "$m" ]] && { printf '%s\n' "$m"; return 0; }
    echo "review mode is not on for branch $branch" >&2; return 1
  fi
  here=$(toplevel_of "$PWD")
  if [[ -n "$here" ]] && m=$(marker_for_worktree "$here"); then printf '%s\n' "$m"; return 0; fi
  mapfile -t all < <(live_markers)
  if [[ ${#all[@]} -eq 1 ]]; then printf '%s\n' "${all[0]}"; return 0; fi
  if [[ ${#all[@]} -eq 0 ]]; then
    echo "review mode is off" >&2
  else
    echo "several reviews are on — pass -b <branch>:" >&2
    for m in "${all[@]}"; do echo "  $(jq -r .branch "$m")  ($(jq -r .worktree "$m"))" >&2; done
  fi
  return 1
}
