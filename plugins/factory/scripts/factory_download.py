#!/usr/bin/env python3
"""factory-download: fetch a card's uploaded attachments (screenshots, mockups) to read them.

A worker can't: the claude.ai Trello connector lists attachments but has no download, and the
Trello token in a worker's environment is the background daemon's, frozen at its start — stale
once rotated (a worker on card r9LYqECY got 401s and specced a dialog without its screenshots).
So, like factory-attach, this reads the factory's own keys from `<repo>/.env`, which wins.
Downloads take the OAuth header: the `?key=&token=` query that the rest of the API accepts is
refused on attachment files.

    factory-download --repo <repo> --card <card id> --out <dir>

Prints one saved path per line. Link attachments (a URL pasted on the card) are not files; they
are listed as `link <url>` for the worker to open itself.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_attach import trello  # noqa: E402
from factory_common import load_repo_secrets  # noqa: E402


def fetch(url: str) -> bytes:
    auth = (f'OAuth oauth_consumer_key="{os.environ["TRELLO_API_KEY"]}", '
            f'oauth_token="{os.environ["TRELLO_TOKEN"]}"')
    req = urllib.request.Request(url, headers={"Authorization": auth})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def download(card: str, out: Path, call=trello, get=fetch) -> list[str]:
    """Save each uploaded attachment of `card` under `out`; returns what was saved or linked."""
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    for a in call("GET", f"cards/{card}/attachments") or []:
        if not a.get("isUpload"):
            lines.append(f"link {a.get('url', '')}")
            continue
        name = re.sub(r"[^\w.-]+", "_", a.get("fileName") or a.get("name") or a["id"])
        path = out / f"{a['id'][-6:]}-{name}"
        path.write_bytes(get(a["url"]))
        lines.append(str(path))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a Trello card's uploaded attachments.")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--card", required=True, help="the card's id or short link")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    load_repo_secrets(args.repo, override=True)
    print("\n".join(download(args.card, args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
