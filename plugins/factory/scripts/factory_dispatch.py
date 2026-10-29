#!/usr/bin/env python3
"""The factory dispatcher: one dispatch = read GitHub, Trello, git and the live workers, decide,
act, exit. Run every couple of minutes by a systemd user timer (see ../systemd/).

    factory_dispatch.py <repo> [--dry-run]

All the routing is in `decide()`, a pure function of the world it is handed — that is what the
tests pin. Everything around it only gathers the world or carries out the actions.
Everything project-specific comes from the repo's `.claude/factory.md` (profile-template.md).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import (  # noqa: E402
    PAUSE_FILE, STATE_DIR, Profile, issue_short, last_developer_message, list_agents, live_workers,
    load_repo_secrets, mark_launched, reviews_on,
    parse_worker_name, run,
    sent_store, split_name, step_branch, step_name,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DROPPED = "[dropped]"

# Step states (spec: "Step state — the one predicate every rule reads").
PENDING, IN_PROGRESS, MERGED, FIXING, DONE, DROPPED_STATE = (
    "pending", "in-progress", "merged", "fixing", "done", "dropped")
HOLDS_SLOT = {IN_PROGRESS, FIXING}


# --- the world ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PR:
    number: int
    state: str               # OPEN | MERGED | CLOSED
    head: str                # branch name
    head_sha: str
    ci: str | None           # passed | failed | pending | None (no checks)
    conflicting: bool
    url: str = ""
    labels: tuple[str, ...] = ()
    created: datetime | None = None
    failing: tuple[str, ...] = ()    # names of the checks that failed on the head commit
    ci_round: str = ""               # which run of the checks `ci` describes (see _ci)


@dataclass(frozen=True)
class Item:
    name: str
    checked: bool


@dataclass(frozen=True)
class Card:
    id: str
    short: str
    name: str
    url: str
    ready: bool
    items: tuple[Item, ...] | None   # None = no "Factory steps" checklist yet
    issue: int | None = None         # a GitHub issue standing in for a card: one step, its own item


ISSUE_STEPS = "Factory steps"
_TASK = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$")


def issue_items(title: str, body: str, open_: bool) -> tuple[Item, ...]:
    """The issue's `## Factory steps` task list — written into the body by its first worker when
    the fix is more than one PR — else the issue as one step named for its title. A closed issue
    reads done throughout: the worker closes it after the last step's beta check."""
    items: list[Item] = []
    inside = False
    for line in (body or "").splitlines():
        if line.startswith("#"):
            inside = line.lstrip("#").strip() == ISSUE_STEPS
        elif inside and (m := _TASK.match(line)):
            items.append(Item(m[2], m[1] != " " or not open_))
    return tuple(items) or (Item(title, not open_),)


def issue_card(number: int, title: str, url: str, open_: bool, body: str = "") -> Card:
    """A labelled GitHub issue as a card: ready while open, its steps from `issue_items`."""
    return Card(str(number), issue_short(number), title, url, open_, issue_items(title, body, open_),
                issue=number)


@dataclass(frozen=True)
class World:
    cards: tuple[Card, ...]          # in board order: list position, then card position
    prs: tuple[PR, ...]              # factory PRs, any state
    branches: frozenset[str]         # local branches
    workers: dict                    # worker name → {"status": "idle"|"busy"|"restarting"|"dead", ...}
    sent: frozenset[str]             # event keys already delivered
    wip: int = 3                     # steps of cards in flight; the developer's review is the bound
    label: str = "factory"           # the GitHub label that makes a PR the factory's
    issue_wip: int = 1               # issues in flight: its own pool, not carved out of wip
    issue_daily: int | None = None   # issues started in any 24 hours; None = no cap
    now: datetime | None = None      # the dispatch's clock, for issue_daily and review_idle
    presence: dict = field(default_factory=dict)  # worker → when the developer last typed there
    reviews: dict = field(default_factory=dict)   # branch in review mode → requests still queued
    review_idle: timedelta = timedelta(minutes=15)  # silence after which the developer has left


@dataclass(frozen=True)
class Step:
    card: Card
    n: int
    item: Item
    state: str
    pr_number: int | None = None     # an adopted PR: the item names it as `#<n> …`
    head: str | None = None          # that PR's branch, once known

    @property
    def worker(self) -> str:
        return step_name(self.card.short, self.n)

    @property
    def branch(self) -> str:
        """The step's own branch: an adopted PR's branch, else the factory's name for it."""
        return self.head or step_branch(self.card.short, self.n)

    @property
    def fix_prefix(self) -> str:
        """Fix PRs always get factory branches, adopted step or not."""
        return step_branch(self.card.short, self.n) + "-fix"


