"""The dispatcher's decision table: every rule and boundary of the spec's Tests section.
Run: python3 -m unittest discover -s plugins/factory/tests"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factory_dispatch import (  # noqa: E402
    DONE, DROPPED_STATE, FIXING, IN_PROGRESS, MERGED, PENDING, PR, Card, Cleanup, Item,
    MarkSent, SendEvent, StartSplit, StartStep, World, decide, derive_step_state,
)


def card(short, items=None, ready=True):
    return Card(id=f"id-{short}", short=short, name=f"Card {short}", url=f"https://trello.com/c/{short}",
                ready=ready, items=None if items is None else tuple(items))


def todo(name="step"):
    return Item(name, False)


def done(name="step"):
    return Item(name, True)


def pr(number, head, state="OPEN", ci=None, conflicting=False, sha="abc"):
    return PR(number, state, head, sha, ci, conflicting, f"https://github.com/o/r/pull/{number}")


def world(cards, prs=(), branches=(), workers=None, sent=(), wip=3):
    return World(tuple(cards), tuple(prs), frozenset(branches),
                 {name: {"status": status} for name, status in (workers or {}).items()},
                 frozenset(sent), wip)


def started(actions):
    return [(a.step.card.short, a.step.n, a.recovered) for a in actions if isinstance(a, StartStep)]


class StepState(unittest.TestCase):
    B = "feature/factory-c1-s1"

    def test_checked_item_is_done_whatever_its_prs(self):
        self.assertEqual(derive_step_state(done(), True, pr(1, self.B, "MERGED"), []), DONE)

    def test_dropped_prefix_is_dropped(self):
        self.assertEqual(derive_step_state(Item("[dropped] step", False), True, pr(1, self.B, "CLOSED"), []),
                         DROPPED_STATE)

    def test_no_branch_no_pr_is_pending(self):
        self.assertEqual(derive_step_state(todo(), False, None, []), PENDING)

    def test_branch_without_pr_is_in_progress(self):
        # a worker that died before opening its draft PR — the branch is the evidence (review O4)
        self.assertEqual(derive_step_state(todo(), True, None, []), IN_PROGRESS)

    def test_open_pr_is_in_progress(self):
        self.assertEqual(derive_step_state(todo(), True, pr(1, self.B), []), IN_PROGRESS)

    def test_merged_unchecked_is_merged_not_restarted(self):
        # review O1: merged, handoff not finished — never pending again
        self.assertEqual(derive_step_state(todo(), True, pr(1, self.B, "MERGED"), []), MERGED)

    def test_merged_with_open_fix_pr_is_fixing(self):
        fix = pr(2, self.B + "-fix1")
        self.assertEqual(derive_step_state(todo(), True, pr(1, self.B, "MERGED"), [fix]), FIXING)

    def test_merged_with_merged_fix_is_merged_again(self):
        fix = pr(2, self.B + "-fix1", "MERGED")
        self.assertEqual(derive_step_state(todo(), True, pr(1, self.B, "MERGED"), [fix]), MERGED)

    def test_closed_pr_without_prefix_holds_until_the_worker_marks_it(self):
        # the worker prefixes [dropped] on the pr-closed event; until then the step keeps its slot
        self.assertEqual(derive_step_state(todo(), True, pr(1, self.B, "CLOSED"), []), IN_PROGRESS)


class Slots(unittest.TestCase):
    def test_three_slot_holders_block_a_new_start(self):
        cards = [card(c, [todo()]) for c in ("a", "b", "c", "d")]
        w = world(cards, branches=[f"feature/factory-{c}-s1" for c in "abc"],
                  workers={f"factory-{c}-s1": "busy" for c in "abc"})
        self.assertEqual(started(decide(w)), [])

    def test_two_slot_holders_leave_room_for_one(self):
        cards = [card(c, [todo()]) for c in ("a", "b", "c", "d")]
        w = world(cards, branches=[f"feature/factory-{c}-s1" for c in "ab"],
                  workers={f"factory-{c}-s1": "busy" for c in "ab"})
        self.assertEqual(started(decide(w)), [("c", 1, None)])

    def test_merged_step_holds_no_slot(self):
        cards = [card("a", [todo()]), card("b", [todo()]), card("c", [todo()]), card("d", [todo()])]
        w = world(cards, prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=[f"feature/factory-{c}-s1" for c in "abc"],
                  workers={f"factory-{c}-s1": "busy" for c in "abc"})
        self.assertEqual(started(decide(w)), [("d", 1, None)])

    def test_fixing_step_holds_a_slot(self):
        cards = [card(c, [todo()]) for c in ("a", "b", "c", "d")]
        prs = [pr(1, "feature/factory-a-s1", "MERGED"), pr(2, "feature/factory-a-s1-fix1")]
        w = world(cards, prs=prs, branches=[f"feature/factory-{c}-s1" for c in "abc"],
                  workers={f"factory-{c}-s1": "busy" for c in "abc"})
        self.assertEqual(started(decide(w)), [])

    def test_split_worker_holds_no_slot(self):
        cards = [card("a"), card("b", [todo()])]
        w = world(cards, workers={"factory-a-split": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [("b", 1, None)])


class Eligibility(unittest.TestCase):
    def test_next_step_waits_while_previous_is_merged_but_unchecked(self):
        w = world([card("a", [todo("one"), todo("two")])], prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_next_step_starts_once_previous_is_checked(self):
        w = world([card("a", [done("one"), todo("two")])])
        self.assertEqual(started(decide(w)), [("a", 2, None)])

    def test_dropped_step_blocks_its_card(self):
        w = world([card("a", [Item("[dropped] one", False), todo("two")])])
        self.assertEqual(started(decide(w)), [])

    def test_card_under_way_goes_before_a_new_card(self):
        cards = [card("new", [todo()]), card("old", [done(), todo()])]
        self.assertEqual(started(decide(world(cards, wip=1))), [("old", 2, None)])

    def test_card_without_ready_label_is_not_started(self):
        self.assertEqual(started(decide(world([card("a", [todo()], ready=False)]))), [])


class Split(unittest.TestCase):
    def test_ready_card_without_checklist_gets_a_split_worker(self):
        actions = decide(world([card("a")]))
        self.assertEqual([a.card.short for a in actions if isinstance(a, StartSplit)], ["a"])

    def test_no_second_split_worker_while_the_first_waits_on_a_ping(self):
        actions = decide(world([card("a")], workers={"factory-a-split": "idle"}))
        self.assertEqual([a for a in actions if isinstance(a, StartSplit)], [])


class Recovery(unittest.TestCase):
    def test_dead_worker_with_branch_but_no_pr_is_replaced_not_restarted(self):
        w = world([card("a", [todo()])], branches=["feature/factory-a-s1"])
        self.assertEqual(started(decide(w)), [("a", 1, IN_PROGRESS)])

    def test_dead_worker_on_merged_step_is_replaced_for_the_handoff(self):
        w = world([card("a", [todo()])], prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-a-s1"])
        actions = decide(w)
        self.assertEqual(started(actions), [("a", 1, MERGED)])
        self.assertIn(MarkSent(("1:merged",)), actions)

    def test_done_step_with_dead_worker_is_cleaned_not_replaced(self):
        w = world([card("a", [done()])], branches=["feature/factory-a-s1"])
        actions = decide(w)
        self.assertEqual(started(actions), [])
        self.assertIn(Cleanup(None, "feature/factory-a-s1", "feature/factory-a-s1-fix"), actions)


class Events(unittest.TestCase):
    def test_merge_is_sent_to_the_live_worker_once(self):
        w = world([card("a", [todo()])], prs=[pr(7, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"})
        self.assertEqual([(a.worker, a.key) for a in decide(w) if isinstance(a, SendEvent)],
                         [("factory-a-s1", "7:merged")])

    def test_event_already_sent_is_not_resent(self):
        w = world([card("a", [todo()])], prs=[pr(7, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"}, sent=["7:merged"])
        self.assertEqual([a for a in decide(w) if isinstance(a, SendEvent)], [])

    def test_ci_failure_on_a_new_push_fires_again(self):
        w = world([card("a", [todo()])], prs=[pr(7, "feature/factory-a-s1", ci="failed", sha="new")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"},
                  sent=["7:ci-failed:old"])
        self.assertEqual([a.key for a in decide(w) if isinstance(a, SendEvent)], ["7:ci-failed:new"])

    def test_closed_pr_tells_the_worker_the_step_is_dropped(self):
        w = world([card("a", [todo()])], prs=[pr(7, "feature/factory-a-s1", "CLOSED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"})
        self.assertEqual([a.key for a in decide(w) if isinstance(a, SendEvent)], ["7:closed"])


def labelled(number, head, state="OPEN", base_labels=("factory",)):
    p = pr(number, head, state)
    return PR(p.number, p.state, p.head, p.head_sha, p.ci, p.conflicting, p.url, tuple(base_labels))


class Adoption(unittest.TestCase):
    """Items named `#<n> …` adopt that PR instead of building the step."""

    def test_unlabelled_adopted_pr_waits_as_pending_and_starts_first(self):
        w = world([card("a", [todo("#11 add the export"), todo("#12 schedule the export")])],
                  prs=[labelled(11, "feat/x", base_labels=()), labelled(12, "feat/y", base_labels=())])
        self.assertEqual(started(decide(w)), [("a", 1, None)])

    def test_labelled_adopted_pr_holds_a_slot(self):
        cards = [card("a", [todo("#11 add the export")]), card("b", [todo()])]
        w = world(cards, prs=[labelled(11, "feat/x")], workers={"factory-a-s1": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [])

    def test_stacked_adopted_pr_waits_until_the_earlier_step_is_done(self):
        w = world([card("a", [todo("#11 add the export"), todo("#12 schedule the export")])],
                  prs=[labelled(11, "feat/x", "MERGED"), labelled(12, "feat/y", base_labels=())],
                  workers={"factory-a-s1": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_stacked_adopted_pr_starts_once_the_earlier_step_is_checked(self):
        w = world([card("a", [done("#11 add the export"), todo("#12 schedule the export")])],
                  prs=[labelled(11, "feat/x", "MERGED"), labelled(12, "feat/y", base_labels=())])
        self.assertEqual(started(decide(w)), [("a", 2, None)])

    def test_merge_of_an_adopted_pr_reaches_its_worker(self):
        w = world([card("a", [todo("#11 add the export")])], prs=[labelled(11, "feat/x", "MERGED")],
                  workers={"factory-a-s1": "idle"})
        self.assertEqual([a.key for a in decide(w) if isinstance(a, SendEvent)], ["11:merged"])

    def test_dead_worker_of_a_taken_adopted_pr_is_replaced(self):
        w = world([card("a", [todo("#11 add the export")])], prs=[labelled(11, "feat/x")])
        self.assertEqual(started(decide(w)), [("a", 1, IN_PROGRESS)])

    def test_done_adopted_step_cleans_up_its_own_branch(self):
        w = world([card("a", [done("#11 add the export")])], prs=[labelled(11, "feat/x", "MERGED")],
                  branches=["feat/x"], workers={"factory-a-s1": "idle"})
        self.assertIn(Cleanup("factory-a-s1", "feat/x", "feature/factory-a-s1-fix"), decide(w))


class CleanupRule(unittest.TestCase):
    def test_idle_worker_of_a_done_step_is_cleaned(self):
        w = world([card("a", [done()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"})
        self.assertIn(Cleanup("factory-a-s1", "feature/factory-a-s1", "feature/factory-a-s1-fix"), decide(w))

    def test_busy_worker_of_a_done_step_is_left_alone(self):
        w = world([card("a", [done()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "busy"})
        self.assertNotIn(Cleanup("factory-a-s1", "feature/factory-a-s1", "feature/factory-a-s1-fix"), decide(w))

    def test_idle_worker_of_an_unfinished_step_is_left_alone(self):
        w = world([card("a", [todo()])], prs=[pr(1, "feature/factory-a-s1")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "idle"})
        self.assertEqual([a for a in decide(w) if isinstance(a, Cleanup)], [])


if __name__ == "__main__":
    unittest.main()
