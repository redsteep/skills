# pre-pr-review

A gated review of a finished feature branch, run by Claude before it opens the PR.
Every step ends on a gate that passes on output Claude saw, not on judgement.

| Step | Who | Gate |
|---|---|---|
| 0. Setup | main agent | targeted tests green on HEAD |
| 1. Surface vs the spec's contract | subagent | no name in the diff the spec didn't declare — delete it or amend the contract out loud |
| 2. E2E in the browser | subagent | every flow works and matches the spec / visual reference |
| 3. Architecture | subagent | no Critical / Important violations of the project's code rules |
| 4. Test strategy | subagent | each contract tested once, at the right layer |
| 5. Manual mutation testing | subagent | every surviving mutant gets a test proven red on it and green without it |
| 6–7. Refactor tests, then code | main agent | targeted tests + the repo's lint/type-check green |
| 8. PR | main agent | `REVIEWED=1 gh pr create`, with a review summary in the body |

Steps 2–4 run in parallel. Surface goes first so nothing reviews or tests code that is about to be deleted.

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

A project attaches its own steps at five named points — `after-setup`,
`after-surface`, `before-pr`, `pr-body`, `after-pr` — each with a path trigger, a
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

## Evaluating the test-strategy reviewer

`evals/test_coverage.py` is this reviewer's adapter for the shared eval runner
(`tools/reviewer-eval/run.py` at the repo root; format in `docs/reviewer-evals.md`). It
fills `test-coverage-reviewer.md` the way step 4 does — the whole branch as step 0 builds
it — so a change to the reviewer or to a project's testing rules is checked against cases
instead of guessed at. The cases belong to the project: each is a defect someone flagged in
a real review, pinned by tags on the project's origin, in an eval dir beside an `eval.yaml`
(the profile's Layout under `inputs`, the rules files to bring up to date in each worktree,
the files that count as project instructions).

```
python3 tools/reviewer-eval/run.py <project>/.claude/evals/test-reviewer \
    --arms full,rules-only --repeat 3
```
