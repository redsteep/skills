#!/usr/bin/env python3
"""PreToolUse(Bash) hook: a factory worker writes to production only on the developer's own word,
through the one command the project declares -- and through nothing else that could write.

A worker reads production freely (that is how it checks its own work) and writes nothing. But
"writes nothing" was never enforced: the runner deny list matches the text of a command, so a
script that reaches the cloud *inside* itself slips past it, and a worker that wanted to could
take the credentials out of the project's own connection helper and run whatever it liked. What
stopped that was the prompt and the worker's judgement. This hook is the enforcement.

The project declares in `## Prod writes`:

- **Command:** the one write path -- a script of the project's own, which decides what a safe
  write looks like there (a transaction, a row count, a log).
- **Word:** what the developer types to authorise one run. Default `PROD OK`.
- bare bullets: routes that can write, or hand out the credentials to write, and are therefore
  closed to a worker outright.

The word is read where an `LGTM` is read -- this session's transcript, and only a message the
developer typed there -- and it authorises **one** run: the next write asks again. That is the
whole point of "by my explicit command": a standing permission is not a command.

Two rails stay here, because no project may relax them:

1. **Schema changes go through migrations**, never this door.
2. **An `UPDATE` or `DELETE` with no `WHERE`** is refused.

Outside a worker (no `FACTORY_WORKER`), or with no `## Prod writes` section in the profile, the
hook exits 0 and the session's normal permissions apply.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_common import STATE_DIR, Profile, developer_messages  # noqa: E402

SPENT_FILE = STATE_DIR / "prod-writes.json"
DEFAULT_WORD = "PROD OK"

# Schema is Alembic's (or whatever the project migrates with): a hand-run DDL on production leaves
# the migration history lying about the database, and nothing downstream can tell.
_DDL = re.compile(r"\b(drop\s+(table|column|index|schema|database|type|view|constraint)"
                  r"|truncate\b|alter\s+(table|column|type|sequence)"
                  r"|create\s+(table|index|schema|database|type|view)"
                  r"|grant\b|revoke\b)", re.I)
# A write with no predicate hits every row. Even when that is what was meant, it is worth saying so.
_UNSCOPED = re.compile(r"\b(delete\s+from|update)\b", re.I)
_WHERE = re.compile(r"\bwhere\b", re.I)


@dataclass(frozen=True)
class Gate:
    declared: str                      # the one command that may write; "" = nothing declared
    word: str                          # what the developer types to authorise one run
    closed: tuple[str, ...]            # routes closed to a worker outright

    @classmethod
    def from_profile(cls, profile: Profile) -> "Gate":
        return cls(profile.get("Prod writes", "Command", "") or "",
                   (profile.get("Prod writes", "Word", "") or DEFAULT_WORD).strip(),
                   tuple(profile.items("Prod writes")))


def _when(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def authorisation(said: list[tuple[str, str]], word: str, spent: str = "") -> str | None:
    """When the developer last authorised a production write, if that word is still unspent.

    One word, one write: a word already spent on a previous run does not cover the next one. The
    latest message decides, as with an `LGTM` -- so a developer who changes their mind just says
    something else.
    """
    pattern = re.compile(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", re.I)
    for stamp, text in reversed(said):
        if not pattern.search(text):
            continue
        if not stamp:
            return None
        if spent and _when(stamp) <= _when(spent):
            return None
        return stamp
    return None


def verdict(command: str, gate: Gate, said: list[tuple[str, str]], spent: str = ""
            ) -> tuple[str, str, str] | None:
    """`(decision, reason, stamp)` for this command, or None when the hook has no opinion.

    `stamp` is the authorisation the run spends -- the caller records it, so the next write asks
    the developer again.
    """
    if not gate.declared:
        return None
    if gate.declared in command:
        if _DDL.search(command):
            return ("deny", "a schema change does not go through this door — production schema "
                            "moves by migration, so write one and let it deploy", "")
        if _UNSCOPED.search(command) and not _WHERE.search(command):
            return ("deny", "this UPDATE/DELETE has no WHERE and would hit every row — name the "
                            "rows it is meant to touch", "")
        stamp = authorisation(said, gate.word, spent)
        if stamp is None:
            return ("deny", f"a production write needs `{gate.word}` from the developer in this "
                            f"conversation, after you have shown them exactly what you will run. "
                            f"One `{gate.word}` covers one run.", "")
        return ("allow", f"the developer's `{gate.word}` in this conversation covers this run", stamp)
    for route in gate.closed:
        if route in command:
            return ("deny", f"`{route}` is not the door to production — a write goes through "
                            f"`{gate.declared}`, which the developer's word gates", "")
    return None


def _spent(session: str) -> str:
    try:
        return json.loads(SPENT_FILE.read_text()).get(session, "")
    except (OSError, ValueError):
        return ""


def _record(session: str, stamp: str) -> None:
    """Remember the authorisation this run spends. A write we cannot record is denied rather than
    run: an unrecorded one would let a single word authorise every write that follows."""
    SPENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(SPENT_FILE.read_text())
    except (OSError, ValueError):
        current = {}
    current[session] = stamp
    SPENT_FILE.write_text(json.dumps(current, indent=0, sort_keys=True))


def main() -> int:
    if not os.environ.get("FACTORY_WORKER"):
        return 0
    event = json.load(sys.stdin)
    command = (event.get("tool_input") or {}).get("command", "")
    repo = Path(os.environ.get("FACTORY_REPO") or event.get("cwd") or ".")
    gate = Gate.from_profile(Profile.load(repo))
    transcript = Path(event.get("transcript_path") or "/nonexistent")
    session = str(event.get("session_id") or transcript.stem)
    # One lock around read-decide-record: two writes racing on one word would both see it unspent.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / ".prod-writes.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        said = developer_messages(transcript) if transcript.is_file() else []
        answer = verdict(command, gate, said, _spent(session))
        if answer is None:
            return 0
        decision, reason, stamp = answer
        if decision == "allow":
            try:
                _record(session, stamp)
            except OSError as exc:
                decision, reason = "deny", f"could not record the authorisation ({exc}) — not running"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
