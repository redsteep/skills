"""Shared by the dispatcher, the auto-merge gate and factory-ping: the profile, the state store,
and the names every part agrees on. Standard library only — the scripts run from a systemd unit
and from hooks, with whatever python3 the box has."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE_DIR = Path(os.environ.get("FACTORY_STATE_DIR", Path.home() / ".local/state/factory"))
SENT_FILE = STATE_DIR / "sent-events.json"
PAUSE_FILE = STATE_DIR / "PAUSED"
SEEN_FILE = STATE_DIR / "workers-seen.json"

WORKER_PREFIX = "factory-"
BRANCH_PREFIX = "feature/factory-"


# --- names -------------------------------------------------------------------------------
def step_name(card_short: str, n: int) -> str:
    """Worker session of step n (1-based) of a card: the dispatcher's routing key.

    Never carries the card's name. Every event, slot and cleanup finds its worker by this
    string, so it stays derivable from `(card, step)` alone -- what a human reads is the
    branch (`step_branch`) and the worktree named after it.
    """
    return f"{WORKER_PREFIX}{card_short}-s{n}"


_TRANSLIT = str.maketrans({
    "\u0430": "a", "\u0431": "b", "\u0432": "v", "\u0433": "g", "\u0434": "d", "\u0435": "e",
    "\u0451": "e", "\u0436": "zh", "\u0437": "z", "\u0438": "i", "\u0439": "i", "\u043a": "k",
    "\u043b": "l", "\u043c": "m", "\u043d": "n", "\u043e": "o", "\u043f": "p", "\u0440": "r",
    "\u0441": "s", "\u0442": "t", "\u0443": "u", "\u0444": "f", "\u0445": "h", "\u0446": "c",
    "\u0447": "ch", "\u0448": "sh", "\u0449": "sch", "\u044a": "", "\u044b": "y", "\u044c": "",
    "\u044d": "e", "\u044e": "yu", "\u044f": "ya",
})


def slugify(text: str, limit: int = 28) -> str:
    """A card's name as the readable head of a branch: latin, lowercase, dash-separated.

    Cyrillic is transliterated rather than dropped -- half this board's cards are in Russian, and
    a branch named after none of their words is the problem this solves. The cut is on a word
    boundary, so the tail reads as words and not as a word broken in half.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().translate(_TRANSLIT)).strip("-")
    if len(slug) <= limit:
        return slug
    head = slug[:limit].rsplit("-", 1)[0]
    return head or slug[:limit].strip("-")


def issue_short(number: int) -> str:
    """An issue's stand-in for a card short id: `i<number>` (a Trello short link is 8 characters,
    so the two never collide)."""
    return f"i{number}"


def split_name(card_short: str) -> str:
    return f"{WORKER_PREFIX}{card_short}-split"


def step_branch(card_short: str, n: int, slug: str = "") -> str:
    """The step's branch. Readable part first, the card's short id in the tail.

    The tail is not decoration: a card gets renamed (and an issue's title edited), so a branch
    named only after the card stops being findable the moment that happens. `branch_matches`
    looks for `-s<n>-<short>`, which no rename touches. Without a slug the name is the one the
    factory has always used, so a branch cut before this version keeps resolving.
    """
    if not slug:
        return f"feature/{step_name(card_short, n)}"
    return f"feature/{WORKER_PREFIX}{slug}-s{n}-{card_short}"


def branch_matches(branch: str, card_short: str, n: int) -> bool:
    """Is this branch step n of that card, under either naming?"""
    if not branch.startswith(BRANCH_PREFIX):
        return False
    return branch == step_branch(card_short, n) or branch.endswith(f"-s{n}-{card_short}")


def resolve_branch(known: Iterable[str], card_short: str, n: int, slug: str) -> str:
    """The step's branch: whichever already exists in the world, else the name to cut.

    Asked of the world rather than computed, because the slug follows the card's current name:
    a step whose branch was cut under the old name keeps it, and work is never orphaned by an
    edit to a card's title.
    """
    for branch in sorted(known):
        if branch_matches(branch, card_short, n):
            return branch
    # Nothing but a fix branch left? Its root is the step's branch under the name it was cut with,
    # which is what the fix prefix has to keep matching.
    for branch in sorted(known):
        root = branch.split("-fix", 1)[0]
        if branch != root and branch_matches(root, card_short, n):
            return root
    return step_branch(card_short, n, slug)


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


def load_repo_secrets(repo: Path, override: bool = False) -> None:
    """Fill the factory's own keys from `<repo>/.env` when the environment lacks them — or, with
    `override`, over what it has (a worker's environment is the daemon's, and can be stale). Only
    these keys — the rest of `.env` never reaches the dispatcher or the workers it starts."""
    env_file = repo / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if m and m[1] in SECRET_KEYS and (override or not os.environ.get(m[1])):
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


# A restarting session drops out of `claude agents`, or loses its process, for a moment. Within
# this long of last being seen alive it still counts as live, so a restart never gets a twin.
WORKER_GRACE = timedelta(minutes=10)


def is_worker(agent: dict) -> bool:
    return agent.get("kind") == "background" and str(agent.get("name", "")).startswith(WORKER_PREFIX)


def list_agents() -> list[dict]:
    """Background Claude sessions named factory-*, as `claude agents --json` lists them — dead
    ones and same-name twins included."""
    return [a for a in json.loads(run(["claude", "agents", "--json"]) or "[]") if is_worker(a)]


