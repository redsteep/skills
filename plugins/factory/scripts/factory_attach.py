#!/usr/bin/env python3
"""factory-attach: put a card's approved brief on the Trello card, as an attachment.

The claude.ai Trello connector has no attachment action, and a worker never holds the Trello
token, so the upload is this script's: it reads the factory's own keys from `<repo>/.env`, the
way factory-ping reads the Slack one. `.env` wins over the environment here: a worker's
environment is the background daemon's, frozen at the daemon's start, and a token rotated since
reaches it stale (measured: the old Trello MCP server's 401s).

One attachment per name: an earlier upload under the same name is replaced, so an amended brief
does not leave the old one beside it.

    factory-attach --repo <repo> --card <card id> <file> [--name card-brief.md]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import load_repo_secrets  # noqa: E402


def trello(method: str, path: str, body: bytes | None = None, content_type: str | None = None):
    auth = {"key": os.environ["TRELLO_API_KEY"], "token": os.environ["TRELLO_TOKEN"]}
    req = urllib.request.Request(f"https://api.trello.com/1/{path}?{urllib.parse.urlencode(auth)}",
                                 data=body, method=method)
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read() or "null")


def multipart(name: str, content: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{name}\r\n'.encode(),
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
         f"Content-Type: text/markdown\r\n\r\n").encode() + content + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def attach(card: str, name: str, content: bytes, call=trello) -> str:
    """Replace the card's attachment called `name` with `content`; returns the new one's URL."""
    for old in call("GET", f"cards/{card}/attachments") or []:
        if old.get("name") == name:
            call("DELETE", f"cards/{card}/attachments/{old['id']}")
    body, content_type = multipart(name, content)
    return call("POST", f"cards/{card}/attachments", body, content_type)["url"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Put a card's approved brief on the Trello card.")
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--card", required=True, help="the card's id or short link")
    ap.add_argument("--name", default="card-brief.md")
    ap.add_argument("file", type=Path)
    args = ap.parse_args()
    load_repo_secrets(args.repo, override=True)
    print(attach(args.card, args.name, args.file.read_bytes()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
