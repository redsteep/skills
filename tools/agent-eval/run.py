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
the worktree's diff, which matches a shape rather than interpreting one; `REPLACE_TOOLS` drops the
read-only base set so the tool list is exactly what the case was measured with, and
`summarise(case, results)` writes the results line's fragment. An entry `grade` cannot settle by
shape -- whether something was *decided* -- comes back as `{"verdict": "JUDGE", "question": ...,
"text": ...}` and is scored by the judge, marked `judged` so a reader can tell the two apart. The four powerful tools (Edit, Write,
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

A case of a kind that runs a real skill adds `plugin: <name>@<ver>`: the plugin to put on disk, at
the version that case is about, so a bare run reproduces its own conditions. `--plugin-ver` is the
arm and overrides it; with neither, such a kind cannot start. Every run also gets
`artifacts["base"]` — the ref the runner checked out.

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
# Every released version of a plugin stays in the install cache, so --plugin-ver can put a kind that
# runs the real skill on the version an incident ran under.
PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache" / "redsteep"
_PLACEHOLDER = re.compile(r"\{[A-Z][A-Z_]+\}")

# A grader's open question: what has no shape to match -- whether something was *decided* -- comes
# back from the adapter as JUDGE with the text that answers it, and is scored here rather than left
# as a string for a human to go and read.
OPEN_SCHEMA = {
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
    },
    "required": ["verdicts"],
}

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

    def header(self, rules: str = WORKTREE) -> str:
        """`record_shas` is resolved at the revision the arm actually read the file from. Taken at
        HEAD it labels every arm with today's sha, so a `--rules <old>` line claims rules it did not
        run on -- which is worse than no label, because it reads as comparable."""
        parts = []
        if self.plugin is not None:
            version = json.loads((self.plugin / ".claude-plugin/plugin.json").read_text())["version"]
            parts.append(f"{self.plugin.name} {version} ({sh('git', 'rev-parse', '--short', 'HEAD', cwd=SKILLS)})")
        at = "HEAD" if rules == WORKTREE else rules
        for rel in self.config.get("record_shas", []):
            parts.append(f"{Path(rel).name} {sh('git', 'log', '-1', '--format=%h', at, '--', rel, cwd=self.repo)}")
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
    try:
        out = subprocess.run(
            ["claude", "-p", "--output-format", "json", *extra],
            input=prompt, cwd=cwd, capture_output=True, text=True, timeout=3600,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired:
        # A chained kind can hang for the whole hour. One job's hang is one job's loss; the sweep's
        # other arms are already paid for.
        return {"is_error": True, "result": "timed out after 3600s", "total_cost_usd": 0}
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": out.stdout + out.stderr, "total_cost_usd": 0}


def _denial(d: dict) -> dict:
    tool_input = d.get("tool_input") or {}
    detail = tool_input.get("command") or tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern")
    return {"tool": d.get("tool_name"), "input": detail if detail is not None else tool_input}


def transcript_of(session_id: str) -> Path | None:
    """The run's own session transcript. A dispatched subagent's report is nowhere in
    `--output-format json`; it is in here, so for a chained kind this file *is* the middle stage's
    only artifact -- and it lives outside the sweep, in the CLI's own directory, on the CLI's own
    rotation schedule. The runner copies it in so a verdict stays re-gradable after that."""
    hits = sorted((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    return hits[0] if hits else None


def wall_seconds(path: Path) -> float | None:
    """How long the run really took, from the transcript's own timestamps. The CLI's `duration_ms`
    describes its last segment only -- 63s against a measured 582s on a chained run -- so for a kind
    that dispatches, the number it reports is not the run's."""
    stamps = []
    for line in path.open():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("timestamp"):
            stamps.append(entry["timestamp"])
    if len(stamps) < 2:
        return None
    first, last = (datetime.datetime.fromisoformat(s.replace("Z", "+00:00")) for s in (stamps[0], stamps[-1]))
    return (last - first).total_seconds()


def judge_open(verdicts: list[dict], cwd: Path) -> dict:
    """Score the entries a grader left open, in one call. `judged` marks a verdict a model gave, so
    a reader can tell it from a shape matched in a diff -- and the quote is what it decided on."""
    open_ = [v for v in verdicts if v.get("verdict") == "JUDGE" and v.get("question") and v.get("text")]
    if not open_:
        return {"total_cost_usd": 0}
    asked = "\n\n".join(
        f"[{i}] question: {v['question'].strip()}\n\n## The text to answer [{i}] from\n{v['text']}"
        for i, v in enumerate(open_)
    )
    judge = claude(
        "You answer one yes/no question per item, each from its own text and from nothing else.\n"
        "`hit` is true when the answer is yes. Quote the line that decides it: the one that makes it\n"
        "yes, or, when the answer is no, the nearest thing to it, so a reader can check you.\n\n" + asked,
        cwd,
        ["--setting-sources", "", "--strict-mcp-config", "--tools", "", "--model", JUDGE_MODEL,
         "--json-schema", json.dumps(OPEN_SCHEMA)],
    )
    answers = {a["index"]: a for a in (judge.get("structured_output") or {}).get("verdicts", [])}
    for i, v in enumerate(open_):
        # The text is already saved beside the report; inlining it in the verdict JSON would put a
        # whole subagent report in a file meant to be read at a glance.
        del v["text"]
        if (answer := answers.get(i)) is None:
            continue
        v.update(verdict="RIGHT" if answer["hit"] else "WRONG", quote=answer["quote"], judged=True)
    return {**judge, "open": len(open_), "answered": sum(1 for v in open_ if v.get("judged"))}


def plugin_dir(name: str, ver: str | None) -> Path:
    if ver is None:
        raise SystemExit(f"no version for plugin {name!r}: pin it in the case "
                         f"(`plugin: {name}@<ver>`) or pass --plugin-ver (installed: "
                         f"{sorted(p.name for p in (PLUGIN_CACHE / name).iterdir())})")
    path = PLUGIN_CACHE / name / ver
    if not (path / "skills").is_dir():
        raise SystemExit(f"no plugin {name} {ver} at {path}")
    return path


def plugin_for(ev: Eval, case: dict, override: str | None) -> tuple[str, str | None] | None:
    """Which plugin, at which version, this case runs its real skill against.

    `plugin: <name>@<ver>` in the case pins the version the incident ran under, so a bare run
    reproduces the incident's own conditions instead of refusing to start. `--plugin-ver` is the
    arm: it overrides the version for every case in the sweep. The adapter's `PLUGIN` is the
    fallback for a kind whose cases do not name one, and there the flag is still the only source.

    Resolved per case, not once per sweep, so cases pinning different baselines can run together."""
    declared = case.get("plugin") or getattr(ev.adapter, "PLUGIN", None)
    if not declared:
        return None
    name, _, ver = str(declared).partition("@")
    return name, override or ver or None


def run_one(ev: Eval, case: dict, arm: str, rules: str, side: str, rep: int, sweep_dir: Path,
            worktree_root: Path, tag_rules: bool, dry: bool = False, plugin_ver: str | None = None) -> dict:
    use_reviewer, use_instructions = ARMS[arm]
    variant = f".{re.sub(r'[^A-Za-z0-9_-]', '_', rules)}" if tag_rules else ""
    name = f"{case['id']}.{arm}{variant}.{side}.{rep}"
    worktree = worktree_root / name
    ref = f"{ev.config['tag_prefix']}/{case['id']}/{side}"
    sh("git", "worktree", "add", "--detach", str(worktree), ref, cwd=ev.repo)
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
            prompt = ev.adapter.plain_prompt(case, worktree, inputs)
            # A kind that runs the project's real skill is the session's own agent, not a named
            # subagent, and needs the plugin on disk at the version that is its arm.
            session = [] if getattr(ev.adapter, "MAIN_AGENT", False) else ["--agent", "general-purpose"]
            if pinned := plugin_for(ev, case, plugin_ver):
                session += ["--plugin-dir", str(plugin_dir(*pinned))]
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
        # `model:` in eval.yaml is passed, not merely recorded: a sweep that means to pin its model
        # and relies on the CLI default instead measures whatever the operator's session happened to
        # be set to, under a results line that names a model.
        model = ["--model", ev.config["model"]] if ev.config.get("model") else []
        review = claude(
            prompt,
            worktree,
            [*SESSION_FLAGS, *session, *model, "--allowedTools", *tools,
             *(["--disallowedTools", *off_limits] if off_limits else [])],
            env={"CLAUDE_PLUGIN_ROOT": str(ev.plugin or "")},
        )
        # The artifact of a writing kind is the worktree, which the `finally` is about to delete.
        # `diff` is what a kind that leaves its work uncommitted produces; `committed_diff` is what
        # a kind that commits produces, and is empty for the other. `session_id` is how a grader
        # reaches the run's own transcript, where a dispatched subagent's report is the only place
        # a middle stage can be read from.
        artifacts = {
            "final_text": review.get("result", ""),
            "session_id": review.get("session_id", ""),
            "diff": sh("git", "diff", cwd=worktree),
            "committed_diff": sh("git", "diff", f"{ref}..HEAD", cwd=worktree),
            "head": sh("git", "rev-parse", "HEAD", cwd=worktree),
            # The ref this run started from. The runner builds it; without it a grader that needs
            # the starting state has to restate it in the case, which is a second source of truth
            # for the same ref and nothing checks the two agree.
            "base": ref,
        }
        # A chain's later stages edit the files its earlier ones wrote -- the review step applies
        # its findings to the same test files the write step created -- so base..HEAD is the round's
        # outcome, not any one stage's artifact. The commits are what separate them.
        log = sh("git", "log", "--reverse", "--format=%H %s", f"{ref}..HEAD", cwd=worktree)
        artifacts["commits"] = [
            {"sha": line.split(" ", 1)[0], "subject": line.split(" ", 1)[1] if " " in line else ""}
            for line in log.splitlines()
        ]
        artifacts["commit_diffs"] = {
            c["sha"]: sh("git", "show", "--format=", c["sha"], cwd=worktree)
            for c in artifacts["commits"]
        }
        # A worktree shares the repo's object database, so removing it only unreferences what the
        # run committed -- the objects are still there until a gc prunes them. One ref keeps a
        # stage's own commit gradeable afterwards, and startable from.
        if artifacts["commits"]:
            sh("git", "update-ref", f"refs/eval/{sweep_dir.name}/{name}", artifacts["head"], cwd=ev.repo)
        # The transcript was the one artifact the runner did not own: the grader globbed the CLI's
        # directory for it at grade time, so a $7 run's review verdict rested on a file the sweep
        # could not produce again. `transcript` is the path a grader reads.
        if source := transcript_of(artifacts["session_id"]):
            destination = sweep_dir / f"{name}.transcript.jsonl"
            shutil.copyfile(source, destination)
            artifacts["transcript"] = str(destination)
    finally:
        # check=False: a failing removal must not replace the real exception with its own.
        subprocess.run(["git", "worktree", "remove", "--force", str(worktree)],
                       cwd=ev.repo, capture_output=True, text=True)
    report = review.get("result", "")
    (sweep_dir / f"{name}.report.md").write_text(report)
    # A verdict that surprises you has to be re-examinable without archaeology: the worktree is
    # gone by now, so whatever the run produced is written beside its report.
    for key in ("diff", "committed_diff"):
        if artifacts.get(key):
            (sweep_dir / f"{name}.{key}").write_text(artifacts[key])
    for i, commit in enumerate(artifacts.get("commits", []), 1):
        (sweep_dir / f"{name}.{i}-{commit['sha'][:8]}.diff").write_text(artifacts["commit_diffs"][commit["sha"]])

    seconds = wall_seconds(Path(artifacts["transcript"])) if artifacts.get("transcript") else None
    contract = list(getattr(ev.adapter, "CONTRACT", []))
    grade = getattr(ev.adapter, "grade", None)
    if grade:
        # A shape in a diff is matched, not interpreted -- no judge for those. What the grader
        # leaves open it hands back as JUDGE with the question and the text, and the judge scores
        # that: the two are not alternatives, and a kind that matches stage 1 and asks about stage 2
        # needs both in one verdict.
        verdicts, held = grade(case, artifacts), []
        judge = judge_open(verdicts, worktree_root)
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
        "judge_error": judge.get("open", 0) != judge.get("answered", 0) if grade else (
            len(verdicts) != len(case["expected"]) or len(held) != len(contract)),
        # A tool the reviewer needed and was refused: its report is short of what it could see. The
        # command or path says which allow rule is missing.
        "permission_denials": [_denial(d) for d in review.get("permission_denials", [])],
        "models": sorted(review.get("modelUsage", {})),
        "session_id": review.get("session_id", ""),
        # Without these a verdict cannot be re-examined at all: the worktree is gone and nothing
        # else records which commits the run made.
        "head": artifacts.get("head", ""),
        "commits": artifacts.get("commits", []),
        "review_cost_usd": round(review.get("total_cost_usd", 0), 2),
        "judge_cost_usd": round(judge.get("total_cost_usd", 0), 2),
        "duration_s": round(seconds if seconds is not None else review.get("duration_ms", 0) / 1000),
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
    parser.add_argument("--plugin-ver", metavar="VER",
                        help="for a kind that runs a real skill: which installed plugin version to "
                             "put on disk for it, overriding what each case pins. That version is "
                             "the arm; omit it to run every case against its own baseline")
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
    # A kind that needs a plugin on disk is checked here, not inside the first job: by then other
    # jobs are running and one bad version costs their results, not just its own. Across the
    # selected cases, since each may pin its own.
    for case in cases:
        if pinned := plugin_for(ev, case, args.plugin_ver):
            plugin_dir(*pinned)
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
    results = []
    with concurrent.futures.ThreadPoolExecutor(args.concurrency) as pool:
        futures = {
            pool.submit(run_one, ev, *job, sweep_dir, worktree_root, len(variants) > 1,
                        args.dry_run, args.plugin_ver): job
            for job in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            case, arm, rules, side, rep = futures[future]
            try:
                results.append(future.result())
            except (Exception, SystemExit) as exc:  # noqa: BLE001 -- one job's failure, not the sweep's
                # Every model call is paid for before anything downstream can fail, and a raise here
                # used to discard the results line of every job that had finished. Record it and
                # summarise what did run.
                print(f"{case['id']}.{arm}.{side}.{rep}: FAILED {type(exc).__name__}: {exc}", flush=True)
                results.append({
                    "case": case["id"], "arm": arm, "rules": rules, "side": side, "rep": rep,
                    "hits": [], "verdicts": [], "contract": [], "contract_verdicts": [],
                    "review_error": True, "judge_error": False, "permission_denials": [],
                    "models": [], "session_id": "", "review_cost_usd": 0, "judge_cost_usd": 0,
                    "duration_s": 0, "failure": f"{type(exc).__name__}: {exc}",
                })
    shutil.rmtree(worktree_root, ignore_errors=True)
    if args.dry_run:
        return

    # The versions actually used, not the flag: with the baseline in the case a bare run still has
    # a plugin version, and its results line has to say which.
    pinned_versions = {p for case in cases if (p := plugin_for(ev, case, args.plugin_ver))}
    used = sorted(f"{n} {v}" for n, v in pinned_versions)

    def header_for(rules: str) -> str:
        head = ev.header(rules)
        if used:
            head = f"{', '.join(used)} · {head}"
        return f"{head} · {ev.rules_label(rules)}"

    lines = [
        summary_line(ev, sweep, arm, rules, cases, results, header_for(rules), args.repeat)
        for arm in arms
        for rules in variants
    ]
    with (ev.dir / "results.md").open("a") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
