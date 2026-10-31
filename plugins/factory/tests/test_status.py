"""factory-status: the snapshot is the dispatcher's own reading of the world, in plain JSON."""

import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import factory_status  # noqa: E402
from factory_dispatch import decide  # noqa: E402
from factory_status import read_status, snapshot, summary, write_status  # noqa: E402
from test_dispatch import NOW, card, done, issue, pr, todo, world  # noqa: E402

B1 = "feature/factory-c1-s1"


def steps(status, short):
    return next(i for i in status["items"] if i["short"] == short)["steps"]


class Snapshot(unittest.TestCase):
    def test_pools_count_what_decide_counts(self):
        w = world([card("c1", [todo()]), card("c2", [todo()]), issue(7)],
                  branches=[B1, "feature/factory-i7-s1"],
                  workers={"factory-c1-s1": "busy", "factory-i7-s1": "idle"}, wip=3, issue_daily=2)
        status = snapshot(w, decide(w))
        self.assertEqual(status["pools"]["cards"], {"busy": 1, "wip": 3})
        self.assertEqual(status["pools"]["issues"], {"busy": 1, "wip": 1, "today": 1, "per_day": 2})

    def test_an_idle_worker_with_its_pr_green_waits_for_you(self):
        w = world([card("c1", [todo(), todo()])], prs=[pr(5, B1, ci="passed")], branches=[B1],
                  workers={"factory-c1-s1": "idle"}, sent=["5:ci-passed:abc"])
        status = snapshot(w, decide(w), conversations={"factory-c1-s1": "https://claude.ai/code/session_X"})
        s1, s2 = steps(status, "c1")
        self.assertEqual((s1["activity"], s2["activity"]), ("waits-you", "later"))
        self.assertEqual(s1["prs"][0]["number"], 5)
        self.assertEqual(status["attention"][0]["conversation"], "https://claude.ai/code/session_X")

    def test_an_idle_worker_with_checks_running_waits_for_ci(self):
        w = world([card("c1", [todo()])], prs=[pr(5, B1, ci="pending")], branches=[B1],
                  workers={"factory-c1-s1": "idle"})
        self.assertEqual(steps(snapshot(w, decide(w)), "c1")[0]["activity"], "waits-ci")

    def test_an_idle_worker_about_to_hear_an_event_is_waking_not_waiting(self):
        w = world([card("c1", [todo()])], prs=[pr(5, B1, ci="failed")], branches=[B1],
                  workers={"factory-c1-s1": "idle"})
        status = snapshot(w, decide(w))
        self.assertEqual(steps(status, "c1")[0]["activity"], "waking")
        self.assertEqual(status["attention"], [])
        self.assertTrue(any("ci-failed PR #5" in d for d in status["dispatch"]))

    def test_a_step_started_this_dispatch_reads_starting(self):
        w = world([card("c1", [todo()])])
        self.assertEqual(steps(snapshot(w, decide(w)), "c1")[0]["activity"], "starting")

    def test_a_pending_step_with_no_free_slot_is_queued(self):
        w = world([card("c1", [todo()]), card("c2", [todo()])], branches=[B1],
                  workers={"factory-c1-s1": "busy"}, wip=1)
        self.assertEqual(steps(snapshot(w, decide(w)), "c2")[0]["activity"], "queued")

    def test_a_step_under_way_with_no_worker_needs_attention(self):
        w = world([card("c1", [todo()]), card("c2", [todo()])], branches=[B1, "feature/factory-c2-s1"],
                  workers={"factory-c2-s1": "busy"}, wip=1)
        status = snapshot(w, decide(w))
        self.assertEqual(steps(status, "c1")[0]["activity"], "no-worker")
        self.assertIn("no worker", status["attention"][0]["why"])

    def test_done_and_unready_cards_without_workers_are_left_out(self):
        w = world([card("c1", [done()]), card("c2", [todo()], ready=False), card("c3")])
        status = snapshot(w, decide(w))
        self.assertEqual(steps(status, "c1")[0]["activity"], "done")
        self.assertEqual([i["short"] for i in status["items"]], ["c1", "c3"])
        self.assertIn("split", status["items"][1])

    def test_review_mode_queue_and_presence_are_shown(self):
        w = world([card("c1", [todo()])], prs=[pr(5, B1)], branches=[B1], workers={"factory-c1-s1": "idle"},
                  reviews={B1: 2}, presence={"factory-c1-s1": NOW - timedelta(minutes=3)})
        s1 = steps(snapshot(w, []), "c1")[0]
        self.assertEqual(s1["review_queued"], 2)
        self.assertEqual(s1["developer_seen"], (NOW - timedelta(minutes=3)).isoformat())

    def test_a_failed_action_needs_attention(self):
        w = world([card("c1", [todo()])])
        actions = decide(w)
        status = snapshot(w, actions, failed=[(actions[0], RuntimeError("worktree script exited 1\nmore"))])
        self.assertIn("worktree script exited 1", status["attention"][-1]["why"])
        self.assertNotIn("more", status["attention"][-1]["why"])

    def test_it_is_plain_json(self):
        w = world([card("c1", [todo()]), issue(7)], prs=[pr(5, B1)], branches=[B1])
        json.dumps(snapshot(w, decide(w)))


class File(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "status.json"
        patch = mock.patch.object(factory_status, "PAUSE_FILE", self.dir / "PAUSED")
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_reader_adds_age_and_pause(self):
        w = world([card("c1", [todo()])])
        write_status(snapshot(w, decide(w)), self.path)
        (self.dir / "PAUSED").touch()
        status = read_status(self.path, now=NOW + timedelta(minutes=3))
        self.assertEqual((status["age_seconds"], status["paused"]), (180, True))
        self.assertIn("PAUSED", summary(status))

    def test_an_old_snapshot_reads_stale(self):
        w = world([card("c1", [todo()])])
        write_status(snapshot(w, decide(w)), self.path)
        self.assertIn("STALE", summary(read_status(self.path, now=NOW + timedelta(minutes=30))))

    def test_no_snapshot_yet(self):
        self.assertIsNone(read_status(self.path))


class Summary(unittest.TestCase):
    def test_what_needs_you_comes_first(self):
        w = world([card("c1", [todo()]), card("c2", [todo()])], prs=[pr(5, B1, ci="passed")],
                  branches=[B1, "feature/factory-c2-s1"],
                  workers={"factory-c1-s1": "idle", "factory-c2-s1": "busy"}, sent=["5:ci-passed:abc"])
        status = snapshot(w, decide(w))
        status.update(age_seconds=60, paused=False)
        text = summary(status)
        self.assertIn("cards 2/3 · issues 0/1", text)
        self.assertLess(text.index("Needs you"), text.index("Steps"))
        steps_part = text[text.index("Steps"):]
        self.assertLess(steps_part.index("Card c1 · 1/1 — waits-you · PR #5 open ci passed"),
                        steps_part.index("Card c2 · 1/1 — working"))


if __name__ == "__main__":
    unittest.main()
