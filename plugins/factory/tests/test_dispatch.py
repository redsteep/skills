"""The dispatcher's decision table: every rule and boundary of the spec's Tests section.
Run: python3 -m unittest discover -s plugins/factory/tests"""

import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from factory_dispatch import (  # noqa: E402
    takes_issue,
    DONE, DROPPED_STATE, FIXING, IN_PROGRESS, MERGED, PENDING, PR, Card, Cleanup, Item, Reinstruct, ReviewIdle, ReviewOff,
    Executor, MarkSent, SendEvent, StartSplit, StartStep, World, checked_out_at, decide, derive_step_state,
    _pr, deny_list, display_name, issue_card, uncommitted,
)
from factory_common import Profile  # noqa: E402


def card(short, items=None, ready=True):
    return Card(id=f"id-{short}", short=short, name=f"Card {short}", url=f"https://trello.com/c/{short}",
                ready=ready, items=None if items is None else tuple(items))


def todo(name="step"):
    return Item(name, False)


def done(name="step"):
    return Item(name, True)


def pr(number, head, state="OPEN", ci=None, conflicting=False, sha="abc"):
    return PR(number, state, head, sha, ci, conflicting, f"https://github.com/o/r/pull/{number}")


NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def world(cards, prs=(), branches=(), workers=None, sent=(), wip=3, issue_wip=1, issue_daily=None,
          presence=None, reviews=None, version=""):
    return World(tuple(cards), tuple(prs), frozenset(branches),
                 {name: {"status": status} for name, status in (workers or {}).items()},
                 frozenset(sent), wip, issue_wip=issue_wip, issue_daily=issue_daily, now=NOW,
                 presence=presence or {}, reviews=reviews or {}, version=version)


def issue(number, open_=True, body=""):
    return issue_card(number, f"Issue {number}", f"https://github.com/o/r/issues/{number}", open_, body)


STEPS_BODY = """## Problem

- [ ] not a step: a task list outside the steps section

## Factory steps

- [x] make the column NOT NULL
- [ ] make the domain types required

## Notes
- [ ] not a step either
"""


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

    def test_a_merged_step_with_its_worker_still_holds_its_slot(self):
        cards = [card("a", [todo()]), card("b", [todo()]), card("c", [todo()]), card("d", [todo()])]
        w = world(cards, prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=[f"feature/factory-{c}-s1" for c in "abc"],
                  workers={f"factory-{c}-s1": "busy" for c in "abc"})
        self.assertEqual(started(decide(w)), [])

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


