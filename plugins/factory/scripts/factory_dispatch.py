#!/usr/bin/env python3
"""The factory dispatcher: one dispatch = read GitHub, Trello, git and the live workers, decide,
act, exit. Run every couple of minutes by a systemd user timer (see ../systemd/).

    factory_dispatch.py <repo> [--dry-run]

All the routing is in `decide()`, a pure function of the world it is handed — that is what the
tests pin. Everything around it only gathers the world or carries out the actions.
Design: docs/superpowers/specs/2026-10-26-software-factory-design.md in the project repo.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import (  # noqa: E402
    PAUSE_FILE, STATE_DIR, Profile, live_workers, parse_worker_name, run, sent_store,
    split_name, step_branch, step_name,
)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
DROPPED = "[dropped]"

# Step states (spec: "Step state — the one predicate every rule reads").
PENDING, IN_PROGRESS, MERGED, FIXING, DONE, DROPPED_STATE = (
    "pending", "in-progress", "merged", "fixing", "done", "dropped")
HOLDS_SLOT = {IN_PROGRESS, FIXING}
NEEDS_WORKER = {IN_PROGRESS, MERGED, FIXING}


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


@dataclass(frozen=True)
class World:
    cards: tuple[Card, ...]          # in board order: list position, then card position
    prs: tuple[PR, ...]              # factory PRs, any state
    branches: frozenset[str]         # local branches
    workers: dict                    # live worker name → {"status": "idle"|"busy", ...}
    sent: frozenset[str]             # event keys already delivered
    wip: int = 3
    label: str = "factory"           # the GitHub label that makes a PR the factory's


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
    """`#401 Sales Calls` (or `[dropped] #401 …`) → 401: the step adopts an existing PR."""
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
        if pr.ci == "failed":
            out.append((f"{pr.number}:ci-failed:{pr.head_sha}", f"ci-failed PR #{pr.number} {pr.url}/checks"))
        elif pr.ci == "passed":
            out.append((f"{pr.number}:ci-passed:{pr.head_sha}", f"ci-passed PR #{pr.number}"))
        if pr.conflicting:
            out.append((f"{pr.number}:conflict:{pr.head_sha}", f"conflict PR #{pr.number} — conflicts with origin/main"))
    return out


# --- the decision ----------------------------------------------------------------------------
def decide(world: World) -> list:
    actions: list = []
    all_steps = {c.short: card_steps(c, world) for c in world.cards if c.items is not None}

    # 1. A ready card with no step list gets one split worker.
    for card in world.cards:
        if card.ready and card.items is None and split_name(card.short) not in world.workers:
            actions.append(StartSplit(card))

    for card in world.cards:
        if not card.ready:
            continue
        for step in all_steps.get(card.short, []):
            prs = step_all_prs(step, world.prs)
            keys = [k for p in prs for k, _ in pr_events(p) if k not in world.sent]
            # 2. A step that needs a worker and has none gets a replacement.
            if step.state in NEEDS_WORKER and step.worker not in world.workers:
                actions.append(StartStep(step, recovered=step.state))
                if keys:
                    actions.append(MarkSent(tuple(keys)))
            # 3. A live worker hears about every change to its PRs once.
            elif step.worker in world.workers:
                for pr in prs:
                    for key, text in pr_events(pr):
                        if key not in world.sent:
                            actions.append(SendEvent(step.worker, key, f"Factory event: {text}"))

    # 4. Free slots go to eligible steps: cards already under way first, then board order.
    held = sum(1 for steps in all_steps.values() for s in steps if s.state in HOLDS_SLOT)
    def started(card: Card) -> bool:
        return any(s.state != PENDING for s in all_steps.get(card.short, []))
    for card in sorted((c for c in world.cards if c.ready), key=lambda c: not started(c)):
        if held >= world.wip:
            break
        eligible = _eligible_step(all_steps.get(card.short, []))
        if eligible is not None:
            actions.append(StartStep(eligible))
            held += 1

    # 5. Done steps and stopped cards are cleaned up; the dispatcher is the only cleanup owner.
    for name, info in world.workers.items():
        parsed = parse_worker_name(name)
        if parsed is None or info.get("status") != "idle":
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


def _eligible_step(steps: list[Step]) -> Step | None:
    """The first pending step whose earlier steps are all done; a dropped step blocks the card."""
    for s in steps:
        if s.state == PENDING:
            return s
        if s.state != DONE:
            return None
    return None


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


def _ci(rollup: list[dict]) -> str | None:
    if not rollup:
        return None
    failed = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "ERROR", "STARTUP_FAILURE"}
    if any((r.get("conclusion") or r.get("state")) in failed for r in rollup):
        return "failed"
    if any(r.get("status") not in (None, "COMPLETED") or r.get("state") == "PENDING" for r in rollup):
        return "pending"
    return "passed"


_PR_FIELDS = "number,state,headRefName,headRefOid,statusCheckRollup,mergeable,url,labels"


def _pr(p: dict) -> PR:
    return PR(p["number"], p["state"], p["headRefName"], p["headRefOid"],
              _ci(p.get("statusCheckRollup") or []), p.get("mergeable") == "CONFLICTING", p["url"],
              tuple(l["name"] for l in p.get("labels") or []))


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
        self._launch(split_name(a.card.short), self.repo, "split.md", card=a.card)

    def _StartStep(self, a: StartStep) -> None:
        s = a.step
        create = self.profile.get("Worktree", "Create", "scripts/create-worktree.sh")
        if s.pr_number is not None:
            # An adopted PR: its own branch, and the label that makes it count as a slot.
            if not s.head or "/" not in s.head:
                raise RuntimeError(f"PR #{s.pr_number}: branch {s.head!r} has no slash — check it out by hand")
            run(["gh", "pr", "edit", str(s.pr_number), "--add-label", self.profile.get("GitHub", "Label", "factory")],
                cwd=self.repo)
            worktree = self.repo / ".worktrees" / s.head.rsplit("/", 1)[1]
            if not worktree.exists():
                run([create, s.head], cwd=self.repo, timeout=1800)
        else:
            worktree = self.repo / ".worktrees" / s.worker
            if not worktree.exists():
                run(["git", "fetch", "origin", "main"], cwd=self.repo)
                if s.branch in load_branches(self.repo):
                    run([create, s.branch], cwd=self.repo, timeout=1800)
                else:
                    run([create, "--base", "origin/main", s.worker], cwd=self.repo, timeout=1800)
        total = len(s.card.items or ())
        self._launch(s.worker, worktree, "recovery.md" if a.recovered else "step.md", card=s.card,
                     step=s, total=total, recovered=a.recovered or "")

    def _SendEvent(self, a: SendEvent) -> None:
        prompt = (f"Use ListAgents to find the session named {a.worker}, then use SendMessage to send it "
                  f"exactly this text and nothing else: {json.dumps(a.text)}. "
                  "Reply with only DELIVERED or FAILED.")
        out = run(["claude", "-p", "--model", "haiku", "--permission-mode", "auto", prompt],
                  cwd=self.repo, timeout=180)
        if "DELIVERED" in out:
            with sent_store() as sent:
                sent.add(a.key)

    def _MarkSent(self, a: MarkSent) -> None:
        with sent_store() as sent:
            sent.update(a.keys)

    def _Cleanup(self, a: Cleanup) -> None:
        if a.worker:
            agent = live_workers().get(a.worker)
            if agent:
                run(["claude", "stop", agent["id"]], check=False)
                run(["claude", "rm", agent["id"]], check=False)
        if a.branch:
            run([str(PLUGIN_ROOT / "scripts/remove-step-worktree.sh"), str(self.repo), a.branch,
                 a.fixes or ""], check=False, timeout=600)

    def _launch(self, name: str, cwd: Path, template: str, **ctx) -> None:
        prompt = render_prompt(template, self.repo, self.profile, name, **ctx)
        cmd = ["claude", "--bg", "--name", name, "--remote-control", name,
               "--permission-mode", self.profile.get("Settings", "Permission mode", "auto"),
               "--disallowedTools", *deny_list(self.profile), "--", prompt]
        run(cmd, cwd=cwd, env={"FACTORY_WORKER": name, "FACTORY_REPO": str(self.repo)})


def deny_list(profile: Profile) -> list[str]:
    """The runner deny list shared with nightly-backlog, minus `gh pr merge` (the auto-merge
    gate hook decides those), plus the profile's own `## Deny` rules."""
    shared = PLUGIN_ROOT.parent.parent / "shared/runner-deny.txt"
    rules = [l.strip() for l in shared.read_text().splitlines() if l.strip() and not l.startswith("#")]
    rules = [r for r in rules if not r.startswith("Bash(gh pr merge")]
    return rules + profile.items("Deny")