# --- actions -----------------------------------------------------------------------------
@dataclass(frozen=True)
class StartSplit:
    card: Card


@dataclass(frozen=True)
class StartStep:
    step: Step
    recovered: str | None = None     # the state a replacement worker takes over in


@dataclass(frozen=True)
class SendEvent:
    worker: str
    key: str
    text: str


@dataclass(frozen=True)
class MarkSent:
    """Events a replacement worker re-derives from the PR itself — recorded, not sent."""
    keys: tuple[str, ...]


@dataclass(frozen=True)
class ReviewIdle:
    """The developer left the review: turn its review mode off and tell the worker."""
    worker: str
    branch: str


@dataclass(frozen=True)
class Cleanup:
    worker: str | None               # live session to stop, if any
    branch: str | None               # step branch whose worktree + branch to remove
    fixes: str | None = None         # prefix of the step's fix branches, removed too


# --- step state ----------------------------------------------------------------------------
def step_prs(prs: tuple[PR, ...], branch: str) -> tuple[PR | None, list[PR]]:
    """The step's own PR (its latest non-closed one wins over a closed one) and its fix PRs
    (branches `<branch>-fix<M>`)."""
    own = [p for p in prs if p.head == branch]
    own.sort(key=lambda p: (p.state != "CLOSED", p.number))
    fixes = [p for p in prs if p.head.startswith(branch + "-fix")]
    return (own[-1] if own else None), fixes


def derive_step_state(item: Item, branch_exists: bool, pr: PR | None, fixes: list[PR]) -> str:
    """The one predicate every dispatcher rule reads (spec, *Step state*).

    item           the step's checklist item (`checked`, and a `[dropped]` name prefix)
    branch_exists  the local branch feature/factory-<card>-s<N> exists
    pr             the step's own PR, preferring a non-closed one (None = never opened)
    fixes          PRs from `<branch>-fix<M>` branches, any state

    Returns one of PENDING, IN_PROGRESS, MERGED, FIXING, DONE, DROPPED_STATE.
    """
    # Order is the behaviour: the checklist is the developer-visible record and wins over any
    # PR state; a merge is never undone into "pending"; a closed PR changes nothing until the
    # worker marks the item, so a redo can reuse the branch.
    if item.checked:
        return DONE
    if item.name.startswith(DROPPED):
        return DROPPED_STATE
    if pr is not None and pr.state == "MERGED":
        return FIXING if any(f.state == "OPEN" for f in fixes) else MERGED
    if branch_exists or pr is not None:
        return IN_PROGRESS
    return PENDING


_ADOPTED = re.compile(r"^(?:\[\w+\]\s*)?#(\d+)\b")


def adopted_number(item: Item) -> int | None:
    """`#12 Add the export` (or `[dropped] #12 …`) → 12: the step adopts an existing PR."""
    m = _ADOPTED.match(item.name)
    return int(m[1]) if m else None


def card_steps(card: Card, world: World) -> list[Step]:
    steps = []
    for n, item in enumerate(card.items or (), start=1):
        number = adopted_number(item)
        if number is None:
            branch = step_branch(card.short, n)
            pr, fixes = step_prs(world.prs, branch)
            state = derive_step_state(item, branch in world.branches, pr, fixes)
            steps.append(Step(card, n, item, state))
            continue
        # An adopted PR is the factory's only once the dispatcher has labelled it: until then an
        # open one waits its turn like any pending step (a stacked PR behind its base, say).
        pr = next((p for p in world.prs if p.number == number), None)
        taken = pr if pr is not None and (pr.state != "OPEN" or world.label in pr.labels) else None
        fixes = [p for p in world.prs if p.head.startswith(step_branch(card.short, n) + "-fix")]
        state = derive_step_state(item, False, taken, fixes)
        steps.append(Step(card, n, item, state, number, pr.head if pr else None))
    return steps


def step_all_prs(step: Step, prs: tuple[PR, ...]) -> list[PR]:
    own = [p for p in prs if (p.number == step.pr_number if step.pr_number else p.head == step.branch)]
    return own + [p for p in prs if p.head.startswith(step.fix_prefix)]


