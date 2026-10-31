#!/usr/bin/env python3
"""factory-status: what the factory is doing, as the last dispatch saw it.

    factory-status                 a summary of ~/.local/state/factory/status.json
    factory-status --json          the snapshot itself, plus `paused` and `age_seconds`
    factory-status --live <repo>   a fresh look: gathers the world and decides, does nothing
    factory-status --html          the status page (factory_page), as each dispatch writes it to
                                   ~/.local/state/factory/www/index.html

Every dispatch writes the snapshot after acting (`write_status`), from the same `World` and the
same `card_steps` / `decide` it routed by — so the status never has rules of its own to drift
from the dispatcher's. A view is all it is: nothing reads it back.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_page import STALE_AFTER, render  # noqa: E402
from factory_common import PAUSE_FILE, STATE_DIR, Profile, conversation_url, load_repo_secrets, split_name  # noqa: E402
from factory_dispatch import (  # noqa: E402
    DONE, DROPPED_STATE, MERGED, PENDING, VERSION, Cleanup, QueueEmpty, Reinstruct, ReviewIdle,
    ReviewOff, SendEvent, StartSplit, StartStep, Step, World, _alive, _eligible_step, _first_open,
    _issues_started_since, card_steps, display_name, slots_held, step_all_prs, step_prs,
)

STATUS_FILE = STATE_DIR / "status.json"
# The page alone, in a folder of its own: whatever serves it serves nothing else of the state.
PAGE_FILE = STATE_DIR / "www" / "index.html"
SCHEMA = 1

# What a step is doing, from the developer's side.
WORKING, WAITS_YOU, WAITS_CI, WAKING, RESTARTING, STARTING, QUEUED, NO_WORKER, LATER = (
    "working", "waits-you", "waits-ci", "waking", "restarting", "starting", "queued", "no-worker", "later")


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None


def _pr(p) -> dict:
    return {"number": p.number, "url": p.url, "state": p.state, "ci": p.ci, "failing": list(p.failing),
            "conflicting": p.conflicting, "head": p.head}


def activity(step: Step, world: World, actions: list, eligible: Step | None) -> str:
    """One word for what the step is doing now. An idle worker on an unfinished step has pinged
    and waits — for CI if its PR's checks are still running, else for the developer — unless this
    dispatch just sent it an event."""
    if step.state in (DONE, DROPPED_STATE):
        return step.state
    if any(isinstance(a, StartStep) and a.step.worker == step.worker for a in actions):
        return STARTING
    info = world.workers.get(step.worker)
    if info is None or info.get("status") == "dead":
        if step.state == PENDING:
            return QUEUED if step is eligible else LATER
        return NO_WORKER
    status = info.get("status")
    if status == "restarting":
        return RESTARTING
    if status != "idle":
        return WORKING
    if any(isinstance(a, SendEvent) and a.worker == step.worker for a in actions):
        return WAKING
    pr, _ = step_prs(world.prs, step.branch)
    if step.pr_number:
        pr = next((p for p in world.prs if p.number == step.pr_number), pr)
    if step.state != MERGED and pr is not None and pr.state == "OPEN" and pr.ci == "pending":
        return WAITS_CI
    return WAITS_YOU


def describe(action) -> str | None:
    """An action in a line a person reads; bookkeeping (MarkSent, Unsent) says nothing."""
    if isinstance(action, StartSplit):
        return f"started the split of {action.card.name}"
    if isinstance(action, StartStep):
        verb = f"replaced the worker ({action.recovered})" if action.recovered else "started"
        return f"{verb}: {display_name(action.step.card, action.step, len(action.step.card.items or ()))}"
    if isinstance(action, SendEvent):
        return f"{action.worker} ← {action.text.removeprefix('Factory event: ')}"
    if isinstance(action, Reinstruct):
        return f"{action.step.worker} ← updated instructions"
    if isinstance(action, ReviewIdle):
        return f"review mode off for {action.branch} (you left)"
    if isinstance(action, ReviewOff):
        return f"review mode off for {action.branch} (no PR left)"
    if isinstance(action, QueueEmpty):
        return f"{'issue' if action.issues else 'card'} queue empty ({action.busy}/{action.wip} busy)"
    if isinstance(action, Cleanup):
        return f"cleaned up {action.worker or action.branch}"
    return None


def snapshot(world: World, actions: list, failed: list = (), conversations: dict | None = None) -> dict:
    """The status as plain JSON: pools, every ready card and issue with its steps, what needs the
    developer, and what this dispatch did. Pure: `conversations` (worker → link) comes in."""
    conversations = conversations or {}
    all_steps = {c.short: card_steps(c, world) for c in world.cards if c.items is not None}
    items, attention = [], []
    for card in world.cards:
        entry = {"kind": "issue" if card.issue is not None else "card", "short": card.short,
                 "name": card.name, "url": card.url, "ready": card.ready, "issue": card.issue}
        if card.items is None:
            if not card.ready:
                continue
            split = split_name(card.short)
            entry["split"] = {"worker": split, "alive": _alive(world, split),
                              "starting": any(isinstance(a, StartSplit) and a.card.short == card.short
                                              for a in actions),
                              "conversation": conversations.get(split)}
            entry["steps"] = []
            items.append(entry)
            continue
        steps = all_steps[card.short]
        if not card.ready and not any(_alive(world, s.worker) for s in steps):
            continue
        eligible = _eligible_step(steps) if _first_open(steps) is not None else None
        entry["steps"] = []
        for s in steps:
            info = world.workers.get(s.worker)
            prs = step_all_prs(s, world.prs)
            reviews = {b: n for b, n in world.reviews.items() if b == s.branch or b.startswith(s.fix_prefix)}
            row = {
                "n": s.n, "total": len(steps), "name": s.item.name, "title": display_name(card, s, len(steps)),
                "state": s.state, "activity": activity(s, world, actions, eligible),
                "worker": s.worker, "worker_status": info.get("status") if info else None,
                "conversation": conversations.get(s.worker), "branch": s.branch, "adopted": s.pr_number,
                "prs": [_pr(p) for p in prs],
                "review_queued": sum(reviews.values()) if reviews else None,
                "developer_seen": _iso(world.presence.get(s.worker)),
            }
            entry["steps"].append(row)
            if row["activity"] == WAITS_YOU:
                attention.append({"why": "waits for you", "title": row["title"], "worker": s.worker,
                                  "conversation": row["conversation"]})
            elif row["activity"] == NO_WORKER:
                attention.append({"why": "under way with no worker — waits for a free slot",
                                  "title": row["title"], "worker": s.worker, "conversation": None})
        items.append(entry)
    for action, exc in failed:
        attention.append({"why": f"failed: {describe(action) or type(action).__name__}: "
                                 f"{(str(exc).splitlines() or [''])[0][:300]}",
                          "title": None, "worker": None, "conversation": None})
    return {
        "schema": SCHEMA,
        "paused": False,
        "version": VERSION,
        "at": _iso(world.now),
        "pools": {
            "cards": {"busy": slots_held(world, all_steps, False), "wip": world.wip},
            "issues": {"busy": slots_held(world, all_steps, True), "wip": world.issue_wip,
                       "today": (_issues_started_since(world, all_steps, world.now - timedelta(days=1))
                                 if world.now else None),
                       "per_day": world.issue_daily},
        },
        "attention": attention,
        "items": items,
        "dispatch": [line for a in actions if (line := describe(a))],
    }


def conversations_of(world: World) -> dict:
    """Each running worker's Remote Control link, read from its transcript."""
    return {n: conversation_url(i.get("sessionId")) for n, i in world.workers.items() if i.get("pid")}