def _entry(step: Step | None) -> str:
    if step is None:
        return ""
    if step.pr_number is None:
        return "Start at *Spec*."
    return (f"This step **adopts PR #{step.pr_number}** (branch `{step.branch}`), written before the "
            "factory took the card: there is no spec phase. Start at *Adopted PR*.")


def render_prompt(template: str, repo: Path, profile: Profile, name: str, card: Card,
                  step: Step | None = None, total: int = 0, recovered: str = "") -> str:
    text = (PLUGIN_ROOT / "prompts" / template).read_text()
    values = {
        "worker": name, "repo": str(repo), "plugin_root": str(PLUGIN_ROOT),
        "profile": str(repo / ".claude/factory.md"),
        "card_name": card.name, "card_url": card.url, "card_id": card.id,
        "step_n": str(step.n if step else ""), "step_total": str(total),
        "step_text": step.item.name if step else "",
        "branch": step.branch if step else "", "recovered_state": recovered,
        "fix_prefix": step.fix_prefix if step else "",
        "entry": _entry(step),
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

    profile = Profile.load(repo)
    with sent_store() as sent:
        sent_now = frozenset(sent)
    label = profile.get("GitHub", "Label", "factory") or "factory"
    cards = load_cards(profile)
    adopted = {n for c in cards if c.ready for i in c.items or () if (n := adopted_number(i)) is not None}
    world = World(
        cards=cards,
        prs=load_prs(repo, label, adopted),
        branches=load_branches(repo),
        workers=live_workers(),
        sent=sent_now,
        wip=int(profile.get("Settings", "WIP", "3")),
        label=label,
    )
    execute = Executor(repo, profile, dry_run=args.dry_run)
    failures = 0
    for action in decide(world):
        try:
            execute(action)
        except Exception as exc:  # one failed action must not stop the rest of the dispatch
            failures += 1
            print(f"factory: {action!r} failed: {exc}", file=sys.stderr)
    for line in execute.log:
        print(("would: " if args.dry_run else "did: ") + line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
