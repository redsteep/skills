#!/usr/bin/env bash
# Remove a finished factory step's worktree, its poetry venvs, and its branch (local + remote),
# without prompting. Called by the dispatcher only — it is the one cleanup owner.
# Follows post-merge-handoff Step 4: venvs are deleted while the worktree still exists, and only
# paths under the poetry venv cache are ever removed.
#
#   remove-step-worktree.sh <repo> <branch>     e.g. feature/factory-aB3d-s1
set -uo pipefail

REPO="${1:?usage: remove-step-worktree.sh <repo> <branch>}"
BRANCH="${2:?usage: remove-step-worktree.sh <repo> <branch>}"
case "$BRANCH" in feature/factory-*) ;; *) echo "refusing: $BRANCH is not a factory branch" >&2; exit 2 ;; esac
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
git -C "$REPO" branch -D "$BRANCH" 2>/dev/null
git -C "$REPO" push origin --delete "$BRANCH" 2>/dev/null
for fix in $(git -C "$REPO" for-each-ref --format='%(refname:short)' "refs/heads/$BRANCH-fix*"); do
  git -C "$REPO" branch -D "$fix" 2>/dev/null
  git -C "$REPO" push origin --delete "$fix" 2>/dev/null
done
git -C "$REPO" worktree prune
exit 0
