"""The auto-merge gate: one case just inside and one just outside each rule, and every other
merge route denied however small the PR."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_merge_gate import Diff, Gate, failed_rule, judge  # noqa: E402

EXCLUDED = ("db/migrations/", "*.lock", "src/generated/api.ts")
GATE = Gate(required_args=("--auto", "--squash"), precondition="", excluded=EXCLUDED)
TRIAGE = "Summary\n\nTriage: copy change in one template, nothing open from review."


def diff(additions=10, deletions=0, files=("docs/a.md",), labels=("factory",), body=TRIAGE, stacked=()):
    return Diff(additions, deletions, tuple(files), tuple(labels), body, tuple(stacked))


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