def worker_view(agents: list[dict], seen: dict[str, datetime], now: datetime
                ) -> tuple[dict[str, dict], dict[str, datetime]]:
    """Workers by name, and when each was last seen alive. A session with a process keeps its
    status (`idle` once its turn has ended); one seen alive within WORKER_GRACE but missing or without a process now reads
    `restarting`; one listed without a process beyond that reads `dead`."""
    listed: dict[str, dict] = {}
    for a in filter(is_worker, agents):
        if a["name"] not in listed or a.get("pid"):
            listed[a["name"]] = a
    workers, fresh = {}, {}
    for name, a in listed.items():
        if a.get("pid"):
            # Since Claude Code 2.1.3xx a background session with a process always reads `busy`;
            # whether it is mid-turn is its `state`. A finished turn (`done`) or one waiting on the
            # developer (`blocked`) is what `idle` used to mean.
            if a.get("state") in ("done", "blocked"):
                a = {**a, "status": "idle"}
            workers[name], fresh[name] = a, now
    for name, at in seen.items():
        if name not in workers and at >= now - WORKER_GRACE:
            workers[name], fresh[name] = {**listed.get(name, {}), "status": "restarting"}, at
    for name, a in listed.items():
        workers.setdefault(name, {**a, "status": "dead"})
    return workers, fresh


def _read_seen() -> dict[str, datetime]:
    return ({k: datetime.fromisoformat(v) for k, v in json.loads(SEEN_FILE.read_text()).items()}
            if SEEN_FILE.exists() else {})


def _write_seen(seen: dict[str, datetime]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: v.isoformat() for k, v in seen.items()}, indent=0))
    tmp.replace(SEEN_FILE)


def live_workers(record: bool = False) -> dict[str, dict]:
    """The workers as `worker_view` reads them. Only the dispatcher records sightings
    (`record=True`); a worker's own scripts just read them."""
    workers, seen = worker_view(list_agents(), _read_seen(), datetime.now(timezone.utc))
    if record:
        _write_seen(seen)
    return workers


def forget_seen(name: str) -> None:
    """A worker stopped on purpose (shelved) is not restarting: it must not keep its slot for the
    grace period a crash gets."""
    seen = _read_seen()
    if seen.pop(name, None) is not None:
        _write_seen(seen)


def mark_launched(name: str) -> None:
    """A just-launched worker counts as seen alive, so it is not replaced before it is listed."""
    seen = _read_seen()
    seen[name] = datetime.now(timezone.utc)
    _write_seen(seen)

# --- the developer's presence ----------------------------------------------------------------
# A worker's conversation is where the developer reviews. What they typed there -- never a peer
# session's message, a task notice, or the dispatcher's start prompt -- is read from the session
# transcript: by the merge gate (their LGTM) and by the dispatcher (whether they are still here).
START_PROMPTS = ("You are **" + WORKER_PREFIX, "**You replace a factory worker")


def developer_messages(transcript: Path) -> list[tuple[str, str]]:
    """(timestamp, text) of every message the developer typed in this session, oldest first. The
    session's first human-origin message is the dispatcher's start prompt, not the developer."""
    out = []
    for line in transcript.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
            continue
        if (entry.get("origin") or {}).get("kind") != "human":
            continue
        content = (entry.get("message") or {}).get("content")
        text = content if isinstance(content, str) else " ".join(
            b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
        if text.strip():
            out.append((entry.get("timestamp", ""), text))
    return out[1:]


def transcript_of(session_id: str) -> Path | None:
    """A session's transcript, wherever Claude Code filed it (one folder per working directory)."""
    found = list((Path.home() / ".claude/projects").glob(f"*/{session_id}.jsonl"))
    return found[0] if found else None


_SESSION_URL = re.compile(r"https://claude\.ai/code/session_[A-Za-z0-9]+")


def conversation_url(session_id: str | None) -> str | None:
    """A session's Remote Control link, as its transcript records it for good (`bridge_status`,
    `remote_session_change`): the latest one, or None."""
    path = transcript_of(session_id) if session_id else None
    found = []
    if path:
        for line in path.read_text().splitlines():
            if '"bridge_status"' in line or '"remote_session_change"' in line:
                found += _SESSION_URL.findall(line)
    return found[-1] if found else None


def last_developer_message(session_id: str | None) -> datetime | None:
    path = transcript_of(session_id) if session_id else None
    said = developer_messages(path) if path else []
    return datetime.fromisoformat(said[-1][0].replace("Z", "+00:00")) if said and said[-1][0] else None


def reviews_on(repo: Path) -> dict[str, int]:
    """Branches in review mode → how many requests their queue still holds. review-mode keeps a
    marker and a queue per branch under the git common dir."""
    out = run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=repo).strip()
    state = Path(out) / "review-mode"
    reviews = {}
    for marker in state.glob("*/marker.json"):
        try:
            branch = json.loads(marker.read_text())["branch"]
        except (ValueError, KeyError):
            continue
        queue = marker.parent / "queue.md"
        reviews[branch] = queue.read_text().count("- [ ]") if queue.is_file() else 0
    return reviews


TITLES_FILE = STATE_DIR / "titles.json"


def record_title(worker: str, title: str) -> None:
    """What a worker works on, as the Claude app shows it: factory-ping reads it for the DM."""
    titles = json.loads(TITLES_FILE.read_text()) if TITLES_FILE.is_file() else {}
    titles[worker] = title
    TITLES_FILE.write_text(json.dumps(titles, indent=1))


def worker_title(worker: str) -> str | None:
    return (json.loads(TITLES_FILE.read_text()) if TITLES_FILE.is_file() else {}).get(worker)
