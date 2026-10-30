"""The auto-merge gate: one case just inside and one just outside each rule, and every other
merge route denied however small the PR."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import json
import tempfile

from auto_merge_gate import (Diff, Gate, approval_failed, ci_state, failed_rule,  # noqa: E402
                             force_push, judge)
from review_presence import typed_by_developer  # noqa: E402
from factory_common import developer_messages  # noqa: E402

EXCLUDED = ("db/migrations/", "*.lock", "src/generated/api.ts")
GATE = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED)
TRIAGE = "Summary\n\nTriage: copy change in one template, nothing open from review."


def diff(additions=10, deletions=0, files=("docs/a.md",), labels=("factory",), body=TRIAGE, stacked=(),
         head_committed="", ci_failed=False, ci_unfinished=False):
    return Diff(additions, deletions, tuple(files), tuple(labels), body, tuple(stacked), head_committed,
                ci_failed, ci_unfinished)


def verdict(command, d=None, gate=GATE):
    return judge(command, lambda _number: d or diff(), gate)


class GateRules(unittest.TestCase):
    def test_tiny_factory_pr_passes(self):
        self.assertIsNone(failed_rule(diff(), GATE))

    def test_size_is_not_a_rule(self):
        """Reversibility, not size, decides — the project's Precondition says so, not a line count."""
        self.assertIsNone(failed_rule(diff(additions=900, deletions=400, files=tuple("abcdefgh")), GATE))

    def test_each_excluded_path_is_refused(self):
        for path, pattern in [("db/migrations/0042_add_x.py", "db/migrations/"),
                              ("app/poetry.lock", "*.lock"),
                              ("src/generated/api.ts", "src/generated/api.ts")]:
            with self.subTest(path=path):
                self.assertEqual(failed_rule(diff(files=(path,)), GATE),
                                 f"`{path}` matches excluded `{pattern}`")

    def test_directory_pattern_does_not_match_a_sibling_name(self):
        self.assertIsNone(failed_rule(diff(files=("db/migrations_notes.md",)), GATE))

    def test_pr_without_factory_label_is_refused_however_small(self):
        self.assertEqual(failed_rule(diff(labels=()), GATE), "not a factory PR (no `factory` label)")

    def test_pr_with_a_pr_stacked_on_it_is_refused_however_small(self):
        self.assertEqual(failed_rule(diff(stacked=(12,)), GATE),
                         "#12 stacked on it — the developer merges it with a merge commit")

    def test_pr_without_triage_reason_is_refused(self):
        self.assertEqual(failed_rule(diff(body="Summary only"), GATE),
                         "no `Triage:` paragraph in the PR description")


class MergeRoutes(unittest.TestCase):
    def test_gated_auto_squash_merge_is_allowed(self):
        self.assertEqual(verdict("gh pr merge --auto --squash 412"),
                         ("allow", "auto-merge gate passed for PR #412"))

    def test_failing_gate_is_denied_with_the_rule(self):
        decision, reason = verdict("gh pr merge --auto --squash 412", diff(files=("app/poetry.lock",)))
        self.assertEqual(decision, "deny")
        self.assertIn("matches excluded `*.lock`", reason)

    def test_other_merge_forms_are_denied_even_for_a_tiny_pr(self):
        for command in ["gh pr merge 412", "gh pr merge --squash 412", "gh pr merge --auto --merge 412",
                        "gh pr merge --auto --squash --admin 412", "gh pr merge --auto --squash",
                        "gh pr merge --auto --squash 412 && echo ok",
                        "gh api -X PUT repos/o/r/pulls/412/merge",
                        "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
                        "git push origin HEAD:main"]:
            with self.subTest(command=command):
                self.assertEqual(verdict(command)[0], "deny")

    def test_the_profiles_command_is_the_allowed_one(self):
        """A project whose repo has auto-merge disabled declares a synchronous merge instead, and
        then the plugin's own default is the denied form."""
        gate = Gate(required_args=("--squash", "--match-head-commit"), precondition="", excluded=EXCLUDED)
        self.assertEqual(verdict("gh pr merge --squash --match-head-commit abc123 412", gate=gate),
                         ("allow", "auto-merge gate passed for PR #412"))
        decision, reason = verdict("gh pr merge --auto --squash 412", gate=gate)
        self.assertEqual(decision, "deny")
        self.assertIn("gh pr merge --squash --match-head-commit <number>", reason)

    def test_unrelated_commands_get_no_opinion(self):
        for command in ["gh pr view 412", "gh api repos/o/r/pulls/412/comments", "git push origin feature/factory-a-s1"]:
            with self.subTest(command=command):
                self.assertIsNone(verdict(command))