# --- events --------------------------------------------------------------------------------
def pr_events(pr: PR) -> list[tuple[str, str]]:
    """(key, text) of every event this PR's current state implies. A key names the state it
    fired for, so the same failure is sent once and a new push can fire again."""
    out = []
    if pr.state == "MERGED":
        out.append((f"{pr.number}:merged", f"merged PR #{pr.number} — run the handoff"))
    elif pr.state == "CLOSED":
        out.append((f"{pr.number}:closed", f"pr-closed PR #{pr.number} — the step is dropped"))
    else:
        # The key names the round of checks, not only the commit: a check can fail on a commit
        # that already had its event -- a re-run, or a status main's own changes re-post (two
        # migration heads) -- and must still reach the worker.
        round_ = f":{pr.ci_round}" if pr.ci_round else ""
        if pr.ci == "failed":
            which = f" ({', '.join(pr.failing)})" if pr.failing else ""
            out.append((f"{pr.number}:ci-failed:{pr.head_sha}{round_}",
                        f"ci-failed PR #{pr.number}{which} {pr.url}/checks"))
        elif pr.ci == "passed":
            out.append((f"{pr.number}:ci-passed:{pr.head_sha}{round_}", f"ci-passed PR #{pr.number}"))
        if pr.conflicting:
            out.append((f"{pr.number}:conflict:{pr.head_sha}", f"conflict PR #{pr.number} — conflicts with origin/main"))
    return out


# --- the decision ----------------------------------------------------------------------------
def _alive(world: World, name: str) -> bool:
    """Listed and not dead — a restarting worker counts, so it gets no twin."""
    return name in world.workers and world.workers[name].get("status") != "dead"


def decide(world: World) -> list:
    actions: list = []
    all_steps = {c.short: card_steps(c, world) for c in world.cards if c.items is not None}

    # 1. A ready card with no step list gets one split worker.
    for card in world.cards:
        if card.ready and card.items is None and not _alive(world, split_name(card.short)):
            actions.append(StartSplit(card))

    for card in world.cards:
        if not card.ready:
            continue
        for step in all_steps.get(card.short, []):
            prs = step_all_prs(step, world.prs)
            # 2. A merged step that lost its worker gets a replacement at once: the handoff needs
            # one, and a merged step holds no slot (rule 4 replaces the others).
            if step.state == MERGED and not _alive(world, step.worker):
                actions += _replace(step, world)
            # 3. A live worker hears about every change to its PRs once.
            elif _alive(world, step.worker):
                for pr in prs:
                    for key, text in pr_events(pr):
                        if key not in world.sent:
                            actions.append(SendEvent(step.worker, key, f"Factory event: {text}"))
                actions += _review_idle(step, prs, world)

    # 4. A slot is held by a **live worker** of an in-progress or fixing step, not by the step's
    # state: a step that reads in-progress with no worker -- its worker died, or a closed PR still
    # sits on its branch -- holds nothing, and gets a worker back only through a free slot. So a
    # slot once given stays with whoever has it. Free slots go first to steps under way without a
    # worker (a crashed worker's step gets its slot back before anything new starts), then to
    # eligible pending steps -- cards with a step behind them first, then board (issue-number)
    # order. Nothing is preempted: a live worker is never stopped to make room.
    # Cards and issues draw on **separate** pools -- wip for cards, issue_wip for issues --
    # because the two queue behind different people: a card's PR waits for the developer's review,
    # an issue's merges itself. Sharing one pool meant three cards waiting on a review stalled
    # every autofix behind them. No more than issue_daily issue steps start in any 24 hours; a
    # replacement is no new start.
    # Only a card's first unfinished step is ever started or replaced, and never while a worker
    # of that name lives. A worker that cuts an adopted PR inserts the pieces before it on the
    # checklist: the adopted PR, still labelled, then reads in-progress behind them, and the
    # worker's own step reads pending until its piece is labelled.
    ready = [c for c in world.cards if c.ready]
    under_way = [s for c in ready if (s := _first_open(all_steps.get(c.short, []))) is not None
                 and s.state in HOLDS_SLOT and not _alive(world, s.worker)]
    def started(card: Card) -> bool:
        return any(s.state != PENDING for s in all_steps.get(card.short, []))
    pending = [s for c in sorted(ready, key=lambda c: not started(c))
               if (s := _eligible_step(all_steps.get(c.short, []))) is not None
               and not _alive(world, s.worker)]
    def holding(issue: bool) -> int:
        return sum(1 for c in world.cards if (c.issue is not None) == issue
                   for s in all_steps.get(c.short, []) if s.state in HOLDS_SLOT and _alive(world, s.worker))
    held = {False: holding(False), True: holding(True)}
    wip = {False: world.wip, True: world.issue_wip}
    issues_today = _issues_started_since(world, all_steps, world.now - timedelta(days=1)) if world.now else 0
    for step in under_way + pending:
        issue = step.card.issue is not None
        if held[issue] >= wip[issue]:
            continue
        if step.state == PENDING:
            if issue and world.issue_daily is not None and issues_today >= world.issue_daily:
                continue
            actions.append(StartStep(step))
            issues_today += issue
        else:
            actions += _replace(step, world)
        held[issue] += 1

    # 5. Done steps and stopped cards are cleaned up; the dispatcher is the only cleanup owner.
    for name, info in world.workers.items():
        parsed = parse_worker_name(name)
        if parsed is None or info.get("status") not in ("idle", "dead"):
            continue
        short, n = parsed
        card = next((c for c in world.cards if c.short == short), None)
        if n is None:
            if card is None or not card.ready or card.items is not None:
                actions.append(Cleanup(name, None))
            continue
        step = _step(all_steps, short, n)
        if card is None or not card.ready or (step is not None and step.state == DONE):
            branch = step.branch if step else step_branch(short, n)
            actions.append(Cleanup(name, branch, step_branch(short, n) + "-fix"))
    for steps in all_steps.values():
        for s in steps:
            if s.state == DONE and s.branch in world.branches and s.worker not in world.workers:
                actions.append(Cleanup(None, s.branch, s.fix_prefix))
    return actions


