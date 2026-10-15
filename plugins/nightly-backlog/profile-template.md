# Nightly backlog profile

<!--
Project profile for the nightly-backlog plugin. Save as `.claude/nightly-backlog.md`
and check it in. Every section is optional — a missing one keeps the generic
behaviour. Keep the section names: the command and the runner read them.
-->

## Backlog

<!-- Where the tech-debt items live. Omit the section for GitHub issues with
     `nightly:ok` / `nightly:no` labels. Each line: a command, or a sentence
     precise enough to act on. -->

- **Allowed:** <how to list the items a human allowed at night>
- **Unmarked:** <how to list the items with no night marking yet>
- **Marking:** <what "allowed" / "not at night" look like, e.g. a label, a line in the file>
- **Age:** <what "oldest" means, e.g. the date in the file name>
- **Id:** <how an item is named in branches, worktrees and PR bodies>
- **Link:** <how the PR refers to the item>
- **Done:** <what the branch does to the item, e.g. deletes its file — or "nothing">

## Off limits

- <extra prohibitions: production systems, expensive services, data that must not be woken or touched>

## Not a night item

- <extra reasons to drop an allowed item, e.g. "touches the billing module">

## Worktree

- **Create:** <command, e.g. `make worktree NAME=nightly-<id>-<slug>` — installs deps, assigns ports>
- **Remove:** <command — and why it matters, e.g. orphaned virtualenvs fill the disk>

## Tests

- <how to run targeted tests per package; switches for tests skipped by default>

## Report

- **Language:** <e.g. Russian — default English; the status token on the first line stays as is>

## Before

<!-- Run by the runner before the session, from the repo root; its output is handed to the agent. -->

```bash
<e.g. ./scripts/sweep-worktrees.sh>
```

## Deny

Tool rules added to the runner's `--disallowedTools`, one backticked rule per bullet:

- `Bash(<command>:*)`
- `mcp__<server>`

## Notify

<!-- Run by the runner after the session, outside it: the report on stdin;
     NIGHTLY_SUBJECT, NIGHTLY_STATUS (failure|questions|stuck|pr|quiet),
     NIGHTLY_RC, NIGHTLY_REPORT, NIGHTLY_LOGS in env. -->

- **When:** failure, questions, stuck

```bash
<e.g. mail -s "$NIGHTLY_SUBJECT" me@example.com
      or: curl -fsS -d @- "$SLACK_WEBHOOK_URL">
```