class Precondition(unittest.TestCase):
    """The project's own "safe to merge right now", in its own words."""

    def gate(self, precondition):
        return Gate(required_args=("--auto", "--squash"), precondition=precondition, excluded=EXCLUDED)

    def test_zero_exit_allows(self):
        self.assertEqual(verdict("gh pr merge --auto --squash 412", gate=self.gate("exit 0")),
                         ("allow", "auto-merge gate passed for PR #412"))

    def test_non_zero_exit_denies_with_what_it_said(self):
        decision, reason = verdict("gh pr merge --auto --squash 412",
                                   gate=self.gate("echo 'main deploy is red'; exit 1"))
        self.assertEqual(decision, "deny")
        self.assertIn("main deploy is red", reason)

    def test_silent_failure_still_denies(self):
        decision, reason = verdict("gh pr merge --auto --squash 412", gate=self.gate("exit 3"))
        self.assertEqual(decision, "deny")
        self.assertIn("exited 3", reason)

    def test_the_pr_number_reaches_it(self):
        gate = self.gate("test '<number>' = 412")
        self.assertEqual(verdict("gh pr merge --auto --squash 412", gate=gate)[0], "allow")
        self.assertEqual(verdict("gh pr merge --auto --squash 777", gate=gate)[0], "deny")


LGTM_GATE = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED, lgtm_merge=True)
HEAD = "2026-10-29T10:00:00Z"
AFTER, BEFORE = "2026-10-29T10:05:00Z", "2026-10-29T09:55:00Z"


def migration(**kw):
    return diff(files=("db/migrations/0042_add_x.py",), **{"head_committed": HEAD, **kw})


def lgtm_verdict(command, d, said, gate=LGTM_GATE):
    return judge(command, lambda _number: d, gate, messages=lambda: said)


