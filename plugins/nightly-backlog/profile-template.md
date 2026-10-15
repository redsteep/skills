# Nightly backlog profile

<!--
Project profile for the nightly-backlog plugin. Save as `.claude/nightly-backlog.md`
and check it in. Every section is optional; keep the section names — the command
and the runner refer to them.
-->

## Off limits

- <extra prohibitions: production systems, expensive services, data that must not be woken or touched>

## Not a night issue

- <extra reasons to drop a `nightly:ok` issue, e.g. "touches the billing module">

## Worktree

- **Create:** <command, e.g. `make worktree NAME=nightly-<N>-<slug>` — installs deps, assigns ports>
- **Remove:** <command — and why it matters, e.g. orphaned virtualenvs fill the disk>

## Tests

- <how to run targeted tests per package; switches for tests skipped by default>

## Deny

Tool rules added to the runner's `--disallowedTools`, one backticked rule per bullet:

- `Bash(<command>:*)`
- `mcp__<server>`