class SlotsHeldByLiveWorkers(unittest.TestCase):
    """A slot is held by a live worker, not by a step's state: a step under way without one gets
    it back only through a free slot, ahead of any pending step."""

    def test_a_step_revived_by_its_closed_pr_waits_while_the_slot_is_taken(self):
        # an issue relabelled after its PR was closed: the closed PR reads in-progress, no worker
        w = world([issue(7), issue(8)], prs=[pr(1, "feature/factory-i7-s1", "CLOSED")],
                  branches=["feature/factory-i8-s1"], workers={"factory-i8-s1": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_a_step_without_a_worker_is_replaced_when_a_slot_is_free(self):
        w = world([issue(7)], prs=[pr(1, "feature/factory-i7-s1", "CLOSED")])
        self.assertEqual(started(decide(w)), [("i7", 1, IN_PROGRESS)])

    def test_a_crashed_step_gets_the_slot_back_before_a_pending_one(self):
        w = world([card("b", [todo()]), card("a", [todo()])], branches=["feature/factory-a-s1"],
                  workers={"factory-a-s1": "dead"}, wip=1)
        self.assertEqual(started(decide(w)), [("a", 1, IN_PROGRESS)])

    def test_a_restarting_worker_keeps_its_slot(self):
        w = world([card("a", [todo()]), card("b", [todo()])], branches=["feature/factory-a-s1"],
                  workers={"factory-a-s1": "restarting"}, wip=1)
        self.assertEqual(started(decide(w)), [])

    def test_a_fixing_step_without_a_worker_waits_for_a_slot(self):
        prs = [pr(1, "feature/factory-a-s1", "MERGED"), pr(2, "feature/factory-a-s1-fix1")]
        w = world([card("a", [todo()]), card("b", [todo()])], prs=prs, branches=["feature/factory-b-s1"],
                  workers={"factory-b-s1": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [])

    def test_a_merged_step_is_replaced_with_the_pool_full(self):
        # the handoff needs a worker, and a merged step holds no slot
        w = world([card("a", [todo()]), card("b", [todo()])], prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-b-s1"], workers={"factory-b-s1": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [("a", 1, MERGED)])

    def test_a_merged_step_in_its_handoff_keeps_the_slot(self):
        w = world([issue(7), issue(8)], prs=[pr(1, "feature/factory-i7-s1", "MERGED")],
                  workers={"factory-i7-s1": "busy"}, sent=["1:merged"])
        self.assertEqual(started(decide(w)), [])

    def test_a_done_step_keeps_the_slot_until_its_worker_is_stopped(self):
        w = world([issue(7, body=STEPS_BODY.replace("- [ ] make the domain", "- [x] make the domain")), issue(8)],
                  workers={"factory-i7-s2": "idle"})
        self.assertEqual(started(decide(w)), [])

    def test_once_the_worker_is_stopped_the_issues_next_step_takes_the_slot(self):
        body = STEPS_BODY.replace("- [x] make the column", "- [x] make the column").replace(
            "- [ ] make the domain types required", "- [ ] make the domain types required\n- [ ] then the cleanup")
        w = world([issue(7, body=body), issue(8)], prs=[pr(1, "feature/factory-i7-s1", "MERGED")])
        self.assertEqual(started(decide(w)), [("i7", 2, None)])

    def test_a_replacement_is_no_new_start_for_the_daily_cap(self):
        p = pr(1, "feature/factory-i7-s1")
        today = PR(p.number, p.state, p.head, p.head_sha, p.ci, p.conflicting, p.url, created=NOW - timedelta(hours=1))
        w = world([issue(7)], prs=[today], issue_daily=1)
        self.assertEqual(started(decide(w)), [("i7", 1, IN_PROGRESS)])

    def test_a_replacement_takes_the_slot_from_a_pending_step_in_the_same_pool(self):
        w = world([issue(8), issue(7)], prs=[pr(1, "feature/factory-i7-s1")])
        self.assertEqual(started(decide(w)), [("i7", 1, IN_PROGRESS)])


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


class Issues(unittest.TestCase):
    def test_open_issue_starts_as_a_one_step_job(self):
        self.assertEqual(started(decide(world([issue(7)]))), [("i7", 1, None)])

    def test_issue_has_its_own_slot_when_the_card_pool_is_full(self):
        w = world([card("a", [todo()]), issue(7)], wip=1)
        self.assertEqual(started(decide(w)), [("a", 1, None), ("i7", 1, None)])

    def test_a_busy_issue_does_not_eat_a_cards_slot(self):
        w = world([card("a", [todo()]), issue(7)], branches=["feature/factory-i7-s1"],
                  workers={"factory-i7-s1": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [("a", 1, None)])

    def test_issue_takes_a_slot_no_card_step_can_use(self):
        # the card's next step waits for its merged one: the free slot goes to the issue
        w = world([card("a", [todo("one"), todo("two")]), issue(7)], prs=[pr(1, "feature/factory-a-s1", "MERGED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "busy"}, wip=1)
        self.assertEqual(started(decide(w)), [("i7", 1, None)])

    def test_issue_limit_holds_with_slots_free(self):
        w = world([issue(7), issue(8)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_issue_limit_above_one_lets_the_next_issue_in(self):
        w = world([issue(7), issue(8)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"},
                  issue_wip=2)
        self.assertEqual(started(decide(w)), [("i8", 1, None)])

    def test_daily_cap_counts_issue_prs_opened_in_the_last_24_hours(self):
        def merged(number, hours_ago):
            p = pr(number, f"feature/factory-i{number}-s1", "MERGED")
            return PR(p.number, p.state, p.head, p.head_sha, p.ci, p.conflicting, p.url,
                      created=NOW - timedelta(hours=hours_ago))
        for cap, prs, expected in [
            (3, [merged(1, 1), merged(2, 2)], [("i9", 1, None)]),            # 2 today: under the cap
            (3, [merged(1, 1), merged(2, 2), merged(3, 24)], []),            # exactly 24 h ago still counts
            (3, [merged(1, 1), merged(2, 2), merged(3, 24.01)], [("i9", 1, None)]),  # just past: dropped out
        ]:
            with self.subTest(prs=[p.created for p in prs]):
                w = world([issue(n, open_=False) for n in (1, 2, 3)] + [issue(9)], prs=prs, issue_daily=cap)
                self.assertEqual(started(decide(w)), expected)

    def test_daily_cap_counts_a_started_issue_without_its_pr_yet(self):
        w = world([issue(7), issue(8)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"},
                  issue_wip=2, issue_daily=1)
        self.assertEqual(started(decide(w)), [])

    def test_closed_issue_is_cleaned_up(self):
        w = world([issue(7, open_=False)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "idle"})
        self.assertEqual([a for a in decide(w) if isinstance(a, Cleanup)],
                         [Cleanup("factory-i7-s1", "feature/factory-i7-s1", "feature/factory-i7-s1-fix")])

    def test_issue_worker_gets_the_issue_deny_rules_and_may_close_its_issue(self):
        profile = Profile("## Deny\n- `mcp__x`\n## Issues\n- **Label:** `ok`\n- `mcp__trello`\n")
        self.assertEqual([r for r in deny_list(profile, issue=True) if r.startswith("mcp__")],
                         ["mcp__x", "mcp__trello"])
        self.assertNotIn("mcp__trello", deny_list(profile))
        self.assertFalse([r for r in deny_list(profile, issue=True) if r.startswith("Bash(gh issue close")])

    def test_every_worker_may_edit_issues(self):
        # an issue's worker writes its step list into the body; any worker corrects an issue it filed
        profile = Profile("## Issues\n- **Label:** `ok`\n")
        for issue in (True, False):
            with self.subTest(issue=issue):
                self.assertFalse([r for r in deny_list(profile, issue=issue) if r.startswith("Bash(gh issue edit")])

    def test_every_worker_may_comment_on_issues(self):
        # a test that flaked again is noted on the issue already open for it
        self.assertFalse([r for r in deny_list(Profile("")) if r.startswith("Bash(gh issue comment")])


class IssueSteps(unittest.TestCase):
    def test_the_steps_section_of_the_body_is_the_step_list(self):
        self.assertEqual(issue(7, body=STEPS_BODY).items,
                         (done("make the column NOT NULL"), todo("make the domain types required")))

    def test_without_a_steps_section_the_issue_is_one_step(self):
        self.assertEqual(issue(7, body="## Problem\n- [ ] a task\n").items, (todo("Issue 7"),))

    def test_a_closed_issue_reads_done_throughout(self):
        self.assertEqual(issue(7, open_=False, body=STEPS_BODY).items,
                         (done("make the column NOT NULL"), done("make the domain types required")))

    def test_the_next_step_starts_once_the_ticked_one_is_cleaned_up(self):
        w = world([issue(7, body=STEPS_BODY)], prs=[pr(1, "feature/factory-i7-s1", "MERGED")])
        self.assertEqual(started(decide(w)), [("i7", 2, None)])

    def test_the_next_step_waits_while_the_merged_one_is_unticked(self):
        body = STEPS_BODY.replace("- [x]", "- [ ]")
        w = world([issue(7, body=body)], prs=[pr(1, "feature/factory-i7-s1", "MERGED")],
                  branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_a_list_written_mid_step_keeps_the_running_worker_as_step_one(self):
        # the first worker splits while it runs: same branch, same worker, nothing restarted
        body = STEPS_BODY.replace("- [x]", "- [ ]")
        w = world([issue(7, body=body)], branches=["feature/factory-i7-s1"], workers={"factory-i7-s1": "busy"})
        self.assertEqual(started(decide(w)), [])
        self.assertFalse([a for a in decide(w) if isinstance(a, Cleanup)])

    def test_each_step_counts_against_the_daily_cap(self):
        p = pr(1, "feature/factory-i7-s1", "MERGED")
        today = PR(p.number, p.state, p.head, p.head_sha, p.ci, p.conflicting, p.url, created=NOW - timedelta(hours=1))
        w = world([issue(7, body=STEPS_BODY)], prs=[today], issue_daily=1)
        self.assertEqual(started(decide(w)), [])


class DisplayName(unittest.TestCase):
    def test_step_names_card_and_position(self):
        c = card("a", [todo(), todo()])
        step = next(a.step for a in decide(world([c])) if isinstance(a, StartStep))
        self.assertEqual(display_name(c, step, 2), "factory · Card a · 1/2")

    def test_issue_names_its_number_and_title(self):
        self.assertEqual(display_name(issue(7)), "factory · #7 Issue 7")

    def test_long_name_is_cut_with_an_ellipsis(self):
        c = card("a")
        long = Card(c.id, c.short, "x" * 80, c.url, True, None)
        self.assertEqual(display_name(long), "factory · " + "x" * 69 + "…")


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


def gh_pr(number, rollup, sha="86e5"):
    """A PR as `gh pr list --json` returns it, with the given check rollup."""
    return _pr({"number": number, "state": "OPEN", "headRefName": "feature/factory-a-s1", "headRefOid": sha,
                "statusCheckRollup": rollup, "mergeable": "MERGEABLE", "url": f"https://github.com/o/r/pull/{number}"})


SMOKE_FAILED = {"name": "Smoke", "status": "COMPLETED", "conclusion": "FAILURE", "completedAt": "2026-10-28T14:05:43Z"}
SMOKE_PASSED = {**SMOKE_FAILED, "conclusion": "SUCCESS", "completedAt": "2026-10-28T15:00:00Z"}
HEADS_FAILED = {"context": "migration-heads", "state": "FAILURE", "createdAt": "2026-10-29T11:07:54Z"}


class CiRounds(unittest.TestCase):
    """A check can fail on a commit that already had its ci event — a re-run, or a status main's
    own changes re-post — and the worker must still hear of it."""

    def events(self, rollup, sent=()):
        w = world([card("a", [todo()])], prs=[gh_pr(7, rollup)], branches=["feature/factory-a-s1"],
                  workers={"factory-a-s1": "busy"}, sent=sent)
        return [a for a in decide(w) if isinstance(a, SendEvent)]

    def test_a_new_failure_on_an_already_reported_commit_is_sent(self):
        first = self.events([SMOKE_FAILED])[0].key
        later = self.events([SMOKE_PASSED, HEADS_FAILED], sent=[first, "7:ci-passed:86e5:2026-10-28T15:00:00Z"])
        self.assertEqual([e.text for e in later],
                         ["Factory event: ci-failed PR #7 (migration-heads) https://github.com/o/r/pull/7/checks"])

    def test_the_same_failure_is_sent_once(self):
        first = self.events([SMOKE_FAILED])[0].key
        self.assertEqual(self.events([SMOKE_FAILED], sent=[first]), [])

    def test_a_rerun_that_fails_again_is_sent_again(self):
        first = self.events([SMOKE_FAILED])[0].key
        rerun = {**SMOKE_FAILED, "completedAt": "2026-10-28T16:00:00Z"}
        self.assertEqual(len(self.events([rerun], sent=[first])), 1)

    def test_green_again_after_a_rerun_is_sent(self):
        early = {**SMOKE_PASSED, "completedAt": "2026-10-28T13:00:00Z"}
        sent = [self.events([early])[0].key, self.events([SMOKE_FAILED])[0].key]
        self.assertEqual([e.text for e in self.events([SMOKE_PASSED], sent=sent)],
                         ["Factory event: ci-passed PR #7"])


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


class CarvedAdoptedPR(unittest.TestCase):
    """A step worker that cuts its adopted PR inserts the pieces before it on the checklist: the
    adopted PR, still labelled, sits behind them, and the worker's own step becomes the first piece."""

    CARVED = [done("one"), todo("#20 refactor, no behaviour change"), todo("#21 the migration"),
              todo("#12 count the orders")]

    def test_the_labelled_adopted_pr_behind_the_pieces_gets_no_worker(self):
        w = world([card("a", self.CARVED)],
                  prs=[labelled(20, "feat/x-refactor"), labelled(21, "feat/x-migration", base_labels=()),
                       labelled(12, "feat/x")],
                  workers={"factory-a-s2": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_a_dead_worker_behind_an_unfinished_step_is_not_replaced(self):
        w = world([card("a", self.CARVED)],
                  prs=[labelled(20, "feat/x-refactor"), labelled(21, "feat/x-migration", base_labels=()),
                       labelled(12, "feat/x")])
        self.assertEqual(started(decide(w)), [("a", 2, IN_PROGRESS)])

    def test_the_cutting_worker_gets_no_twin_before_its_piece_is_labelled(self):
        w = world([card("a", self.CARVED)],
                  prs=[labelled(20, "feat/x-refactor", base_labels=()),
                       labelled(21, "feat/x-migration", base_labels=()), labelled(12, "feat/x")],
                  workers={"factory-a-s2": "busy"})
        self.assertEqual(started(decide(w)), [])

    def test_the_adopted_pr_is_replaced_once_the_pieces_are_done(self):
        items = [done("one"), done("#20 refactor"), done("#21 the migration"), todo("#12 count the orders")]
        w = world([card("a", items)],
                  prs=[labelled(20, "feat/x-refactor", "MERGED"), labelled(21, "feat/x-migration", "MERGED"),
                       labelled(12, "feat/x")])
        self.assertEqual(started(decide(w)), [("a", 4, IN_PROGRESS)])


class BaseBranchCi(unittest.TestCase):
    """CI on the base branch after a merge reaches the step's worker: a red run skips the deploy
    its handoff waits for."""

    def merged(self, base_ci, sent=()):
        p = replace(pr(7, "feature/factory-a-s1", "MERGED"), merge_sha="5d589aea0000", base_ci=base_ci)
        w = world([card("a", [todo()])], prs=[p], workers={"factory-a-s1": "busy"},
                  sent=["7:merged", *sent])
        return [a for a in decide(w) if isinstance(a, SendEvent)]

    def test_a_failure_on_the_merge_commit_is_sent(self):
        self.assertEqual([e.text for e in self.merged(("failed", ("Frontend Tests (1)",), "r1"))],
                         ["Factory event: base-ci-failed PR #7 — CI on the merge commit 5d589aea failed "
                          "(Frontend Tests (1)), so it was not deployed"])

    def test_the_same_failure_is_sent_once_and_a_rerun_failing_again_anew(self):
        first = self.merged(("failed", ("Frontend Tests (1)",), "r1"))[0].key
        self.assertEqual(self.merged(("failed", ("Frontend Tests (1)",), "r1"), sent=[first]), [])
        self.assertEqual(len(self.merged(("failed", ("Frontend Tests (1)",), "r2"), sent=[first])), 1)

    def test_green_or_pending_base_ci_sends_nothing(self):
        for ci in (("passed", (), "t"), ("pending", (), ""), (None, (), "")):
            with self.subTest(ci=ci[0]):
                self.assertEqual(self.merged(ci), [])


class ReviewPresence(unittest.TestCase):
    """Review mode lasts while the developer is in the worker's conversation: 15 minutes of
    silence there turns it off, and the worker then applies whatever they queued."""

    BRANCH = "feature/factory-a-s1"

    def idle(self, presence, reviews, prs=()):
        w = world([card("a", [todo()])], prs=prs or [pr(7, self.BRANCH)], branches=[self.BRANCH],
                  workers={"factory-a-s1": "idle"}, presence=presence, reviews=reviews)
        return [a for a in decide(w) if isinstance(a, ReviewIdle)]

    def test_fifteen_minutes_of_silence_ends_the_review(self):
        self.assertEqual(self.idle({"factory-a-s1": NOW - timedelta(minutes=15)}, {self.BRANCH: 0}),
                         [ReviewIdle("factory-a-s1", self.BRANCH)])

    def test_just_under_fifteen_minutes_the_review_stays(self):
        self.assertEqual(self.idle({"factory-a-s1": NOW - timedelta(minutes=14, seconds=59)}, {self.BRANCH: 0}), [])

    def test_a_review_the_developer_never_spoke_in_ends(self):
        self.assertEqual(self.idle({}, {self.BRANCH: 0}), [ReviewIdle("factory-a-s1", self.BRANCH)])

    def test_a_review_with_queued_changes_ends_too(self):
        self.assertEqual(self.idle({}, {self.BRANCH: 2}), [ReviewIdle("factory-a-s1", self.BRANCH)])

    def test_no_review_on_nothing_to_end(self):
        self.assertEqual(self.idle({}, {}), [])

    def test_a_fix_prs_review_ends_too(self):
        fix = "feature/factory-a-s1-fix1"
        prs = [pr(7, self.BRANCH, "MERGED"), pr(8, fix)]
        self.assertEqual(self.idle({}, {fix: 0}, prs), [ReviewIdle("factory-a-s1", fix)])

    def test_another_workers_review_is_left_alone(self):
        self.assertEqual(self.idle({}, {"feature/factory-b-s1": 0}), [])


class ReviewWithoutAPr(unittest.TestCase):
    """A review whose PR is gone has nothing left to review: it goes off at once, even with the
    developer here, so a redo's edits are not denied by the old review's marker."""

    BRANCH = "feature/factory-a-s1"

    def actions(self, prs, reviews, presence=None):
        w = world([card("a", [todo()])], prs=prs, branches=[self.BRANCH], workers={"factory-a-s1": "busy"},
                  presence=presence or {"factory-a-s1": NOW}, reviews=reviews)
        return [a for a in decide(w) if isinstance(a, (ReviewOff, ReviewIdle))]

    def test_a_closed_prs_review_goes_off_with_the_developer_here(self):
        self.assertEqual(self.actions([pr(7, self.BRANCH, "CLOSED")], {self.BRANCH: 0}), [ReviewOff(self.BRANCH)])

    def test_an_open_prs_review_stays_while_the_developer_is_here(self):
        self.assertEqual(self.actions([pr(7, self.BRANCH)], {self.BRANCH: 0}), [])

    def test_a_closed_fix_prs_review_goes_off_too(self):
        fix = "feature/factory-a-s1-fix1"
        prs = [pr(7, self.BRANCH, "MERGED"), pr(8, fix, "CLOSED")]
        self.assertEqual(self.actions(prs, {fix: 1}), [ReviewOff(fix)])

    def test_another_steps_review_is_left_alone(self):
        self.assertEqual(self.actions([pr(7, self.BRANCH, "CLOSED")], {"feature/factory-a-s2": 0}), [])


class Reinstructing(unittest.TestCase):
    """A worker started on an older factory gets its instructions again, once per version."""

    def reinstructed(self, workers, sent=(), version="0.13.0"):
        w = world([card("a", [todo()])], branches=["feature/factory-a-s1"], workers=workers,
                  sent=sent, version=version)
        return [a.step.worker for a in decide(w) if isinstance(a, Reinstruct)]

    def test_a_live_worker_without_this_version_is_reinstructed(self):
        self.assertEqual(self.reinstructed({"factory-a-s1": "busy"}), ["factory-a-s1"])

    def test_once_per_version(self):
        self.assertEqual(self.reinstructed({"factory-a-s1": "busy"}, sent=["instructions:0.13.0:factory-a-s1"]), [])
        self.assertEqual(self.reinstructed({"factory-a-s1": "busy"}, sent=["instructions:0.12.3:factory-a-s1"]),
                         ["factory-a-s1"])

    def test_a_dead_worker_is_replaced_not_reinstructed(self):
        self.assertEqual(self.reinstructed({"factory-a-s1": "dead"}), [])

    def test_a_done_steps_worker_waiting_to_be_stopped_is_left_alone(self):
        w = world([card("a", [done()])], workers={"factory-a-s1": "busy"}, version="0.13.0")
        self.assertEqual([a for a in decide(w) if isinstance(a, Reinstruct)], [])

    def test_no_version_known_no_reinstructing(self):
        self.assertEqual(self.reinstructed({"factory-a-s1": "busy"}, version=""), [])


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


class DeadAndRestartingWorkers(unittest.TestCase):
    """`dead`: listed with no process. `restarting`: seen alive within the grace, now missing or
    without a process — it counts as live, so a restart never gets a twin."""

    def test_dead_worker_of_an_unfinished_step_is_replaced(self):
        w = world([card("a", [todo()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "dead"})
        self.assertEqual(started(decide(w)), [("a", 1, IN_PROGRESS)])

    def test_dead_worker_is_sent_no_events(self):
        w = world([card("a", [todo()])], prs=[pr(7, "feature/factory-a-s1", "CLOSED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "dead"})
        self.assertEqual([a for a in decide(w) if isinstance(a, SendEvent)], [])

    def test_dead_worker_of_a_done_step_is_cleaned(self):
        w = world([card("a", [done()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "dead"})
        self.assertIn(Cleanup("factory-a-s1", "feature/factory-a-s1", "feature/factory-a-s1-fix"), decide(w))

    def test_dead_worker_of_a_card_no_longer_ready_is_cleaned(self):
        w = world([card("a", [todo()], ready=False)], prs=[pr(7, "feature/factory-a-s1", "CLOSED")],
                  branches=["feature/factory-a-s1"], workers={"factory-a-s1": "dead"})
        self.assertIn(Cleanup("factory-a-s1", "feature/factory-a-s1", "feature/factory-a-s1-fix"), decide(w))

    def test_dead_split_worker_is_replaced(self):
        w = world([card("a")], workers={"factory-a-split": "dead"})
        self.assertEqual([a.card.short for a in decide(w) if isinstance(a, StartSplit)], ["a"])

    def test_restarting_worker_is_not_replaced(self):
        w = world([card("a", [todo()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "restarting"})
        self.assertEqual(started(decide(w)), [])

    def test_restarting_worker_of_a_done_step_is_not_cleaned(self):
        w = world([card("a", [done()])], branches=["feature/factory-a-s1"], workers={"factory-a-s1": "restarting"})
        self.assertEqual([a for a in decide(w) if isinstance(a, Cleanup)], [])


class ExistingWorktree(unittest.TestCase):
    """An adopted PR's branch may already be checked out in a worktree the developer named: the
    step takes it over when it holds nothing unsaved, and refuses otherwise."""

    PORCELAIN = ("worktree /r\nHEAD 1\nbranch refs/heads/main\n\n"
                 "worktree /r/.worktrees/mine\nHEAD 2\nbranch refs/heads/feat/orders\n")

    def test_finds_the_worktree_by_branch_not_by_name(self):
        self.assertEqual(checked_out_at(self.PORCELAIN, "feat/orders"), Path("/r/.worktrees/mine"))

    def test_a_branch_checked_out_nowhere_has_no_worktree(self):
        self.assertIsNone(checked_out_at(self.PORCELAIN, "feat/order"))

    def test_a_file_turned_symlink_is_setup_not_work(self):
        self.assertEqual(uncommitted(" T dev.env\n M src/a.py\n?? notes.md\n"), [" M src/a.py", "?? notes.md"])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        def git(*args, cwd=None):
            return subprocess.run(["git", *args], cwd=cwd or self.repo, check=True, capture_output=True, text=True)
        self.git = git
        git("init", "-q", "--bare", str(self.tmp / "origin.git"), cwd=self.tmp)
        self.repo = self.tmp / "repo"
        git("init", "-q", "-b", "main", str(self.repo), cwd=self.tmp)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        git("remote", "add", "origin", str(self.tmp / "origin.git"))
        git("push", "-q", "origin", "main", "main:feat/orders")
        self.mine = self.repo / ".worktrees/mine"
        git("worktree", "add", "-q", str(self.mine), "-b", "feat/orders", "origin/feat/orders")
        self.executor = Executor(self.repo, Profile(""))

    def tearDown(self):
        subprocess.run(["rm", "-rf", str(self.tmp)], check=True)

    def test_a_clean_worktree_in_sync_is_taken_over(self):
        self.assertEqual(self.executor._existing_worktree("feat/orders"), self.mine)

    def test_uncommitted_work_is_refused(self):
        (self.mine / "wip.py").write_text("x")
        with self.assertRaisesRegex(RuntimeError, "1 uncommitted change"):
            self.executor._existing_worktree("feat/orders")

    def test_an_unpushed_commit_is_refused(self):
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "local",
                 cwd=self.mine)
        with self.assertRaisesRegex(RuntimeError, "1 unpushed commit"):
            self.executor._existing_worktree("feat/orders")

    def test_the_main_checkout_is_never_taken(self):
        with self.assertRaisesRegex(RuntimeError, "main checkout"):
            self.executor._existing_worktree("main")


if __name__ == "__main__":
    unittest.main()


class NeedsDecision(unittest.TestCase):
    """A worker that finds a design decision in an issue hands it back by labelling it. Without
    this the factory would offer the same issue every two minutes and the slot never moves."""

    def issue(self, *labels):
        return {"number": 7, "labels": [{"name": n} for n in labels]}

    def test_an_issue_marked_as_needing_a_decision_is_not_taken(self):
        self.assertFalse(takes_issue(self.issue("tech-debt", "autofix: no"), "autofix: no"))

    def test_an_unmarked_issue_is_taken(self):
        self.assertTrue(takes_issue(self.issue("tech-debt"), "autofix: no"))

    def test_without_the_key_every_issue_is_taken(self):
        self.assertTrue(takes_issue(self.issue("tech-debt", "autofix: no"), ""))

    def test_no_labels_at_all_is_taken(self):
        self.assertTrue(takes_issue({"number": 7}, "autofix: no"))
