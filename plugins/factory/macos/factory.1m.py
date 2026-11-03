#!/usr/bin/env python3
# <xbar.title>factory</xbar.title>
# <xbar.desc>What the factory waits on you for, from its status page's status.json.</xbar.desc>
# <xbar.dependencies>python3, curl</xbar.dependencies>
"""The factory in the Mac menu bar: a SwiftBar (or xbar) plugin that reads the status.json the
dispatcher writes beside its status page, once a minute (the `1m` in the file name).

The title is how many things wait for you; the menu lists them — each opens the worker's
conversation — then every step under way, the slots, and the status page itself. Logic none: the
snapshot already says it all; this only prints it the way SwiftBar reads a menu.

Where the page is served (README, *Status page*): `FACTORY_URL` in the environment, or the
first line of `~/.config/factory/menubar-url`, e.g. `https://box.tailnet.ts.net`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path.home() / ".config/factory/menubar-url"
STALE_AFTER = 10 * 60
ICON = "🏭"

LABEL = {
    "waits-you": "waits for you", "no-worker": "no worker", "waking": "hearing an event",
    "waits-ci": "waits for CI", "working": "working", "restarting": "restarting",
    "starting": "starting", "queued": "queued",
}
ORDER = list(LABEL)


def base_url() -> str | None:
    url = os.environ.get("FACTORY_URL") or os.environ.get("VAR_FACTORY_URL")
    if not url and CONFIG.is_file():
        url = (CONFIG.read_text().splitlines() or [""])[0]
    url = (url or "").strip().rstrip("/")
    return url or None


def _clean(text: str) -> str:
    """A menu line's text: `|` starts SwiftBar's parameters, and a newline ends the line."""
    return " ".join(str(text).replace("|", "¦").split())


def item(text: str, **params) -> str:
    extra = " ".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    return _clean(text) + (f" | {extra}" if extra else "")


def _ago(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 90 * 60:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


def menu(status: dict | None, url: str, now: datetime, error: str = "") -> list[str]:
    """The plugin's output, line by line: the title first, then `---` and the menu."""
    page = item("Open the status page", href=url + "/")
    if status is None:
        return [f"{ICON} ?", "---", item(f"Can't read {url}/status.json"),
                item(error or "no answer", color="gray"), page, item("Refresh", refresh="true")]
    at = datetime.fromisoformat(status["at"]) if status.get("at") else None
    age = int((now - at).total_seconds()) if at else None
    paused = bool(status.get("paused"))
    stale = not paused and age is not None and age > STALE_AFTER
    attention = status.get("attention") or []

    title = ICON + (f" {len(attention)}" if attention else "")
    title += " ⏸" if paused else " ⚠" if stale else ""
    lines = [title, "---"]

    if attention:
        lines.append(item("Needs you", color="gray"))
        for a in attention:
            what = (a.get("title") or "").removeprefix("factory · ")
            lines.append(item(f"{what} — {a['why']}" if what else a["why"], href=a.get("conversation")))
        lines.append("---")

    rows = []
    for it in status.get("items") or []:
        name = f"#{it['issue']} {it['name']}" if it.get("issue") is not None else it["name"]
        split = it.get("split")
        if split:
            rows.append((split.get("activity", "queued"), f"{name} · {split.get('phase', 'split')}",
                         split.get("conversation") or it.get("url")))
        for s in it.get("steps") or []:
            if s["activity"] not in LABEL:
                continue
            open_pr = next((p for p in s.get("prs") or [] if p["state"] == "OPEN"), None)
            ci = f" · CI {open_pr['ci']}" if open_pr and open_pr.get("ci") else ""
            rows.append((s["activity"], f"{name} · {s['n']}/{s['total']} — {LABEL[s['activity']]}{ci}",
                         s.get("conversation") or (open_pr or {}).get("url") or it.get("url")))
    if rows:
        rows.sort(key=lambda r: ORDER.index(r[0]) if r[0] in ORDER else len(ORDER))
        lines.append(item(f"Steps ({len(rows)})", color="gray"))
        lines += [item(text, href=href) for _, text, href in rows]
        lines.append("---")

    pools = status.get("pools") or {}
    cards, issues = pools.get("cards") or {}, pools.get("issues") or {}
    lines.append(item(f"Cards {cards.get('busy', 0)}/{cards.get('wip', 0)} · "
                      f"issues {issues.get('busy', 0)}/{issues.get('wip', 0)}", color="gray"))
    when = "paused" if paused else ("updated " + _ago(age) if age is not None else "")
    if stale:
        when += " — stale: is the timer running?"
    if when:
        lines.append(item(when.capitalize() if paused else when, color="red" if stale else "gray"))
    lines += [page, item("Refresh", refresh="true")]
    return lines


def fetch(url: str) -> dict:
    """curl, not urllib: the system's own, with the system's certificates."""
    out = subprocess.run(["curl", "-fsS", "--max-time", "10", url + "/status.json"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"curl exited {out.returncode}")
    return json.loads(out.stdout)


def main() -> int:
    url = base_url()
    if url is None:
        print("\n".join([f"{ICON} ?", "---", item(f"Set FACTORY_URL, or write the page's URL to {CONFIG}")]))
        return 0
    try:
        status, error = fetch(url), ""
    except Exception as exc:  # the menu says what went wrong; a plugin that exits shows nothing
        status, error = None, str(exc)
    print("\n".join(menu(status, url, datetime.now(timezone.utc), error)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