def _review_idle(step: Step, prs: list, world: World) -> list:
    """Review mode is for the developer's presence: it goes on with their first message in the
    worker's conversation (a hook) and off once they have said nothing there for review_idle --
    unless they queued changes, which wait for their go. Off, the worker keeps its PR healthy."""
    if world.now is None:
        return []
    seen = world.presence.get(step.worker)
    if seen is not None and world.now - seen < world.review_idle:
        return []
    branches = dict.fromkeys([step.branch, *(p.head for p in prs if p.state == "OPEN")])
    return [ReviewIdle(step.worker, b) for b in branches if world.reviews.get(b) == 0]


def _issues_started_since(world: World, all_steps: dict, since: datetime) -> int:
    """Issue steps started since `since`: a PR opened since then, or a branch with no PR yet. A
    PR's creation stands in for the start, so the count needs no state of the dispatcher's own."""
    count = 0
    for card in world.cards:
        if card.issue is None:
            continue
        for step in all_steps.get(card.short, []):
            pr, _ = step_prs(world.prs, step.branch)
            if pr is None:
                count += step.state == IN_PROGRESS
            elif pr.created is not None and pr.created >= since:
                count += 1
    return count


def _replace(step: Step, world: World) -> list:
    """A replacement worker for a step under way. The events it would have heard are recorded,
    not sent: it re-derives them from the PRs themselves."""
    keys = [k for p in step_all_prs(step, world.prs) for k, _ in pr_events(p) if k not in world.sent]
    return [StartStep(step, recovered=step.state)] + ([MarkSent(tuple(keys))] if keys else [])


def _eligible_step(steps: list[Step]) -> Step | None:
    """The first pending step whose earlier steps are all done; a dropped step blocks the card."""
    for s in steps:
        if s.state == PENDING:
            return s
        if s.state != DONE:
            return None
    return None


def _first_open(steps: list[Step]) -> Step | None:
    return next((s for s in steps if s.state != DONE), None)


def _step(all_steps: dict, short: str, n: int) -> Step | None:
    steps = all_steps.get(short, [])
    return steps[n - 1] if 0 < n <= len(steps) else None


# --- gathering the world -----------------------------------------------------------------------
def _trello(method: str, path: str, **params) -> Any:
    params |= {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}
    url = f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "null")


def load_cards(profile: Profile) -> tuple[Card, ...]:
    board = profile.require("Trello", "Board")
    ready_name = profile.get("Trello", "Ready label", "ready")
    checklist_name = profile.get("Trello", "Checklist", "Factory steps")
    labels = {l["id"]: l["name"] for l in _trello("GET", f"boards/{board}/labels", fields="name")}
    lists = {l["id"]: l["pos"] for l in _trello("GET", f"boards/{board}/lists", fields="pos")}
    raw = _trello("GET", f"boards/{board}/cards", fields="name,idList,idLabels,shortLink,pos,shortUrl",
                  checklists="all")
    cards = []
    for c in sorted(raw, key=lambda c: (lists.get(c["idList"], 0), c["pos"])):
        ready = any((labels.get(i) or "").casefold() == ready_name.casefold() for i in c["idLabels"])
        checklist = next((cl for cl in c.get("checklists", []) if cl["name"] == checklist_name), None)
        items = None
        if checklist is not None:
            items = tuple(Item(i["name"], i["state"] == "complete")
                          for i in sorted(checklist["checkItems"], key=lambda i: i["pos"]))
        if ready or items is not None:
            cards.append(Card(c["id"], c["shortLink"], c["name"], c["shortUrl"], ready, items))
    return tuple(cards)


