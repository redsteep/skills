# pre-pr-review

A gated review of a finished feature branch, run by Claude before it opens the PR.
Every step ends on a gate that passes on output Claude saw, not on judgement.

| Step | Who | Gate |
|---|---|---|
| 0. Setup | main agent | targeted tests green on HEAD; extra gates (e.g. migrations) pass |
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
command and its traps, extra gates, where specs and rules live, how to bring the
app up for E2E, project-shaped hints for the reviewers, final checks, PR
conventions. Start from [`profile-template.md`](skills/pre-pr-review/profile-template.md).

Without a profile, the skill infers what it can from the repo, says what it
guessed, and offers to write the profile.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install pre-pr-review@redsteep
```

Pairs with [review-mode](../review-mode), which turns on when the PR opens.
