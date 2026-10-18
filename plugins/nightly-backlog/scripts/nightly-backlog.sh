#!/usr/bin/env bash
# Unattended night run: one tech-debt backlog item → one PR (see commands/nightly-backlog.md).
#
# Meant for a timer on the developer's own machine: a cloud routine would see only what is
# in git, and lose memory, user-level plugins, local test stacks and worktree tooling.
#
# Usage:
#   nightly-backlog.sh <repo>          # pick an allowed item
#   nightly-backlog.sh <repo> <item>   # force one item (dry run by hand)
#
# Env:
#   NIGHTLY_BUDGET_USD   spend cap for the run (default 40)
#   NIGHTLY_TIMEOUT      wall-clock cap, timeout(1) syntax (default 3h)
#   NIGHTLY_DIR          logs + reports (default <git common dir>/nightly)
#   NIGHTLY_PERMISSION_MODE   claude --permission-mode (default auto)
#
# The profile (.claude/nightly-backlog.md) feeds the runner three sections:
#   ## Before  — a ```bash block run before the session (housekeeping); failure is logged, not fatal
#   ## Deny    — extra --disallowedTools rules, one backticked rule per bullet
#   ## Notify  — `- **When:** failure, questions, stuck` (tokens: failure questions stuck pr quiet always)
#                and a ```bash block that gets the report on stdin and
#                NIGHTLY_SUBJECT / NIGHTLY_STATUS / NIGHTLY_RC / NIGHTLY_REPORT / NIGHTLY_LOGS in env
#
# The repo must have the nightly-backlog plugin enabled (its .claude/settings.json),
# so that `/nightly-backlog` resolves in the headless session.

set -euo pipefail

REPO="$(cd "${1:?usage: nightly-backlog.sh <repo> [item]}" && pwd)"
ISSUE="${2:-}"
GITDIR="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)"
LOG_DIR="${NIGHTLY_DIR:-$GITDIR/nightly}"
mkdir -p "$LOG_DIR"
STAMP="$(date +%F-%H%M)"
REPORT="$LOG_DIR/$(date +%F).md"

# One run at a time — a slow night must not overlap with the next one.
exec 9>"$LOG_DIR/.lock"
flock -n 9 || { echo "nightly-backlog: previous run still active" >&2; exit 0; }

cd "$REPO"

# Everything the agent must not do unattended. Hooks and the permission mode are the
# other two layers; this one does not depend on the model's judgement.
DENY=(
  "Bash(git push origin main:*)"
  "Bash(git push origin master:*)"
  "Bash(git push -f:*)"
  "Bash(git push --force:*)"
  "Bash(gh pr merge:*)"
  "Bash(gh issue edit:*)"
  "Bash(gh issue close:*)"
  "Bash(gh issue comment:*)"
  "Bash(gh label:*)"
  "Bash(gh workflow:*)"
  "Bash(gh secret:*)"
  "Bash(aws:*)"
  "Bash(gcloud:*)"
  "Bash(az:*)"
  "Bash(kubectl:*)"
  "Bash(terraform:*)"
  "Bash(ssh:*)"
)

PROFILE="$REPO/.claude/nightly-backlog.md"

# Body of a `## <name>` section of the profile.
section() { [[ -f "$PROFILE" ]] && awk -v want="## $1" '/^## /{on = ($0 == want); next} on' "$PROFILE"; }
# The first ```bash block of a section.
code_block() { section "$1" | awk '/^```/{ if (on) exit; on = 1; next } on'; }

# --- Before: housekeeping the agent should not be trusted to improvise -----------
BEFORE_LOG="$LOG_DIR/$STAMP.before.log"
BEFORE="$(code_block Before || true)"
if [[ -n "$BEFORE" ]]; then
  timeout 10m bash -c "$BEFORE" > "$BEFORE_LOG" 2>&1 \
    || echo "before: exited with $? — see $BEFORE_LOG" >> "$BEFORE_LOG"
fi

# Project additions: backticked rules under "## Deny" in the profile, one per bullet.
if [[ -f "$PROFILE" ]]; then
  while IFS= read -r rule; do
    [[ -n "$rule" ]] && DENY+=("$rule")
  done < <(awk '/^## /{on = ($0 ~ /^## Deny[[:space:]]*$/); next} on && /^- `/' "$PROFILE" \
           | sed -E 's/^- `([^`]+)`.*/\1/')
fi

RUN_RC=0
timeout --kill-after=2m "${NIGHTLY_TIMEOUT:-3h}" \
  claude -p "/nightly-backlog report=$REPORT${BEFORE:+ before=$BEFORE_LOG} $ISSUE" \
    --permission-mode "${NIGHTLY_PERMISSION_MODE:-auto}" \
    --disallowedTools "${DENY[@]}" \
    --max-budget-usd "${NIGHTLY_BUDGET_USD:-40}" \
    --output-format stream-json --verbose \
  > "$LOG_DIR/$STAMP.jsonl" 2> "$LOG_DIR/$STAMP.stderr" \
  || { RUN_RC=$?; echo "nightly-backlog: exited with $RUN_RC — see $LOG_DIR/$STAMP.*" >&2; }

# --- Notify: only when there is something to tell -------------------------------
# Silence must not mean both "quiet success" and "died", so a failure always
# counts. The command runs here, outside the session: the agent itself holds no
# messaging tools.
NOTIFY="$(code_block Notify || true)"
[[ -n "$NOTIFY" ]] || exit 0
WHEN="$(section Notify | sed -nE 's/^- \*\*When:\*\*[[:space:]]*(.*)$/\1/p' | head -1)"
WHEN="${WHEN:-failure, questions, stuck}"

STATUS="failure"
if [[ "$RUN_RC" -eq 0 && -f "$REPORT" ]]; then
  # `# Night <date> — <status>`: the last word of the first line.
  STATUS="$(head -1 "$REPORT" | awk '{print $NF}')"
  [[ "$STATUS" =~ ^(pr|questions|stuck|quiet)$ ]] || STATUS="questions"   # unreadable → someone should look
fi
grep -qwE "always|$STATUS" <<<"$WHEN" || exit 0

SUBJECT="[nightly] $(basename "$REPO") $(date +%F) — $STATUS"
[[ "$RUN_RC" -ne 0 ]] && SUBJECT="$SUBJECT (rc=$RUN_RC)"
{ [[ -f "$REPORT" ]] && cat "$REPORT" || echo "No report: the run exited with $RUN_RC. Logs: $LOG_DIR/$STAMP.*"; } \
  | NIGHTLY_SUBJECT="$SUBJECT" NIGHTLY_STATUS="$STATUS" NIGHTLY_RC="$RUN_RC" \
    NIGHTLY_REPORT="$REPORT" NIGHTLY_LOGS="$LOG_DIR/$STAMP" \
    timeout 5m bash -c "$NOTIFY" >> "$LOG_DIR/$STAMP.notify.log" 2>&1 \
  || echo "nightly-backlog: notify failed — report still at $REPORT" >&2