def takes_issue(issue: dict, decision_label: str) -> bool:
    """Whether the factory takes this issue. The selection label says what kind of work an issue
    is, not that anyone approved it for unattended work — so a worker that finds a design decision
    in one marks it with the **Needs decision** label and ends. The next dispatch has to leave it
    alone, or the factory offers it again every two minutes and the slot never moves on."""
    if not decision_label:
        return True
    return not any(l["name"] == decision_label for l in issue.get("labels") or [])


def load_issues(repo: Path, label: str, decision_label: str = "") -> tuple[Card, ...]:
    """Issues labelled for the factory, oldest first; closed ones too, so their steps read done."""
    out = run(["gh", "issue", "list", "--label", label, "--state", "all", "--limit", "200",
               "--json", "number,title,state,url,body,labels"], cwd=repo)
    issues = [i for i in json.loads(out) if takes_issue(i, decision_label)]
    return tuple(issue_card(i["number"], i["title"], i["url"], i["state"] == "OPEN", i.get("body") or "")
                 for i in sorted(issues, key=lambda i: i["number"]))


_FAILED = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"}


def _ci(rollup: list[dict]) -> tuple[str | None, tuple[str, ...], str]:
    """(state, failing check names, round). The round tells one run of the checks from another
    on the same commit: the failing checks with when each finished, or, once all passed, when
    the last one did."""
    if not rollup:
        return None, (), ""
    def name(r: dict) -> str:
        return r.get("name") or r.get("context") or "?"
    def at(r: dict) -> str:
        return r.get("completedAt") or r.get("createdAt") or r.get("startedAt") or ""
    failed = sorted((r for r in rollup if (r.get("conclusion") or r.get("state")) in _FAILED), key=name)
    if failed:
        return "failed", tuple(name(r) for r in failed), ",".join(f"{name(r)}@{at(r)}" for r in failed)
    if any(r.get("status") not in (None, "COMPLETED") or r.get("state") == "PENDING" for r in rollup):
        return "pending", (), ""
    return "passed", (), max(at(r) for r in rollup)


_PR_FIELDS = "number,state,headRefName,headRefOid,statusCheckRollup,mergeable,url,labels,createdAt"


def _pr(p: dict) -> PR:
    ci, failing, round_ = _ci(p.get("statusCheckRollup") or [])
    return PR(p["number"], p["state"], p["headRefName"], p["headRefOid"],
              ci, p.get("mergeable") == "CONFLICTING", p["url"],
              tuple(l["name"] for l in p.get("labels") or []),
              datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00")) if p.get("createdAt") else None,
              failing, round_)


def load_prs(repo: Path, label: str, adopted: set[int]) -> tuple[PR, ...]:
    """Factory-labelled PRs, plus the PRs cards adopt that the factory has not labelled yet."""
    out = run(["gh", "pr", "list", "--label", label, "--state", "all", "--limit", "200",
               "--json", _PR_FIELDS], cwd=repo)
    prs = {p["number"]: _pr(p) for p in json.loads(out)}
    for number in adopted - prs.keys():
        prs[number] = _pr(json.loads(run(["gh", "pr", "view", str(number), "--json", _PR_FIELDS], cwd=repo)))
    return tuple(prs.values())


def load_branches(repo: Path) -> frozenset[str]:
    out = run(["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"], cwd=repo)
    return frozenset(out.split())


def checked_out_at(porcelain: str, branch: str) -> Path | None:
    """Where `git worktree list --porcelain` shows `branch` checked out, if anywhere. Asked, not
    guessed from the branch name: an adopted PR's branch may sit in a worktree the developer named."""
    path = None
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}":
            return path
    return None


def uncommitted(status: str) -> list[str]:
    """`git status --porcelain` lines that are someone's work. A file turned into a symlink (a
    worktree setup linking shared env files) is setup, not work."""
    return [l for l in status.splitlines() if l.strip() and "T" not in l[:2]]


