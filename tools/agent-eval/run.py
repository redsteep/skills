#!/usr/bin/env python3
"""Run a reviewer over a project's eval cases and judge each report against what the case expects.

    python3 tools/agent-eval/run.py <eval-dir> [--case GLOB] [--arms full,...] [--repeat N]
                                                  [--after-arms full] [--rules REV ...] [-j 3]

Would the instruction edit I am making work better?

    run.py <eval-dir> --rules HEAD --rules worktree --repeat 3

`--rules` picks where the repo-side `copy_in` files (`from: /path`) come from: `worktree` — the
checkout as it is, uncommitted edits included (the default) — or any git revision. Given more than
once, every job runs once per variant and results.md gets a line per arm and variant, labelled with
the revision, or with the files that differ from HEAD.

<eval-dir> lives in the project (e.g. `.claude/evals/test-reviewer`): `eval.yaml`, the project's
side of the setup, and `cases/*.yaml`, each pointing at tagged commits of that project. Format:
`docs/reviewer-evals.md`.

An adapter decides what a run *is*. A reviewer's reads and reports, and is judged by a model. One
that names Edit/Write in `TOOLS` writes code, and is graded by its own `grade(case, artifacts)` over
the worktree's diff -- no judge, since a shape is matched rather than interpreted; `REPLACE_TOOLS`
drops the read-only base set so the tool list is exactly what the case was measured with, and
`summarise(case, results)` writes the results line's fragment. The four powerful tools (Edit, Write,
Agent, Skill) are denied unless `TOOLS` asks for them, so a reviewer adapter's flags are unchanged.

`eval.yaml` names the reviewer as `<plugin>/<adapter>`: the module
`plugins/<plugin>/evals/<adapter>.py` of this repo, which knows the reviewer's template and how
its caller fills it. An adapter defines:

    AGENT         the plugin's agent that is the reviewer (`<plugin>:<name>`), run from this
                  checkout with `--plugin-dir`; inputs() then returns {"MESSAGE": its task message}
    TEMPLATE      or: the reviewer prompt, relative to its plugin, filled from inputs()
    TOOLS         tools allowed on top of Read, Grep, Glob and Bash(git:*)
    CONTRACT      assertions judged on every run — the reviewer's own promises, not the case's
    inputs(case, worktree, config) -> {PLACEHOLDER: value}
    plain_prompt(case, worktree, inputs) -> str      the ask of the arms without the reviewer

Arms cross two switches — the reviewer prompt vs the adapter's plain ask, and the project's
instructions (`instruction_files`) present vs removed from the worktree:

    full           reviewer prompt + project instructions   (what the caller runs)
    reviewer-only  reviewer prompt, no project instructions
    rules-only     plain ask + project instructions
    neither        plain ask, no project instructions

Per case, arm and repeat: a throwaway worktree at the case's `before` tag (and `after` for the arms
in --after-arms), `copy_in` applied and, without instructions, `instruction_files` removed; a
read-only `claude -p` run as the general-purpose agent; a judge run that answers yes/no per expected
finding and per contract assertion. The reviewer template comes from this checkout, not from the
installed plugin: the eval measures the version being edited. Raw output lands in
<eval-dir>/runs/<sweep>/, one summary line per arm in <eval-dir>/results.md.
"""

import argparse
import concurrent.futures
import datetime
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SKILLS = Path(__file__).resolve().parents[2]
ARMS = {  # arm: (reviewer prompt?, project instructions?)
    "full": (True, True),
    "reviewer-only": (True, False),
    "rules-only": (False, True),
    "neither": (False, False),
}
# Project settings only (its hooks, its plugins), like a subagent of a session in this repo: the
# user's own plugins, output style and MCP servers are not part of what is measured.
SESSION_FLAGS = ["--setting-sources", "project", "--strict-mcp-config"]
BASE_TOOLS = ["Read", "Grep", "Glob", "Bash(git:*)"]
JUDGE_MODEL = "sonnet"
WORKTREE = "worktree"  # --rules value: the checkout as it is, uncommitted edits included
_PLACEHOLDER = re.compile(r"\{[A-Z][A-Z_]+\}")

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "hit": {"type": "boolean"},
                    "quote": {"type": "string"},
                },
                "required": ["index", "hit", "quote"],
            },
        },
        "contract": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "held": {"type": "boolean"},
                    "quote": {"type": "string"},
                },
                "required": ["index", "held", "quote"],
            },
        },
    },
    "required": ["verdicts", "contract"],
}


