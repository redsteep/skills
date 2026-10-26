#!/usr/bin/env bash
# Remove a finished factory step's worktree, its poetry venvs, and its branch (local + remote),
# without prompting. Called by the dispatcher only — it is the one cleanup owner.
# Follows post-merge-handoff Step 4: venvs are deleted while the worktree still exists, and only
# paths under the poetry venv cache are ever removed.
#
#   remove-step-worktree.sh <repo> <branch> [<fix-prefix>]
#     <branch>      a factory branch, or an adopted PR's branch
#     <fix-prefix>  the step's fix branches, e.g. feature/factory-aB3d-s1-fix
#
# The remote branch is kept while an open PR is based on it: GitHub closes a PR whose base
# branch is deleted (a stacked PR the next step adopts).
set -uo pipefail

REPO="${1:?usage: remove-step-worktree.sh <repo> <branch>}"
BRANCH="${2:?usage: remove-step-worktree.sh <repo> <branch>}"
case "$BRANCH" in main|master|"") echo "refusing to remove $BRANCH" >&2; exit 2 ;; esac
WT="$REPO/.worktrees/${BRANCH##*/}"

if [[ -d "$WT" ]]; then
  for p in backend common agent tasks; do
    [[ -f "$WT/$p/pyproject.toml" ]] || continue
    V=$(poetry -C "$WT/$p" env info -p 2>/dev/null)
    case "$V" in
      "$HOME"/.cache/pypoetry/virtualenvs/*) rm -rf "$V" ;;
    esac
  done
  git -C "$REPO" worktree remove --force "$WT"
fi

delete_remote() {
  local b="$1"
  if [[ -n "$(gh pr list --repo "$(git -C "$REPO" remote get-url origin)" --base "$b" --state open --json number --jq '.[].number' 2>/dev/null)" ]]; then
    echo "keeping origin/$b: an open PR is based on it" >&2
    return
  fi
  git -C "$REPO" push origin --delete "$b" 2>/dev/null
}

git -C "$REPO" branch -D "$BRANCH" 2>/dev/null
delete_remote "$BRANCH"
FIXES="${3:-}"
[[ -n "$FIXES" ]] && for fix in $(git -C "$REPO" for-each-ref --format='%(refname:short)' "refs/heads/$FIXES*"); do
  git -C "$REPO" branch -D "$fix" 2>/dev/null
  delete_remote "$fix"
done
git -C "$REPO" worktree prune
exit 0
