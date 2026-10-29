#!/usr/bin/env python3
"""UserPromptSubmit hook: the developer's message in a worker's conversation puts its PR in
review mode.

Review mode protects a conversation the developer is in: what they read stays put, and what they
ask for is queued, not done mid-read. While they are away there is nothing to protect, so a
worker opens its PR without it and keeps the PR healthy on its own (conflicts, migration heads,
red CI). Their first message turns it on; the dispatcher turns it off again after `Review idle`
minutes of silence, and the worker applies what they queued as if they had said go.

Only a message the developer typed counts: not a peer session's message, a task notice, or the
dispatcher's start prompt. Applies only inside a factory worker (env FACTORY_WORKER), and only
when the worktree's branch has an open PR — before the PR there is nothing to review.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import START_PROMPTS, run  # noqa: E402

NOT_TYPED = ("<cross-session-message", "<agent-message", "<task-notification", "Another Claude session sent")
REVIEW_MODE = Path(__file__).resolve().parents[2] / "review-mode/scripts/review-mode.sh"


def typed_by_developer(prompt: str) -> bool:
    text = prompt.lstrip()
    return bool(text) and not text.startswith(START_PROMPTS) and not any(m in prompt for m in NOT_TYPED)


def main() -> int:
    if not os.environ.get("FACTORY_WORKER"):
        return 0
    event = json.load(sys.stdin)
    if not typed_by_developer(event.get("prompt") or ""):
        return 0
    cwd = Path(event.get("cwd") or ".")
    try:
        wt = run(["git", "rev-parse", "--show-toplevel"], cwd=cwd).strip()
        branch = run(["git", "symbolic-ref", "--short", "HEAD"], cwd=cwd).strip()
        common = Path(run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd).strip())
        if (common / "review-mode" / branch.replace("/", "__") / "marker.json").is_file():
            return 0
        if not json.loads(run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"],
                              cwd=cwd) or "[]"):
            return 0
        repo = common.parent
        run(["bash", str(REVIEW_MODE), "on", wt], cwd=cwd, env={"CLAUDE_PROJECT_DIR": str(repo)})
    except Exception as exc:  # a failed lookup must never block the developer's message
        print(f"review presence: {exc}", file=sys.stderr)
        return 0
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "The developer is here: review mode is now on for this PR. Queue their "
                             "change requests; hold upkeep until they say go or leave."}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
