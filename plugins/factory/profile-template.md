# Factory profile — <project>

Read by the `factory@redsteep` plugin: the dispatcher, the auto-merge gate hook and `factory-ping`.
Section and key names are read by code — keep them. Values in backticks.

## Trello

- **Board:** `<board id>`
- **Doing:** `<list id>` — a card moves here when its split starts
- **Testing:** `<list id>` — the last step's handoff proposes moving the card here
- **Ready label:** `ready`
- **Checklist:** `Factory steps`

## GitHub

- **Label:** `factory`

## Settings

- **WIP:** `3`
- **Slack user:** `<your Slack member id>` — factory-ping DMs this user
- **Developer GitHub:** `<your GitHub login>` — an adopted PR by anyone else starts with the architecture gate
- **Requester:** `<name>` `<Slack member id>` — who hears that a card is done
- **Requester channel:** `<#channel>` `<channel id>`
- **Permission mode:** `auto`

## Repo

- **Base:** `main`
- **Rules:** `CLAUDE.md` — what the workers must follow, as you'd say it in a prompt
- **Spec template:** `<path>` — a step's spec is written from it
- **Specs:** `<dir>` — where specs go
- **Handoff skill:** `<skill name>` — run after each merge with `step=<n>/<total>` (README)

## Worktree

- **Create:** `<script>` — `--base <ref> <name>` makes a new branch; a branch ref containing a
  slash is checked out. The worktree lands in **Dir** under the name after the last slash.
- **Dir:** `.worktrees`

## Cleanup

Optional. A bash block the dispatcher runs before it removes a finished step's worktree, with
`$WT` set — per-worktree caches the project needs deleted.

```bash
```

## Deny

Extra `--disallowedTools` rules for workers, one backticked rule per bullet.

## Auto-merge

The gate the hook checks. Every rule must hold. Relax it here as trust grows.

- **Max changed lines:** `30`
- **Max files:** `3`

Excluded paths — a trailing `/` means anything under it, otherwise a glob:

- `migrations/`
- `.github/`
- `*.lock`
