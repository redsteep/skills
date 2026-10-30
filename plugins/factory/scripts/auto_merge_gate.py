#!/usr/bin/env python3
"""PreToolUse(Bash) hook: the only way a factory worker merges is the command its profile
declares, on a PR that passes the profile's `## Auto-merge` gate. Every other merge route is denied.

The gate is two things the project owns: the flags the merge must carry (`Merge command`) and a
command that must exit 0 first (`Precondition`) -- whatever "safe to merge right now" means in that
project, said in its own terms. The hook keeps only what no project may relax: no merge through
`gh api`, no push to the base branch, no `--admin`, one PR number, no shell metacharacters, the
factory label, no PR stacked on this one, a `Triage:` paragraph, and the excluded paths.

**Merge on LGTM** is not auto-merge: it is the developer's merge, run by the worker. With the
profile's `## Merge on LGTM` enabled, the developer's own LGTM in the worker's conversation lets
the worker run the merge past what its own judgement never may: the excluded paths, the
`Triage:` paragraph, and a stacked PR (with `--merge`, a merge commit, instead of `--squash`). It is read from the
session transcript at merge time -- only a message the developer typed counts (origin `human`,
never the session's first, which is the dispatcher's start prompt), and only when it is newer
than the PR's head commit: a push after the LGTM needs another look.

A worker may force-push, with a lease, only to its own factory branch: it rebases on main to
resolve a conflict. Everything else stays denied -- the runner deny list's force-push rule is
lifted for workers so that this hook, which can tell the two apart, decides.

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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import BRANCH_PREFIX, Profile, developer_messages, run  # noqa: E402

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
    head_committed: str = ""           # the head commit's ISO committer date
    ci_failed: bool = False            # a check on the head commit concluded in failure


DEFAULT_MERGE = "gh pr merge --auto --squash"


@dataclass(frozen=True)
class Gate:
    required_args: tuple[str, ...]     # flags the merge command must carry, from `Merge command`
    precondition: str                  # shell command that must exit 0; "" = none
    excluded: tuple[str, ...]          # fnmatch globs; a trailing / means "anything under"
    required_label: str = "factory"
    lgtm_merge: bool = False           # `## Merge on LGTM` enabled: the developer's LGTM merges

    @classmethod
    def from_profile(cls, profile: Profile) -> "Gate":
        declared = profile.get("Auto-merge", "Merge command", DEFAULT_MERGE) or DEFAULT_MERGE
        args = [a for a in shlex.split(declared)[3:] if a.startswith("-")]
        return cls(tuple(args),
                   profile.get("Auto-merge", "Precondition", "") or "",
                   tuple(profile.items("Auto-merge")),
                   profile.get("GitHub", "Label", "factory") or "factory",
                   (profile.get("Merge on LGTM", "Enabled", "") or "").strip("`").lower() == "yes")

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


_HOLD = re.compile(r"\b(don'?t|do not|not yet|wait|hold)\b|\bnot\s+lgtm\b", re.I)
_APPROVE = re.compile(r"\blgtm\b|\bmerge\b", re.I)
_NUMBER = re.compile(r"#(\d+)")


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def approval_failed(messages: list[tuple[str, str]], number: str, diff: Diff) -> str | None:
    """Why the developer's word does not cover merging PR `number` at its current head, or None.
    The latest message that says either way decides: an LGTM (or "merge"), or a hold."""
    for stamp, text in reversed(messages):
        named = _NUMBER.findall(text)
        if named and number not in named:
            continue
        if _HOLD.search(text):
            return "your latest word on it is a hold"
        if not _APPROVE.search(text) or text.rstrip().endswith("?"):
            continue
        if diff.head_committed and stamp and _when(stamp) < _when(diff.head_committed):
            return "a commit was pushed after your LGTM — look again"
        if diff.ci_failed:
            return "CI failed on the head commit"
        return None
    return "no LGTM from the developer in this conversation"


def precondition_failed(gate: Gate, number: str, repo: Path, on_lgtm: bool = False) -> str | None:
    """The project's own "safe to merge right now" check. Its output is the reason, so a project
    says why in its own words; a non-zero exit with no output still denies."""
    if not gate.precondition:
        return None
    # `FACTORY_LGTM` is how the command learns which merge this is. The hook waives its own
    # excluded paths on an LGTM, and a project that moved that list into its Precondition has to be
    # told, or the ban comes back through the back door and the developer's word means nothing.
    # What the command must still refuse on an LGTM is its own business — a red CI, a deploy of the
    # base branch already running — and only it knows those.
    env = {**os.environ, "FACTORY_LGTM": "1" if on_lgtm else ""}
    try:
        out = subprocess.run(["bash", "-c", gate.precondition.replace("<number>", number)],
                             cwd=repo, capture_output=True, text=True, timeout=90, env=env)
    except subprocess.TimeoutExpired:
        return "precondition timed out"
    if out.returncode == 0:
        return None
    said = (out.stdout or out.stderr or "").strip().splitlines()
    return said[-1] if said else f"precondition exited {out.returncode}"


FORCE = re.compile(r"\bgit\s+push\b.*(\s--force\b|\s--force-with-lease\b|\s-f\b|\s\+\S)")


def force_push(command: str, current_branch) -> tuple[str, str] | None:
    """A worker may force-push its own factory branch, with a lease, and nothing else: a rebase
    on main is how it resolves a conflict. An adopted PR's branch is someone else's -- a merge."""
    if not FORCE.search(command):
        return None
    if re.search(r"[;&|`$]", command):
        return "deny", "run `git push --force-with-lease [origin <branch>]` as a command of its own"
    args = shlex.split(command)[2:]
    flags = [a for a in args if a.startswith("-")]
    rest = [a for a in args if not a.startswith("-")]
    if flags != ["--force-with-lease"] or len(rest) > 2 or (rest and rest[0] != "origin"):
        return "deny", "the only force-push is `git push --force-with-lease [origin <branch>]`"
    branch = rest[1] if len(rest) == 2 else current_branch()
    if not branch.startswith(BRANCH_PREFIX):
        return "deny", f"`{branch}` is not a factory branch — merge `origin/main` into it instead of rebasing"
    return "allow", f"force-push with lease to the worker's own branch `{branch}`"


def judge(command: str, fetch_diff, gate: Gate, repo: Path = Path("."),
          messages=lambda: [], current_branch=lambda: "") -> tuple[str, str] | None:
    """(decision, reason) for a factory worker's Bash command; None = not a merge, no opinion.
    `messages` returns the developer's messages in this session (only read for an LGTM merge)."""
    if PUSH_MAIN.search(command):
        return "deny", "factory workers never push to main"
    pushed = force_push(command, current_branch)
    if pushed:
        return pushed
    if re.search(r"\bgh\s+api\b", command) and MERGE_API.search(command):
        return "deny", f"merging through `gh api` is not allowed — use `{gate.shape}`"
    m = re.search(r"\bgh\s+pr\s+merge\b(.*)", command)
    if not m:
        return None
    if re.search(r"[;&|`$]", command):
        return "deny", f"run `{gate.shape}` as a command of its own"
    args = shlex.split(m[1])
    # A PR another one is stacked on merges with a merge commit, never a squash: only on an LGTM.
    merge_commit = "--merge" in args
    required = [("--merge" if a == "--squash" else a) for a in gate.required_args] if merge_commit \
        else gate.required_args
    missing = [a for a in required if a not in args]
    if missing or {"--admin", "--delete-branch", "-d"} & set(args) or (merge_commit and "--squash" in args) \
            or (merge_commit and not gate.lgtm_merge):
        return "deny", f"the only allowed merge is `{gate.shape}`"
    numbers = [a for a in args if a.isdigit()]
    if len(numbers) != 1:
        return "deny", f"name the PR number explicitly: `{gate.shape}`"
    diff = fetch_diff(numbers[0])
    rule = failed_rule(diff, gate)
    on_lgtm = bool(rule) or merge_commit
    if on_lgtm:
        if not gate.lgtm_merge or gate.required_label not in diff.labels:
            return "deny", f"auto-merge gate: {rule}. Take the review path instead."
        if merge_commit and not diff.stacked:
            return "deny", f"no PR is stacked on #{numbers[0]} — merge it with `{gate.shape}`"
        refused = approval_failed(messages(), numbers[0], diff)
        if refused:
            return "deny", f"merge on LGTM: {refused}."
    rule = precondition_failed(gate, numbers[0], repo, on_lgtm)
    if rule:
        return "deny", (f"merge on LGTM: {rule}." if on_lgtm
                        else f"auto-merge gate: {rule}. Take the review path instead.")
    if on_lgtm:
        return "allow", f"merging PR #{numbers[0]} on the developer's LGTM"
    return "allow", f"auto-merge gate passed for PR #{numbers[0]}"


