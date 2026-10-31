#!/usr/bin/env python3
"""factory-ping: a worker tells the developer it waits on them, or (`--done`) that it did
something on its own. The message names what the worker works on (the title the dispatcher
recorded at launch) and links the PR the reason names and the worker's conversation. At most once
per reason per step: a replacement worker with the same name does not ping the same reason again.

    factory-ping [--done] --worker <name> "<one-line reason>"
    factory-ping --factory "<one-line notice>"      # about the factory itself, from the dispatcher

Two channels, and a project picks one in its profile:

- **`Settings` → `Ping command`** — any command. It gets the message as plain text on **stdin**
  and `FACTORY_PING_KIND` (`needs-you` | `done` | `factory`), `FACTORY_PING_WORKER`,
  `FACTORY_PING_URL` and `FACTORY_PING_PR` in its environment, and runs with the repository as
  its working directory. This is the channel to declare when the project has a bot of its own —
  Telegram, a desktop notifier, a webhook. It wins over Slack when both are configured.
- **Slack** — `FACTORY_SLACK_TOKEN` (a bot token: a DM from the developer's own user would not
  notify them; read from <repo>/.env when absent from the environment) plus `Settings` →
  `Slack user`.

With neither, nothing is sent and the worker's question waits in the Claude app — which is
silent, so a project that runs unattended wants one of the two. `FACTORY_REPO` is set by the
dispatcher.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import subprocess
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import (  # noqa: E402
    Profile, live_workers, load_repo_secrets, run, sent_store, transcript_of, worker_title,
)

FALLBACK_URL = "https://claude.ai/code"


def ping_key(worker: str, reason: str) -> str:
    return f"ping:{worker}:{reason.strip()}"


_PR = re.compile(r"\bPR #(\d+)")


_HEAD = {False: ("👋", "Needs you"), True: ("✅", "Done")}


def message(reason: str, title: str, url: str, pr_url: str | None = None, done: bool = False) -> str:
    """Slack mrkdwn, not markdown: *bold*, <url|text>. What happened first, then what it is about,
    then where to look."""
    icon, word = _HEAD[done]
    links = ([f"<{pr_url}|PR #{_PR.search(reason)[1]}>"] if pr_url else []) + [f"<{url}|Open the conversation>"]
    return f"{icon} *{word}* — {reason.strip()}\n{title}\n{'  ·  '.join(links)}"


def plain_message(reason: str, title: str, url: str, pr_url: str | None = None, done: bool = False) -> str:
    """The same three lines without Slack's markup, for a `Ping command` channel. Every link on
    its own line: a client that auto-links bare URLs finds them, and one that does not still
    shows something a human can copy."""
    icon, word = _HEAD[done]
    links = ([pr_url] if pr_url else []) + [url]
    return f"{icon} {word} — {reason.strip()}\n{title}\n" + "\n".join(links)


def factory_message(notice: str) -> str:
    return f"📭 *Queue empty* — {notice.strip()}"


def plain_factory_message(notice: str) -> str:
    return f"📭 Queue empty — {notice.strip()}"


def pr_url(reason: str) -> str | None:
    """The URL of the PR the reason names (`PR #12 …`), if any."""
    m = _PR.search(reason)
    return run(["gh", "pr", "view", m[1], "--json", "url", "-q", ".url"], check=False).strip() or None if m else None


def session_url(worker: str) -> str:
    """The worker's Remote Control link. Its transcript records it for good (`bridge_status`,
    `remote_session_change`); its terminal output, the fallback, keeps only the recent part."""
    agent = live_workers().get(worker)
    if not agent:
        return FALLBACK_URL
    path = transcript_of(agent.get("sessionId") or "")
    found = []
    if path:
        for line in path.read_text().splitlines():
            if '"bridge_status"' in line or '"remote_session_change"' in line:
                found += re.findall(r"https://claude\.ai/code/session_[A-Za-z0-9]+", line)
    if not found:
        found = re.findall(r"https://claude\.ai/code/session_[A-Za-z0-9]+",
                           run(["claude", "logs", agent["id"]], check=False)) if agent.get("id") else []
    return found[-1] if found else FALLBACK_URL


def slack(token: str, method: str, payload: dict) -> dict:
    req = urllib.request.Request(f"https://slack.com/api/{method}", data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read())
    if not body.get("ok"):
        raise RuntimeError(f"slack {method}: {body.get('error')}")
    return body


def ping_command(command: str, repo: Path, text: str, *, kind: str, worker: str = "",
                 url: str = "", pr: str = "") -> None:
    """Run the project's `Ping command` with the message on stdin. A non-zero exit raises, so the
    reason is not recorded as sent and the next worker on the same reason tries again — a ping
    nobody received must not count as delivered."""
    env = {**os.environ, "FACTORY_PING_KIND": kind, "FACTORY_PING_WORKER": worker,
           "FACTORY_PING_URL": url, "FACTORY_PING_PR": pr or ""}
    done = subprocess.run(["bash", "-c", command], input=text, text=True, cwd=repo, env=env,
                          capture_output=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(f"ping command exited {done.returncode}: "
                           f"{(done.stderr or done.stdout).strip()[:300]}")


def send(worker: str, reason: str, post, done: bool = False, fmt=message) -> bool:
    """Post unless this reason was already pinged for this step; True when posted."""
    key = ping_key(worker, reason)
    with sent_store() as sent:
        if key in sent:
            return False
        title = worker_title(worker) or worker
        url, pr = session_url(worker), pr_url(reason)
        post(fmt(reason, title, url, pr, done), url=url, pr=pr)
        sent.add(key)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Slack-DM the developer that a factory worker waits on them.")
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--worker")
    who.add_argument("--factory", action="store_true", help="a notice from the dispatcher; the caller dedupes")
    ap.add_argument("--done", action="store_true", help="something the worker did on its own, for information")
    ap.add_argument("reason")
    args = ap.parse_args()
    repo = Path(os.environ.get("FACTORY_REPO", "."))
    load_repo_secrets(repo)
    profile = Profile.load(repo)
    command = (profile.get("Settings", "Ping command", "") or "").strip("`")
    token = os.environ.get("FACTORY_SLACK_TOKEN")
    kind = "factory" if args.factory else ("done" if args.done else "needs-you")

    if command:
        # A project's own channel wins: it was declared on purpose, and a Slack token may be
        # lying around from an earlier setup.
        fmt, factory_fmt = plain_message, plain_factory_message

        def post(text: str, url: str = "", pr: str = "") -> None:
            ping_command(command, repo, text, kind=kind, worker=args.worker or "", url=url, pr=pr)
    elif token:
        user = profile.require("Settings", "Slack user")
        fmt, factory_fmt = message, factory_message

        def post(text: str, url: str = "", pr: str = "") -> None:
            channel = slack(token, "conversations.open", {"users": user})["channel"]["id"]
            slack(token, "chat.postMessage", {"channel": channel, "text": text, "unfurl_links": False})
    else:
        # Both are optional: without either the worker still waits, and the developer sees it in
        # the Claude app's session list — which notifies nobody, so an unattended factory should
        # declare one. Measured 2026-10-31: a handoff's question sat unseen for five hours.
        print("factory-ping: no `Settings` → `Ping command` and no FACTORY_SLACK_TOKEN — "
              "nothing sent; the session waits for you in the Claude app")
        return 0

    if args.factory:
        post(factory_fmt(args.reason))
        print("factory-ping: sent")
        return 0
    posted = send(args.worker, args.reason, post, args.done, fmt)
    print("factory-ping: sent" if posted else "factory-ping: already sent for this step, skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
