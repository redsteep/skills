---
description: Unattended night run — take one tech-debt item to a PR, triage a few unmarked ones
argument-hint: "[report=<path>] [before=<log>] [item — force this item, skip selection]"
---

You are working at night, with nobody around. Nobody will answer a question or click "allow": where you would normally ask the user, write the question into the report and the PR body and take the most conservative path (usually: don't do it). Every rule of the repo, every skill and memory apply as they do by day; night is no reason to cut any of them.

`$ARGUMENTS` may hold `report=<path>` (where the report goes; default `<git common dir>/nightly/<YYYY-MM-DD>.md`), `before=<log>` (the output of the runner's `Before` commands) and an item (force that item).

The night's result is **at most one PR** and the report. The PR is ready for review unless a gate stands open on it (step 3.6); a draft says "not mergeable yet", so a clean night does not open one. Zero PRs with an honest reason is a normal outcome; a PR "just in case" is not.

## The project profile

Project specifics come from `.claude/nightly-backlog.md` in the repository, if it exists — read it in full first. Its sections, referred to below as **Profile → Section**: *Backlog* (where the items live and how to read them), *Off limits* (extra prohibitions), *Not a night item* (extra drop criteria), *Worktree* (how to create and remove one), *Tests* (how to run them, traps), *Report* (language). The runner reads *Before*, *Deny* and *Notify* itself. A template sits at `${CLAUDE_PLUGIN_ROOT}/profile-template.md`. A missing section falls back to the generic behaviour below.

### The backlog

**Profile → Backlog** says how each operation is done; without it the backlog is the open **GitHub issues** of this repo:

| Operation | Default (GitHub issues) |
|---|---|
| **Allowed** — items a human allowed at night | `gh issue list --state open --label "nightly:ok" --json number,title,createdAt,body --limit 50` |
| **Unmarked** — items with no night marking yet | `gh issue list --state open --json number,title,labels,createdAt --limit 100 --jq '[.[] \| select([.labels[].name] \| any(startswith("nightly:")) \| not)] \| sort_by(.createdAt) \| .[:10]'` |
| **Marking** — how "allowed" / "not at night" look | labels `nightly:ok` / `nightly:no` |
| **Age** — what "oldest" means | `createdAt` |
| **Id** — how an item is named in branches, worktrees and PR bodies | `#N`; branch `nightly/<N>-<slug>` |
| **Link** — how the PR refers to the item | `Closes #N` in the body |
| **Done** — what the branch does to the item | nothing: merging the PR closes the issue |

Work tracked anywhere else than the backlog is never taken at night. Whatever the backlog, you never mark, edit or close items yourself outside the branch (**Done** is the only change, and only when the profile says it happens in the branch).

## Prohibitions on top of the usual ones

- Nothing committed or pushed to the default branch. Work only in your own worktree `nightly-<id>-<slug>`.
- Do not merge; do not mark, edit, comment on or close backlog items beyond **Done**; do not trigger CI workflows or touch repository secrets.
- No messaging or tracking tools (chat, e-mail, boards), no cloud CLIs, no `ssh` to any host. Telling the owner about the night is the runner's job (**Notify**), not yours.
- Production is off limits: no production databases, logs, consoles or runbooks.
- Other people's worktrees and branches are not touched.
- Tests — targeted only, in the foreground, output redirected to a file. Never the full suite.
- Plus everything in **Profile → Off limits**.

## 0. Before

If `before=<log>` is given, read its last line — the runner's housekeeping (e.g. sweeping orphaned worktrees) — and carry it into the report. A failure there is one line in the report, never a reason to stop.

## 1. Look around

```bash
git -C <repo> fetch origin && git -C <repo> pull --ff-only   # the default branch must be fresh
git -C <repo> worktree list
gh pr list --state open --json number,title,headRefName,body,isDraft --limit 100
git -C <repo> branch -r --sort=-committerdate | head -30
```

An item is **taken** if its id appears in a branch or worktree name, or in the body of an open PR. Taken items are not picked.

## 2. Pick an item

**Precondition: the previous night's item has landed.** While an open `[nightly]` PR (a draft too) or a `nightly-*` worktree with unpushed commits exists, take nothing — not even a forced item — and say in the report what is waiting and on what (a gate, a review, a merge). Parallel night branches pile up worktrees, drift apart on migrations, and turn the morning into five PRs instead of one.

If an item is given, take that item (still run the "taken" check); otherwise pick by the criteria below, from **Allowed**.

### Selection criteria

The main criterion: the item goes from description to PR **without a single architectural decision**. The decision is already made — in the item itself, or in the code as an existing pattern that only has to be repeated. If you would have to choose between options along the way, it is work for two, with a human, not night work.

Even when allowed, drop an item if:
- the fix introduces a new mechanism, abstraction, layer, module or pattern that the code does not have yet;
- the item lists options, says "needs a decision", "discuss", "product question first" or "waiting";
- the fix changes a public API contract or generated client types;
- the fix needs a database schema migration;
- the fix is visible in the UI (a frontend change with nothing visible is fine);
- the item does not name a concrete file / function to start from;
- anything in **Profile → Not a night item** applies.

Of those left — the oldest by **Age**. No suitable item is a normal outcome: go to step 4.

## 3. Do it

The ordinary cycle, as by day, no shortcuts:

1. A worktree `nightly-<id>-<slug>` from the fresh default branch, made as **Profile → Worktree** says (generic: `git worktree add <repo>/.worktrees/nightly-<id>-<slug> -b nightly/<id>-<slug> origin/<default branch>`, then install what the package needs).
2. Test first, watched red, then the fix — run as **Profile → Tests** says.
3. **Done**, if the profile's backlog has a step for the branch.
4. 2–4 logical commits, explicit `git add` paths (never `-A`).
5. Review. If the `pre-pr-review` skill is available, run it in full — it is an unattended run, so its extensions follow their `Unattended` setting. Night specifics:
   - step 1: an item has no spec, so the contract is the item's text — any name the item does not call for is a finding; if the gate needs the user's decision, the item was not a night one: see "Stuck" below;
   - step 2 (if UI code was touched): run E2E via the subagent, but do not leave an app running for the human — write in the PR which screens to look at.

   Without that skill: read the whole diff against the repo's own conventions, and run its lint / type-check over the changed files.
6. `REVIEWED=1 gh pr create`, title prefixed `[nightly]`, body: the **Link**, the review summary, open questions. Add `--draft` only when the review left a gate open — an extension with `Unattended: draft` triggered and not run — and name it in the body as `pre-pr-review` says; undrafting is then the owner's, after the gate. Open questions in the body are not a gate: they are read before the merge either way.

Stuck — stop, do not open a PR. Stuck means: a red baseline; the test does not reproduce the problem; the fix pulls in a module the item does not name; a choice between two designs appeared that no existing pattern settles. Remove the worktree (Profile → Worktree; generic: `git worktree remove` + delete the branch), and put in the report the reason and which question a human has to settle for the item to become a night one.

## 4. Triage

Take up to 10 items from **Unmarked**, oldest first, and for each propose a marking by the main criterion of step 2: "allowed?" (the decision is made, only execution is left) or "not at night — <which decision is not made>", in the backlog's **Marking** words, one line of reasoning. Do **not** mark them — report only; a human applies markings.

## 5. Report

At the report path, in the language **Profile → Report** names (default English). The first line carries the night's **status** as a fixed token, whatever the language — the runner reads it to decide whether to notify:

- `pr` — a ready PR was opened and nothing waits on the owner beyond reading it;
- `questions` — something needs the owner: an open question, an outstanding gate on the PR, a forced item refused;
- `stuck` — the item stopped half-way;
- `quiet` — nothing taken, nothing to ask.

```
# Night <date> — <status>
Before: <the last line of the before log, if any>
Taken: <id> <title> → PR #M [(draft — <the open gate>)] | nothing taken: <why>
Open questions for the morning: … (only when there are some)
Stopped at: … (if stuck)
Markings (proposed):
- <id> <title> — allowed? — <why>
- <id> <title> — not at night — <why>
```

The last message is the same as the report.
