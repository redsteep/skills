"""The auto-merge gate: one case just inside and one just outside each rule, and every other
merge route denied however small the PR."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import json
import tempfile

from auto_merge_gate import Diff, Gate, approval_failed, developer_messages, failed_rule, judge  # noqa: E402

EXCLUDED = ("db/migrations/", "*.lock", "src/generated/api.ts")
GATE = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED)
TRIAGE = "Summary\n\nTriage: copy change in one template, nothing open from review."


def diff(additions=10, deletions=0, files=("docs/a.md",), labels=("factory",), body=TRIAGE, stacked=(),
         head_committed="", ci_failed=False):
    return Diff(additions, deletions, tuple(files), tuple(labels), body, tuple(stacked), head_committed, ci_failed)


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


if __name__ == "__main__":
    unittest.main()


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
