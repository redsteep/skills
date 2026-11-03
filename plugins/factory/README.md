# factory

A software factory on your own box. You label a Trello card `ready`; the factory analyses it,
and once you approve the analysis cuts it into steps (one step = one PR), and for each step a background Claude worker writes the spec, waits
for your approval, builds, reviews, and hands off after you merge. At most **three factory PRs**
are in flight, and a card's next step starts only once the previous one is green on staging — so
your review stays the bottleneck by design.

You make the decisions only you can make, from the Claude app on your Mac or phone: each card's
brief, each step's spec, each PR's review and merge, "test it manually first?", and every message to the requester.
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

**Every card but a trivial one is analysed before it is split.** A card says what hurts, guesses why, and proposes
a fix; a split cut straight from it freezes the guess into its step lines, and every spec and
review after that checks against the line, not the problem. So the split worker first has a
subagent analyse the card — from the card alone, handed no guess — and write a **brief** to
`~/.local/state/factory/briefs/<card>.md`: the symptom measured across every source, prior art
(code, scripts, stored prompts, history), every reader and writer of what changes, at least two
approaches, what each makes irreversible, and adjacent problems — then findings, decisions for
you, and a proposed split. You settle it in the split worker's conversation and approve it
("approved, split it"); only then are the steps cut, and each step's spec reads the brief. The brief's measurements
come with the queries that took them, so a spec template that asks how a change is verified
gets its "before" from them. A **trivial** card — presentation only (a copy text, a label, a
style), one PR — skips both: the split worker cuts it as one `[trivial] ` item without an
analysis, and that step starts at the build, with no spec; the PR review is the only gate. Say
"approved, split it, attach" and the approved brief also goes on the card as `card-brief.md`
(`factory-attach`, with the factory's own Trello key from `.env`) — for the requester to read,
so a bare approval keeps it local. The
analysis prompt is `prompts/analysis.md`; where it may look (a read-only DB script, places the
product keeps prompts) is the profile's `## Analysis` → `Sources`.

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
split worker (per card) → analysis (subagent, from the card alone) → brief → ping → approval
                         → steps on the card's `Factory steps` checklist (one step: no checklist)
worker (one per step)  → spec (subagent) → design-review → spec on the branch → ping → approval
                         → build (subagents) → pre-pr-review → triage → ping or auto-merge
                         → on merge: the project's handoff skill, step=n/total → item checked → done
```

The dispatcher keeps no state of its own beyond `~/.local/state/factory/`: which events and pings
were already delivered, two locks, the cards' briefs, and the step of a card cut into just one —
`steps/<card>.md`, a single `- [ ]` line, because a one-item checklist on the card tells its reader
nothing. Everything else is re-derived each dispatch from the PRs, the card's `Factory steps`
checklist and the `feature/factory-*` branches — a reboot loses nothing.

**Branch names read as the card, not as its id.** A step's branch is
`feature/factory-<card name>-s<n>-<card short id>` — the readable part first, the short id in the
tail — and its worktree is named after the branch, so `.worktrees/` reads as the work. Only the
tail is load-bearing: a card gets renamed and an issue's title edited, so the dispatcher finds a
step's branch by `-s<n>-<short>`, which no rename touches, and keeps whatever branch already
exists over the name it would cut today. A Russian card name is transliterated, not dropped. A
branch cut before this version (`feature/factory-<short>-s<n>`) keeps resolving — both shapes are
the step's own. The **worker's session name** stays `factory-<short>-s<n>`: it is the routing key
every event, slot and cleanup resolves by, so it carries no name that can change.

**Slots belong to live workers.** A WIP slot is held by a step's live worker from its start until
the dispatcher stops it after the handoff — not by the step's state. So the slot a merged step
frees goes to the next step of the same card or issue, which has started first, rather than to
whatever else was waiting. A step that reads in progress with no worker (its worker died,
or a closed PR still sits on its branch) gets a replacement only through a free slot, ahead of
any new start; a merged step's replacement, there for the handoff, starts at once. Nothing is
preempted: a slot once given stays with whoever has it.

**A retired worker is resumed, not replaced.** A worker waiting for you sits at an idle prompt,
and that is what the background daemon reclaims when the machine runs short of memory — on the
box this was built for, 23 of 29 of its retirements, one after three minutes of silence. Its
conversation holds what the world does not: the question it asked, your answer, and the `LGTM`
the merge gate reads from that transcript and nowhere else. So when the daemon's log says it
*retired* the session, the dispatcher continues it (`claude --bg --resume`, which keeps the id,
the name and the context) and nudges it with `prompts/resumed.md` instead of re-reading the card
from scratch. A session the daemon reports as **crashed** — its worktree removed under it — is
replaced the old way: nobody knows what state it stopped in, and the worktree has to be rebuilt
anyway. The world stays the source of truth either way; resuming only saves what was never
written into it.

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

**Postponing a card.** A card with the **hold label** (`on hold` by default) is set aside, not
stopped. Nothing of it starts — no split, no step, no replacement — it hears no events, and
nothing of it is cleaned up: its branches, the spec on them, its brief and every worker's
conversation stay. Its idle workers are **shelved**: stopped without being removed (the
dispatcher records each session in `~/.local/state/factory/shelved.json`), so their WIP slot goes
to the next card; their open PRs turn to drafts. A worker busy when the label comes is told
(`on-hold`) to reach a safe point, push and end its turn, and is shelved once idle. The hold
wins over a missing `ready` label, so taking `ready` off a held card destroys nothing. Take the
label off and the card's step queues for a slot like any step under way; when it gets one, the
shelved conversation is **resumed** (`claude --bg --resume`) with `prompts/unshelved.md`: it
re-reads the card and the PR, catches its branch up with the base, re-asks an open question once,
and its drafts are marked ready. A session that is gone by then is replaced the usual way, from
the branch. A worker told "put it on hold" by the developer runs `factory-hold` itself
(`--off` takes the card off hold); issues have no hold — take their label off instead.

A worker is a normal Claude Code session: open it in the Claude app (Code → its name, the link
in the Slack DM, or **Open** on the status page, which opens it in the Claude desktop app through
`claude://` — *web* next to it is the same session in a browser) and type. Events from the dispatcher start with `Factory event:`.

## Setup

1. **Profile** — copy `profile-template.md` to `<repo>/.claude/factory.md` and fill it in.
2. **Labels** — once per repo: `gh label create factory`, `gh label create factory:auto-merged`,
   `gh label create factory:arch-approved`; and a `ready` label on the Trello board.
3. **Secrets** — `TRELLO_API_KEY`, `TRELLO_TOKEN` and, optionally, `FACTORY_SLACK_TOKEN` (a **bot**
   token with `chat:write` and `im:write`; a DM from your own user would not notify you), from the
   environment, `~/.config/factory/env` (`chmod 600`), or the repo's `.env` — only these keys are
   read from it.
4. **A channel for the pings** — Slack as above, or your own: `Settings` → **Ping command** in the
   profile is any command, handed the message on stdin (see the profile template for the
   environment it gets). A project with its own bot declares that instead of giving the factory a
   Slack token. With neither, a waiting worker shows only in the Claude app — which notifies
   nobody, and a question nobody sees stops the card it belongs to.
5. **Plugin** — enable `factory@redsteep` in the repo's `.claude/settings.json` and run
   `claude plugin install factory@redsteep --scope project` (headless and background sessions
   only load plugins installed that way).
6. **Requirements** — Claude Code ≥ 2.1.224 (cross-session messaging), logged in with claude.ai
   (Remote Control does not work with an API key), `gh` authenticated, and whatever your
   worktree script needs. That script must accept `--base <ref> <name>` and check out an existing
   branch ref. The redsteep plugins `pre-pr-review`, `design-review` and `review-mode`.
   A **handoff skill** in the project, run after each merge with `step=<n>/<total>`: it checks the
   deploy, asks "test manually first?" by ping, links the PR on the card and checks item `<n>`; on
   the last step it drafts the card move and requester message and posts them on a yes; it does
   no cleanup (the dispatcher does). With `## Issues`, it also takes `issue=<n>`: the deploy check
   alone — no ping, no card, no message, no cleanup — reporting whether the change is live.
7. **Dry run** — `scripts/factory-dispatch <repo> --dry-run` prints what one dispatch would do.
   Then walk one small card through by hand before the timer: run `factory-dispatch <repo>`
   yourself after each of your actions.
8. **Timer** — copy `systemd/factory-dispatch.{service,timer}` to `~/.config/systemd/user/`, set
   `REPO_PATH` and `PATH` in the service, `systemctl --user daemon-reload`,
   `systemctl --user enable --now factory-dispatch.timer`. Needs `loginctl enable-linger`.
9. **Status page on your Mac and phone** (optional) — each dispatch writes the page, its
   `status.json`, a web app manifest and icons into `~/.local/state/factory/www/`, a folder of
   their own. Tailscale serves the folder itself, so there is no web server to run:
   `tailscale serve --bg ~/.local/state/factory/www` (it stays up across reboots; it needs a
   Tailscale that serves a path, not only a port — else `systemd/factory-page.service` serves
   the folder on `127.0.0.1:8765` for `tailscale serve --bg 8765`). The page has no login of its
   own: the tailnet is what keeps it private. Then:
   - **profile** `Settings` → **Status page**: the `https://<box>.<tailnet>.ts.net` it printed —
     every ping links it;
   - **Mac**: open that URL in the browser and bookmark it;
   - **phone**: open it, *Share → Add to Home Screen*; it opens full screen, as an app.

## Operating it

- **Pause:** `touch ~/.local/state/factory/PAUSED` — dispatches stop; workers keep their state.
  `rm` it to resume.
- **Status page:** `~/.local/state/factory/www/index.html`, rewritten by every dispatch (setup step
  9 serves it to your Mac and phone). The slots, then what waits for you — one card per decision,
  named by what it is (*Approve brief*, *Approve spec*, *Review PR #n*, *After merge*, *Answer*;
  *No worker* and *Dispatch failed* first), each with one **Open in Claude** button — then what
  is under way, without what already waits for you; queued and held steps and what the dispatch did
  are folded away. The snapshot's `attention[].kind` carries that name. It reloads every minute, reads **stale**
  once nothing has rewritten it for ten minutes, and **paused** while you have paused the factory.
- **Logs:** `journalctl --user -u factory-dispatch` (each dispatch prints what it did).
- **Status:** `scripts/factory-status` — what the last dispatch saw: slots busy per pool, what
  waits for you (with the worker's conversation link), every step under way and what it is doing
  (`working`, `waits-you`, `waits-ci`, `waking`, `queued`, `no-worker`, `on-hold`…), a card still to split
  by its brief (`analysing`, `brief` — before you, `approved` — being cut), and what the dispatch
  did. Each dispatch writes it to `~/.local/state/factory/status.json` after acting, from the same
  reading of the world it routed by; `--json` prints that file (plus `paused`, `age_seconds`),
  `--live <repo>` looks now without acting, `--html` prints the status page. A dashboard reads the
  JSON — it needs no rules of its own. "Waits for you" is read from an idle worker on an
  unfinished step whose PR is not waiting on CI and that hears no event this dispatch.
- **Workers:** `claude agents` lists them; `claude attach <id>` opens one in a terminal.
- **A worker with no process** (listed by `claude agents` but not running) counts as dead: its
  step gets a fresh worker, or its session is removed when the step is done. One seen alive in the
  last 10 minutes counts as restarting instead — never replaced, so a restart gets no twin.
- **Postpone a card:** add the `on hold` label (profile `Trello` → `Hold label`), or tell its
  worker "put it on hold" — it runs `factory-hold`. See *Postponing a card* below.
- **Stop a card:** remove its `ready` label; idle workers of that card are cleaned up — their
  sessions **and** their step branches, a committed spec included. To set a card aside for later,
  put it on hold instead.

## Safety

1. **Runner deny list** — `<marketplace>/shared/runner-deny.txt`, shared with nightly-backlog:
   no push to main, no force-push, no `gh workflow` / `gh secret`, no cloud CLIs, no `ssh`; plus
   the profile's `## Deny`. Factory drops `gh pr merge` and `git push --force` from it, because:
2. **`auto-merge-gate` hook** — inside a worker, the only force-push is `--force-with-lease` to
   the worker's own factory branch (an adopted PR's branch is merged into, never rebased); the only merge is the profile's **Merge command**,
   alone on its line, on a `factory` PR with a `Triage:` paragraph, a `Reviewed at` line naming the
   head commit (a push after pre-pr-review means re-running it), no PR stacked on it, no excluded path, and the profile's **Precondition** exiting 0; `gh api` merges, `--admin` and
   pushes to main are denied too.
3. **Merge on LGTM** (optional, profile `## Merge on LGTM`) — not auto-merge: your merge, run
   by the worker. The gate hook reads your `LGTM` from the worker's own transcript — a message you
   typed, never a peer's or the dispatcher's, newer than the PR's head commit, not followed by a
   hold — and lets the merge past the excluded paths (and a stacked PR's `--merge`), telling the
   `Precondition` through `FACTORY_LGTM=1` so a ban kept there alone is waived as well. Your word
   is read on every merge, not only on one the hook itself objected to: a project whose guarded
   paths live in the `Precondition` gives the hook nothing to object to, and an LGTM that is
   never read is an LGTM that does nothing. A worker cannot approve on your behalf. Your word is a
   standing one: when the checks have not finished (the usual case, since the push of your queued
   changes restarted them), the worker waits and merges on `ci-passed` without asking again —
   GitHub cannot be relied on to hold a merge for CI, so the worker is where that waiting lives.
4. **`prod-write-gate` hook** (optional, profile `## Prod writes`) — a worker reads production
   freely and writes to it only on your explicit word, through the one **Command** the profile
   declares. The word (**Word**, default `PROD OK`) is read where an `LGTM` is read — this
   session's transcript, a message you typed — and covers **one** run: the next write asks again,
   because a standing permission is not a command. Routes that hand out the credentials (the
   profile's bare bullets, e.g. a connection helper a worker could `source`) are denied outright,
   which is what makes the door the only door: the runner deny list matches the text of a command,
   so a script that reaches the cloud inside itself was never covered by it. Two rails your word
   does not lift: a schema change goes by migration, and an `UPDATE`/`DELETE` with no `WHERE` is
   refused.
5. **The prompts** — a worker writes no code before your approval, posts nothing to anyone but you
   without your yes, and its judgement can only send a PR to review, never past it.
6. **Locks** — handoffs and migration round-trips run one worker at a time (`factory-lock`).

## Files

| Path | What |
|---|---|
| `scripts/factory_dispatch.py` | the dispatcher; all routing is `decide()`, a pure function |
| `scripts/auto_merge_gate.py` | the PreToolUse gate hook |
| `scripts/factory_ping.py` | `factory-ping` — Slack DM, once per reason per step; `--factory` for the dispatcher's own notices |
| `scripts/factory_hold.py` | `factory-hold` — puts a card on hold (the hold label), or `--off` |
| `scripts/factory_attach.py` | `factory-attach` — puts an approved card brief on the Trello card, replacing an earlier upload |
| `scripts/factory_download.py` | `factory-download` — fetches a card's uploaded files (screenshots, mockups) for the analyst and the spec writer, with the key from `.env` |
| `scripts/prod_write_gate.py` | `PreToolUse(Bash)` — production writes: the declared door, your word, one word per run |
| `scripts/factory_status.py` | `factory-status [--json] [--live <repo>]` — the snapshot each dispatch writes |
| `scripts/factory_page.py` | the status page, rendered from the snapshot |
| `systemd/factory-page.service` | serves the status page on localhost, where `tailscale serve` cannot serve the folder |
| `www/` | the status page's icons, copied beside it |
| `scripts/factory_lock.py` | `factory-lock acquire|release handoff|migration` |
| `scripts/remove-step-worktree.sh` | non-interactive cleanup of a finished step |
| `prompts/` | split, analysis, step, recovery, resume and unshelve worker prompts; `triage.md` and `analysis.md` also run alone |
| `tests/` | `python3 -m unittest discover -s plugins/factory/tests` |
