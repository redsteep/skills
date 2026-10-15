#!/usr/bin/env bash
# Unattended night run: one tech-debt GitHub issue → one draft PR (see commands/nightly-backlog.md).
#
# Meant for a timer on the developer's own machine: a cloud routine would see only what is
# in git, and lose memory, user-level plugins, local test stacks and worktree tooling.
#
# Usage:
#   nightly-backlog.sh <repo>          # pick an issue labelled nightly:ok
#   nightly-backlog.sh <repo> 331      # force one issue (dry run by hand)
#
# Env:
#   NIGHTLY_BUDGET_USD   spend cap for the run (default 40)
#   NIGHTLY_TIMEOUT      wall-clock cap, timeout(1) syntax (default 3h)
#   NIGHTLY_DIR          logs + reports (default <git common dir>/nightly)
#   NIGHTLY_PERMISSION_MODE   claude --permission-mode (default auto)
#
# The repo must have the nightly-backlog plugin enabled (its .claude/settings.json),
# so that `/nightly-backlog` resolves in the headless session.

set -euo pipefail

REPO="$(cd "${1:?usage: nightly-backlog.sh <repo> [issue]}" && pwd)"
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

# Project additions: backticked rules under "## Deny" in the profile, one per bullet.
PROFILE="$REPO/.claude/nightly-backlog.md"
if [[ -f "$PROFILE" ]]; then
  while IFS= read -r rule; do
    [[ -n "$rule" ]] && DENY+=("$rule")
  done < <(awk '/^## /{on = ($0 ~ /^## Deny[[:space:]]*$/); next} on && /^- `/' "$PROFILE" \
           | sed -E 's/^- `([^`]+)`.*/\1/')
fi

timeout --kill-after=2m "${NIGHTLY_TIMEOUT:-3h}" \
  claude -p "/nightly-backlog report=$REPORT $ISSUE" \
    --permission-mode "${NIGHTLY_PERMISSION_MODE:-auto}" \
    --disallowedTools "${DENY[@]}" \
    --max-budget-usd "${NIGHTLY_BUDGET_USD:-40}" \
    --output-format stream-json --verbose \
  > "$LOG_DIR/$STAMP.jsonl" 2> "$LOG_DIR/$STAMP.stderr" \
  || echo "nightly-backlog: exited with $? — see $LOG_DIR/$STAMP.*" >&2