# --- carrying out actions -------------------------------------------------------------------------
@dataclass
class Executor:
    repo: Path
    profile: Profile
    dry_run: bool = False
    log: list[str] = field(default_factory=list)

    def __call__(self, action) -> None:
        self.log.append(repr(action))
        if self.dry_run:
            return
        getattr(self, "_" + type(action).__name__)(action)

    def _StartSplit(self, a: StartSplit) -> None:
        doing = self.profile.get("Trello", "Doing")
        if doing:
            _trello("PUT", f"cards/{a.card.id}", idList=doing)
        self._launch(split_name(a.card.short), self.repo, "split.md", card=a.card,
                     title=display_name(a.card))

    @property
    def _worktrees(self) -> Path:
        return self.repo / (self.profile.get("Worktree", "Dir", ".worktrees") or ".worktrees")

    @property
    def _base(self) -> str:
        return self.profile.get("Repo", "Base", "main") or "main"

    def _StartStep(self, a: StartStep) -> None:
        s = a.step
        create = self.profile.require("Worktree", "Create")
        if s.pr_number is not None:
            # An adopted PR: its own branch, and the label that makes it count as a slot.
            if not s.head or "/" not in s.head:
                raise RuntimeError(f"PR #{s.pr_number}: branch {s.head!r} has no slash — check it out by hand")
            worktree = self._existing_worktree(s.head)
            if worktree is None:
                worktree = self._worktrees / s.head.rsplit("/", 1)[1]
                if not worktree.exists():
                    run([create, s.head], cwd=self.repo, timeout=1800)
            run(["gh", "pr", "edit", str(s.pr_number), "--add-label", self.profile.get("GitHub", "Label", "factory")],
                cwd=self.repo)
        else:
            worktree = self._worktrees / s.worker
            if not worktree.exists():
                run(["git", "fetch", "origin", self._base], cwd=self.repo)
                if s.branch in load_branches(self.repo):
                    run([create, s.branch], cwd=self.repo, timeout=1800)
                else:
                    run([create, "--base", f"origin/{self._base}", s.worker], cwd=self.repo, timeout=1800)
        total = len(s.card.items or ())
        self._launch(s.worker, worktree, "recovery.md" if a.recovered else "step.md", card=s.card,
                     step=s, total=total, recovered=a.recovered or "", title=display_name(s.card, s, total))

    def ping_failed_start(self, action, exc: Exception) -> None:
        """A start that fails is retried every dispatch; the developer hears of it once per reason
        (factory-ping drops repeats), not only in the journal."""
        name = action.step.worker if isinstance(action, StartStep) else split_name(action.card.short)
        reason = f"can't start: {(str(exc).splitlines() or [type(exc).__name__])[0][:300]}"
        run([str(PLUGIN_ROOT / "scripts/factory-ping"), "--worker", name, reason], check=False,
            env={"FACTORY_REPO": str(self.repo)})

    def _existing_worktree(self, branch: str) -> Path | None:
        """The worktree `branch` is already checked out in, taken over as it is — its installs
        are the slow part of a launch. Refused while it holds work of its own (uncommitted, or
        commits its remote lacks): that is the developer's to save or drop, not a worker's."""
        found = checked_out_at(run(["git", "worktree", "list", "--porcelain"], cwd=self.repo), branch)
        if found is None:
            return None
        if found.resolve() == self.repo.resolve():
            raise RuntimeError(f"{branch} is checked out in the main checkout — switch it to another branch")
        run(["git", "fetch", "origin", branch], cwd=self.repo)
        work = uncommitted(run(["git", "status", "--porcelain"], cwd=found))
        ahead = run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], cwd=found).strip()
        if work or ahead != "0":
            what = f"{len(work)} uncommitted change(s)" if work else f"{ahead} unpushed commit(s)"
            raise RuntimeError(f"{branch} is checked out in {found} with {what} — "
                               "commit and push it, or remove that worktree")
        return found

    def _SendEvent(self, a: SendEvent) -> None:
        prompt = (f"Use ListAgents to find the session named {a.worker}, then use SendMessage to send it "
                  f"exactly this text and nothing else: {json.dumps(a.text)}. "
                  "Reply with only DELIVERED or FAILED.")
        out = run(["claude", "-p", "--model", "haiku", "--permission-mode", "auto", prompt],
                  cwd=self.repo, timeout=180)
        if "DELIVERED" in out:
            with sent_store() as sent:
                sent.add(a.key)

    def _ReviewIdle(self, a: ReviewIdle) -> None:
        script = PLUGIN_ROOT.parent / "review-mode/scripts/review-mode.sh"
        run(["bash", str(script), "off", "-b", a.branch], cwd=self.repo,
            env={"CLAUDE_PROJECT_DIR": str(self.repo)})
        self._SendEvent(SendEvent(a.worker, f"review-idle:{a.branch}:{datetime.now(timezone.utc).isoformat()}",
                                  f"Factory event: review-idle {a.branch} — the developer has said nothing here "
                                  "for a while, so review mode is off: do the upkeep you held"))

    def _MarkSent(self, a: MarkSent) -> None:
        with sent_store() as sent:
            sent.update(a.keys)

    def _Cleanup(self, a: Cleanup) -> None:
        if a.worker:
            for agent in list_agents():  # every session of that name, a dead twin included
                if agent["name"] == a.worker:
                    run(["claude", "stop", agent["id"]], check=False)
                    run(["claude", "rm", agent["id"]], check=False)
        if a.branch:
            found = checked_out_at(run(["git", "worktree", "list", "--porcelain"], cwd=self.repo), a.branch)
            if found is not None and found.resolve() == self.repo.resolve():
                return  # never the main checkout
            worktree = found or self._worktrees / a.branch.rsplit("/", 1)[-1]
            run([str(PLUGIN_ROOT / "scripts/remove-step-worktree.sh"), str(self.repo), str(worktree),
                 a.branch, a.fixes or ""], check=False, timeout=600,
                env={"FACTORY_CLEANUP": self.profile.code_block("Cleanup") or ""})

    def _launch(self, name: str, cwd: Path, template: str, title: str, **ctx) -> None:
        # Checked again here: the decision is minutes old by now (the worktree setup alone runs
        # npm and poetry), and a worker that came back meanwhile must not get a twin. Dead
        # sessions of the name go first, so the name stays one session.
        same_name = [a for a in list_agents() if a["name"] == name]
        if any(a.get("pid") for a in same_name):
            raise RuntimeError(f"{name} is live again — not launching a twin")
        for agent in same_name:
            run(["claude", "stop", agent["id"]], check=False)
            run(["claude", "rm", agent["id"]], check=False)
        prompt = render_prompt(template, self.repo, self.profile, name, **ctx)
        # A worker inherits the settings of the branch it sits on, and an adopted PR's branch can
        # predate the repo enabling these plugins — no skills, no reviewer agents, no merge gate.
        # Loading the marketplace's plugins explicitly makes every worker carry them (no
        # duplicates where the branch already enables them).
        # `--name` is the routing key (the dispatcher and its events find the worker by it);
        # the Remote Control name is what the developer reads in the Claude app.
        cmd = ["claude", "--bg", "--name", name, "--remote-control", title,
               "--plugin-dir", str(PLUGIN_ROOT.parent),
               "--permission-mode", self.profile.get("Settings", "Permission mode", "auto"),
               "--disallowedTools", *deny_list(self.profile, issue=ctx["card"].issue is not None),
               "--", prompt]
        # `claude --bg` hands the session to a background daemon, started on demand by whoever
        # launches first. Started from the dispatch service, that daemon would live in the
        # service's cgroup and die with it the moment the oneshot exits — every worker with it.
        # A transient scope of its own keeps it outside.
        if shutil.which("systemd-run"):
            cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect",
                   f"--unit=factory-launch-{name}-{int(time.time())}", *cmd]
        run(cmd, cwd=cwd, env={"FACTORY_WORKER": name, "FACTORY_REPO": str(self.repo)})
        mark_launched(name)


