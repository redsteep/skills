# pr-when-done

A finished feature should end up in a PR, not sit on a branch waiting to be asked
about. A `Stop` hook looks at the worktrees **this session** worked in, and when one
is

- clean (`git status --porcelain` empty — untracked new files count as unfinished),
- ahead of the default branch by at least one commit,
- without any PR, open or merged (`gh pr list --head`),

it blocks the stop once with: review it (with the `pre-pr-review` skill, if
available) and open the PR — or say in one line what is left and carry on.

Quiet by design:

- at most **one nudge per commit** (a stamp per branch + HEAD, in `.git/pr-nudge/`);
- never re-enters itself (`stop_hook_active`);
- other sessions' worktrees are ignored — only worktrees named in this session's
  own tool calls count;
- any `gh` failure (offline, no auth) means silence, never a false nudge.

The default branch is `origin/HEAD` (falls back to `origin/main`).

## Install

```
/plugin marketplace add redsteep/skills
/plugin install pr-when-done@redsteep
```

Requires `git`, `jq`, `gh`.
