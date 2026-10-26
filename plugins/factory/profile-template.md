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
- **Requester:** `<name>` `<Slack member id>` — who hears that a card is done
- **Requester channel:** `<#channel>` `<channel id>`
- **Permission mode:** `auto`

## Worktree

- **Create:** `scripts/create-worktree.sh` — must accept `--base <ref>` and, for an existing
  branch ref containing a slash, check it out

## Deny

Extra `--disallowedTools` rules for workers, one backticked rule per bullet.

## Auto-merge

The gate the hook checks. Every rule must hold. Relax it here as trust grows.

- **Max changed lines:** `30`
- **Max files:** `3`

Excluded paths — a trailing `/` means anything under it, otherwise a glob:

- `migrations/`
- `.github/`