class MergeOnLgtm(unittest.TestCase):
    """The developer's LGTM, typed in the worker's conversation after the head commit, merges what
    the worker's own judgement may not; nothing else does."""

    def test_lgtm_after_the_head_commit_merges_an_excluded_path(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), [(AFTER, "LGTM")]),
                         ("allow", "merging PR #412 on the developer's LGTM"))

    def test_lgtm_before_the_head_commit_is_refused(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), [(BEFORE, "LGTM")]),
                         ("deny", "merge on LGTM: a commit was pushed after your LGTM — look again."))

    def test_without_the_profile_switch_an_lgtm_changes_nothing(self):
        gate = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED)
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), [(AFTER, "LGTM")], gate)[0],
                         "deny")

    def test_no_developer_message_is_refused(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), []),
                         ("deny", "merge on LGTM: no LGTM from the developer in this conversation."))

    def test_a_later_hold_beats_an_earlier_lgtm(self):
        said = [(AFTER, "LGTM"), ("2026-10-29T10:06:00Z", "wait, don't merge yet")]
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), said),
                         ("deny", "merge on LGTM: your latest word on it is a hold."))

    def test_an_lgtm_naming_another_pr_does_not_count(self):
        self.assertEqual(approval_failed([(AFTER, "#413 LGTM")], "412", migration()),
                         "no LGTM from the developer in this conversation")

    def test_an_lgtm_naming_this_pr_counts(self):
        self.assertIsNone(approval_failed([(AFTER, "#412 LGTM - merge")], "412", migration()))

    def test_a_question_about_merging_is_no_approval(self):
        self.assertEqual(approval_failed([(AFTER, "should we merge?")], "412", migration()),
                         "no LGTM from the developer in this conversation")

    def test_failed_ci_is_refused(self):
        self.assertEqual(approval_failed([(AFTER, "LGTM")], "412", migration(ci_failed=True)),
                         "CI failed on the head commit")

    def test_unfinished_ci_is_a_wait_that_names_ci(self):
        """The developer's LGTM normally arrives while the checks are still running: a push of
        their queued changes voids the previous LGTM and restarts CI, so the one they then type is
        minutes older than the build. The reason names CI because that is how the worker tells a
        wait from a review path — it holds the approval and retries on `ci-passed` instead of
        reporting a failure to someone who already said yes."""
        self.assertEqual(approval_failed([(AFTER, "LGTM")], "412", migration(ci_unfinished=True)),
                         "CI has not finished on the head commit")

    def test_a_finished_green_ci_merges(self):
        self.assertIsNone(approval_failed([(AFTER, "LGTM")], "412", migration()))

    def test_a_failed_check_beats_an_unfinished_one(self):
        """Two checks, one red and one still running: the red one decides — waiting for the other
        would end in the merge of a branch already known to be broken."""
        self.assertEqual(approval_failed([(AFTER, "LGTM")], "412",
                                         migration(ci_failed=True, ci_unfinished=True)),
                         "CI failed on the head commit")

    def test_the_precondition_is_told_that_this_merge_is_on_an_lgtm(self):
        """A project that moved the excluded paths into its Precondition has to learn which merge
        this is, or the ban the LGTM waives comes back through the command and the developer's word
        means nothing. Measured live on PR #404: the hook waived its own paths, the project's
        `--gate` refused on the same path, and the merge the developer had approved did not happen.
        What the command still refuses on an LGTM — a red CI, a deploy of the base already
        running — stays its own call."""
        lgtm = Gate(required_args=("--auto", "--squash"), excluded=EXCLUDED, lgtm_merge=True,
                    precondition='test "$FACTORY_LGTM" = 1')
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(), [(AFTER, "LGTM")],
                                      gate=lgtm)[0], "allow")

    def test_an_ordinary_auto_merge_does_not_claim_an_lgtm(self):
        plain = Gate(required_args=("--auto", "--squash"), excluded=EXCLUDED, lgtm_merge=True,
                     precondition='test -z "$FACTORY_LGTM"')
        self.assertEqual(verdict("gh pr merge --auto --squash 412", gate=plain),
                         ("allow", "auto-merge gate passed for PR #412"))

    def test_an_lgtm_never_merges_a_pr_without_the_factory_label(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --squash 412", migration(labels=()), [(AFTER, "LGTM")])[0],
                         "deny")

    def test_a_stacked_base_merges_with_a_merge_commit_on_lgtm(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --merge 412", migration(stacked=(13,)), [(AFTER, "LGTM")]),
                         ("allow", "merging PR #412 on the developer's LGTM"))

    def test_a_merge_commit_without_a_stack_is_refused(self):
        self.assertEqual(lgtm_verdict("gh pr merge --auto --merge 412", migration(), [(AFTER, "LGTM")])[0], "deny")

    def test_a_merge_commit_is_refused_without_the_profile_switch(self):
        gate = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED)
        self.assertEqual(lgtm_verdict("gh pr merge --auto --merge 412", migration(stacked=(13,)),
                                      [(AFTER, "LGTM")], gate)[0], "deny")


class DeveloperMessages(unittest.TestCase):
    """Only what the developer typed: not the dispatcher's start prompt, not peers or notices."""

    def transcript(self, entries):
        f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        f.write("\n".join(json.dumps(e) for e in entries))
        f.close()
        return Path(f.name)

    def test_the_start_prompt_peers_and_meta_messages_are_skipped(self):
        def user(text, kind=None, **kw):
            return {"type": "user", "timestamp": AFTER, "message": {"content": text},
                    **({"origin": {"kind": kind}} if kind else {}), **kw}
        path = self.transcript([
            user("You are factory-a-s1 ... LGTM ...", "human"),
            user("Factory event: merged PR #412", "peer", isMeta=True),
            user("<task-notification>LGTM</task-notification>", "task-notification"),
            user("summary: LGTM", None, isCompactSummary=True),
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "LGTM"}]}},
            user([{"type": "text", "text": "#412 LGTM"}], "human"),
        ])
        self.assertEqual(developer_messages(path), [(AFTER, "#412 LGTM")])


