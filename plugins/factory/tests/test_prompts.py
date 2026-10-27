"""The prompts are the worker's procedure, so three of their promises are contracts, not prose:
a spec opens no PR, the approval is recorded on the branch, and the merge command comes from the
profile. Each of the three was a bug once — a PR per spec, a replacement worker redoing an
approved spec, and a hardcoded `--auto` on a repo where auto-merge is off."""

import re
import unittest
from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[1] / "prompts"


def section(text: str, name: str) -> str:
    m = re.search(rf"^## {name}$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no § {name}"
    return m[1]


class Prompts(unittest.TestCase):
    def setUp(self):
        self.step = (PROMPTS / "step.md").read_text()
        self.recovery = (PROMPTS / "recovery.md").read_text()

    def test_spec_phase_opens_no_pr(self):
        self.assertNotIn("gh pr create", section(self.step, "Spec"))

    def test_build_opens_the_pr_with_the_factory_label(self):
        self.assertIn("--label {label}", section(self.step, "Build"))

    def test_approval_is_recorded_on_the_branch_and_never_amended(self):
        spec = section(self.step, "Spec")
        self.assertIn("Approved-by:", spec)
        self.assertIn("--allow-empty", spec)
        self.assertIn("Never `--amend`", spec)

    def test_recovery_reads_the_trailer_not_a_label(self):
        self.assertIn("Approved-by:", self.recovery)
        self.assertNotIn("spec-approved", self.recovery)

    def test_no_prompt_hardcodes_a_merge_command(self):
        for path in PROMPTS.glob("*.md"):
            with self.subTest(prompt=path.name):
                self.assertNotRegex(path.read_text(), r"gh pr merge\s+--")


if __name__ == "__main__":
    unittest.main()
