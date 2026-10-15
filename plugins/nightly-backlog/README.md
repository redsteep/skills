# nightly-backlog

An unattended night run for the tech-debt backlog. Each night Claude takes **at
most one** item a human allowed to a **draft** PR, and proposes night markings for
up to 10 unmarked items — in a report only; a human applies them.

An item qualifies only if it goes from description to PR without a single
architectural decision: no new mechanism, no options to choose between, no API
contract change, no schema migration, nothing visible in the UI, and a concrete
place to start. Zero PRs with an honest reason is a normal night. While the last
night's PR is still open, nothing new is taken.

## Safety

Three layers, so nothing rests on the model's judgement alone:

1. **Runner deny list** (`--disallowedTools`): no push to `main`/`master`, no
   force-push, no merge, no issue edits / labels / comments, no `gh workflow` or
   `gh secret`, no cloud CLIs (`aws`, `gcloud`, `az`, `kubectl`, `terraform`), no
   `ssh` — plus the project's own rules from its profile.
2. **The command's prohibitions** — production, messaging tools, other people's
   worktrees, full test suites, and backlog items beyond the PR's own change.
3. **The project's hooks** and the permission mode (default `auto`).

Wall-clock and spend caps: `NIGHTLY_TIMEOUT` (default `3h`), `NIGHTLY_BUDGET_USD`
(default `40`). One run at a time (`flock`).

## The project profile

`.claude/nightly-backlog.md`, checked in — start from
[`profile-template.md`](profile-template.md). Every section is optional.

| Section | Read by | What it changes |
|---|---|---|
| Backlog | command | where items live: how to list allowed and unmarked ones, what a marking looks like, the id, how the PR links the item and what the branch does to it. Default: GitHub issues labelled `nightly:ok` / `nightly:no` |
| Off limits, Not a night item | command | extra prohibitions, extra drop criteria |
| Worktree, Tests | command | how to create/remove a worktree, how to run targeted tests |
| Report | command | the report's language |
| Before | runner | a bash block run before the session — housekeeping such as sweeping orphaned worktrees |
| Deny | runner | extra `--disallowedTools` rules |
| Notify | runner | a bash block run after the session, with the report on stdin, when the night's status matches `When` (default: failure, questions, stuck) |

The report's first line ends with the night's status — `pr`, `questions`,
`stuck` or `quiet` — a fixed token whatever the report's language; a run that died
counts as `failure`. Notifying is the runner's job: the agent holds no messaging
tools, so a project wires mail, chat or a webhook in **Notify**.

The night run uses the `pre-pr-review` skill when it is available, and opens the PR
with `REVIEWED=1`; that skill's extensions follow their `Unattended` setting.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install nightly-backlog@redsteep
```

Enable it in the repo's `.claude/settings.json` — the headless run resolves
`/nightly-backlog` from the project's settings.

## Schedule it (systemd user timer)

Point the timer at the runner in the marketplace clone — a stable path that
`/plugin marketplace update redsteep` keeps current (the plugin cache path carries
the version and changes on every update):

```ini
# ~/.config/systemd/user/nightly-backlog.service
[Service]
Type=oneshot
# Login-shell PATH: claude, gh and the project's toolchain.
ExecStart=/bin/bash -lc '~/.claude/plugins/marketplaces/redsteep/plugins/nightly-backlog/scripts/nightly-backlog.sh ~/Projects/<repo>'
Nice=10

# ~/.config/systemd/user/nightly-backlog.timer
[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
```

`systemctl --user enable --now nightly-backlog.timer`. Logs and the report land in
`.git/nightly/` (override with `NIGHTLY_DIR`).

A dry run by hand: `nightly-backlog.sh <repo> <item>`.
