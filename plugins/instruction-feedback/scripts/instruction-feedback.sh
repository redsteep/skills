#!/usr/bin/env bash
# UserPromptSubmit: when a message reads as a correction to the implementation,
# remind the model to propose an amendment to the instructions the implementer
# and the reviewer read — not only to fix the code at hand.
#
# Where each kind of lesson belongs is project-specific: the project lists it in
# `.claude/instruction-feedback.md`; without one, a generic map is used.
#
# The markers stay narrow so the hook does not fire every turn; widen them from
# transcripts, not by guessing.
set -uo pipefail

payload=$(cat)
prompt=$(jq -r '.prompt // .user_prompt // .message // .content // empty' <<<"$payload" 2>/dev/null) || prompt=""
# Fall back to the whole event if the field is missing.
[[ -z "$prompt" ]] && prompt="$payload"

markers='why did you|why is this|no need|don.t need|remove (this|that|it)|revert|not what i|didn.t ask|over-?engineer|unnecessary'

project="${CLAUDE_PROJECT_DIR:-$PWD}"
map_file="$project/.claude/instruction-feedback.md"
# The profile may add markers in the project's own language:
#   - **Markers:** `зачем|не надо|убери`
if [[ -f "$map_file" ]]; then
  extra=$(sed -nE 's/^- \*\*Markers:\*\* `([^`]+)`.*/\1/p' "$map_file" | head -1)
  [[ -n "$extra" ]] && markers="$markers|$extra"
fi
grep -qiE "$markers" <<<"$prompt" || exit 0

if [[ -f "$map_file" ]]; then
  # The file's body, minus its title line, HTML comments and the markers line.
  map=$(sed '1{/^# /d}' "$map_file" | sed '/<!--/,/-->/d' | sed -E '/^- \*\*Markers:\*\*/d' | sed '/./,$!d')
else
  read -r -d '' map <<'TXT' || true
- a project convention (code, tests, layering) → the instructions file the project loads (CLAUDE.md / AGENTS.md), or the guidelines it imports
- process and the user's preferences → memory
TXT
fi

note="This message reads like a correction to the implementation. Besides the fix itself, end the reply with ONE line about the instructions: either a concrete proposed amendment (file + wording), or \"one-off, no rule follows\". Propose, do not amend silently, and do not grow it into a section.

Where to look, by kind of lesson:
$map"

jq -n --arg c "$note" '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $c
  }
}'
