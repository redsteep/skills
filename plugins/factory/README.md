# factory

A software factory on your own box. You label a Trello card `ready`; the factory cuts it into
steps (one step = one PR), and for each step a background Claude worker writes the spec, waits
for your approval, builds, reviews, and hands off after you merge. At most **three factory PRs**
are in flight, and a card's next step starts only once the previous one is green on staging — so
your review stays the bottleneck by design.

You make the decisions only you can make, from the Claude app on your Mac or phone: each step's
spec, each PR's review and merge, "test it manually first?", and every message to the requester.
Whenever a step waits for you, its worker DMs you on Slack with a link to its conversation.

Only the tiniest PRs skip your review: the worker may run `gh pr merge --auto --squash`, and a
hook lets it through only when the diff passes the gate in your profile. Start strict; relax the
gate by editing the profile.

**Cards that already have PRs.** The split worker turns each open PR linked on the card into a
step named `#<n> …`, and the factory adopts it instead of building it: no spec phase, the PR's own
branch, stacked PRs retargeted onto `main` in turn. An adopted PR written by someone other than
you starts with an **architecture gate**: pre-pr-review's architecture reviewer alone, then the
worker waits for your OK before anything else runs.

## How it runs

```
systemd timer (2 min) → factory-dispatch (a script, no LLM): read GitHub, Trello, git, live workers
                         → start split / step / replacement workers   (claude --bg --remote-control)
                         → send status events to live workers         (cross-session messaging)
                         → clean up finished steps                    (the only cleanup owner)
worker (one per step)  → spec (subagent) → design-review → draft PR → ping → your approval
                         → build (subagents) → pre-pr-review → triage → ping or auto-merge
                         → on merge: the project's handoff skill, step=n/total → item checked → done
```

The dispatcher keeps no state of its own beyond `~/.local/state/factory/`: which events and pings
were already delivered, and two locks. Everything else is re-derived each dispatch from the PRs,
the card's `Factory steps` checklist and the `feature/factory-*` branches — a reboot loses nothing.

A worker is a normal Claude Code session: open it in the Claude app (Code → its name, or the link
in the Slack DM) and type. Events from the dispatcher start with `Factory event:`.

## Setup

1. **Profile** — copy `profile-template.md` to `<repo>/.claude/factory.md` and fill it in.
2. **Labels** — once per repo: `gh label create factory`, `gh label create factory:spec-approved`,
   `gh label create factory:auto-merged`, `gh label create factory:arch-approved`; and a `ready` label on the Trello board.
3. **Secrets** — `TRELLO_API_KEY`, `TRELLO_TOKEN` and, optionally, `FACTORY_SLACK_TOKEN` (a **bot**
   token with `chat:write` and `im:write`; a DM from your own user would not notify you), from the
   environment, `~/.config/factory/env` (`chmod 600`), or the repo's `.env` — only these keys are
   read from it. Without a Slack token there are no DMs: waiting workers show in the Claude app.
4. **Plugin** — enable `factory@redsteep` in the repo's `.claude/settings.json` and run
   `claude plugin install factory@redsteep --scope project` (headless and background sessions
   only load plugins installed that way).
5. **Requirements** — Claude Code ≥ 2.1.224 (cross-session messaging), logged in with claude.ai
   (Remote Control does not work with an API key), `gh` authenticated, and whatever your
   worktree script needs. That script must accept `--base <ref> <name>` and check out an existing
   branch ref. The redsteep plugins `pre-pr-review`, `design-review` and `review-mode`.
   A **handoff skill** in the project, run after each merge with `step=<n>/<total>`: it checks the
   deploy, asks "test manually first?" by ping, links the PR on the card and checks item `<n>`; on
   the last step it drafts the card move and requester message and posts them on a yes; it does
   no cleanup (the dispatcher does).
6. **Dry run** — `scripts/factory-dispatch <repo> --dry-run` prints what one dispatch would do.
   Then walk one small card through by hand before the timer: run `factory-dispatch <repo>`
   yourself after each of your actions.
7. **Timer** — copy `systemd/factory-dispatch.{service,timer}` to `~/.config/systemd/user/`, set
   `REPO_PATH` and `PATH` in the service, `systemctl --user daemon-reload`,
   `systemctl --user enable --now factory-dispatch.timer`. Needs `loginctl enable-linger`.

## Operating it

- **Pause:** `touch ~/.local/state/factory/PAUSED` — dispatches stop; workers keep their state.
  `rm` it to resume.
- **Logs:** `journalctl --user -u factory-dispatch` (each dispatch prints what it did).
- **Workers:** `claude agents` lists them; `claude attach <id>` opens one in a terminal.
- **Stop a card:** remove its `ready` label; idle workers of that card are cleaned up.

## Safety

1. **Runner deny list** — `<marketplace>/shared/runner-deny.txt`, shared with nightly-backlog:
   no push to main, no force-push, no `gh workflow` / `gh secret`, no cloud CLIs, no `ssh`; plus
   the profile's `## Deny`. Factory drops only `gh pr merge` from it, because:
2. **`auto-merge-gate` hook** — inside a worker, the only merge is `gh pr merge --auto --squash
   <n>`, alone on its line, on a `factory` PR with a `Triage:` paragraph whose diff passes the
   profile's `## Auto-merge`; `gh api` merges and pushes to main are denied too.
3. **The prompts** — a worker writes no code before your approval, posts nothing to anyone but you
   without your yes, and its judgement can only send a PR to review, never past it.
4. **Locks** — handoffs and migration round-trips run one worker at a time (`factory-lock`).

## Files

| Path | What |
|---|---|
| `scripts/factory_dispatch.py` | the dispatcher; all routing is `decide()`, a pure function |
| `scripts/auto_merge_gate.py` | the PreToolUse gate hook |
| `scripts/factory_ping.py` | `factory-ping` — Slack DM, once per reason per step |
| `scripts/factory_lock.py` | `factory-lock acquire|release handoff|migration` |
| `scripts/remove-step-worktree.sh` | non-interactive cleanup of a finished step |
| `prompts/` | split, step and recovery worker prompts |
| `tests/` | `python3 -m unittest discover -s plugins/factory/tests` |
