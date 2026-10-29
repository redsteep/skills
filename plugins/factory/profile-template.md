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
- **Flaky label:** `<label>` — optional: a test a worker finds flaky gets an issue with this label (or a comment on the open one)
- **Review idle:** `15` — minutes without a message from you in a worker's conversation before its review mode goes off

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

## Issues

Optional: GitHub issues as a second source of work — one step each, no spec phase, auto-merge
tried first. Leave the section out to take Trello cards only. Bare bullets are extra deny rules
for an issue's worker.

- **Label:** `<label>` — an open issue with it is taken. It says what kind of work the issue is,
  not that a human approved it for unattended work: a worker that finds a design decision in one
  hands it back with the label below
- **Needs decision:** `<label>` — an issue carrying it is not taken. A worker adds it, with a
  comment saying which decision is needed; the developer removes it once the decision is made.
  Leave the key out and a worker pings and waits instead, holding its slot until you answer
- **WIP:** `1` — issues in flight: **its own pool**, not carved out of `Settings` → **WIP**. A
  card's PR waits for your review, an issue's merges itself, so sharing one pool let cards waiting
  on review stall every issue behind them
- **Per day:** `3` — at most this many issues started in any 24 hours; leave it out for no cap
- **Handoff:** `<skill name>` — run after the merge with `issue=<n>`: the deploy check only (README)
- **Off limits:** <what an issue's worker must not touch, as you'd say it in a prompt>

## Deny

Extra `--disallowedTools` rules for workers, one backticked rule per bullet.

## Auto-merge

The gate the hook checks before it lets a worker merge. Every rule must hold. Relax it here as
trust grows.

- **Merge command:** `gh pr merge --auto --squash <number>` — the only merge a worker may run, and
  its flags are what the hook requires. A repository with auto-merge disabled declares a
  synchronous form instead: `gh pr merge --squash --match-head-commit <sha> <number>`.
- **Precondition:** `<command>` — optional. Run with `<number>` substituted, from the repo; the
  merge is denied unless it exits 0, and its last line of output is the reason the worker is given.
  This is "safe to merge right now" in the project's own terms — CI green, the base branch's
  deploy not mid-flight, whatever else only the project knows.

Excluded paths — a trailing `/` means anything under it, otherwise a glob:

- `migrations/`
- `.github/`
- `*.lock`

## Merge on LGTM

Optional. Not auto-merge: the developer's own merge, which the worker runs for them. With it
enabled, the developer's `LGTM` (or "merge") typed in a worker's conversation lets the worker
merge the PR under review — past the excluded paths above, and with a merge commit for a PR
another is stacked on. Only a message the developer typed after the PR's last commit counts; a
later "wait" or "don't merge" cancels it, and CI must not have failed. Leave it out to merge
every reviewed PR yourself.

- **Enabled:** yes
