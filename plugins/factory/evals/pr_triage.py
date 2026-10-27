"""Eval adapter for the factory's PR triage (`prompts/triage.md`): auto-merge or review.

Run by `tools/agent-eval/run.py`. A case is a merged PR replayed as it was when it was opened: the
worktree at its first pushed head (`before`), `base` the commit it forked from, `description` its
body as first written (title as its heading), `expected` what the triage should have said —
`auto-merge` when it merged without fixes, `review` when the code changed after it opened, or when
a wrong merge would cost too much to risk. The verdict is a line, so the adapter grades it itself; no judge.

The two errors are not alike: a false auto-merge ships what review would have changed, a needless
review costs the developer a read. The results line keeps them apart.
"""

import re
from pathlib import Path

TEMPLATE = "prompts/triage.md"
TOOLS: list[str] = []
CONTRACT: list[str] = []

_VERDICT = re.compile(r"^\s*\**Verdict:\**\s*\**(auto-merge|review)\**\s*$", re.I | re.M)


def inputs(case: dict, worktree: Path, config: dict) -> dict[str, str]:
    return {
        "DIFF": f"git diff {case['base']}...HEAD",
        "DESCRIPTION": f"\n\n<description>\n{case['description'].strip()}\n</description>\n",
        "SPEC": case.get("spec") or "none",
    }


def plain_prompt(case: dict, worktree: Path, inputs: dict[str, str]) -> str:
    return (
        f"A pull request changes this repo; `{inputs['DIFF']}` shows it. Its description: "
        f"{inputs['DESCRIPTION']}\nShould it merge without the developer reading the code? Say why in "
        "a sentence or two, then end with a last line that is exactly `Verdict: auto-merge` or "
        "`Verdict: review`."
    )


def verdict_of(text: str) -> str | None:
    """The last `Verdict:` line wins — a triage that reconsiders ends on its final answer."""
    found = _VERDICT.findall(text)
    return found[-1].lower() if found else None


def grade(case: dict, artifacts: dict) -> list[dict]:
    said = verdict_of(artifacts["final_text"])
    if said is None:
        return [{"verdict": "NEITHER", "said": None, "expected": case["expected"]}]
    return [{"verdict": "RIGHT" if said == case["expected"] else "WRONG", "said": said,
             "expected": case["expected"]}]


def summarise(case: dict, results: list[dict]) -> str:
    """`pr366 ✓✗!` per case: ✓ right, ✗! a false auto-merge, ✗ a needless review, ? no verdict."""
    marks = []
    for r in results:
        v = (r["verdicts"] or [{}])[0]
        if v.get("verdict") == "RIGHT":
            marks.append("✓")
        elif v.get("verdict") == "WRONG":
            marks.append("✗!" if v["said"] == "auto-merge" else "✗")
        else:
            marks.append("?")
    return f"{case['id'].split('-')[0]} {''.join(marks)}"
