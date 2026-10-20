#!/usr/bin/env bash
# PostToolUse(Write|Edit): a new design spec has just been written → run the proposal review now.
#
# The review belongs between "spec written" and "spec committed", a moment nobody announces:
# left to the skill's description it was skipped, because the user's next words are "commit it"
# or "let's implement", not "review the design". So the hook names the moment instead.
#
# Fires once per spec per worktree: the review's own edits (findings applied, `### Rejected`
# filled in) must not start another review. Only specs this branch introduces — a spec already
# on the base branch was reviewed, or predates the skill.
#
# Configured by `.claude/design-review.md` in the project:
#   - **Specs live in:** `<glob, relative to the repo root>`
# No profile → the hook does nothing.
set -uo pipefail

payload=$(cat)
file=$(jq -r '.tool_input.file_path // ""' <<<"$payload")
[[ -n "$file" && -f "$file" ]] || exit 0

repo=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) || exit 0
profile="$repo/.claude/design-review.md"
[[ -f "$profile" ]] || exit 0

glob=$(sed -nE 's/^- \*\*Specs live in:\*\* `([^`]+)`.*/\1/p' "$profile" | head -1)
[[ -n "$glob" ]] || exit 0

rel=${file#"$repo"/}
# shellcheck disable=SC2053  # the glob is meant to match
[[ "$rel" == $glob ]] || exit 0
[[ "$(basename "$file")" == _* ]] && exit 0

base=$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || base="origin/main"
git -C "$repo" cat-file -e "${base}:${rel}" 2>/dev/null && exit 0

# Per worktree: `--git-path` resolves inside .git/worktrees/<name>/ for a linked worktree.
state=$(git -C "$repo" rev-parse --path-format=absolute --git-path design-review 2>/dev/null) || exit 0
marker="$state/$(basename "$rel").started"
[[ -e "$marker" ]] && exit 0
mkdir -p "$state" && : >"$marker"

context="A new design spec was just written: ${rel}. Run the design-review skill on it now, in proposal mode — once the spec passes its template check, before presenting it as ready, before committing it, and before writing any code for it. Do not wait to be asked. Findings go to the user, not into the spec unasked."
jq -n --arg c "$context" '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $c}}'
