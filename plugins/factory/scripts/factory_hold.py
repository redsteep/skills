#!/usr/bin/env python3
"""factory-hold: put a card on hold (postpone it), or take it off hold.

On hold, the dispatcher starts nothing of the card, shelves its idle workers — stopped, not
removed — and cleans up nothing: the branch, the spec, the brief and each worker's conversation
stay as they are. Off hold, the card's next step resumes the shelved conversation where it was.
This script only sets the label (the profile's `## Trello` → `Hold label`, default `on hold`);
adding or removing it by hand on the board does the same.

The worker runs it when the developer tells it to postpone the card: a worker never holds the
Trello token, so the factory's own keys are read from `<repo>/.env`, as factory-attach does.

    factory-hold --repo <repo> --card <card id or short link> [--off]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import Profile, load_repo_secrets  # noqa: E402


def trello(method: str, path: str, **params):
    params |= {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}
    req = urllib.request.Request(f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(params)}",
                                 method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or "null")


def set_hold(card: str, name: str, on: bool, call=trello) -> str:
    """Add or remove the label called `name` on the card; the board gets the label if it lacks it."""
    current = call("GET", f"cards/{card}", fields="idBoard,idLabels")
    labels = call("GET", f"boards/{current['idBoard']}/labels", fields="name")
    label = next((l for l in labels if (l.get("name") or "").casefold() == name.casefold()), None)
    has = label is not None and label["id"] in current["idLabels"]
    if on and not has:
        if label is None:
            label = call("POST", "labels", name=name, color="sky", idBoard=current["idBoard"])
        call("POST", f"cards/{card}/idLabels", value=label["id"])
        return f"on hold: `{name}` added"
    if not on and has:
        call("DELETE", f"cards/{card}/idLabels/{label['id']}")
        return f"off hold: `{name}` removed"
    return f"already {'on' if on else 'off'} hold"


def main() -> int:
    ap = argparse.ArgumentParser(description="Put a card on hold, or take it off hold.")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--card", required=True, help="the card's id or short link")
    ap.add_argument("--off", action="store_true", help="take the card off hold")
    args = ap.parse_args()
    load_repo_secrets(args.repo, override=True)
    name = Profile.load(args.repo).get("Trello", "Hold label", "on hold") or "on hold"
    print(set_hold(args.card, name, not args.off))
    return 0


if __name__ == "__main__":
    sys.exit(main())
