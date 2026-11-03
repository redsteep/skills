"""The Mac menu bar plugin prints the snapshot the way SwiftBar reads a menu."""

import importlib.util
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factory_dispatch import decide  # noqa: E402
from factory_status import snapshot  # noqa: E402
from test_dispatch import NOW, card, issue, pr, todo, world  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "menubar", Path(__file__).resolve().parents[1] / "macos" / "factory.1m.py")
menubar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(menubar)

URL = "https://box.ts.net"
B1 = "feature/factory-c1-s1"


def status_of(w, **kw):
    s = snapshot(w, decide(w), **kw)
    s["paused"] = False
    return s


class Menu(unittest.TestCase):
    def test_the_title_counts_what_waits_for_you_and_each_opens_its_conversation(self):
        w = world([card("c1", [todo()]), card("c2", [todo()])], prs=[pr(5, B1, ci="passed")],
                  branches=[B1, "feature/factory-c2-s1"],
                  workers={"factory-c1-s1": "idle", "factory-c2-s1": "busy"}, sent=["5:ci-passed:abc"])
        lines = menubar.menu(status_of(w, conversations={"factory-c1-s1": "https://claude.ai/code/session_A"}),
                             URL, NOW + timedelta(minutes=1))
        self.assertEqual(lines[0], "🏭 1")
        self.assertIn("Card c1 — waits for you | href=https://claude.ai/code/session_A", lines)
        steps = lines.index("Steps (2) | color=gray")
        self.assertTrue(lines[steps + 1].startswith("Card c1 · 1/1 — waits for you · CI passed"))
        self.assertTrue(lines[steps + 2].startswith("Card c2 · 1/1 — working"))
        self.assertIn("Open the status page | href=https://box.ts.net/", lines)

    def test_nothing_waiting_is_the_bare_icon(self):
        self.assertEqual(menubar.menu(status_of(world([])), URL, NOW)[0], "🏭")

    def test_stale_and_paused_show_in_the_title(self):
        s = status_of(world([]))
        self.assertEqual(menubar.menu(s, URL, NOW + timedelta(minutes=30))[0], "🏭 ⚠")
        self.assertEqual(menubar.menu({**s, "paused": True}, URL, NOW + timedelta(minutes=30))[0], "🏭 ⏸")

    def test_a_card_being_split_and_an_issue_are_listed(self):
        w = world([card("c3"), issue(7)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"})
        lines = menubar.menu(status_of(w), URL, NOW)
        self.assertTrue(any(l.startswith("Card c3 · analysing") for l in lines))
        self.assertTrue(any(l.startswith("#7 Issue 7 · 1/1 — working") for l in lines))

    def test_a_pipe_in_a_name_cannot_inject_menu_parameters(self):
        self.assertEqual(menubar.item("a | href=evil\nb", href="x"), "a ¦ href=evil b | href=x")

    def test_no_answer_says_so(self):
        lines = menubar.menu(None, URL, NOW, "Could not resolve host")
        self.assertEqual(lines[0], "🏭 ?")
        self.assertIn("Could not resolve host | color=gray", lines)


if __name__ == "__main__":
    unittest.main()
