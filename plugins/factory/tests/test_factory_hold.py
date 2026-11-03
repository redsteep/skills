"""factory-hold sets or clears the hold label: the one Trello write a postpone needs."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from factory_hold import set_hold  # noqa: E402


def board(card_labels, board_labels):
    calls = []

    def call(method, path, **params):
        calls.append((method, path, params))
        if path.startswith("cards/") and method == "GET":
            return {"idBoard": "b1", "idLabels": card_labels}
        if path == "boards/b1/labels":
            return board_labels
        if path == "labels":
            return {"id": "new"}
    return call, calls


class Hold(unittest.TestCase):
    def test_puts_the_boards_label_on_the_card(self):
        call, calls = board(["r"], [{"id": "r", "name": "ready"}, {"id": "h", "name": "On Hold"}])
        self.assertIn("added", set_hold("c9", "on hold", True, call))
        self.assertEqual(calls[-1], ("POST", "cards/c9/idLabels", {"value": "h"}))

    def test_creates_the_label_on_a_board_that_lacks_it(self):
        call, calls = board([], [])
        set_hold("c9", "on hold", True, call)
        self.assertEqual(calls[-2][:2], ("POST", "labels"))
        self.assertEqual(calls[-1], ("POST", "cards/c9/idLabels", {"value": "new"}))

    def test_off_removes_it_and_leaves_ready_alone(self):
        call, calls = board(["r", "h"], [{"id": "r", "name": "ready"}, {"id": "h", "name": "on hold"}])
        self.assertIn("removed", set_hold("c9", "on hold", False, call))
        self.assertEqual(calls[-1][:2], ("DELETE", "cards/c9/idLabels/h"))

    def test_nothing_to_do_writes_nothing(self):
        call, calls = board([], [{"id": "h", "name": "on hold"}])
        self.assertEqual(set_hold("c9", "on hold", False, call), "already off hold")
        self.assertTrue(all(m == "GET" for m, _, _ in calls))


if __name__ == "__main__":
    unittest.main()
