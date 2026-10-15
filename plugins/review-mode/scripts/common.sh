# Sourced by the review-mode scripts: where the mode keeps its state.
#
# State lives in the git common dir, not the working tree: it is never committed,
# needs no .gitignore entry, and every worktree of the repo sees the same marker —
# a session started in the main checkout and one started inside a worktree agree
# on whether review is on.

project="${CLAUDE_PROJECT_DIR:-$PWD}"
gitdir=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || gitdir=""
state="${gitdir:+$gitdir/review-mode}"
marker="$state/marker.json"
queue="$state/queue.md"
