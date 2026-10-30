# factory

A software factory on your own box. You label a Trello card `ready`; the factory cuts it into
steps (one step = one PR), and for each step a background Claude worker writes the spec, waits
for your approval, builds, reviews, and hands off after you merge. At most **three factory PRs**
are in flight, and a card's next step starts only once the previous one is green on staging — so
your review stays the bottleneck by design.

You make the decisions only you can make, from the Claude app on your Mac or phone: each step's
spec, each PR's review and merge, "test it manually first?", and every message to the requester.
Whenever a step waits for you, its worker DMs you on Slack (👋 *Needs you*); when it does something
on its own you'd want to know — an auto-merge, an issue closed as already done or skipped for a
decision, an upkeep push, a flaky test recorded — it says so (✅ *Done*). Each DM names what the
worker works on and links the PR and the worker's conversation. When a slot is free and no card or
issue is waiting to fill it, the dispatcher DMs you once (📭 *Queue empty*, with how many slots are
still busy); queuing something there re-arms it.

Only the tiniest PRs skip your review: the worker may run the one merge command your profile
declares, and a hook lets it through only when the PR passes the gate in your profile — its
excluded paths and its `Precondition`, a command of yours that must exit 0 first. Start strict;
relax the gate by editing the profile.

**Cards that already have PRs.** The split worker turns each open PR linked on the card into a
step named `#<n> …`, and the factory adopts it instead of building it: no spec phase, the PR's own
branch — in the worktree it is already checked out in, if any, when that holds nothing unsaved;
with uncommitted or unpushed work there the step waits and you get a ping. A stack merges bottom-up with merge commits (the gate refuses to auto-merge a PR
another one is based on), and deleting a merged branch lets GitHub repoint the PR above. An adopted PR written by someone other than
you starts with an **architecture gate**: pre-pr-review's architecture reviewer alone, then the
worker waits for your OK before anything else runs.
A PR too big to read in one sitting is then **cut**: the worker carves the parts that stand
alone — a refactor, a migration — into new PRs off main, inserts them as `#<m>` items before the
adopted one, and builds the first; the adopted PR keeps the rest, its author and its discussion,
and comes last. Only a card's first unfinished step is ever started or replaced, so the adopted
PR waits behind its pieces.

**GitHub issues, too** (optional, profile `## Issues`). An open issue with the profile's label is
a job with no spec. Its first worker builds it as one PR — or, when the fix is more than one PR you
could read in one sitting, first writes a `## Factory steps` task list into the issue body (a
migration on its own, a type change before the cleanup it allows, cleanup by area) and the steps
then run one PR at a time, like a card's. Issues have their own pool, `WIP` (default one), apart
from the cards': a card's PR waits for your review, an issue's tries the auto-merge, and you
review it only when the gate hook refuses. A merged step frees the slot, so while the gate lets
PRs through the next step or issue follows; `Per day` caps how many issue steps start in any 24
hours. After each merge the profile's issue handoff checks the deploy; the worker ticks its step,
and after the last one closes the issue. The label says what kind of work an issue is, not that you
approved it: a worker that finds a design decision in one adds the profile's **Needs decision**
label, comments which decision it needs, and moves on, so a slot is never held waiting on you.
Removing that label is how you say the decision is made.

In the Claude app a worker shows by what it works on — `factory · <card> · 1/2`,
`factory · #<n> <issue title>` — while `factory-<card>-s<N>` stays its routing name.

## How it runs

```
systemd timer (2 min) → factory-dispatch (a script, no LLM): read GitHub, Trello, git, live workers
                         → start split / step / replacement workers   (claude --bg --remote-control)
                         → send status events to live workers         (cross-session messaging)
                         → clean up finished steps                    (the only cleanup owner)
worker (one per step)  → spec (subagent) → design-review → spec on the branch → ping → approval
                         → build (subagents) → pre-pr-review → triage → ping or auto-merge
                         → on merge: the project's handoff skill, step=n/total → item checked → done
```

The dispatcher keeps no state of its own beyond `~/.local/state/factory/`: which events and pings
were already delivered, and two locks. Everything else is re-derived each dispatch from the PRs,
the card's `Factory steps` checklist and the `feature/factory-*` branches — a reboot loses nothing.

**Slots belong to live workers.** A WIP slot is held by a step's live worker from its start until
the dispatcher stops it after the handoff — not by the step's state. So the slot a merged step
frees goes to the next step of the same card or issue, which has started first, rather than to
whatever else was waiting. A step that reads in progress with no worker (its worker died,
or a closed PR still sits on its branch) gets a replacement only through a free slot, ahead of
any new start; a merged step's replacement, there for the handoff, starts at once. Nothing is
preempted: a slot once given stays with whoever has it.