class ForcePush(unittest.TestCase):
    """A worker force-pushes only its own factory branch, only with a lease."""

    def push(self, command, on="feature/factory-a-s1"):
        return judge(command, None, GATE, current_branch=lambda: on)

    def test_with_lease_to_its_own_branch_is_allowed(self):
        for command in ("git push --force-with-lease", "git push --force-with-lease origin feature/factory-a-s1"):
            with self.subTest(command=command):
                self.assertEqual(self.push(command)[0], "allow")

    def test_plain_force_is_refused(self):
        self.assertEqual(self.push("git push --force origin feature/factory-a-s1"),
                         ("deny", "the only force-push is `git push --force-with-lease [origin <branch>]`"))

    def test_a_plus_refspec_is_refused(self):
        self.assertEqual(self.push("git push origin +feature/factory-a-s1")[0], "deny")

    def test_someone_elses_branch_is_refused(self):
        self.assertEqual(self.push("git push --force-with-lease", on="feat/performance-overview-orders"),
                         ("deny", "`feat/performance-overview-orders` is not a factory branch — merge `origin/main` "
                                  "into it instead of rebasing"))

    def test_main_is_refused(self):
        self.assertEqual(self.push("git push --force-with-lease origin main"),
                         ("deny", "factory workers never push to main"))

    def test_a_plain_push_is_no_concern_of_the_gate(self):
        self.assertIsNone(self.push("git push origin feature/factory-a-s1"))


class TypedByDeveloper(unittest.TestCase):
    def test_what_the_developer_types_counts(self):
        self.assertTrue(typed_by_developer("why does this skip archived leads?"))

    def test_start_prompts_peers_and_notices_do_not(self):
        for prompt in ("You are **factory-a-s1**, the factory worker for step 1",
                       "**You replace a factory worker that died.**",
                       "Another Claude session sent a message: <cross-session-message>Factory event: merged",
                       "<task-notification><task-id>x</task-id></task-notification>", "  "):
            with self.subTest(prompt=prompt[:30]):
                self.assertFalse(typed_by_developer(prompt))


class CiState(unittest.TestCase):
    """The shapes `gh pr view --json statusCheckRollup` really returns. Measured on the host
    project's PR #408: Cloud Build posts a `CheckRun`, so `conclusion` carries the verdict and
    `status` says whether it is over. A GitHub App or an external service posts a `StatusContext`
    instead, which has neither — only `state`."""

    def test_a_finished_check_run(self):
        self.assertEqual(ci_state([{"__typename": "CheckRun", "name": "uspex-billing-ci (archive-dwh)",
                                    "status": "COMPLETED", "conclusion": "SUCCESS"}]),
                         (False, False))

    def test_a_check_run_still_building(self):
        self.assertEqual(ci_state([{"__typename": "CheckRun", "status": "IN_PROGRESS", "conclusion": ""}]),
                         (False, True))

    def test_a_check_run_queued_right_after_the_pr_opened(self):
        self.assertEqual(ci_state([{"__typename": "CheckRun", "status": "QUEUED", "conclusion": None}]),
                         (False, True))

    def test_a_failed_check_run(self):
        self.assertEqual(ci_state([{"__typename": "CheckRun", "status": "COMPLETED", "conclusion": "FAILURE"}]),
                         (True, False))

    def test_a_pending_commit_status_has_no_status_field(self):
        self.assertEqual(ci_state([{"__typename": "StatusContext", "context": "ci/external", "state": "PENDING"}]),
                         (False, True))

    def test_a_failed_commit_status(self):
        self.assertEqual(ci_state([{"__typename": "StatusContext", "context": "ci/external", "state": "FAILURE"}]),
                         (True, False))

    def test_no_checks_at_all_is_neither(self):
        """A repository without CI still merges on an LGTM; whether a check *should* have reported
        is the project's `Precondition` to judge — only it knows which checks it expects."""
        self.assertEqual(ci_state([]), (False, False))

    def test_one_green_and_one_running(self):
        self.assertEqual(ci_state([{"status": "COMPLETED", "conclusion": "SUCCESS"},
                                   {"status": "IN_PROGRESS"}]),
                         (False, True))


if __name__ == "__main__":
    unittest.main()
