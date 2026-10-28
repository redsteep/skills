#!/usr/bin/env bash
# Remove a finished factory step's worktree, its branches (local + remote) and its review-mode state, without
# prompting. Called by the dispatcher only — it is the one cleanup owner.
#
#   remove-step-worktree.sh <repo> <worktree> <branch> [<fix-prefix>]
#     <worktree>    the step's worktree directory (may already be gone)
#     <branch>      a factory branch, or an adopted PR's branch
#     <fix-prefix>  the step's fix branches, e.g. feature/factory-aB3d-s1-fix
#
# Env FACTORY_CLEANUP: the profile's `## Cleanup` bash block, run first with $WT set, while the
# worktree still exists (per-worktree caches a project needs deleted).
#
# A remote branch whose PR merged is deleted: GitHub then repoints any open PR based on it
# onto the merged PR's base (a stacked PR a later step adopts). An unmerged branch is kept while
# an open PR is based on it — deleting it would close that PR.
set -uo pipefail

REPO="${1:?usage: remove-step-worktree.sh <repo> <worktree> <branch> [<fix-prefix>]}"
WT="${2:?usage: remove-step-worktree.sh <repo> <worktree> <branch> [<fix-prefix>]}"
BRANCH="${3:?usage: remove-step-worktree.sh <repo> <worktree> <branch> [<fix-prefix>]}"
FIXES="${4:-}"
DEFAULT="$(git -C "$REPO" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
case "$BRANCH" in "${DEFAULT:-main}"|main|master|"") echo "refusing to remove $BRANCH" >&2; exit 2 ;; esac

if [[ -d "$WT" ]]; then
  if [[ -n "${FACTORY_CLEANUP:-}" ]]; then
    WT="$WT" bash -c "$FACTORY_CLEANUP" || echo "cleanup block exited $? — removing the worktree anyway" >&2
  fi
  git -C "$REPO" worktree remove --force "$WT"
fi

delete_remote() {
  local b="$1" origin
  origin="$(git -C "$REPO" remote get-url origin)"
  if [[ -z "$(gh pr list --repo "$origin" --head "$b" --state merged --json number --jq '.[].number' 2>/dev/null)" ]] \
     && [[ -n "$(gh pr list --repo "$origin" --base "$b" --state open --json number --jq '.[].number' 2>/dev/null)" ]]; then
    echo "keeping origin/$b: unmerged, and an open PR is based on it" >&2
    return
  fi
  git -C "$REPO" push origin --delete "$b" 2>/dev/null
}

git -C "$REPO" branch -D "$BRANCH" 2>/dev/null
delete_remote "$BRANCH"
if [[ -n "$FIXES" ]]; then
  for fix in $(git -C "$REPO" for-each-ref --format='%(refname:short)' "refs/heads/$FIXES*"); do
    git -C "$REPO" branch -D "$fix" 2>/dev/null
    delete_remote "$fix"
  done
fi

# The step's review ends with it. review-mode keeps its state per branch in the git common dir
# and counts a marker as stale only while its worktree is missing — so a marker left here would
# come back to life, denying every edit, when a later step recreates the same worktree.
REVIEW="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)/review-mode"
rm -rf -- "${REVIEW:?}/${BRANCH//\//__}"
[[ -n "$FIXES" ]] && rm -rf -- "${REVIEW:?}/${FIXES//\//__}"*

git -C "$REPO" worktree prune
exit 0
