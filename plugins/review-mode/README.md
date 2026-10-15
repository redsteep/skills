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
| `deny-edits-in-review.sh` | `PreToolUse` (Edit/Write/NotebookEdit) | Denies edits to files inside the reviewed worktree; other worktrees are untouched |
| `review-drift-check.sh` | `Stop` | Compares `git status` against the snapshot taken on entry, so an edit made through Bash is caught too |
| `/review-mode` | command | `on [worktree]`, `done`, `status` |

State lives in the repo's git common dir (`.git/review-mode/`): never committed,
no `.gitignore` entry needed, shared by all worktrees of the repo. Claude Code
guards `.git/` against its edit tools, so requests are queued through
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
