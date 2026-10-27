#!/usr/bin/env python3
"""PreToolUse(Bash) hook: the only way a factory worker merges is the command its profile
declares, on a PR that passes the profile's `## Auto-merge` gate. Every other merge route is denied.

The gate is two things the project owns: the flags the merge must carry (`Merge command`) and a
command that must exit 0 first (`Precondition`) -- whatever "safe to merge right now" means in that
project, said in its own terms. The hook keeps only what no project may relax: no merge through
`gh api`, no push to the base branch, no `--admin`, one PR number, no shell metacharacters, the
factory label, no PR stacked on this one, a `Triage:` paragraph, and the excluded paths.

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
import subprocess
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
    stacked: tuple[int, ...] = ()      # open PRs based on this PR's branch


DEFAULT_MERGE = "gh pr merge --auto --squash"


@dataclass(frozen=True)
class Gate:
    required_args: tuple[str, ...]     # flags the merge command must carry, from `Merge command`
    precondition: str                  # shell command that must exit 0; "" = none
    excluded: tuple[str, ...]          # fnmatch globs; a trailing / means "anything under"
    required_label: str = "factory"

    @classmethod
    def from_profile(cls, profile: Profile) -> "Gate":
        declared = profile.get("Auto-merge", "Merge command", DEFAULT_MERGE) or DEFAULT_MERGE
        args = [a for a in shlex.split(declared)[3:] if a.startswith("-")]
        return cls(tuple(args),
                   profile.get("Auto-merge", "Precondition", "") or "",
                   tuple(profile.items("Auto-merge")),
                   profile.get("GitHub", "Label", "factory") or "factory")

    @property
    def shape(self) -> str:
        return " ".join(("gh pr merge", *self.required_args, "<number>"))


def failed_rule(diff: Diff, gate: Gate) -> str | None:
    """The first gate rule the diff breaks, or None when it may auto-merge."""
    if gate.required_label not in diff.labels:
        return f"not a factory PR (no `{gate.required_label}` label)"
    if diff.stacked:
        above = ", ".join(f"#{n}" for n in diff.stacked)
        return f"{above} stacked on it — the developer merges it with a merge commit"
    if not re.search(r"(?m)^Triage:", diff.body):
        return "no `Triage:` paragraph in the PR description"
    for path in diff.files:
        for pattern in gate.excluded:
            hit = path.startswith(pattern) if pattern.endswith("/") else fnmatch.fnmatch(path, pattern)
            if hit:
                return f"`{path}` matches excluded `{pattern}`"
    return None


def precondition_failed(gate: Gate, number: str, repo: Path) -> str | None:
    """The project's own "safe to merge right now" check. Its output is the reason, so a project
    says why in its own words; a non-zero exit with no output still denies."""
    if not gate.precondition:
        return None
    try:
        out = subprocess.run(["bash", "-c", gate.precondition.replace("<number>", number)],
                             cwd=repo, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return "precondition timed out"
    if out.returncode == 0:
        return None
    said = (out.stdout or out.stderr or "").strip().splitlines()
    return said[-1] if said else f"precondition exited {out.returncode}"


def judge(command: str, fetch_diff, gate: Gate, repo: Path = Path(".")) -> tuple[str, str] | None:
    """(decision, reason) for a factory worker's Bash command; None = not a merge, no opinion."""
    if PUSH_MAIN.search(command):
        return "deny", "factory workers never push to main"
    if re.search(r"\bgh\s+api\b", command) and MERGE_API.search(command):
        return "deny", f"merging through `gh api` is not allowed — use `{gate.shape}`"
    m = re.search(r"\bgh\s+pr\s+merge\b(.*)", command)
    if not m:
        return None
    if re.search(r"[;&|`$]", command):
        return "deny", f"run `{gate.shape}` as a command of its own"
    args = shlex.split(m[1])
    missing = [a for a in gate.required_args if a not in args]
    if missing or {"--admin", "--delete-branch", "-d"} & set(args):
        return "deny", f"the only allowed merge is `{gate.shape}`"
    numbers = [a for a in args if a.isdigit()]
    if len(numbers) != 1:
        return "deny", f"name the PR number explicitly: `{gate.shape}`"
    rule = failed_rule(fetch_diff(numbers[0]), gate)
    if rule:
        return "deny", f"auto-merge gate: {rule}. Take the review path instead."
    rule = precondition_failed(gate, numbers[0], repo)
    if rule:
        return "deny", f"auto-merge gate: {rule}. Take the review path instead."
    return "allow", f"auto-merge gate passed for PR #{numbers[0]}"


def _fetch_diff(number: str) -> Diff:
    data = json.loads(run(["gh", "pr", "view", number, "--json",
                           "additions,deletions,files,labels,body,headRefName"]))
    stacked = json.loads(run(["gh", "pr", "list", "--base", data["headRefName"], "--state", "open",
                              "--json", "number"]) or "[]")
    return Diff(data["additions"], data["deletions"], tuple(f["path"] for f in data["files"]),
                tuple(l["name"] for l in data["labels"]), data.get("body") or "",
                tuple(p["number"] for p in stacked))


def main() -> int:
    if not os.environ.get("FACTORY_WORKER"):
        return 0
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command", "")
    repo = Path(os.environ.get("FACTORY_REPO") or event.get("cwd") or ".")
    gate = Gate.from_profile(Profile.load(repo))
    verdict = judge(command, _fetch_diff, gate, repo)
    if verdict is None:
        return 0
    decision, reason = verdict
    # The `factory:auto-merged` label is the worker's to add after the command returns: a hook that
    # runs before it cannot know whether the merge happened, and every denied attempt used to leave
    # the label behind.
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