**Review mode follows you.** A worker opens its PR and pings you; review mode stays off while
you're away, so the worker keeps the PR healthy itself — rebases on a conflict, re-parents a
migration head, fixes red CI — and tells you what it changed. Your first message in its
conversation turns review mode on (a `UserPromptSubmit` hook): what you read stays put, and your
change requests queue for your go. After `Review idle` minutes (profile `## Settings`, default 15)
with nothing from you, the dispatcher turns it off again: your leaving counts as your go, so the
worker applies what you queued and does the upkeep it held, then pings what changed.

**CI on main after a merge.** The dispatcher also reads CI on each merged PR's merge commit (for
two days) and sends its worker `base-ci-failed` when it goes red — a red run skips the deploy the
handoff waits for. A test the worker finds **flaky**, there or on its own PR, gets one re-run of
the failed jobs and is recorded every time: an issue with the profile's `Flaky label`, or a
comment on the one already open for that test.

**Updates reach running workers.** A worker's instructions are its first message, so a factory
update would otherwise pass it by. The first dispatch after an update re-renders each live worker's
instructions for its step and sends it `instructions updated to <version> — read <file>`; a
worker started on the current version is skipped. Scripts already run the new code; hooks the
update added reach only workers started after it.

A worker is a normal Claude Code session: open it in the Claude app (Code → its name, or the link
in the Slack DM) and type. Events from the dispatcher start with `Factory event:`.

## Setup

1. **Profile** — copy `profile-template.md` to `<repo>/.claude/factory.md` and fill it in.
2. **Labels** — once per repo: `gh label create factory`, `gh label create factory:auto-merged`,
   `gh label create factory:arch-approved`; and a `ready` label on the Trello board.
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
   no cleanup (the dispatcher does). With `## Issues`, it also takes `issue=<n>`: the deploy check
   alone — no ping, no card, no message, no cleanup — reporting whether the change is live.
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
- **A worker with no process** (listed by `claude agents` but not running) counts as dead: its
  step gets a fresh worker, or its session is removed when the step is done. One seen alive in the
  last 10 minutes counts as restarting instead — never replaced, so a restart gets no twin.
- **Stop a card:** remove its `ready` label; idle workers of that card are cleaned up.

## Safety

1. **Runner deny list** — `<marketplace>/shared/runner-deny.txt`, shared with nightly-backlog:
   no push to main, no force-push, no `gh workflow` / `gh secret`, no cloud CLIs, no `ssh`; plus
   the profile's `## Deny`. Factory drops `gh pr merge` and `git push --force` from it, because:
2. **`auto-merge-gate` hook** — inside a worker, the only force-push is `--force-with-lease` to
   the worker's own factory branch (an adopted PR's branch is merged into, never rebased); the only merge is the profile's **Merge command**,
   alone on its line, on a `factory` PR with a `Triage:` paragraph, no PR stacked on it, no
   excluded path, and the profile's **Precondition** exiting 0; `gh api` merges, `--admin` and
   pushes to main are denied too.
3. **Merge on LGTM** (optional, profile `## Merge on LGTM`) — not auto-merge: your merge, run
   by the worker. The gate hook reads your `LGTM` from the worker's own transcript — a message you
   typed, never a peer's or the dispatcher's, newer than the PR's head commit, not followed by a
   hold, CI neither failed nor still running — and only then lets the merge past the excluded
   paths (and a stacked PR's `--merge`). A worker cannot approve on your behalf. Your word is a
   standing one: when the checks have not finished (the usual case, since the push of your queued
   changes restarted them), the worker waits and merges on `ci-passed` without asking again —
   GitHub cannot be relied on to hold a merge for CI, so the worker is where that waiting lives.
4. **The prompts** — a worker writes no code before your approval, posts nothing to anyone but you
   without your yes, and its judgement can only send a PR to review, never past it.
5. **Locks** — handoffs and migration round-trips run one worker at a time (`factory-lock`).

## Files

| Path | What |
|---|---|
| `scripts/factory_dispatch.py` | the dispatcher; all routing is `decide()`, a pure function |
| `scripts/auto_merge_gate.py` | the PreToolUse gate hook |
| `scripts/factory_ping.py` | `factory-ping` — Slack DM, once per reason per step; `--factory` for the dispatcher's own notices |
| `scripts/factory_lock.py` | `factory-lock acquire|release handoff|migration` |
| `scripts/remove-step-worktree.sh` | non-interactive cleanup of a finished step |
| `prompts/` | split, step and recovery worker prompts |
| `tests/` | `python3 -m unittest discover -s plugins/factory/tests` |