def dispatch_status(world: World, actions: list, failed: list) -> dict:
    """The snapshot a dispatch writes once it has acted."""
    return snapshot(world, actions, failed, conversations_of(world))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def write_status(status: dict, path: Path = STATUS_FILE, page: Path = PAGE_FILE) -> None:
    """The snapshot, and the page rendered from it."""
    _write(path, json.dumps(status, indent=1, ensure_ascii=False))
    _write(page, render(status))


def mark_paused(path: Path = STATUS_FILE, page: Path = PAGE_FILE) -> None:
    """A paused dispatch acts on nothing and writes no snapshot; the last one says it is paused,
    so the page reads paused rather than stale. Resuming, the next dispatch writes a fresh one."""
    if not path.is_file():
        return
    status = json.loads(path.read_text())
    if not status.get("paused"):
        write_status({**status, "paused": True}, path, page)


def read_status(path: Path = STATUS_FILE, now: datetime | None = None) -> dict | None:
    """The last snapshot, with what only the reader knows: paused now, and how old it is."""
    if not path.is_file():
        return None
    status = json.loads(path.read_text())
    now = now or datetime.now(timezone.utc)
    at = datetime.fromisoformat(status["at"]) if status.get("at") else None
    status["paused"] = PAUSE_FILE.exists()
    status["age_seconds"] = int((now - at).total_seconds()) if at else None
    return status


