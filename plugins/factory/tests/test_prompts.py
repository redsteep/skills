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

    def test_a_gate_refusal_about_ci_is_a_wait_not_a_review(self):
        """Measured on #401: the worker tried the merge 25 seconds after opening the PR, was
        refused with `CI queued`, read that as "needs a developer", and slept — while `ci-passed`
        arrived three minutes later and went unused. A six-minute merge took eight hours and left
        a review request standing that nobody needed."""
        triage = section(self.step, "Triage")
        self.assertIn("CI queued", triage)
        self.assertIn("ci-passed", triage)
        self.assertIn("--done", triage)
        events = section(self.step, "Events")
        self.assertIn("go back to *Triage*", events)

    def test_an_lgtm_outlives_the_wait_for_ci(self):
        """Measured on #336: the developer's LGTM landed while CI was still running — on the very
        push that had applied their queued changes, which is the normal order. The merge was
        refused, the worker read the refusal as a failure and said LGTM had not worked, and the PR
        sat waiting for a word already given. The wait does not spend their approval; only a later
        push does."""
        triage = section(self.step, "Triage")
        self.assertIn("standing intent", triage)
        self.assertIn("CI has not finished", triage)
        self.assertIn("spent their word", triage)
        self.assertIn("still their word", section(self.step, "Events"))

    def test_no_prompt_hardcodes_a_merge_command(self):
        for path in PROMPTS.glob("*.md"):
            with self.subTest(prompt=path.name):
                self.assertNotRegex(path.read_text(), r"gh pr merge\s+--")


class CardAnalysis(unittest.TestCase):
    """Measured on card 1tJsfZ93 (2026-10-30): the split wrote "the given name found in the
    email's local part" into step 1, the spec worker handed its subagent that reading as "what I
    already know — verify in code", and the spec measured only the source the card named. The
    developer spent two hours of questions recovering what an analysis of the card finds from
    the card alone: the symptom in four times as many contacts, prior art in two scripts, the
    rendered emails that a contact fix never reaches."""

    def setUp(self):
        self.split = (PROMPTS / "split.md").read_text()
        self.analysis = (PROMPTS / "analysis.md").read_text()

    def test_the_card_is_analysed_before_it_is_split(self):
        self.assertLess(self.split.index("## Analysis"), self.split.index("## Split"))
        self.assertIn("{analysis}", section(self.split, "Analysis"))

    def test_the_split_waits_for_the_approved_brief(self):
        analysis = section(self.split, "Analysis")
        self.assertIn("Cut nothing until the developer approves", analysis)
        self.assertIn("Approved-by:", analysis)
        self.assertIn("card brief ready", analysis)

    def test_the_analyst_gets_the_card_not_a_guess(self):
        self.assertIn("nothing of your own", section(self.split, "Analysis"))

    def test_the_analyst_measures_the_symptom_beyond_the_named_source(self):
        self.assertIn("across *every* source", self.analysis)
        self.assertIn("Prior art", self.analysis)
        self.assertIn("Readers and writers", self.analysis)

    def test_the_spec_reads_the_brief_and_gets_no_conclusion(self):
        spec = section((PROMPTS / "step.md").read_text(), "Spec")
        self.assertIn("{brief}", spec)
        self.assertIn("not your\n   own reading of them", spec)


class Rendering(unittest.TestCase):
    """Every placeholder a template uses is filled: an unfilled one reaches the worker as literal
    text (`--label {label}` did, from the start until 0.13.0)."""

    def test_no_placeholder_is_left_unfilled(self):
        import sys
        sys.path.insert(0, str(PROMPTS.parent / "scripts"))
        from factory_common import Profile
        from factory_dispatch import Item, Step, issue_card, render_prompt
        card = issue_card(7, "Issue 7", "https://github.com/o/r/issues/7", True)
        step = Step(card, 1, Item("fix it", False), "in-progress")
        for template in ("step.md", "recovery.md", "split.md", "resumed.md"):
            with self.subTest(template=template):
                text = render_prompt(template, Path("/repo"), Profile(""), "factory-i7-s1", card=card, step=step,
                                     total=1, recovered="in-progress")
                self.assertEqual(re.findall(r"\{[a-z_]+\}", text), [])
                if template not in ("split.md", "resumed.md"):
                    # `resumed.md` carries no commands: the session it wakes already has them.
                    self.assertIn("factory-ping --worker factory-i7-s1", text)


    def test_the_split_carries_the_analysis_with_the_profile_sources(self):
        import sys
        sys.path.insert(0, str(PROMPTS.parent / "scripts"))
        from factory_common import Profile
        from factory_dispatch import BRIEFS_DIR, Card, render_prompt
        card = Card("c1", "abc123", "A card", "https://trello.com/c/abc123", True, None)
        profile = Profile("## Analysis\n\n- **Sources:** the prod DB through `q.sh`\n")
        text = render_prompt("split.md", Path("/repo"), profile, "factory-abc123-split", card=card)
        self.assertIn("across *every* source", text)
        self.assertIn("the prod DB through `q.sh`", text)
        self.assertIn(str(BRIEFS_DIR / "abc123.md"), text)


if __name__ == "__main__":
    unittest.main()