class Eval:
    def __init__(self, eval_dir: Path):
        self.dir = eval_dir
        self.repo = Path(sh("git", "rev-parse", "--show-toplevel", cwd=eval_dir))
        self.config = yaml.safe_load((eval_dir / "eval.yaml").read_text())
        # `reviewer: <plugin>/<adapter>` -- a plugin's reviewer is the subject, and its version goes
        # into every results line. `adapter: <file>.py` -- a kind with no plugin under test, where
        # the project's own rules are the subject and `record_shas` carries the version; the adapter
        # then lives in the eval dir beside the cases.
        if "reviewer" in self.config:
            plugin, adapter = self.config["reviewer"].split("/")
            self.plugin: Path | None = SKILLS / "plugins" / plugin
            path = self.plugin / "evals" / f"{adapter}.py"
        else:
            self.plugin = None
            adapter = Path(self.config["adapter"]).stem
            path = eval_dir / self.config["adapter"]
        spec = importlib.util.spec_from_file_location(adapter, path)
        if spec is None or spec.loader is None:
            raise SystemExit(f"no adapter at {path}")
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)

    def repo_files(self) -> list[str]:
        return [e["from"][1:] for e in self.config.get("copy_in", []) if e["from"].startswith("/")]

    def copy_in(self, worktree: Path, rules: str) -> None:
        """`from: /x` is the repo's file — from the working tree when `rules` is `worktree`
        (uncommitted edits included), else from that revision; `from: x` is the eval dir's
        (frozen). `to` defaults to `from` without the slash. `${CLAUDE_PLUGIN_ROOT}` is expanded to
        this checkout's plugin, so a profile's commands reach the scripts being measured."""
        for entry in self.config.get("copy_in", []):
            if not entry["from"].startswith("/"):
                text = (self.dir / entry["from"]).read_text()
            elif rules == WORKTREE:
                text = (self.repo / entry["from"][1:]).read_text()
            else:
                text = subprocess.run(["git", "show", f"{rules}:{entry['from'][1:]}"], cwd=self.repo,
                                      check=True, capture_output=True, text=True).stdout
            dest = worktree / entry.get("to", entry["from"].lstrip("/"))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text.replace("${CLAUDE_PLUGIN_ROOT}", str(self.plugin or "")))

    def rules_label(self, rules: str) -> str:
        """What the repo-side files were, for the results line. A sha alone would claim a commit's
        version while the run read an uncommitted edit."""
        if rules != WORKTREE:
            return f"rules {rules} ({sh('git', 'rev-parse', '--short', rules, cwd=self.repo)})"
        files = self.repo_files()
        dirty = sh("git", "status", "--porcelain", "--", *files, cwd=self.repo).splitlines() if files else []
        if not dirty:
            return "rules worktree (= HEAD)"
        return "rules worktree (uncommitted: " + ", ".join(Path(l[3:]).name for l in dirty) + ")"

    def reviewer_prompt(self, inputs: dict) -> str:
        if self.plugin is None:
            raise SystemExit("TEMPLATE needs a plugin; an eval-dir adapter must define plain_prompt")
        prompt = (self.plugin / self.adapter.TEMPLATE).read_text().replace("${CLAUDE_PLUGIN_ROOT}", str(self.plugin))
        for key, value in inputs.items():
            prompt = prompt.replace("{" + key + "}", value)
        # A placeholder renamed in the template and not in the adapter would reach the reviewer as
        # literal text; fail the run instead.
        if left := sorted(set(_PLACEHOLDER.findall(prompt)) - {"{" + k + "}" for k in inputs}):
            raise SystemExit(f"{self.adapter.TEMPLATE}: placeholders the adapter does not fill: {left}")
        return prompt

    def header(self) -> str:
        parts = []
        if self.plugin is not None:
            version = json.loads((self.plugin / ".claude-plugin/plugin.json").read_text())["version"]
            parts.append(f"{self.plugin.name} {version} ({sh('git', 'rev-parse', '--short', 'HEAD', cwd=SKILLS)})")
        for rel in self.config.get("record_shas", []):
            parts.append(f"{Path(rel).name} {sh('git', 'log', '-1', '--format=%h', '--', rel, cwd=self.repo)}")
        return " · ".join(parts)


