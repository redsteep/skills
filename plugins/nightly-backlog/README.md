# nightly-backlog

An unattended night run for the tech-debt backlog. Each night Claude takes **at
most one** open GitHub issue labelled `nightly:ok` to a **draft** PR, and proposes
`nightly:ok?` / `nightly:no` labels for up to 10 unlabelled issues — in a report
only; a human applies labels.

An issue qualifies only if it goes from description to PR without a single
architectural decision: no new mechanism, no options to choose between, no API
contract change, no schema migration, nothing visible in the UI, and a concrete
place to start. Zero PRs with an honest reason is a normal night.

## Safety

Three layers, so nothing rests on the model's judgement alone:

1. **Runner deny list** (`--disallowedTools`): no push to `main`/`master`, no
   force-push, no merge, no issue edits / labels / comments, no `gh workflow` or
   `gh secret`, no cloud CLIs (`aws`, `gcloud`, `az`, `kubectl`, `terraform`), no
   `ssh` — plus the project's own rules from its profile.
2. **The command's prohibitions** — production, messaging tools, other people's
   worktrees, full test suites.
3. **The project's hooks** and the permission mode (default `auto`).

Wall-clock and spend caps: `NIGHTLY_TIMEOUT` (default `3h`), `NIGHTLY_BUDGET_USD`
(default `40`). One run at a time (`flock`).

## The project profile

`.claude/nightly-backlog.md`, checked in: extra prohibitions, extra drop criteria,
how to create/remove a worktree, how to run tests, extra deny rules. Start from
[`profile-template.md`](profile-template.md).

The night run uses the `pre-pr-review` skill when it is available, and opens the PR
with `REVIEWED=1`.

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

A dry run by hand: `nightly-backlog.sh <repo> <issue>`.
