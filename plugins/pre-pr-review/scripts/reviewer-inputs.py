#!/usr/bin/env python3
"""The task message every pre-pr-review agent receives — generated, never written by hand.

    reviewer-inputs.py --worktree <path> [--base <sha>] [--spec <path>] [--test-command <cmd>]

Prints one block of labelled fields: Feature, Worktree, Profile, Base, Head, Source files, Test
files and, when given, Targeted test command. The `PreToolUse` hook on `Agent` runs it for every
dispatch of this plugin's agents and puts its output in place of whatever prompt the dispatch
carried, so a reviewer never sees a summary, a framing or a paraphrase from the main agent. The
eval runner calls it too, so an eval measures what a review sends.

- Base: `--base` (a re-review round's `Reviewed at` sha), else the merge-base with the profile's
  base branch, else with the remote's default branch.
- Feature: the spec's first heading and its path, else the branch name. Nothing else: the
  reviewer reads the diff and the spec itself.
- Source / test files: the changed files, split by the profile's layout block; test files also
  list the existing tests that name a unit the branch adds or changes (a public def/class or
  export on an added line), as step 0 describes.

Exit 1 with a message on stderr when an input is unusable; the hook turns that into a denial.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

PROFILE = ".claude/pre-pr-review.md"
# The profile's machine-readable layout: a fenced block opened with ```yaml pre-pr-review-layout
_LAYOUT_BLOCK = re.compile(r"```ya?ml pre-pr-review-layout\n(.*?)```", re.S)
_BASE_BRANCH = re.compile(r"\*\*Base branch:\*\*\s*`([^`]+)`")
# A public def/class (Python) or export (TypeScript) on a line the branch adds: the units it changes.
_UNIT = re.compile(
    r"^\+\s*(?:async def|def|class|export (?:default )?(?:async )?(?:function|const|class|interface|type))\s+([A-Za-z]\w*)"
)


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def git(worktree: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True)
    if check and out.returncode != 0:
        fail(f"git {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def layout(profile_text: str) -> dict[str, list[str]]:
    """`source_prefixes:` and `test_dirs:` lists from the profile's layout block (a flat YAML
    subset, parsed here so the hook needs no third-party package)."""
    match = _LAYOUT_BLOCK.search(profile_text)
    keys: dict[str, list[str]] = {"source_prefixes": [], "test_dirs": ["tests", "__tests__"]}
    if not match:
        return keys
    current = None
    for raw in match.group(1).splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if m := re.match(r"^(\w+):\s*(.*)$", line):
            current, value = m.group(1), m.group(2).strip()
            if value.startswith("["):
                keys[current] = [v.strip().strip("'\"") for v in value.strip("[]").split(",") if v.strip()]
            elif not value:
                keys[current] = []
        elif current and (m := re.match(r"^\s*-\s*(.+)$", line)):
            keys[current].append(m.group(1).strip().strip("'\""))
    return keys


def is_test(path: str, test_dirs: list[str]) -> bool:
    return any(f"/{d}/" in f"/{path}" for d in test_dirs)


def is_source(path: str, prefixes: list[str], test_dirs: list[str]) -> bool:
    if is_test(path, test_dirs):
        return False
    if prefixes:
        return path.startswith(tuple(prefixes))
    # No layout block: everything that is not a test, a doc or config.
    return not path.endswith((".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".lock"))


def changed_units(worktree: Path, base: str, source: str) -> set[str]:
    diff = git(worktree, "diff", "-U0", f"{base}..HEAD", "--", source)
    names = {m.group(1) for line in diff.splitlines() if (m := _UNIT.match(line))}
    # Single lowercase words (`handle`, `of`, `build`) name a method on every class of their
    # kind, not this unit: grepping for them would list half the test tree.
    return {n for n in names if "_" in n or not n.islower()}


def feature(worktree: Path, spec: str | None) -> str:
    if spec:
        path = worktree / spec
        if not path.is_file():
            fail(f"spec: {spec} is not a file in {worktree}")
        heading = next((l.lstrip("# ").strip() for l in path.read_text().splitlines() if l.startswith("# ")), "")
        return f"{heading} — spec: {spec}" if heading else f"spec: {spec}"
    return f"branch {git(worktree, 'rev-parse', '--abbrev-ref', 'HEAD')} (no spec)"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--base")
    parser.add_argument("--spec")
    parser.add_argument("--test-command")
    args = parser.parse_args()

    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir() or git(worktree, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        fail(f"worktree: {args.worktree} is not a git worktree")
    profile = worktree / PROFILE
    profile_text = profile.read_text() if profile.is_file() else ""
    keys = layout(profile_text)

    if args.base:
        base = git(worktree, "rev-parse", "--verify", f"{args.base}^{{commit}}")
    else:
        m = _BASE_BRANCH.search(profile_text)
        branch = m.group(1) if m else git(worktree, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
        base = git(worktree, "merge-base", "HEAD", branch or "origin/main")
    head = git(worktree, "rev-parse", "HEAD")

    changed = git(worktree, "diff", "--name-only", f"{base}..HEAD").splitlines()
    sources = [f for f in changed if is_source(f, keys["source_prefixes"], keys["test_dirs"])]
    tests = [f for f in changed if is_test(f, keys["test_dirs"])]
    units = set().union(*(changed_units(worktree, base, s) for s in sources))
    covering: set[str] = set()
    if units:
        paths = [p for d in keys["test_dirs"] for p in (f"{d}/*", f"*/{d}/*")]
        found = git(worktree, "grep", "-lw", *[a for u in sorted(units) for a in ("-e", u)], "--", *paths, check=False)
        covering = set(found.splitlines())

    lines = [
        f"**Feature:** {feature(worktree, args.spec)}",
        f"**Worktree:** {worktree}",
        f"**Profile:** {profile if profile.is_file() else '(none — use the generic behaviour)'}",
        f"**Base:** {base}",
        f"**Head:** {head}",
        "",
        "**Source files:**",
        *(sources or ["(none)"]),
        "",
        "**Test files:**",
        *(tests + sorted(covering - set(tests)) or ["(none)"]),
    ]
    if args.test_command:
        lines += ["", "**Targeted test command:**", args.test_command]
    print("\n".join(lines))


if __name__ == "__main__":
    main()
