#!/usr/bin/env python3
"""factory-ping: a worker tells the developer it waits on them, or (`--done`) that it did
something on its own -- a Slack DM from a bot. The message names what the worker works on (env
the title the dispatcher recorded at launch) and links the PR the reason names and the worker's
conversation. At most once per reason per step: a replacement worker with the same name does not
ping the same reason again.

    factory-ping [--done] --worker <name> "<one-line reason>"
    factory-ping --factory "<one-line notice>"      # about the factory itself, from the dispatcher

Env: FACTORY_SLACK_TOKEN (optional — without it nothing is sent; a bot token, since a DM from the
developer's own user would not notify them; read from <repo>/.env if not in the environment),
FACTORY_REPO (set by the dispatcher). The developer's Slack id comes from the profile.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import (  # noqa: E402
    Profile, conversation_url, live_workers, load_repo_secrets, run, sent_store, worker_title,
)

FALLBACK_URL = "https://claude.ai/code"


def ping_key(worker: str, reason: str) -> str:
    return f"ping:{worker}:{reason.strip()}"


_PR = re.compile(r"\bPR #(\d+)")


def message(reason: str, title: str, url: str, pr_url: str | None = None, done: bool = False) -> str:
    """Slack mrkdwn, not markdown: *bold*, <url|text>. What happened first, then what it is about,
    then where to look."""
    head = "✅ *Done*" if done else "👋 *Needs you*"
    links = ([f"<{pr_url}|PR #{_PR.search(reason)[1]}>"] if pr_url else []) + [f"<{url}|Open the conversation>"]
    return f"{head} — {reason.strip()}\n{title}\n{'  ·  '.join(links)}"


def factory_message(notice: str) -> str:
    return f"📭 *Queue empty* — {notice.strip()}"


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
    url = conversation_url(agent.get("sessionId"))
    if url:
        return url
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


def send(worker: str, reason: str, post, done: bool = False) -> bool:
    """Post unless this reason was already pinged for this step; True when posted."""
    key = ping_key(worker, reason)
    with sent_store() as sent:
        if key in sent:
            return False
        title = worker_title(worker) or worker
        post(message(reason, title, session_url(worker), pr_url(reason), done))
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
    token = os.environ.get("FACTORY_SLACK_TOKEN")
    if not token:
        # Slack is optional: without a token the worker still waits; the developer sees it in
        # the Claude app's session list instead of a DM.
        print("factory-ping: no FACTORY_SLACK_TOKEN — Slack skipped; the session waits for you in the Claude app")
        return 0
    profile = Profile.load(repo)
    user = profile.require("Settings", "Slack user")

    def post(text: str) -> None:
        channel = slack(token, "conversations.open", {"users": user})["channel"]["id"]
        slack(token, "chat.postMessage", {"channel": channel, "text": text, "unfurl_links": False})

    if args.factory:
        post(factory_message(args.reason))
        print("factory-ping: sent")
        return 0
    posted = send(args.worker, args.reason, post, args.done)
    print("factory-ping: sent" if posted else "factory-ping: already sent for this step, skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
