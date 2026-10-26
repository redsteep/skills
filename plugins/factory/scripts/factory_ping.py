#!/usr/bin/env python3
"""factory-ping: a worker tells the developer it waits on them — a Slack DM from a bot, with a
link to the worker's conversation. At most once per reason per step: a replacement worker with
the same name does not ping the same reason again.

    factory-ping --worker <name> "<one-line reason>"

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
from factory_common import Profile, live_workers, load_repo_secrets, run, sent_store  # noqa: E402

FALLBACK_URL = "https://claude.ai/code"


def ping_key(worker: str, reason: str) -> str:
    return f"ping:{worker}:{reason.strip()}"


def message(worker: str, reason: str, url: str) -> str:
    # Slack mrkdwn, not markdown: *bold*, <url|text>.
    return f"*{worker}* — {reason.strip()}\n<{url}|Open the conversation>"


def session_url(worker: str) -> str:
    """The worker's Remote Control link, read from its own terminal output."""
    agent = live_workers().get(worker)
    if not agent:
        return FALLBACK_URL
    logs = run(["claude", "logs", agent["id"]], check=False)
    found = re.findall(r"https://claude\.ai/code/session_[A-Za-z0-9]+", logs)
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


def send(worker: str, reason: str, post) -> bool:
    """Post unless this reason was already pinged for this step; True when posted."""
    key = ping_key(worker, reason)
    with sent_store() as sent:
        if key in sent:
            return False
        post(message(worker, reason, session_url(worker)))
        sent.add(key)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Slack-DM the developer that a factory worker waits on them.")
    ap.add_argument("--worker", default=os.environ.get("FACTORY_WORKER"), required=not os.environ.get("FACTORY_WORKER"))
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

    posted = send(args.worker, args.reason, post)
    print("factory-ping: sent" if posted else "factory-ping: already sent for this step, skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
