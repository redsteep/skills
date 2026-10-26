"""factory-ping builds the DM from the reason and the session link, and sends a reason once per step."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import factory_common  # noqa: E402
import factory_ping  # noqa: E402

URL = "https://claude.ai/code/session_01ABC"


class Ping(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(factory_ping, "session_url", return_value=URL)
        patcher.start()
        self.addCleanup(patcher.stop)
        state = Path(tempfile.mkdtemp(prefix="factory-ping-test-"))
        for name, value in (("STATE_DIR", state), ("SENT_FILE", state / "sent-events.json")):
            p = mock.patch.object(factory_common, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.posted = []

    def test_dm_carries_the_reason_and_the_session_link(self):
        factory_ping.send("factory-aB3d-s1", "spec ready, 2 questions", self.posted.append)
        self.assertEqual(self.posted, [f"*factory-aB3d-s1* — spec ready, 2 questions\n<{URL}|Open the conversation>"])

    def test_same_reason_for_the_same_step_is_sent_once(self):
        factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.posted.append)
        sent_again = factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.posted.append)
        self.assertFalse(sent_again)
        self.assertEqual(len(self.posted), 1)

    def test_same_reason_for_another_step_is_sent(self):
        factory_ping.send("factory-yy-s1", "PR ready for review", self.posted.append)
        factory_ping.send("factory-yy-s2", "PR ready for review", self.posted.append)
        self.assertEqual([p.split(" — ")[0] for p in self.posted], ["*factory-yy-s1*", "*factory-yy-s2*"])


if __name__ == "__main__":
    unittest.main()