# Shared runner rules the factory replaces: the gate hook decides merges and force-pushes, and an
# issue's worker closes its issue after the beta check. An issue's worker also writes its step
# list into the issue body and ticks it, and reports a shipped step in a comment.
NOT_DENIED = ("Bash(gh pr merge", "Bash(gh issue close", "Bash(git push --force")
NOT_DENIED_TO_ISSUES = ("Bash(gh issue edit", "Bash(gh issue comment")


def deny_list(profile: Profile, issue: bool = False) -> list[str]:
    """The runner deny list shared with nightly-backlog, minus what the factory replaces, plus
    the profile's `## Deny` rules — and, for an issue's worker, the `## Issues` ones."""
    shared = PLUGIN_ROOT.parent.parent / "shared/runner-deny.txt"
    rules = [l.strip() for l in shared.read_text().splitlines() if l.strip() and not l.startswith("#")]
    rules = [r for r in rules if not r.startswith(NOT_DENIED + (NOT_DENIED_TO_ISSUES if issue else ()))]
    return rules + profile.items("Deny") + (profile.items("Issues") if issue else [])


def display_name(card: Card, step: Step | None = None, total: int = 0) -> str:
    """The worker's name in the Claude app: what it works on, not its routing key."""
    if card.issue is not None:
        title = f"#{card.issue} {card.name}"
    elif step is None:
        title = f"{card.name} · split"
    else:
        title = f"{card.name} · {step.n}/{total}"
    return "factory · " + (title if len(title) <= 70 else title[:69] + "…")


def _entry(step: Step | None) -> str:
    if step is None:
        return ""
    if step.card.issue is not None:
        return (f"This step is **GitHub issue #{step.card.issue}**, marked as needing no design "
                "decision: there is no spec phase and no Trello card. Start at *Issue*"
                + (" — its steps are already listed, so skip the split." if step.n > 1 else "."))
    if step.pr_number is None:
        return "Start at *Spec*."
    return (f"This step **adopts PR #{step.pr_number}** (branch `{step.branch}`), written before the "
            "factory took the card: there is no spec phase. Start at *Adopted PR*.")


