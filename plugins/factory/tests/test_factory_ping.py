"""factory-ping builds the DM from the reason and the session link, and sends a reason once per step."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import factory_common  # noqa: E402
import factory_ping  # noqa: E402

URL = "https://claude.ai/code/session_01ABC"
PR_URL = "https://github.com/o/r/pull/9"


class Ping(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(factory_ping, "session_url", return_value=URL),
                        mock.patch.object(factory_ping, "pr_url", side_effect=lambda r: PR_URL if "PR #9" in r else None),
                        mock.patch.object(factory_ping, "worker_title", return_value="Fix Campaign Reviewer Filters · 1/2")):
            patcher.start()
            self.addCleanup(patcher.stop)
        state = Path(tempfile.mkdtemp(prefix="factory-ping-test-"))
        for name, value in (("STATE_DIR", state), ("SENT_FILE", state / "sent-events.json")):
            p = mock.patch.object(factory_common, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.posted = []

    def test_a_wait_names_what_happened_what_it_is_about_and_where_to_look(self):
        factory_ping.send("factory-aB3d-s1", "PR #9 ready for review", self.posted.append)
        self.assertEqual(self.posted, ["👋 *Needs you* — PR #9 ready for review\n"
                                       "Fix Campaign Reviewer Filters · 1/2\n"
                                       f"<{PR_URL}|PR #9>  ·  <{URL}|Open the conversation>"])

    def test_something_done_on_its_own_is_marked_done(self):
        factory_ping.send("factory-aB3d-s1", "issue #121 closed — already done in #122", self.posted.append, done=True)
        self.assertEqual(self.posted, ["✅ *Done* — issue #121 closed — already done in #122\n"
                                       "Fix Campaign Reviewer Filters · 1/2\n"
                                       f"<{URL}|Open the conversation>"])

    def test_same_reason_for_the_same_step_is_sent_once(self):
        factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.posted.append)
        sent_again = factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.posted.append)
        self.assertFalse(sent_again)
        self.assertEqual(len(self.posted), 1)

    def test_same_reason_for_another_step_is_sent(self):
        factory_ping.send("factory-yy-s1", "PR ready for review", self.posted.append)
        factory_ping.send("factory-yy-s2", "PR ready for review", self.posted.append)
        self.assertEqual(len(self.posted), 2)


class SessionUrl(unittest.TestCase):
    def test_the_link_is_read_from_the_transcript_not_only_recent_output(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        f.write("\n".join(json.dumps(e) for e in [
            {"type": "assistant", "message": {"content": "Claude-Session: https://claude.ai/code/session_OTHER"}},
            {"type": "system", "subtype": "bridge_status", "url": "https://claude.ai/code/session_01RC"}]))
        f.close()
        with mock.patch.object(factory_ping, "live_workers", return_value={"w": {"id": "x", "sessionId": "s"}}), \
                mock.patch.object(factory_ping, "transcript_of", return_value=Path(f.name)), \
                mock.patch.object(factory_ping, "run", return_value=""):
            self.assertEqual(factory_ping.session_url("w"), "https://claude.ai/code/session_01RC")


if __name__ == "__main__":
    unittest.main()
