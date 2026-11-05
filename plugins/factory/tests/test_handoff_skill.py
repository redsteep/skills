"""The handoff skill moved out of one repository into the plugin, so the thing to keep pinned is
that it stayed generic: a path, a chat id or a service name baked in here would work for the
project it came from and silently mislead every other one."""

import re
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[1] / "skills/after-merge-handoff/SKILL.md").read_text()

# What "a project leaked in" looks like: someone's checkout, someone's chat, someone's region.
LEAKS = (
    (r"/home/|/Users/", "an absolute path from whoever wrote it"),
    (r"-?\d{10,}", "a chat or account id"),
    (r"europe-\w+\d|us-(east|west|central)\d", "a cloud region"),
    (r"gcloud |aws |az |kubectl ", "a cloud CLI invoked directly"),
)


class StaysGeneric(unittest.TestCase):
    def test_no_project_of_its_own_leaked_into_the_skill(self):
        for pattern, what in LEAKS:
            found = re.search(pattern, SKILL)
            self.assertIsNone(found, f"{what} in the handoff skill: {found and found.group(0)!r}")

    def test_every_project_specific_step_is_read_from_the_profile(self):
        """The four things that cannot be generic — how to ask whether a commit is live, how to
        look at a failed build, which list the card moves to, and where the requester hears back —
        are named as profile keys, so a project supplies them instead of this file."""
        for key in ("Deploy → Live check", "Deploy → Failed build", "Trello → Testing",
                    "Profile → Announce"):
            self.assertIn(key, SKILL, f"{key} is not read from the profile")


class KeepsItsRails(unittest.TestCase):
    """Three rules the move must not quietly drop — each one was paid for."""

    def test_a_broken_deploy_ticks_nothing(self):
        self.assertIn("Do not tick anything", SKILL)

    def test_silence_is_not_an_approval(self):
        self.assertIn("a silence is not a yes", SKILL)

    def test_the_worker_never_cleans_up_after_itself(self):
        """The dispatcher owns the worktree; a worker that removes its own has removed the
        evidence of what it did."""
        self.assertIn("Do not clean up", SKILL)

    def test_the_message_that_leaves_the_team_needs_an_explicit_yes(self):
        self.assertIn("explicit yes", SKILL)


if __name__ == "__main__":
    unittest.main()
