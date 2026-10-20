#!/usr/bin/env python3
"""PreToolUse hook on `Agent`: a dispatch of this plugin's agents gets a generated task message.

The main agent names the agent and passes a few `key: value` lines; this hook replaces the whole
prompt with `reviewer-inputs.py`'s output. Whatever else the dispatch said — a summary of the
change, what earlier rounds fixed, where to look — never reaches the agent: in replays of real
rounds that framing is what made the test reviewer miss what it found from the bare template.

Keys read from the dispatch prompt (anything else is dropped):
    worktree:      required — the worktree to review (step 4: the mutation copy)
    base:          a re-review round's `Reviewed at` sha; omitted → merge-base with the base branch
    spec:          the feature's spec, relative to the worktree; omitted → no spec
    test_command:  required for mutation-tester — the targeted test command, one line
"""

import json
import re
import subprocess
import sys
from pathlib import Path

AGENTS = {"pre-pr-review:architecture-reviewer", "pre-pr-review:test-reviewer", "pre-pr-review:mutation-tester"}
KEYS = ("worktree", "base", "spec", "test_command")
INPUTS = Path(__file__).resolve().parent / "reviewer-inputs.py"
FORMAT = (
    "Dispatch this plugin's agents with a prompt of `key: value` lines only — worktree: <path> "
    "(required), base: <sha> (re-review rounds), spec: <path relative to the worktree>, "
    "test_command: <one line> (mutation-tester, required). The prompt is replaced by a generated "
    "input; anything else in it is dropped."
)


def respond(decision: str, **extra: object) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, **extra}}))
    sys.exit(0)


def main() -> None:
    event = json.load(sys.stdin)
    tool_input = event.get("tool_input") or {}
    agent = tool_input.get("subagent_type", "")
    if agent not in AGENTS:
        sys.exit(0)

    given = {}
    for line in (tool_input.get("prompt") or "").splitlines():
        if m := re.match(r"^\s*[-*]?\s*`?(\w+)`?\s*:\s*`?(.+?)`?\s*$", line):
            key = m.group(1).lower()
            if key in KEYS:
                given[key] = m.group(2)
    if "worktree" not in given:
        respond("deny", permissionDecisionReason=f"{agent}: no `worktree:` line. {FORMAT}")
    if agent == "pre-pr-review:mutation-tester" and "test_command" not in given:
        respond("deny", permissionDecisionReason=f"{agent}: no `test_command:` line. {FORMAT}")

    cmd = [sys.executable, str(INPUTS), "--worktree", given["worktree"]]
    for key in ("base", "spec", "test_command"):
        if key in given:
            cmd += [f"--{key.replace('_', '-')}", given[key]]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        respond("deny", permissionDecisionReason=f"{agent}: {out.stderr.strip()}. {FORMAT}")
    respond("allow", updatedInput={**tool_input, "prompt": out.stdout})


if __name__ == "__main__":
    main()