def render_prompt(template: str, repo: Path, profile: Profile, name: str, card: Card,
                  step: Step | None = None, total: int = 0, recovered: str = "") -> str:
    text = (PLUGIN_ROOT / "prompts" / template).read_text()
    # The triage decision is its own template so the eval can run it alone (evals/pr_triage.py);
    # here it is filled the way a worker reaches its PR.
    text = text.replace("{triage}", (PLUGIN_ROOT / "prompts/triage.md").read_text().strip()
                        .replace("{DIFF}", "git diff origin/{base}...HEAD")
                        .replace("{DESCRIPTION}", "the PR's body (`gh pr view <n> --json body -q .body`)")
                        .replace("{SPEC}", "the step's spec, committed on this branch (none for an issue "
                                           "or an adopted PR)"))
    values = {
        "worker": name, "repo": str(repo), "plugin_root": str(PLUGIN_ROOT),
        "profile": str(repo / ".claude/factory.md"),
        "card_name": card.name, "card_url": card.url, "card_id": card.id,
        "source": (f'GitHub issue #{card.issue} "{card.name}" ({card.url})' if card.issue is not None
                   else f'the Trello card "{card.name}" ({card.url}, card id `{card.id}`)'),
        "issue_label": profile.get("Issues", "Label", "") or "",
        "issue_decision_label": profile.get("Issues", "Needs decision", "") or "",
        "issue_handoff": profile.get("Issues", "Handoff", "") or "",
        "issue_off_limits": profile.text("Issues", "Off limits", "nothing beyond the ground rules")
                            or "nothing beyond the ground rules",
        "step_n": str(step.n if step else ""), "step_total": str(total),
        "step_text": step.item.name if step else "",
        "branch": step.branch if step else "", "recovered_state": recovered,
        "fix_prefix": step.fix_prefix if step else "",
        "entry": _entry(step),
        "base": profile.get("Repo", "Base", "main") or "main",
        "rules": profile.text("Repo", "Rules", "`CLAUDE.md`") or "`CLAUDE.md`",
        "spec_template": profile.get("Repo", "Spec template", "") or "(none — use the repo's usual spec shape)",
        "specs_dir": profile.get("Repo", "Specs", "docs") or "docs",
        "handoff_skill": profile.get("Repo", "Handoff skill", "") or "",
        "ping": shlex.quote(str(PLUGIN_ROOT / "scripts/factory-ping")),
        "lock": shlex.quote(str(PLUGIN_ROOT / "scripts/factory-lock")),
    }
    if "{step_prompt}" in text:
        values["step_prompt"] = render_prompt("step.md", repo, profile, name, card, step, total)
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


# --- main ------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="The factory dispatcher: one dispatch, then exit.")
    ap.add_argument("repo", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print the actions, do nothing")
    args = ap.parse_args()
    repo = args.repo.resolve()

    if PAUSE_FILE.exists() and not args.dry_run:
        print(f"factory: paused ({PAUSE_FILE})")
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(STATE_DIR / ".dispatch.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("factory: previous dispatch still running")
        return 0

    load_repo_secrets(repo)
    profile = Profile.load(repo)
    with sent_store() as sent:
        sent_now = frozenset(sent)
    label = profile.get("GitHub", "Label", "factory") or "factory"
    cards = load_cards(profile)
    adopted = {n for c in cards if c.ready for i in c.items or () if (n := adopted_number(i)) is not None}
    issue_label = profile.get("Issues", "Label")
    if issue_label:
        cards += load_issues(repo, issue_label, profile.get("Issues", "Needs decision", "") or "")
    workers = live_workers(record=True)
    world = World(
        cards=cards,
        prs=load_prs(repo, label, adopted),
        branches=load_branches(repo),
        workers=workers,
        sent=sent_now,
        wip=int(profile.get("Settings", "WIP", "3")),
        label=label,
        issue_wip=int(profile.get("Issues", "WIP", "1")),
        issue_daily=int(daily) if (daily := profile.get("Issues", "Per day")) else None,
        now=datetime.now(timezone.utc),
        presence={name: last_developer_message(info.get("sessionId"))
                  for name, info in workers.items() if info.get("pid")},
        reviews=reviews_on(repo),
        review_idle=timedelta(minutes=int(profile.get("Settings", "Review idle", "15"))),
    )
    execute = Executor(repo, profile, dry_run=args.dry_run)
    failures = 0
    for action in decide(world):
        try:
            execute(action)
        except Exception as exc:  # one failed action must not stop the rest of the dispatch
            failures += 1
            print(f"factory: {action!r} failed: {exc}", file=sys.stderr)
            if isinstance(action, (StartStep, StartSplit)):
                execute.ping_failed_start(action, exc)
    for line in execute.log:
        print(("would: " if args.dry_run else "did: ") + line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