def _fetch_diff(number: str) -> Diff:
    data = json.loads(run(["gh", "pr", "view", number, "--json",
                           "additions,deletions,files,labels,body,headRefName,commits,statusCheckRollup"]))
    stacked = json.loads(run(["gh", "pr", "list", "--base", data["headRefName"], "--state", "open",
                              "--json", "number"]) or "[]")
    return Diff(data["additions"], data["deletions"], tuple(f["path"] for f in data["files"]),
                tuple(l["name"] for l in data["labels"]), data.get("body") or "",
                tuple(p["number"] for p in stacked),
                (data.get("commits") or [{}])[-1].get("committedDate", ""),
                any((c.get("conclusion") or "").upper() in ("FAILURE", "TIMED_OUT", "CANCELLED")
                    for c in data.get("statusCheckRollup") or []))


def main() -> int:
    if not os.environ.get("FACTORY_WORKER"):
        return 0
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command", "")
    repo = Path(os.environ.get("FACTORY_REPO") or event.get("cwd") or ".")
    gate = Gate.from_profile(Profile.load(repo))
    transcript = Path(event.get("transcript_path") or "/nonexistent")
    cwd = Path(event.get("cwd") or ".")
    verdict = judge(command, _fetch_diff, gate, repo,
                    lambda: developer_messages(transcript) if transcript.is_file() else [],
                    lambda: run(["git", "symbolic-ref", "--short", "HEAD"], cwd=cwd).strip())
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
