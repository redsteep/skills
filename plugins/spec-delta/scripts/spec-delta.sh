#!/usr/bin/env bash
# PostToolUse(Write|Edit): a design spec must follow the project's spec template.
#
# Two things are checked, both structural: every `##` / `###` section of the
# template is present in the spec, and none of them is left empty. The point of a
# "Delta" in particular is that a diff can be subtracted from a list and never
# from prose, so its subsections are mandatory too. "The surface does not change"
# is valid content — the pre-pr-review skill checks that claim against the diff.
#
# The required sections are read from the template itself, so renaming one is a
# change to the template only.
#
# Configured by `.claude/spec-delta.md` in the project:
#   - **Specs:** `<glob, relative to the repo root>`
#   - **Template:** `<path, relative to the repo root>`
# No profile → the hook does nothing.
set -uo pipefail

payload=$(cat)
file=$(jq -r '.tool_input.file_path // ""' <<<"$payload")
[[ -n "$file" && -f "$file" ]] || exit 0

repo=$(git -C "$(dirname "$file")" rev-parse --show-toplevel 2>/dev/null) || exit 0
profile="$repo/.claude/spec-delta.md"
[[ -f "$profile" ]] || exit 0

setting() { sed -nE "s/^- \*\*$1:\*\* \`([^\`]+)\`.*/\1/p" "$profile" | head -1; }
glob=$(setting Specs)
template=$(setting Template)
[[ -n "$glob" && -n "$template" && -f "$repo/$template" ]] || exit 0

rel=${file#"$repo"/}
# shellcheck disable=SC2053  # the glob is meant to match
[[ "$rel" == $glob ]] || exit 0
# The template itself, and anything named like one (`_*`), is exempt.
[[ "$rel" == "$template" || "$(basename "$file")" == _* ]] && exit 0

# Only specs this branch introduces. Specs written before the template stay
# editable — a "phase 2" appended to a live spec months later must not demand a retrofit.
base=$(git -C "$repo" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null) || base="origin/main"
git -C "$repo" cat-file -e "${base}:${rel}" 2>/dev/null && exit 0

# Required sections: the template's `##` and `###` headings, outside code fences.
mapfile -t required < <(awk '/^```/{f=!f; next} !f && /^###? /{sub(/[[:space:]]+$/, ""); print}' "$repo/$template")
[[ ${#required[@]} -gt 0 ]] || exit 0

missing=()
for h in "${required[@]}"; do
  grep -qxF "$h" <(sed -E 's/[[:space:]]+$//' "$file") || missing+=("$h")
done

# Sections that exist but were left empty.
wanted=$(printf '%s\n' "${required[@]}" | paste -sd'|' -)
empty=$(awk -v want="$wanted" '
  BEGIN { n = split(want, a, "|"); for (i = 1; i <= n; i++) W[a[i]] = 1 }
  /^```/ { fence = !fence; if (sec != "") body = 1; next }
  !fence && /^##/ {
      h = $0; sub(/[[:space:]]+$/, "", h)
      match(h, /^#+/); lvl = RLENGTH
      if (sec != "") {
          # A deeper heading is content for its parent: "## Delta" whose body is
          # only its subsections is filled in, not empty.
          if (lvl > seclvl) body = 1
          if (!body) print sec
      }
      sec = ""; body = 0
      if (h in W) { sec = h; seclvl = lvl }
      next
  }
  sec != "" && NF { body = 1 }
  END { if (sec != "" && !body) print sec }
' "$file")

[[ ${#missing[@]} -eq 0 && -z "$empty" ]] && exit 0

reason="Spec ${rel} does not follow ${template}."
[[ ${#missing[@]} -gt 0 ]] && reason+=$'\n'"Missing sections: $(printf '%s; ' "${missing[@]}")"
[[ -n "$empty" ]] && reason+=$'\n'"Empty sections: $(tr '\n' ';' <<<"$empty")"
reason+=$'\n'"Copy the template and fill it in. The Delta is a list, not prose: one line per name, with its justification from the task. If a surface does not change, say so in one line in that subsection — it is a claim the review checks against the diff."

jq -n --arg r "$reason" '{decision: "block", reason: $r}'
