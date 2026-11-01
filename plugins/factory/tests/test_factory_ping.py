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
        self.ctx = []

    def collect(self, text, url="", pr=""):
        """A channel: `send` hands it the rendered text plus the links it resolved, because a
        `Ping command` channel passes those to the command in its environment."""
        self.posted.append(text)
        self.ctx.append({"url": url, "pr": pr})

    def test_a_wait_names_what_happened_what_it_is_about_and_where_to_look(self):
        factory_ping.send("factory-aB3d-s1", "PR #9 ready for review", self.collect)
        self.assertEqual(self.posted, ["👋 *Needs you* — PR #9 ready for review\n"
                                       "Fix Campaign Reviewer Filters · 1/2\n"
                                       f"<{PR_URL}|PR #9>  ·  <{URL}|Open the conversation>"])

    def test_something_done_on_its_own_is_marked_done(self):
        factory_ping.send("factory-aB3d-s1", "issue #121 closed — already done in #122", self.collect, done=True)
        self.assertEqual(self.posted, ["✅ *Done* — issue #121 closed — already done in #122\n"
                                       "Fix Campaign Reviewer Filters · 1/2\n"
                                       f"<{URL}|Open the conversation>"])

    def test_same_reason_for_the_same_step_is_sent_once(self):
        factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.collect)
        sent_again = factory_ping.send("factory-zz-s2", "PR #9 ready for review", self.collect)
        self.assertFalse(sent_again)
        self.assertEqual(len(self.posted), 1)

    def test_same_reason_for_another_step_is_sent(self):
        factory_ping.send("factory-yy-s1", "PR ready for review", self.collect)
        factory_ping.send("factory-yy-s2", "PR ready for review", self.collect)
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

class PingCommand(unittest.TestCase):
    """The channel a project declares itself (`Settings` → `Ping command`): the message on
    stdin, the links in the environment, and a failure that does not count as delivered."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="factory-ping-cmd-"))
        self.out = self.repo / "received.txt"

    def test_the_message_arrives_on_stdin_with_the_links_in_the_environment(self):
        factory_ping.ping_command(
            f'cat > {self.out}; env | grep ^FACTORY_PING_ | sort >> {self.out}',
            self.repo, "👋 Needs you — PR #9 ready for review\nCard · 1/2\nhttps://pr\nhttps://conv",
            kind="needs-you", worker="factory-aB3d-s1", url="https://conv", pr="https://pr")
        got = self.out.read_text()
        self.assertIn("👋 Needs you — PR #9 ready for review", got)
        self.assertIn("FACTORY_PING_KIND=needs-you", got)
        self.assertIn("FACTORY_PING_WORKER=factory-aB3d-s1", got)
        self.assertIn("FACTORY_PING_URL=https://conv", got)
        self.assertIn("FACTORY_PING_PR=https://pr", got)

    def test_it_runs_in_the_repository(self):
        factory_ping.ping_command(f"pwd > {self.out}", self.repo, "x", kind="done")
        self.assertEqual(self.out.read_text().strip(), str(self.repo.resolve()))

    def test_a_failing_command_raises_with_what_it_said(self):
        """So `send` does not record the reason as sent: a ping nobody received must be tried
        again by the next worker on the same reason, not swallowed."""
        with self.assertRaises(RuntimeError) as caught:
            factory_ping.ping_command("echo 'bot token rejected' >&2; exit 3", self.repo, "x", kind="done")
        self.assertIn("exited 3", str(caught.exception))
        self.assertIn("bot token rejected", str(caught.exception))

    def test_a_missing_pr_is_an_empty_variable_not_the_word_none(self):
        factory_ping.ping_command(f'echo "[$FACTORY_PING_PR]" > {self.out}', self.repo, "x",
                                  kind="needs-you", pr=None)
        self.assertEqual(self.out.read_text().strip(), "[]")


class PlainMessage(unittest.TestCase):
    """Slack's `*bold*` and `<url|text>` are Slack's; a Telegram bot or a desktop notifier shows
    them literally. Same three lines, every link on its own."""

    def test_a_wait_has_no_slack_markup_and_one_link_per_line(self):
        self.assertEqual(
            factory_ping.plain_message("PR #9 ready for review", "Card · 1/2", URL, PR_URL),
            f"👋 Needs you — PR #9 ready for review\nCard · 1/2\n{PR_URL}\n{URL}")

    def test_done_without_a_pr(self):
        self.assertEqual(
            factory_ping.plain_message("issue #121 closed", "Card · 1/2", URL, None, done=True),
            f"✅ Done — issue #121 closed\nCard · 1/2\n{URL}")

    def test_the_factory_notice_too(self):
        self.assertEqual(factory_ping.plain_factory_message("nothing ready"), "📭 Queue empty — nothing ready")


if __name__ == "__main__":
    unittest.main()
