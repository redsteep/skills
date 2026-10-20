# Reviewer evals

How to measure a reviewer (`design-review`, the `pre-pr-review` reviewers) on mistakes whose
answer is already known. The plugin owns this format and the assertions that test its own
contract; the project owns the cases, because a case is a pair of commits in that project's
history.

## Where things live

| Part | Where |
|---|---|
| This format | here |
| Generic assertions — the reviewer's contract, checked on every case | the plugin's README, "Evals" |
| Cases | the project: `.claude/evals/<reviewer>/cases/<id>.yaml`, one file per case |
| A frozen profile, when the reviewer needs one at old commits | the project: `.claude/evals/<reviewer>/profile.md` |
| Raw reports and verdicts | `.claude/evals/<reviewer>/runs/` (gitignored) |
| One line per sweep | `.claude/evals/<reviewer>/results.md` |

Nothing case-specific goes into the plugin: it ships to every project that installs it.

## A case

A mistake the reviewer missed or the project corrected by hand, replayed at the commit before
the correction. Name it `<date of the incident>-<what went wrong>`.

```yaml
id: 2026-04-29-model-override-env-var
origin: "where it was caught — the review comment, or the commit that corrected it"
before: eval/<reviewer>/<id>/before   # 82bc9f40
after: eval/<reviewer>/<id>/after     # 4d615b16
mode: proposal                        # reviewer-specific inputs, named as its dispatch names them:
spec: docs/…/design.md                #   a spec, or base + feature + source_files + test_files
expected:
  - defect: >-
      What is wrong, where, and what it should be instead.
    match: >-
      What counts as finding it — and what does not ("a generic 'extract a helper' without
      pointing at the existing one is not a match").
```

- **`before` / `after` are tags, pushed to origin** — `eval/<reviewer>/<id>/before|after`. A
  squash-merged branch leaves its commits unreachable, and GitHub drops unreachable objects; a
  tag keeps them. The sha goes in a comment for a reader.
- **`after`** is the corrected commit. A run there must flag none of `expected` — the false
  alarm check, in the same case instead of a separate control.
- **Inputs** are what the reviewer is dispatched with, not a user's phrasing. Whether the review
  starts at all is the hook's or the caller's job, tested separately.
- **`expected`** — one entry per defect; a judge answers one yes/no question per entry from the
  report alone. `match` carries the edge cases, both ways. Fields that help a reader (`file`,
  `lines`, the rule or test it breaks) are welcome; the judge needs only `defect` and `match`.

## Rules, profiles and leaks

A rule or known-failure written because of a case's own incident makes that case easier — it may
quote it. Two ways to handle it, depending on what the eval is for:

- **Measuring the reviewer:** freeze the profile with the set, and retire a case whose answer
  later went into it.
- **Gating the rules too** (a change to `testing.md` should not lose a case): copy the project's
  current rules into the worktree, record their sha in `results.md`, and read a hit on a case
  older than its rule as weaker evidence.

## Arms

Two switches — the reviewer's prompt, and the project's instructions (`CLAUDE.md`, guidelines) —
give four arms: `full`, `reviewer-only`, `rules-only`, `neither`. They tell apart a finding the
reviewer earns from one the rules hand it, and a case every arm hits measures nothing: replace it.
Comparing two versions of a reviewer is `full` against `full` at the old version.

## Grading and results

Binary: each `expected` entry, each generic assertion, hit or missed, with the quote that decided
it. No scores. `results.md` gets one line per sweep and arm: date, plugin version (and the rules'
sha when they are copied in), model, runs per case, cost, hits per case on `before`, entries still
flagged on `after`.

An assertion that passes in every arm on every case measures nothing — drop it.

## Running

```
python3 tools/reviewer-eval/run.py <project>/.claude/evals/<reviewer> \
    [--case GLOB] [--arms full,neither] [--after-arms full] [--repeat 3] [-j 3]
```

Per case, arm and repeat: a detached worktree at the tag, `copy_in` applied (or the instructions
removed), a read-only headless run of the reviewer, a judge run with no tools that returns
structured verdicts. The template comes from this checkout, not from the installed plugin: the
eval measures the version being edited.

The runner is generic; what differs per reviewer is an **adapter** that ships with its plugin,
`plugins/<plugin>/evals/<name>.py`, and changes in the same commit as the template's placeholders:

| Name | What |
|---|---|
| `TEMPLATE` | the reviewer prompt, relative to the plugin |
| `TOOLS` | allowed on top of `Read`, `Grep`, `Glob`, `Bash(git:*)` |
| `CONTRACT` | the generic assertions, judged on every run |
| `inputs(case, worktree, config)` | `{PLACEHOLDER: value}`, filled the way the caller fills it; an unfilled placeholder fails the run |
| `plain_prompt(case, worktree, inputs)` | the ask of the arms without the reviewer |

The project's `eval.yaml`:

```yaml
reviewer: <plugin>/<adapter>
tag_prefix: eval/<reviewer>
copy_in:                       # `/path` = the repo's current file, same path; `path` = from the eval dir
  - {from: profile.md, to: .claude/design-review.md}
record_shas: []                # files whose last commit goes into each results line
instruction_files: [CLAUDE.md, docs/guidelines/code.md]
inputs: {}                     # the adapter's own settings
```

`${CLAUDE_PLUGIN_ROOT}` in the template and in copied files is expanded to the checkout's plugin.
Each verdict records the tools the reviewer was refused; a run with denials saw less than it could.
