"""Eval adapter for the design reviewer (`design-reviewer.md`).

Run by `tools/reviewer-eval/run.py`. The reviewer gets what step 2 of the skill fills in: the spec,
the repo, the profile and the mode. A case adds `spec` and `mode` (`proposal` | `drift`). The
project's eval.yaml copies its frozen profile in as `.claude/design-review.md`.
"""

from pathlib import Path

TEMPLATE = "skills/design-review/design-reviewer.md"
# The profile's Containment command: `CONTAINMENT_SOURCES=… python3 …/containment.py`.
TOOLS = ["Bash(python3:*)", "Bash(CONTAINMENT_SOURCES=*)"]
# The skill's own scope (README "Seven tests" and design-reviewer.md "Outside the tests"), quoted
# rather than paraphrased: a narrower wording made the judge reject the contradictions and
# figures that won't compute which the skill asks for.
CONTRACT = [
    "Every finding is either a placement finding — one of the seven tests: value object / entity, "
    "aggregate boundary, ubiquitous language, anti-corruption layer, translation between stages, OCP, "
    "LSP — or an 'Outside the tests' item: something the reading surfaced that no test covers, such as "
    "a figure that will not compute, a condition that matches nothing, or a contradiction within the "
    "spec or between the spec and the code. Broken only by a finding about what the skill deliberately "
    "leaves out: whether the feature is worth doing, completeness of declarations, tests, style or "
    "wording, file size, or anything a tool already enforces.",
]


def inputs(case: dict, worktree: Path, config: dict) -> dict[str, str]:
    return {
        "SPEC_PATH": case["spec"],
        "MODE": case["mode"],
        "REPO": str(worktree),
        "PROFILE": str(worktree / ".claude/design-review.md"),
    }


def plain_prompt(case: dict, worktree: Path, inputs: dict[str, str]) -> str:
    when = "before it is implemented" if case["mode"] == "proposal" else "against the branch that implements it"
    return (
        f"Review the design in {inputs['SPEC_PATH']} (repo: {worktree}) {when}. List every issue you "
        "find, each with the evidence (file:line in the code or the spec), what is wrong and what it "
        "should be. Your final message IS the report."
    )
