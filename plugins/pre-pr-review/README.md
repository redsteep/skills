# pre-pr-review

A gated review of a finished feature branch, run by Claude before it opens the PR.
Every step ends on a gate that passes on output Claude saw, not on judgement.

| Step | Who | Gate |
|---|---|---|
| 0. Setup | main agent | targeted tests green on HEAD |
| 1. E2E in the browser | subagent | every flow works and matches the spec / visual reference |
| 2. Architecture | `pre-pr-review:architecture-reviewer` | no Critical / Important violations of the project's code rules |
| 3. Test strategy | `pre-pr-review:test-reviewer` | each contract tested once, at the right layer |
| 4. Manual mutation testing | `pre-pr-review:mutation-tester` | every surviving mutant gets a test proven red on it and green without it |
| 5–6. Refactor tests, then code | main agent | targeted tests + the repo's lint/type-check green |
| 7. PR | main agent | `REVIEWED=1 gh pr create`, with a review summary in the body |

Steps 1–4 run in parallel, mutation in its own copy of the worktree.

Steps 2–4 are the plugin's own agents (`agents/`): each one's procedure is its definition, so it
reaches the agent exactly as written. The main agent dispatches them with a few `key: value`
lines (worktree, spec, base, test command), and a `PreToolUse` hook replaces that prompt with an
input generated from the worktree and the profile (`scripts/reviewer-inputs.py`): the spec's
title, base and head, the source and test files. No summary, framing or paraphrase from the main
agent reaches a reviewer. In replays of real review rounds, that framing made the test reviewer
miss every finding it caught from its bare procedure.

A `PreToolUse` hook denies `gh pr create` unless it's prefixed with `REVIEWED=1`,
so the review is the road to every PR. The same prefix is the opt-out for
docs-only changes, trivial fixes and dependency bumps — named in the PR body.

## The project profile

The skill is generic; each repository supplies its specifics in a checked-in
`.claude/pre-pr-review.md`: which paths are production code, the targeted test
command and its traps, where specs and rules live, how to bring the
app up for E2E, project-shaped hints for the reviewers, final checks, PR
conventions. Start from [`profile-template.md`](skills/pre-pr-review/profile-template.md).

### Extension points

A project attaches its own steps at four named points — `after-setup`,
`before-pr`, `pr-body`, `after-pr` — each with a path trigger, a
gate, and what an unattended run does with it (`run`, `draft`: open the PR as a
draft naming the step, or `skip`). A migration round-trip goes at `after-setup`; a
slow check against production data at `before-pr`, with `Unattended: draft`.

Without a profile, the skill infers what it can from the repo, says what it
guessed, and offers to write the profile.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install pre-pr-review@redsteep
```

Pairs with [review-mode](../review-mode), which turns on when the PR opens.

## Evaluating the test reviewer

`evals/test_reviewer.py` is this reviewer's adapter for the shared eval runner
(`tools/agent-eval/run.py` at the repo root; format in `docs/reviewer-evals.md`). It runs
the `pre-pr-review:test-reviewer` agent from this checkout with the message
`scripts/reviewer-inputs.py` generates — what a real dispatch delivers — so a change to the
reviewer or to a project's testing rules is checked against cases instead of guessed at. The cases belong to the project: each is a defect someone flagged in
a real review, pinned by tags on the project's origin, in an eval dir beside an `eval.yaml`
(the rules files and profile to bring up to date in each worktree, the files that count as
project instructions; the source/test layout comes from the profile's layout block).

```
python3 tools/agent-eval/run.py <project>/.claude/evals/test-reviewer \
    --arms full,rules-only --repeat 3
```
