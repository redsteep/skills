"""Eval adapter for the design reviewer (`design-reviewer.md`).

Run by `tools/reviewer-eval/run.py`. The reviewer gets what step 2 of the skill fills in: the spec,
the repo, the profile and the mode. A case adds `spec` and `mode` (`proposal` | `drift`). The
project's eval.yaml copies its frozen profile in as `.claude/design-review.md`.
"""

from pathlib import Path

TEMPLATE = "skills/design-review/design-reviewer.md"
# The profile's Containment command: `CONTAINMENT_SOURCES=… python3 …/containment.py`.
TOOLS = ["Bash(python3:*)", "Bash(CONTAINMENT_SOURCES=*)"]
CONTRACT = [
    "Every finding is a placement finding — one of the seven tests (value object / entity, aggregate "
    "boundary, ubiquitous language, anti-corruption layer, translation between stages, OCP, LSP), or "
    "listed under 'Outside the tests' as a correctness error. No findings about tests, typed ids, "
    "wording or prose, counts, undeclared surface, or whether the feature is worth doing.",
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
