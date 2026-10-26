"""Shared by the dispatcher, the auto-merge gate and factory-ping: the profile, the state store,
and the names every part agrees on. Standard library only — the scripts run from a systemd unit
and from hooks, with whatever python3 the box has."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path

STATE_DIR = Path(os.environ.get("FACTORY_STATE_DIR", Path.home() / ".local/state/factory"))
SENT_FILE = STATE_DIR / "sent-events.json"
PAUSE_FILE = STATE_DIR / "PAUSED"

WORKER_PREFIX = "factory-"
BRANCH_PREFIX = "feature/factory-"


# --- names -------------------------------------------------------------------------------
def step_name(card_short: str, n: int) -> str:
    """Worker session, worktree dir and branch suffix of step n (1-based) of a card."""
    return f"{WORKER_PREFIX}{card_short}-s{n}"


def split_name(card_short: str) -> str:
    return f"{WORKER_PREFIX}{card_short}-split"


def step_branch(card_short: str, n: int) -> str:
    return f"feature/{step_name(card_short, n)}"


_WORKER_RE = re.compile(r"^factory-(?P<card>[A-Za-z0-9]+)-(?:s(?P<n>\d+)|(?P<split>split))$")


def parse_worker_name(name: str) -> tuple[str, int | None] | None:
    """`factory-<card>-s<N>` → (card, N); `factory-<card>-split` → (card, None); else None."""
    m = _WORKER_RE.match(name)
    if not m:
        return None
    return m["card"], (int(m["n"]) if m["n"] else None)


# --- profile -------------------------------------------------------------------------------
class Profile:
    """`.claude/factory.md`: `## Section` headings holding `- **Key:** value` bullets and
    bare `` - `value` `` list bullets. Backticks around values are stripped."""

    def __init__(self, text: str, path: Path | None = None):
        self.path = path
        self._sections: dict[str, list[str]] = {}
        current = None
        for line in text.splitlines():
            if line.startswith("## "):
                current = line[3:].strip()
                self._sections[current] = []
            elif current is not None:
                self._sections[current].append(line)

    @classmethod
    def load(cls, repo: Path) -> "Profile":
        path = repo / ".claude/factory.md"
        return cls(path.read_text(), path)

    def get(self, section: str, key: str, default: str | None = None) -> str | None:
        """The key's value: its first backticked token, else the text up to the end of line."""
        raw = self.text(section, key)
        return _unquote(raw) if raw is not None else default

    def text(self, section: str, key: str, default: str | None = None) -> str | None:
        """The key's whole line as written — for values that are prose, not a token."""
        for line in self._sections.get(section, []):
            m = re.match(r"^- \*\*(.+?):\*\*\s*(.*)$", line)
            if m and m[1].strip().lower() == key.lower():
                return m[2].strip()
        return default

    def require(self, section: str, key: str) -> str:
        value = self.get(section, key)
        if value is None:
            raise KeyError(f"profile: `- **{key}:**` missing under `## {section}`")
        return value

    def items(self, section: str) -> list[str]:
        """Bare list bullets (`` - `value` ``) of a section, in order."""
        out = []
        for line in self._sections.get(section, []):
            m = re.match(r"^- `([^`]+)`", line)
            if m:
                out.append(m[1])
        return out

    def code_block(self, section: str) -> str | None:
        lines, inside = [], False
        for line in self._sections.get(section, []):
            if line.startswith("```"):
                if inside:
                    return "\n".join(lines)
                inside = True
                continue
            if inside:
                lines.append(line)
        return None


def _unquote(value: str) -> str:
    value = value.strip()
    first = re.match(r"^`([^`]*)`", value)
    return first[1] if first else value


# --- secrets -------------------------------------------------------------------------------
SECRET_KEYS = ("TRELLO_API_KEY", "TRELLO_TOKEN", "FACTORY_SLACK_TOKEN")


def load_repo_secrets(repo: Path) -> None:
    """Fill the factory's own keys from `<repo>/.env` when the environment lacks them. Only these
    keys — the rest of `.env` never reaches the dispatcher or the workers it starts."""
    env_file = repo / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m and m[1] in SECRET_KEYS and not os.environ.get(m[1]):
            os.environ[m[1]] = m[2].strip().strip("'\"")


# --- state store ---------------------------------------------------------------------------
@contextmanager
def sent_store():
    """The set of event / ping keys already delivered, locked for the duration of the block.
    Losing the file only re-sends: workers ignore duplicates."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / ".sent.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        sent = set(json.loads(SENT_FILE.read_text())) if SENT_FILE.exists() else set()
        before = set(sent)
        yield sent
        if sent != before:
            tmp = SENT_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(sorted(sent), indent=0))
            tmp.replace(SENT_FILE)


# --- processes -----------------------------------------------------------------------------
def run(cmd: list[str], cwd: Path | None = None, check: bool = True, timeout: int = 120,
        env: dict | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})})
    if check and proc.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])}… exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    return proc.stdout


def live_workers() -> dict[str, dict]:
    """Background Claude sessions named factory-*, by name (`claude agents --json`)."""
    agents = json.loads(run(["claude", "agents", "--json"]) or "[]")
    return {a["name"]: a for a in agents
            if a.get("kind") == "background" and str(a.get("name", "")).startswith(WORKER_PREFIX)}
