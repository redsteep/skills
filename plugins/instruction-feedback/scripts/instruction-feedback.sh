#!/usr/bin/env bash
# UserPromptSubmit: when a message reads as a correction to the implementation,
# remind the model to propose an amendment to the instructions the implementer
# and the reviewer read — not only to fix the code at hand.
#
# Three parts, each overridable from the project's `.claude/instruction-feedback.md`:
#   ## Markers  — regexes, one per backticked bullet; `- **Mode:** replace` drops
#                 the built-in English ones (default: extend them)
#   ## Reply    — what the model is told to do (default: the English note below)
#   ## Map      — where each kind of lesson goes (default: a generic map)
# A profile without these headings is read whole as the map (the 0.1 format).
#
# The markers stay narrow so the hook does not fire every turn; widen them from
# transcripts, not by guessing.
set -uo pipefail

payload=$(cat)
prompt=$(jq -r '.prompt // .user_prompt // .message // .content // empty' <<<"$payload" 2>/dev/null) || prompt=""
# Fall back to the whole event if the field is missing.
[[ -z "$prompt" ]] && prompt="$payload"

markers='why did you|why is this|no need|don.t need|remove (this|that|it)|revert|not what i|didn.t ask|over-?engineer|unnecessary'
reply="This message reads like a correction to the implementation. Besides the fix itself, end the reply with ONE line about the instructions: either a concrete proposed amendment (file + wording), or \"one-off, no rule follows\". Propose, do not amend silently, and do not grow it into a section."
map="- a project convention (code, tests, layering) → the instructions file the project loads (CLAUDE.md / AGENTS.md), or the guidelines it imports
- process and the user's preferences → memory"

project="${CLAUDE_PROJECT_DIR:-$PWD}"
profile="$project/.claude/instruction-feedback.md"

# Body of a `## <name>` section, HTML comments stripped, blank edges trimmed.
# A one-line comment is dropped first: a sed range would run past its own end.
strip_comments() { sed -e 's/<!--.*-->//' -e '/<!--/,/-->/d' "$1"; }

section() {
  strip_comments "$profile" \
    | awk -v want="## $1" '/^## /{on = ($0 == want); next} on' \
    | sed '/./,$!d' | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
}

if [[ -f "$profile" ]]; then
  if grep -qE '^## (Markers|Reply|Map)[[:space:]]*$' "$profile"; then
    extra=$(section Markers | sed -nE 's/^- `([^`]+)`.*/\1/p' | paste -sd'|' -)
    if [[ -n "$extra" ]]; then
      if section Markers | grep -qiE '^- \*\*Mode:\*\*[[:space:]]*replace'; then
        markers="$extra"
      else
        markers="$markers|$extra"
      fi
    fi
    r=$(section Reply); [[ -n "$r" ]] && reply="$r"
    m=$(section Map);   [[ -n "$m" ]] && map="$m"
  else
    # 0.1 format: the whole body, minus its title line and comments, is the map.
    map=$(strip_comments "$profile" | sed '1{/^# /d}' | sed '/./,$!d')
  fi
fi

grep -qiE "$markers" <<<"$prompt" || exit 0

note="$reply

Where to look, by kind of lesson:
$map"

jq -n --arg c "$note" '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $c
  }
}'
