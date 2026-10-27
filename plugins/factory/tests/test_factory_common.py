"""Secrets from the repo's .env: only the factory's own keys, never overriding the environment."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from datetime import datetime, timedelta, timezone  # noqa: E402

from factory_common import WORKER_GRACE, load_repo_secrets, worker_view  # noqa: E402

ENV = """# comment
export TRELLO_API_KEY="key-from-dotenv"
TRELLO_TOKEN='token-from-dotenv'
OPENAI_API_KEY=must-not-leak
"""


class RepoSecrets(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="factory-secrets-"))
        (self.repo / ".env").write_text(ENV)

    def test_only_the_factory_keys_are_read_unquoted(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            load_repo_secrets(self.repo)
            self.assertEqual({k: os.environ[k] for k in os.environ},
                             {"TRELLO_API_KEY": "key-from-dotenv", "TRELLO_TOKEN": "token-from-dotenv"})

    def test_a_key_already_in_the_environment_wins(self):
        with mock.patch.dict(os.environ, {"TRELLO_TOKEN": "from-systemd"}, clear=True):
            load_repo_secrets(self.repo)
            self.assertEqual(os.environ["TRELLO_TOKEN"], "from-systemd")


NOW = datetime(2026, 10, 27, 17, 0, tzinfo=timezone.utc)


def agent(name, pid=None, status=None):
    a = {"name": name, "kind": "background", "id": name[-4:]}
    if pid:
        a["pid"] = pid
    if status:
        a["status"] = status
    return a


def statuses(workers):
    return {name: info["status"] for name, info in workers.items()}


class WorkerView(unittest.TestCase):
    """What the dispatcher counts as a worker: alive with a process; `restarting` while one seen
    alive within the grace is missing or has no process; `dead` when listed without a process
    beyond it."""

    def test_a_session_with_a_process_keeps_its_status_and_is_seen_now(self):
        workers, seen = worker_view([agent("factory-a-s1", pid=1, status="idle")], {}, NOW)
        self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "idle"}, {"factory-a-s1": NOW}))

    def test_a_session_without_a_process_never_seen_alive_is_dead(self):
        workers, _ = worker_view([agent("factory-a-s1")], {}, NOW)
        self.assertEqual(statuses(workers), {"factory-a-s1": "dead"})

    def test_missing_or_without_a_process_within_the_grace_is_restarting(self):
        for listed in ([], [agent("factory-a-s1")]):
            with self.subTest(listed=bool(listed)):
                seen_at = NOW - WORKER_GRACE
                workers, seen = worker_view(listed, {"factory-a-s1": seen_at}, NOW)
                self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "restarting"}, {"factory-a-s1": seen_at}))

    def test_just_past_the_grace_a_missing_one_is_gone_and_one_without_a_process_is_dead(self):
        past = {"factory-a-s1": NOW - WORKER_GRACE - timedelta(seconds=1)}
        self.assertEqual(worker_view([], past, NOW), ({}, {}))
        self.assertEqual(statuses(worker_view([agent("factory-a-s1")], past, NOW)[0]), {"factory-a-s1": "dead"})

    def test_a_live_twin_wins_over_a_dead_one_of_the_same_name(self):
        workers, _ = worker_view([agent("factory-a-s1"), agent("factory-a-s1", pid=2, status="busy")], {}, NOW)
        self.assertEqual(statuses(workers), {"factory-a-s1": "busy"})

    def test_other_sessions_are_not_workers(self):
        workers, _ = worker_view([agent("my-session", pid=1, status="idle"),
                                  {**agent("factory-a-s1", pid=2, status="idle"), "kind": "interactive"}], {}, NOW)
        self.assertEqual(workers, {})


if __name__ == "__main__":
    unittest.main()
