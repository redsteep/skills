"""The auto-merge gate: one case just inside and one just outside each rule, and every other
merge route denied however small the PR."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from auto_merge_gate import Diff, Gate, failed_rule, judge  # noqa: E402

GATE = Gate(max_lines=30, max_files=3, excluded=("backend/migrations/", "*.lock", "frontend/src/types/api-generated.ts"))
TRIAGE = "Summary\n\nTriage: copy change in one template, nothing open from review."


def diff(additions=10, deletions=0, files=("docs/a.md",), labels=("factory",), body=TRIAGE):
    return Diff(additions, deletions, tuple(files), tuple(labels), body)


def verdict(command, d=None):
    return judge(command, lambda _number: d or diff(), GATE)


class GateRules(unittest.TestCase):
    def test_tiny_factory_pr_passes(self):
        self.assertIsNone(failed_rule(diff(), GATE))

    def test_lines_boundary(self):
        self.assertIsNone(failed_rule(diff(additions=20, deletions=10), GATE))
        self.assertEqual(failed_rule(diff(additions=21, deletions=10), GATE), "31 changed lines > 30")

    def test_files_boundary(self):
        self.assertIsNone(failed_rule(diff(files=("a", "b", "c")), GATE))
        self.assertEqual(failed_rule(diff(files=("a", "b", "c", "d")), GATE), "4 files > 3")

    def test_each_excluded_path_is_refused(self):
        for path, pattern in [("backend/migrations/versions/x.py", "backend/migrations/"),
                              ("backend/poetry.lock", "*.lock"),
                              ("frontend/src/types/api-generated.ts", "frontend/src/types/api-generated.ts")]:
            with self.subTest(path=path):
                self.assertEqual(failed_rule(diff(files=(path,)), GATE),
                                 f"`{path}` matches excluded `{pattern}`")

    def test_directory_pattern_does_not_match_a_sibling_name(self):
        self.assertIsNone(failed_rule(diff(files=("backend/migrations_notes.md",)), GATE))

    def test_pr_without_factory_label_is_refused_however_small(self):
        self.assertEqual(failed_rule(diff(labels=()), GATE), "not a factory PR (no `factory` label)")

    def test_pr_without_triage_reason_is_refused(self):
        self.assertEqual(failed_rule(diff(body="Summary only"), GATE),
                         "no `Triage:` paragraph in the PR description")


class MergeRoutes(unittest.TestCase):
    def test_gated_auto_squash_merge_is_allowed(self):
        self.assertEqual(verdict("gh pr merge --auto --squash 412"),
                         ("allow", "auto-merge gate passed for PR #412"))

    def test_failing_gate_is_denied_with_the_rule(self):
        decision, reason = verdict("gh pr merge --auto --squash 412", diff(additions=31))
        self.assertEqual(decision, "deny")
        self.assertIn("31 changed lines > 30", reason)

    def test_other_merge_forms_are_denied_even_for_a_tiny_pr(self):
        for command in ["gh pr merge 412", "gh pr merge --squash 412", "gh pr merge --auto --merge 412",
                        "gh pr merge --auto --squash --admin 412", "gh pr merge --auto --squash",
                        "gh pr merge --auto --squash 412 && echo ok",
                        "gh api -X PUT repos/o/r/pulls/412/merge",
                        "gh api graphql -f query='mutation { enablePullRequestAutoMerge(input: {}) { clientMutationId } }'",
                        "git push origin HEAD:main"]:
            with self.subTest(command=command):
                self.assertEqual(verdict(command)[0], "deny")

    def test_unrelated_commands_get_no_opinion(self):
        for command in ["gh pr view 412", "gh api repos/o/r/pulls/412/comments", "git push origin feature/factory-a-s1"]:
            with self.subTest(command=command):
                self.assertIsNone(verdict(command))


if __name__ == "__main__":
    unittest.main()
