#!/usr/bin/env python3
"""PreToolUse(Bash) hook: the only way a factory worker merges is `gh pr merge --auto --squash`
on a PR that passes the profile's `## Auto-merge` gate. Every other merge route is denied.

Applies only inside a factory worker (env FACTORY_WORKER, set by the dispatcher). Outside one it
exits 0 silently and the session's normal permissions apply. The worker's judgement can only
downgrade a PR to "needs review" — it never reaches this code with anything but a request.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import Profile, run  # noqa: E402

MERGE_API = re.compile(r"/pulls/\d+/merge\b|mergePullRequest|enablePullRequestAutoMerge|/merges\b")
PUSH_MAIN = re.compile(r"\bgit\s+push\b[^;&|]*\b(main|master)\b")


@dataclass(frozen=True)
class Diff:
    additions: int
    deletions: int
    files: tuple[str, ...]
    labels: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class Gate:
    max_lines: int
    max_files: int
    excluded: tuple[str, ...]          # fnmatch globs; a trailing / means "anything under"
    required_label: str = "factory"

    @classmethod
    def from_profile(cls, profile: Profile) -> "Gate":
        return cls(int(profile.get("Auto-merge", "Max changed lines", "0")),
                   int(profile.get("Auto-merge", "Max files", "0")),
                   tuple(profile.items("Auto-merge")),
                   profile.get("GitHub", "Label", "factory") or "factory")


def failed_rule(diff: Diff, gate: Gate) -> str | None:
    """The first gate rule the diff breaks, or None when it may auto-merge."""
    if gate.required_label not in diff.labels:
        return f"not a factory PR (no `{gate.required_label}` label)"
    if not re.search(r"(?m)^Triage:", diff.body):
        return "no `Triage:` paragraph in the PR description"
    changed = diff.additions + diff.deletions
    if changed > gate.max_lines:
        return f"{changed} changed lines > {gate.max_lines}"
    if len(diff.files) > gate.max_files:
        return f"{len(diff.files)} files > {gate.max_files}"
    for path in diff.files:
        for pattern in gate.excluded:
            hit = path.startswith(pattern) if pattern.endswith("/") else fnmatch.fnmatch(path, pattern)
            if hit:
                return f"`{path}` matches excluded `{pattern}`"
    return None


def judge(command: str, fetch_diff, gate: Gate) -> tuple[str, str] | None:
    """(decision, reason) for a factory worker's Bash command; None = not a merge, no opinion."""
    if PUSH_MAIN.search(command):
        return "deny", "factory workers never push to main"
    if re.search(r"\bgh\s+api\b", command) and MERGE_API.search(command):
        return "deny", "merging through `gh api` is not allowed — use `gh pr merge --auto --squash`"
    m = re.search(r"\bgh\s+pr\s+merge\b(.*)", command)
    if not m:
        return None
    if re.search(r"[;&|`$]", command):
        return "deny", "run `gh pr merge --auto --squash <number>` as a command of its own"
    args = shlex.split(m[1])
    if "--auto" not in args or not ({"--squash", "-s"} & set(args)) or {"--admin", "--delete-branch", "-d"} & set(args):
        return "deny", "the only allowed merge is `gh pr merge --auto --squash <number>`"
    numbers = [a for a in args if a.isdigit()]
    if len(numbers) != 1:
        return "deny", "name the PR number explicitly: `gh pr merge --auto --squash <number>`"
    rule = failed_rule(fetch_diff(numbers[0]), gate)
    if rule:
        return "deny", f"auto-merge gate: {rule}. Take the review path instead."
    return "allow", f"auto-merge gate passed for PR #{numbers[0]}"


def _fetch_diff(number: str) -> Diff:
    data = json.loads(run(["gh", "pr", "view", number, "--json", "additions,deletions,files,labels,body"]))
    return Diff(data["additions"], data["deletions"], tuple(f["path"] for f in data["files"]),
                tuple(l["name"] for l in data["labels"]), data.get("body") or "")


def main() -> int:
    if not os.environ.get("FACTORY_WORKER"):
        return 0
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command", "")
    repo = Path(os.environ.get("FACTORY_REPO") or event.get("cwd") or ".")
    gate = Gate.from_profile(Profile.load(repo))
    verdict = judge(command, _fetch_diff, gate)
    if verdict is None:
        return 0
    decision, reason = verdict
    if decision == "allow":
        number = re.findall(r"\d+", command.split("merge", 1)[1])[0]
        run(["gh", "pr", "edit", number, "--add-label", "factory:auto-merged"], check=False)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
