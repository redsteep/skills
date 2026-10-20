"""Eval adapter for step 4's test-strategy reviewer (`test-coverage-reviewer.md`).

Run by `tools/reviewer-eval/run.py`. The reviewer gets the whole branch as step 0 builds it: the
changed source files, and the changed test files plus the existing ones naming a unit the branch
adds or changes. `inputs:` in the project's eval.yaml carries the profile's Layout:
`source_prefixes` and `test_dirs`.

A case adds `base` (the diff is `base..before`) and `feature` (FEATURE_DESCRIPTION).
"""

import re
import subprocess
from pathlib import Path

TEMPLATE = "skills/pre-pr-review/test-coverage-reviewer.md"
TOOLS: list[str] = []
CONTRACT: list[str] = []

# A public def/class (Python) or export (TypeScript) on a line the branch adds: the units it changes.
_UNIT = re.compile(
    r"^\+\s*(?:async def|def|class|export (?:default )?(?:async )?(?:function|const|class|interface|type))\s+([A-Za-z]\w*)"
)


def _git(worktree: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=worktree, check=True, capture_output=True, text=True).stdout


def _is_test(path: str, config: dict) -> bool:
    return any(f"/{d}/" in f"/{path}" for d in config["test_dirs"])


def _changed_units(case: dict, source: str, worktree: Path) -> set[str]:
    diff = _git(worktree, "diff", "-U0", f"{case['base']}..HEAD", "--", source)
    names = {m.group(1) for line in diff.splitlines() if (m := _UNIT.match(line))}
    # Single lowercase words (`handle`, `of`, `build`, `upgrade`) name a method on every class of
    # their kind, not this unit: grepping for them would list half the test tree.
    return {n for n in names if "_" in n or not n.islower()}


def _branch_files(case: dict, worktree: Path, config: dict) -> tuple[list[str], list[str]]:
    changed = _git(worktree, "diff", "--name-only", f"{case['base']}..HEAD").splitlines()
    tests = [f for f in changed if _is_test(f, config)]
    sources = [f for f in changed if f.startswith(tuple(config["source_prefixes"])) and not _is_test(f, config)]
    units = set().union(*(_changed_units(case, s, worktree) for s in sources))
    covering = set()
    if units:
        covering.update(subprocess.run(
            ["git", "grep", "-lw", *[a for u in sorted(units) for a in ("-e", u)], "--",
             *[p for d in config["test_dirs"] for p in (f"{d}/*", f"*/{d}/*")]],
            cwd=worktree, capture_output=True, text=True,
        ).stdout.splitlines())
    return sources, tests + sorted(covering - set(tests))


def inputs(case: dict, worktree: Path, config: dict) -> dict[str, str]:
    sources, tests = _branch_files(case, worktree, config)
    return {
        "FEATURE_DESCRIPTION": case["feature"],
        "SOURCE_FILES": "\n".join(sources),
        "TEST_FILES": "\n".join(tests),
        "WORKTREE": str(worktree),
        "PROFILE": str(worktree / ".claude/pre-pr-review.md"),
    }


def plain_prompt(case: dict, worktree: Path, inputs: dict[str, str]) -> str:
    return (
        f"Review the tests of this feature branch in {worktree}.\n\n**Feature:** {inputs['FEATURE_DESCRIPTION']}\n\n"
        f"**Source files:**\n{inputs['SOURCE_FILES']}\n\n**Test files:**\n{inputs['TEST_FILES']}"
        "\n\nList every issue you find in these tests, each with file:line, what is wrong and the fix. "
        "Your final message IS the report."
    )
