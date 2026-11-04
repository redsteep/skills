"""Secrets from the repo's .env: only the factory's own keys, never overriding the environment."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from datetime import datetime, timedelta, timezone  # noqa: E402

from factory_common import (  # noqa: E402
    WORKER_GRACE, branch_matches, load_repo_secrets, resolve_branch, slugify, step_branch,
    worker_view,
)

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
    """What the dispatcher counts as a worker: alive with a process; `restarting` from the first
    dispatch that finds one seen alive missing or without a process, for the grace; `dead` when
    listed without a process beyond it. The grace runs from that first miss, not from the last
    sighting: a dispatch that sets up a worktree can keep the next one away for many minutes."""

    def test_a_session_with_a_process_keeps_its_status_and_is_recorded_alive(self):
        workers, seen = worker_view([agent("factory-a-s1", pid=1, status="idle")], {}, NOW)
        self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "idle"}, {"factory-a-s1": None}))

    def test_a_worker_alive_last_time_and_missing_now_is_restarting_from_now(self):
        # however long ago that last dispatch was
        for listed in ([], [agent("factory-a-s1")]):
            with self.subTest(listed=bool(listed)):
                workers, seen = worker_view(listed, {"factory-a-s1": None}, NOW)
                self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "restarting"}, {"factory-a-s1": NOW}))

    def test_a_busy_session_whose_turn_ended_reads_idle(self):
        for state in ("done", "blocked"):
            with self.subTest(state=state):
                workers, _ = worker_view([{**agent("factory-a-s1", pid=1, status="busy"), "state": state}], {}, NOW)
                self.assertEqual(statuses(workers), {"factory-a-s1": "idle"})

    def test_a_session_mid_turn_stays_busy(self):
        workers, _ = worker_view([{**agent("factory-a-s1", pid=1, status="busy"), "state": "working"}], {}, NOW)
        self.assertEqual(statuses(workers), {"factory-a-s1": "busy"})

    def test_a_session_without_a_process_never_seen_alive_is_dead(self):
        workers, _ = worker_view([agent("factory-a-s1")], {}, NOW)
        self.assertEqual(statuses(workers), {"factory-a-s1": "dead"})

    def test_missing_or_without_a_process_for_the_whole_grace_is_still_restarting(self):
        for listed in ([], [agent("factory-a-s1")]):
            with self.subTest(listed=bool(listed)):
                since = NOW - WORKER_GRACE
                workers, seen = worker_view(listed, {"factory-a-s1": since}, NOW)
                self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "restarting"}, {"factory-a-s1": since}))

    def test_back_within_the_grace_is_alive_again(self):
        workers, seen = worker_view([agent("factory-a-s1", pid=1, status="busy")],
                                    {"factory-a-s1": NOW - WORKER_GRACE}, NOW)
        self.assertEqual((statuses(workers), seen), ({"factory-a-s1": "busy"}, {"factory-a-s1": None}))

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


class BranchNames(unittest.TestCase):
    """What a human reads comes first; what the dispatcher needs stays in the tail."""

    def test_a_russian_card_name_becomes_latin_words(self):
        self.assertEqual(slugify("Payswix: \u043f\u043e\u0434\u0434\u0435\u0440\u0436\u043a\u0430"),
                         "payswix-podderzhka")

    def test_a_long_name_is_cut_on_a_word_and_not_mid_word(self):
        self.assertEqual(slugify("Provider settlement fee is not counted at all"),
                         "provider-settlement-fee-is")

    def test_a_name_with_nothing_latin_or_cyrillic_in_it_slugs_to_nothing(self):
        self.assertEqual(slugify("### !!! ###"), "")

    def test_without_a_slug_the_branch_is_the_name_the_factory_always_used(self):
        self.assertEqual(step_branch("4oJCA5h7", 2), "feature/factory-4oJCA5h7-s2")

    def test_with_a_slug_the_readable_part_leads_and_the_card_id_trails(self):
        self.assertEqual(step_branch("4oJCA5h7", 2, "payswix"), "feature/factory-payswix-s2-4oJCA5h7")

    def test_a_step_owns_both_shapes_of_its_own_branch(self):
        self.assertTrue(branch_matches("feature/factory-4oJCA5h7-s2", "4oJCA5h7", 2))
        self.assertTrue(branch_matches("feature/factory-payswix-s2-4oJCA5h7", "4oJCA5h7", 2))

    def test_a_branch_of_another_step_card_or_prefix_is_not_the_step_s(self):
        self.assertFalse(branch_matches("feature/factory-payswix-s3-4oJCA5h7", "4oJCA5h7", 2))
        self.assertFalse(branch_matches("feature/factory-payswix-s2-Zzzzzzzz", "4oJCA5h7", 2))
        self.assertFalse(branch_matches("wip/payswix-s2-4oJCA5h7", "4oJCA5h7", 2))

    def test_the_branch_that_already_exists_wins_over_the_name_to_cut(self):
        self.assertEqual(resolve_branch(["feature/factory-4oJCA5h7-s2"], "4oJCA5h7", 2, "payswix"),
                         "feature/factory-4oJCA5h7-s2")

    def test_a_renamed_card_keeps_the_branch_cut_under_its_old_name(self):
        self.assertEqual(resolve_branch(["feature/factory-oldname-s2-4oJCA5h7"], "4oJCA5h7", 2, "newname"),
                         "feature/factory-oldname-s2-4oJCA5h7")

    def test_a_step_known_only_by_a_fix_branch_resolves_to_that_branch_s_root(self):
        self.assertEqual(resolve_branch(["feature/factory-payswix-s2-4oJCA5h7-fix1"], "4oJCA5h7", 2, "other"),
                         "feature/factory-payswix-s2-4oJCA5h7")

    def test_a_step_with_nothing_in_the_world_gets_the_new_name(self):
        self.assertEqual(resolve_branch([], "4oJCA5h7", 2, "payswix"),
                         "feature/factory-payswix-s2-4oJCA5h7")


if __name__ == "__main__":
    unittest.main()
