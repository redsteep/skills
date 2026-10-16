# review-mode

While you read a PR, Claude stays interactive — it answers questions and runs
tests, queries, the app — but does **not** act on change requests. Each request
goes into a queue as one line; when you say you're done, Claude applies the whole
queue in one iteration.

Why: fixing comments one by one while you're still reading means the diff under
your eyes keeps moving, and every fix restarts the review. Batching keeps the
review stable and the fixes coherent.

## How it works

Claude Code has no notion of a "mode", so this is a state file plus hooks:

| Piece | Event | What it does |
|---|---|---|
| `enter-review-after-pr.sh` | `PostToolUse` (Bash) | A non-draft `gh pr create` that printed a PR URL turns the mode on for that worktree |
| `deny-edits-in-review.sh` | `PreToolUse` (Edit/Write/NotebookEdit) | Denies edits to files whose own worktree (resolved through git, not by path prefix) is under review; other worktrees — including ones nested inside the main checkout — are untouched |
| `review-drift-check.sh` | `Stop` | Compares each reviewed worktree's `git status` against the snapshot taken on entry, so an edit made through Bash is caught too |
| `/review-mode` | command | `on [worktree]`, `done [-b branch]`, `status` |

State lives in the repo's git common dir, one directory per reviewed branch
(`.git/review-mode/<branch>/marker.json` + `queue.md`; `/` in a branch name
becomes `__`): never committed, no `.gitignore` entry needed, visible from every
worktree. Several reviews can be on at once — one per worktree — without
replacing each other or mixing their queues. `add` and `done` act on the review
of the current worktree, else the only one that is on; with several on, pass
`-b <branch>`. The default branch is never put under review.

Claude Code guards `.git/` against its edit tools, so requests are queued through
`review-mode.sh add "…"` — allowlist `Bash(*/review-mode/scripts/review-mode.sh:*)`
to skip the prompt.

A marker whose worktree no longer exists is ignored, so a forgotten mode never
blocks edits forever.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install review-mode@redsteep
```

Requires `bash`, `git`, `jq`, and `gh` for the automatic trigger.

## Use

- Open a PR with `gh pr create` — review mode turns on by itself.
- For a PR opened earlier: `/review-mode on` (or `/review-mode on <worktree>`).
- Ask anything; ask for changes — they queue.
- `/review-mode done` — Claude prints the queue and applies it.
- Then, with `pre-pr-review@redsteep` enabled, Claude runs another review round
  over the branch, updates the PR and turns review mode back on — every
  iteration of fixes is reviewed before you read it again.
