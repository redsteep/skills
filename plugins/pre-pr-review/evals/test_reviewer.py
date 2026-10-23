"""Eval adapter for step 3's test reviewer (the `pre-pr-review:test-reviewer` agent).

Run by `tools/agent-eval/run.py`. The reviewer arms run the plugin's agent itself, from this
checkout, with the message `scripts/reviewer-inputs.py` generates — the same message the plugin's
hook puts in place of a real dispatch's prompt — so the eval measures what a review sends. The
input generator reads the source/test layout from the profile's `pre-pr-review-layout` block,
which `copy_in` brings into the worktree.

A case gives `base` (the diff is `base..before`) and the spec, as `spec:` or as the
`Spec: <path>` in its `feature` line.
"""

import re
import subprocess
import sys
from pathlib import Path

AGENT = "pre-pr-review:test-reviewer"
TOOLS: list[str] = []
CONTRACT: list[str] = []

INPUTS = Path(__file__).resolve().parents[1] / "scripts/reviewer-inputs.py"


def _spec(case: dict) -> str | None:
    if case.get("spec"):
        return case["spec"]
    m = re.search(r"Spec:\s*(\S+)", case.get("feature", ""))
    return m.group(1) if m else None


def inputs(case: dict, worktree: Path, config: dict) -> dict[str, str]:
    cmd = [sys.executable, str(INPUTS), "--worktree", str(worktree), "--base", case["base"]]
    if spec := _spec(case):
        cmd += ["--spec", spec]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"reviewer-inputs.py: {out.stderr.strip()}")
    return {"MESSAGE": out.stdout}


def plain_prompt(case: dict, worktree: Path, inputs: dict[str, str]) -> str:
    return (
        f"Review the tests of this feature branch in {worktree}.\n\n{inputs['MESSAGE']}\n\n"
        "List every issue you find in these tests, each with file:line, what is wrong and the fix. "
        "Your final message IS the report."
    )