def _ago(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 90 * 60:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


_ORDER = [WAITS_YOU, NO_WORKER, WAKING, WAITS_CI, WORKING, RESTARTING, STARTING, QUEUED]


def summary(status: dict) -> str:
    """The snapshot as a person reads it: the header, what needs them, then every step under way."""
    head = f"factory {status.get('version', '?')} · {_ago(status.get('age_seconds'))}"
    if status.get("paused"):
        head += " · PAUSED"
    if (status.get("age_seconds") or 0) > STALE_AFTER and not status.get("paused"):
        head += " · STALE (is the timer running?)"
    cards, issues = status["pools"]["cards"], status["pools"]["issues"]
    pools = f"cards {cards['busy']}/{cards['wip']} · issues {issues['busy']}/{issues['wip']}"
    if issues.get("per_day") is not None:
        pools += f" · {issues['today']}/{issues['per_day']} issue steps today"
    lines = [head, pools]
    if status["attention"]:
        lines += ["", "Needs you"]
        for a in status["attention"]:
            title = (a["title"] or "").removeprefix("factory · ")
            lines.append(f"  {title + ' — ' if title else ''}{a['why']}"
                         + (f"  {a['conversation']}" if a.get("conversation") else ""))
    rows = []
    for item in status["items"]:
        if "split" in item:
            split = item["split"]
            word = WORKING if split["alive"] else STARTING if split["starting"] else QUEUED
            rows.append((word, f"  {item['name']} · split — {word}"))
        for s in item["steps"]:
            if s["activity"] in (DONE, DROPPED_STATE, LATER):
                continue
            prs = ", ".join(f"PR #{p['number']} {p['state'].lower()}"
                            + (f" ci {p['ci']}" if p["state"] == "OPEN" and p["ci"] else "")
                            + (" conflict" if p["conflicting"] else "") for p in s["prs"])
            extra = [x for x in (prs, f"{s['review_queued']} queued" if s["review_queued"] else "") if x]
            rows.append((s["activity"], f"  {s['title'].removeprefix('factory · ')} — {s['activity']}"
                                        + (f" · {' · '.join(extra)}" if extra else "")))
    if rows:
        rows.sort(key=lambda r: _ORDER.index(r[0]) if r[0] in _ORDER else len(_ORDER))
        lines += ["", "Steps"] + [r[1] for r in rows]
    if status["dispatch"]:
        lines += ["", "Last dispatch"] + [f"  {d}" for d in status["dispatch"]]
    return "\n".join(lines)


def live(repo: Path) -> dict:
    """A snapshot of now, decided but not acted on: what the next dispatch would do."""
    from factory_dispatch import decide, load_world
    load_repo_secrets(repo)
    world = load_world(repo, Profile.load(repo), record=False)
    status = snapshot(world, decide(world), conversations=conversations_of(world))
    status["dispatch"] = [f"would: {d}" for d in status["dispatch"]]
    status["paused"], status["age_seconds"] = PAUSE_FILE.exists(), 0
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description="What the factory is doing, as the last dispatch saw it.")
    ap.add_argument("--json", action="store_true", help="print the snapshot as JSON")
    ap.add_argument("--html", action="store_true", help="print the status page")
    ap.add_argument("--live", type=Path, metavar="REPO", help="look now instead of reading the last snapshot")
    args = ap.parse_args()
    status = live(args.live.resolve()) if args.live else read_status()
    if status is None:
        print(f"factory-status: no snapshot yet ({STATUS_FILE}) — has a dispatch run? "
              "Try --live <repo>.", file=sys.stderr)
        return 2
    print(json.dumps(status, indent=1, ensure_ascii=False) if args.json
          else render(status) if args.html else summary(status))
    return 0


if __name__ == "__main__":
    sys.exit(main())
