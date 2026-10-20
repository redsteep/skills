---
description: Review mode — while the user reads a PR, answer questions and queue change requests instead of editing
argument-hint: "[on [worktree] | done | status]"
---

Review mode — the user reads a PR while you answer and collect, instead of editing.

`$ARGUMENTS` is `done` to leave the mode, `status` to check it, a worktree path
to enter it for that worktree, or empty to enter it for the only linked worktree
(the main checkout itself needs its path passed explicitly).

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/review-mode.sh" on [worktree]             # enter
"${CLAUDE_PLUGIN_ROOT}/scripts/review-mode.sh" add [-b branch] "<line>"  # queue a request
"${CLAUDE_PLUGIN_ROOT}/scripts/review-mode.sh" done [-b branch]          # leave, print the queue
"${CLAUDE_PLUGIN_ROOT}/scripts/review-mode.sh" status                    # every review that is on
```

Each reviewed branch has its own marker and queue, so other sessions' reviews in
other worktrees may be on at the same time. Without `-b`, `add` and `done` mean
the review of the current worktree, else the only one that is on; when several
are on, pass `-b <branch>` — the hooks' messages name the branch.

Entering is normally automatic — a `PostToolUse` hook turns the mode on the
moment a non-draft `gh pr create` succeeds. Use this command to enter it for a PR
opened earlier, to check the state, or to leave.

## While the mode is on

- **A question** — answer it immediately and in full. Runs are allowed and
  expected: tests, queries, the running app. This is the interactivity the mode
  exists to protect; "I'll check after we exit" is a failure of the mode, not a
  rule of it.
- **A request to change something** — do not do it. Queue it with `add`
  (the queue lives under `.git/`, so don't edit the file directly):
  `review-mode.sh add "<the user's wording> — path/file:line — <what you will do>"`
  Then confirm in one line. No implementation, no plan, no restating their words
  back at them.
- **Edits are denied by a hook** inside the reviewed worktree, and a `Stop` hook
  compares the tree against the snapshot taken on entry — so an edit made through
  Bash is reported even though the deny hook never saw it.
- Other worktrees are unaffected: a marker names one worktree, and a file is
  matched to its own worktree through git, so worktrees nested inside the main
  checkout are not caught by a review of the main checkout.

## Leaving

Only on the user's explicit go-ahead. Then `done`, read the queue, and apply the
whole list in one iteration — ordinary workflow, commits and all.

**Then offer eval cases for what the reviewers missed.** An item that a reviewer
should have caught — a test the test-strategy reviewer passed, a layering slip the
architecture reviewer passed, a design flaw design-review passed — is a known
answer the reviewer can be measured on. For each, offer a case for that reviewer's
eval set (`.claude/evals/<reviewer>/`, whose `eval.yaml` names the reviewer;
format in `redsteep/skills` `docs/reviewer-evals.md`): `before` is the commit `done`
printed, `after` the commit that applied the item, `origin` the user's wording
from the queue. List the candidates in one message; draft the case files and push
the tags only for the ones the user picks. A matter of taste, or an item no
reviewer is asked to check, gets no case. Skip when the project has no eval sets.

**Then review the branch again before handing it back.** A queue of fixes is new
code nobody has reviewed: when the `pre-pr-review` plugin is enabled, run its
skill over the whole branch (it updates the open PR instead of creating one),
then turn review mode back on with `on <worktree>` for the user's next pass.
Skip the round only when every queued item was docs or wording, and say so.

A marker whose worktree no longer exists is treated as stale and ignored, so a
forgotten mode does not block edits forever.
