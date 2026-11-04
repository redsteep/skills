#!/usr/bin/env python3
"""What this branch changed and no test ran — the lines, not a percentage.

A coverage percentage over a whole project says nothing a reviewer can act on: it moves by tenths
and is dominated by code nobody touched. What a reviewer wants before opening a diff is the other
question — *of the lines this branch added, which ones did no test execute?* That list is short,
it is specific, and every entry is either a gap worth filling or a decision worth writing down.

The project declares how its coverage is produced (profile → `## Coverage`); this reads what the
run wrote and crosses it with the diff:

    <the project's coverage command, writing a JSON report>
    python3 scripts/diff_coverage.py --coverage <report> --base origin/main \\
        --root <dir the run started in> --suite "what produced it, in words"

Two report shapes are read, which covers most of what projects already have:

- **coverage.py** (`--cov-report=json`): `{"files": {path: {"missing_lines": [...]}}}`
- **istanbul / nyc / vitest v8** (`coverage-final.json`): `{path: {"statementMap": …, "s": …}}`,
  where a statement with zero hits marks the lines it spans

`--suite` is required on purpose. Coverage read from a **targeted** run under-reports: a changed
line exercised by a test file outside the run reads as uncovered, and a report that does not say
which run produced it is a report a reader cannot weigh. The text goes into the header, so the
claim always carries its own provenance.

Nothing here is a gate. The output is the section step 7 puts in the PR body, and the same rows
become check-run annotations where a project has an App that may post them — the mapping is file
plus line range, which is what this prints.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
NEW_FILE = re.compile(r"^\+\+\+ b/(.+)$")
MEASURED_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue", ".svelte")


def changed_lines(diff: str) -> dict[str, set[int]]:
    """`path → the line numbers this diff adds or rewrites`, on the new side.

    Deletions carry no line to cover, and a file the diff only removes never appears.
    """
    out: dict[str, set[int]] = {}
    path, line = "", 0
    for raw in diff.splitlines():
        if (m := NEW_FILE.match(raw)) is not None:
            path = m[1]
            out.setdefault(path, set())
            continue
        if (m := HUNK.match(raw)) is not None:
            line = int(m[1])
            continue
        if not path or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            out[path].add(line)
            line += 1
        elif raw.startswith(" "):
            line += 1
    return {p: lines for p, lines in out.items() if lines}


def _istanbul_missing(report: dict, repo: Path | None = None) -> dict[str, set[int]]:
    """Istanbul's shape: every statement with zero hits marks the lines it spans.

    Its paths are absolute, so they are brought back to repository-relative ones — a diff has no
    idea where the machine that ran the tests kept the checkout.
    """
    out: dict[str, set[int]] = {}
    for path, data in report.items():
        statements = data.get("statementMap") or {}
        hits = data.get("s") or {}
        lines: set[int] = set()
        for sid, span in statements.items():
            if hits.get(sid):
                continue
            start = (span.get("start") or {}).get("line")
            end = (span.get("end") or {}).get("line") or start
            if start:
                lines.update(range(start, end + 1))
        name = data.get("path") or path
        if repo is not None:
            try:
                name = str(Path(name).resolve().relative_to(repo.resolve()))
            except ValueError:
                pass
        out[name] = lines
    return out


def missing_lines(report: dict, repo: Path | None = None) -> dict[str, set[int]]:
    """`path → the lines the run recorded as never executed`, paths as the run named them.

    The shape is detected, not configured: a project should not have to tell a tool what its own
    coverage file obviously is, and getting that setting wrong would silently report zero gaps.
    """
    if isinstance(report.get("files"), dict):
        return {path: set(data.get("missing_lines") or ())
                for path, data in report["files"].items()}
    if report and all(isinstance(v, dict) and "statementMap" in v for v in report.values()):
        return _istanbul_missing(report, repo)
    return {}


def as_ranges(lines: set[int]) -> list[tuple[int, int]]:
    """Consecutive line numbers collapse into one range: `343-347` reads, a column of numbers does
    not."""
    ranges: list[tuple[int, int]] = []
    for line in sorted(lines):
        if ranges and line == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], line)
        else:
            ranges.append((line, line))
    return ranges


def measured_roots(missing: dict[str, set[int]]) -> set[str]:
    """The top-level directories the run actually looked at (`app`, `src`, `scripts`, …).

    Read from the report rather than configured, because the report is the only place that knows
    what the run was pointed at. It is what tells "inside the scope and never imported" (a real
    gap) apart from "outside the scope entirely" (not measured at all) — two answers that look
    identical in a report that only lists what it saw.
    """
    return {path.split("/", 1)[0] for path in missing}


def _relative(path: str, root: str) -> str:
    prefix = f"{root.rstrip('/')}/" if root else ""
    return path[len(prefix):] if prefix and path.startswith(prefix) else path


def uncovered(changed: dict[str, set[int]], missing: dict[str, set[int]], root: str = ""
              ) -> dict[str, set[int]]:
    """Changed lines that no test ran, per file, within what the run measured.

    `root` is the directory the coverage run started in, because a diff names files from the
    repository root and a report names them from there. A changed source file **inside** the
    measured scope but absent from the report is not silently dropped: it comes back with all of
    its changed lines, which is the honest reading of "no test reached this file at all". A file
    outside the scope is not reported as a gap at all — see `unmeasured`.
    """
    roots = measured_roots(missing)
    out: dict[str, set[int]] = {}
    for path, lines in changed.items():
        if not path.endswith(MEASURED_SUFFIXES):
            continue
        relative = _relative(path, root)
        if relative in missing:
            gap = lines & missing[relative]
        elif path in missing:
            gap = lines & missing[path]
        elif relative.split("/", 1)[0] in roots:
            gap = set(lines)
        else:
            continue
        if gap:
            out[path] = gap
    return out


def unmeasured(changed: dict[str, set[int]], missing: dict[str, set[int]] | None = None,
               root: str = "") -> dict[str, int]:
    """Changed lines nothing measured: files of a kind no coverage tool here reads, and source
    outside the run's scope — a second package, `scripts/`, migrations. Listed, never counted as
    covered: silence is what makes a report read better than the thing it reports."""
    measured = missing or {}
    roots = measured_roots(measured)
    out: dict[str, int] = {}
    for path, lines in changed.items():
        if not path.endswith(MEASURED_SUFFIXES):
            out[path] = len(lines)
            continue
        relative = _relative(path, root)
        if relative not in measured and relative.split("/", 1)[0] not in roots:
            out[path] = len(lines)
    return out


def render(gaps: dict[str, set[int]], changed: dict[str, set[int]], others: dict[str, int],
           suite: str) -> str:
    """The section step 7 puts in the PR body."""
    measured = sum(len(v) for p, v in changed.items() if p.endswith(MEASURED_SUFFIXES))
    missed = sum(len(v) for v in gaps.values())
    out = [f"Coverage of the changed lines — run: {suite}.", "",
           f"Changed lines measured: {measured}; of them never executed by a test: {missed}."]
    if gaps:
        out += ["", "| File | Uncovered changed lines | Why |", "|---|---|---|"]
        for path in sorted(gaps):
            spans = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in as_ranges(gaps[path]))
            out.append(f"| `{path}` | {spans} |  |")
    else:
        out += ["", "No changed line is left uncovered."]
    if others:
        out += ["", "Not measured (outside the run, or no coverage tool for this kind of file): "
                + ", ".join(f"`{p}` ({n})" for p, n in sorted(others.items()))]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--coverage", type=Path, required=True, help="the run's JSON report")
    ap.add_argument("--base", default="origin/main", help="what this branch is diffed against")
    ap.add_argument("--root", default="", help="directory the coverage run started in")
    ap.add_argument("--suite", required=True, help="which run produced the coverage, in words")
    ap.add_argument("--repo", type=Path, default=Path("."), help="repository root")
    args = ap.parse_args()

    if not args.coverage.is_file():
        print(f"diff_coverage: no coverage report at {args.coverage} — run the project's "
              f"coverage command first (profile → ## Coverage)", file=sys.stderr)
        return 2
    diff = subprocess.run(["git", "diff", "--no-renames", f"{args.base}...HEAD"],
                          cwd=args.repo, capture_output=True, text=True, check=True).stdout
    changed = changed_lines(diff)
    missing = missing_lines(json.loads(args.coverage.read_text()), args.repo)
    print(render(uncovered(changed, missing, args.root), changed,
                 unmeasured(changed, missing, args.root), args.suite))
    return 0


if __name__ == "__main__":
    sys.exit(main())
