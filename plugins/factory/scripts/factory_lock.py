#!/usr/bin/env python3
"""factory-lock: one worker at a time through a phase that shares a single resource — the
post-merge handoff (one QA browser session, fixed ports) and the migration round-trip (one test
Postgres). Held across many tool calls, so it is a named lock with an owner, not a flock.

    factory-lock acquire <handoff|migration>   # waits; prints when held
    factory-lock release <handoff|migration>

The owner is $FACTORY_WORKER. A lock whose owner is no longer a live session is stale and taken over.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory_common  # noqa: E402

NAMES = {"handoff", "migration"}
POLL_SECONDS = 20


def lock_file(name: str) -> Path:
    return factory_common.STATE_DIR / "locks" / name


def try_acquire(name: str, owner: str, is_live) -> str | None:
    """Take the lock for `owner`; return None when held, else the owner holding it."""
    path = lock_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, owner.encode())
        os.close(fd)
        return None
    except FileExistsError:
        holder = path.read_text().strip()
        if holder == owner:
            return None
        if not is_live(holder):
            path.unlink(missing_ok=True)
            return try_acquire(name, owner, is_live)
        return holder


def release(name: str, owner: str) -> bool:
    path = lock_file(name)
    if path.exists() and path.read_text().strip() == owner:
        path.unlink()
        return True
    return False


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"acquire", "release"} or sys.argv[2] not in NAMES:
        print(__doc__, file=sys.stderr)
        return 2
    action, name = sys.argv[1], sys.argv[2]
    owner = os.environ.get("FACTORY_WORKER")
    if not owner:
        print("factory-lock: FACTORY_WORKER is not set", file=sys.stderr)
        return 2
    if action == "release":
        print("released" if release(name, owner) else "not held by you")
        return 0
    announced = False
    while (holder := try_acquire(name, owner, lambda w: w in factory_common.live_workers())) is not None:
        if not announced:
            print(f"factory-lock: {name} held by {holder}, waiting…", flush=True)
            announced = True
        time.sleep(POLL_SECONDS)
    print(f"factory-lock: {name} held by you — release it when the phase ends")
    return 0


if __name__ == "__main__":
    sys.exit(main())