def sh(*args: str, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def judge_prompt(case: dict, contract: list[str], report: str) -> str:
    def where(e: dict) -> str:
        if "file" not in e:
            return ""
        lines = e.get("lines")
        return f"{e['file']}:{lines[0]}-{lines[1]}\n  " if lines else f"{e['file']}\n  "

    expected = "\n".join(
        f"[{i}] {where(e)}defect: {e['defect'].strip()}\n  counts as a hit: {e['match'].strip()}"
        for i, e in enumerate(case["expected"])
    )
    promises = "\n".join(f"[{i}] {c.strip()}" for i, c in enumerate(contract)) or "(none)"
    return (
        "You grade a review report. Two lists, two kinds of answer.\n\n"
        "`verdicts` — for each expected defect, one yes/no question: does any issue in the report name "
        "this defect, as the 'counts as a hit' line describes? Coverage-map or table rows count only when "
        "they mark the defect as a problem. When hit is true, quote the report's line that names it; "
        "when false, quote nothing.\n\n"
        "`contract` — for each promise, does the report as a whole keep it? When held is false, quote "
        "the line that breaks it; when true, quote nothing.\n\n"
        f"## Expected defects\n{expected}\n\n## Promises\n{promises}\n\n## Report\n{report}"
    )


def claude(prompt: str, cwd: Path, extra: list[str], env: dict | None = None) -> dict:
    out = subprocess.run(
        ["claude", "-p", "--output-format", "json", *extra],
        input=prompt, cwd=cwd, capture_output=True, text=True, timeout=3600,
        env={**os.environ, **(env or {})},
    )
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": out.stdout + out.stderr, "total_cost_usd": 0}


def _denial(d: dict) -> dict:
    tool_input = d.get("tool_input") or {}
    detail = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern")
    return {"tool": d.get("tool_name"), "input": detail if detail is not None else tool_input}


def run_one(ev: Eval, case: dict, arm: str, rules: str, side: str, rep: int, sweep_dir: Path,
            worktree_root: Path, tag_rules: bool, dry: bool = False) -> dict:
    use_reviewer, use_instructions = ARMS[arm]
    variant = f".{re.sub(r'[^A-Za-z0-9_-]', '_', rules)}" if tag_rules else ""
    name = f"{case['id']}.{arm}{variant}.{side}.{rep}"
    worktree = worktree_root / name
    sh("git", "worktree", "add", "--detach", str(worktree), f"{ev.config['tag_prefix']}/{case['id']}/{side}", cwd=ev.repo)
    try:
        # Every eval set of the project (cases, `match` texts, past reports): a case cut from a commit
        # newer than the eval dir would otherwise carry its own answer.
        shutil.rmtree(worktree / ev.dir.relative_to(ev.repo).parent, ignore_errors=True)
        ev.copy_in(worktree, rules)
        if not use_instructions:
            for rel in ev.config["instruction_files"]:
                (worktree / rel).unlink(missing_ok=True)
        inputs = ev.adapter.inputs(case, worktree, ev.config.get("inputs", {}))
        agent = getattr(ev.adapter, "AGENT", None)
        if use_reviewer and agent:
            # The plugin's own agent, loaded from this checkout: its definition is the procedure,
            # the generated message its whole input — what a real dispatch delivers.
            prompt, session = inputs["MESSAGE"], ["--agent", agent, "--plugin-dir", str(ev.plugin)]
        elif use_reviewer:
            prompt, session = ev.reviewer_prompt(inputs), ["--agent", "general-purpose"]
        else:
            prompt, session = ev.adapter.plain_prompt(case, worktree, inputs), ["--agent", "general-purpose"]
        # A kind whose artifact is code *replaces* the read-only base set rather than extending it:
        # the recorded implementer runs had no Bash at all, and `Bash(git:*)` would be a different
        # environment from the one their results line was measured in.
        base = [] if getattr(ev.adapter, "REPLACE_TOOLS", False) else [*BASE_TOOLS]
        tools = base + [*getattr(ev.adapter, "TOOLS", [])]
        if use_reviewer and agent:
            tools.append("Bash")  # the agent's own `tools:` line has unrestricted Bash, as in a real review
        # The four powerful tools stay denied unless the adapter asked for them -- read-only for a
        # reviewer, Edit/Write for an implementer, Agent/Skill for a run of the real skill. One rule
        # instead of a per-kind switch, and a reviewer adapter's flags come out unchanged.
        off_limits = [t for t in ("Edit", "Write", "Agent", "Skill") if t not in tools]
        if dry:
            print(f"{name}: tools={tools} denied={off_limits} prompt={len(prompt)}c", flush=True)
            return {"case": case["id"], "arm": arm, "rules": rules, "side": side, "rep": rep, "dry": True}
        review = claude(
            prompt,
            worktree,
            [*SESSION_FLAGS, *session, "--allowedTools", *tools,
             *(["--disallowedTools", *off_limits] if off_limits else [])],
            env={"CLAUDE_PLUGIN_ROOT": str(ev.plugin or "")},
        )
        # The artifact of a writing kind is the worktree, which the `finally` is about to delete.
        artifacts = {
            "final_text": review.get("result", ""),
            "diff": sh("git", "diff", cwd=worktree),
            "head": sh("git", "rev-parse", "HEAD", cwd=worktree),
        }
    finally:
        sh("git", "worktree", "remove", "--force", str(worktree), cwd=ev.repo)
    report = review.get("result", "")
    (sweep_dir / f"{name}.report.md").write_text(report)

    contract = list(getattr(ev.adapter, "CONTRACT", []))
    grade = getattr(ev.adapter, "grade", None)
    if grade:
        # A shape in a diff is matched, not interpreted: no judge model, so no judge cost and no
        # judge error. The adapter returns the same list-of-dicts the judge would.
        judge = {"total_cost_usd": 0}
        verdicts, held = grade(case, artifacts), []
    else:
        judge = claude(
            judge_prompt(case, contract, report),
            worktree_root,
            ["--setting-sources", "", "--strict-mcp-config", "--tools", "", "--model", JUDGE_MODEL,
             "--json-schema", json.dumps(JUDGE_SCHEMA)],
        )
        verdict = judge.get("structured_output") or {}
        verdicts = sorted(verdict.get("verdicts", []), key=lambda v: v["index"])
        held = sorted(verdict.get("contract", []), key=lambda v: v["index"])
    result = {
        "case": case["id"], "arm": arm, "rules": rules, "side": side, "rep": rep,
        "hits": [v["hit"] for v in verdicts if "hit" in v], "verdicts": verdicts,
        "contract": [c["held"] for c in held], "contract_verdicts": held,
        "review_error": review.get("is_error", False),
        "judge_error": False if grade else (
            len(verdicts) != len(case["expected"]) or len(held) != len(contract)),
        # A tool the reviewer needed and was refused: its report is short of what it could see. The
        # command or path says which allow rule is missing.
        "permission_denials": [_denial(d) for d in review.get("permission_denials", [])],
        "models": sorted(review.get("modelUsage", {})),
        "review_cost_usd": round(review.get("total_cost_usd", 0), 2),
        "judge_cost_usd": round(judge.get("total_cost_usd", 0), 2),
        "duration_s": round(review.get("duration_ms", 0) / 1000),
    }
    (sweep_dir / f"{name}.verdict.json").write_text(json.dumps(result, indent=2))
    denied = f" denied={[d['tool'] for d in result['permission_denials']]}" if result["permission_denials"] else ""
    shown = result["hits"] or [v.get("verdict") for v in verdicts]
    print(f"{name}: {shown} contract={result['contract']}{denied} "
          f"${result['review_cost_usd']} {result['duration_s']}s", flush=True)
    return result


def summary_line(ev: Eval, sweep: str, arm: str, rules: str, cases: list[dict], results: list[dict],
                 header: str, repeat: int) -> str:
    mine = [r for r in results if r["arm"] == arm and r["rules"] == rules]
    # A kind graded on a shape has no hit count -- WRONG/RIGHT/NEITHER is the verdict -- so its
    # adapter writes its own fragment instead of having n/m arithmetic imposed on it.
    summarise = getattr(ev.adapter, "summarise", None)
    parts = []
    for case in cases:
        if summarise:
            parts.append(summarise(case, [r for r in mine if r["case"] == case["id"]]))
            continue
        before = [r for r in mine if r["case"] == case["id"] and r["side"] == "before"]
        after = [r for r in mine if r["case"] == case["id"] and r["side"] == "after"]
        part = f"{case['id']} {sum(sum(r['hits']) for r in before)}/{len(case['expected']) * len(before)}"
        if after:
            part += f" (after: {sum(sum(r['hits']) for r in after)} flagged)"
        parts.append(part)
    cost = sum(r["review_cost_usd"] + r["judge_cost_usd"] for r in mine)
    models = sorted({m for r in mine for m in r["models"]})
    errors = sum(r["review_error"] or r["judge_error"] for r in mine)
    denials = sum(bool(r["permission_denials"]) for r in mine)
    contract = [held for r in mine for held in r["contract"]]
    return (
        f"- {sweep} · **{arm}** · {header} · {', '.join(models) or '?'} · ×{repeat} · ${cost:.2f}"
        f"{f' · contract {sum(contract)}/{len(contract)}' if contract else ''}"
        f"{f' · {errors} errors' if errors else ''}{f' · {denials} runs with denied tools' if denials else ''} — "
        + "; ".join(parts)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("eval_dir", type=Path, help="the project's eval dir: eval.yaml + cases/")
    parser.add_argument("--case", default="*")
    parser.add_argument("--arms", default="full", help=f"comma-separated, of {', '.join(ARMS)}")
    parser.add_argument("--after-arms", default="full", help="arms that also run on `after` ('' for none)")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--rules", action="append", metavar="REV",
                        help=f"where `from: /path` files come from: {WORKTREE!r} (default, uncommitted edits "
                             "included) or a git revision; repeat to compare variants")
    parser.add_argument("-j", "--concurrency", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true",
                        help="build every job -- worktree, copy_in, prompt, tools, denials -- print "
                             "them and run no model")
    args = parser.parse_args()

    ev = Eval(args.eval_dir.resolve())
    arms = args.arms.split(",")
    after_arms = set(filter(None, args.after_arms.split(",")))
    if unknown := [a for a in arms if a not in ARMS]:
        sys.exit(f"unknown arm(s): {unknown}")
    cases = [
        yaml.safe_load(p.read_text())
        for p in sorted((ev.dir / "cases").glob("*.yaml"))
        if fnmatch.fnmatch(p.stem, args.case)
    ]
    if not cases:
        sys.exit(f"no case matches {args.case!r}")
    variants = list(dict.fromkeys(args.rules or [WORKTREE]))
    for rules in variants:
        if rules != WORKTREE:
            sh("git", "rev-parse", "--verify", "--quiet", f"{rules}^{{commit}}", cwd=ev.repo)
    tags = f"refs/tags/{ev.config['tag_prefix']}/*"
    sh("git", "fetch", "origin", f"{tags}:{tags}", cwd=ev.repo)

    sweep = datetime.datetime.now().strftime("%Y-%m-%dT%H%M")
    sweep_dir = ev.dir / "runs" / sweep
    if not args.dry_run:
        sweep_dir.mkdir(parents=True)
    worktree_root = Path(tempfile.mkdtemp(prefix=f"{ev.dir.name}-eval-"))

    jobs = [
        (case, arm, rules, side, rep)
        for case in cases
        for arm in arms
        for rules in variants
        # A case without `after` has no corrected commit to check a false alarm against.
        for side in (["before", "after"] if arm in after_arms and case.get("after") else ["before"])
        for rep in range(1, args.repeat + 1)
    ]
    print(f"{len(jobs)} runs{' (dry)' if args.dry_run else ''} → {sweep_dir}", flush=True)
    with concurrent.futures.ThreadPoolExecutor(args.concurrency) as pool:
        results = list(pool.map(
            lambda j: run_one(ev, j[0], j[1], j[2], j[3], j[4], sweep_dir, worktree_root,
                              len(variants) > 1, args.dry_run), jobs))
    shutil.rmtree(worktree_root, ignore_errors=True)
    if args.dry_run:
        return

    header = ev.header()
    lines = [
        summary_line(ev, sweep, arm, rules, cases, results, f"{header} · {ev.rules_label(rules)}", args.repeat)
        for arm in arms
        for rules in variants
    ]
    with (ev.dir / "results.md").open("a") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
