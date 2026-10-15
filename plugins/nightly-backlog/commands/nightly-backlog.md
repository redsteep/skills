---
description: Unattended night run — take one tech-debt issue to a draft PR, triage a few unlabelled ones
argument-hint: "[report=<path>] [issue number — force this issue, skip selection]"
---

You are working at night, with nobody around. Nobody will answer a question or click "allow": where you would normally ask the user, write the question into the report and the PR body and take the most conservative path (usually: don't do it). Every rule of the repo, every skill and memory apply as they do by day; night is no reason to cut any of them.

`$ARGUMENTS` may hold `report=<path>` (where the report goes; default `<git common dir>/nightly/<YYYY-MM-DD>.md`) and an issue number (force that issue).

The night's result is **at most one draft PR** and the report. Zero PRs with an honest reason is a normal outcome; a PR "just in case" is not.

The tech-debt backlog is the open **GitHub issues** of this repo. Work tracked anywhere else is never taken at night.

## The project profile

Project specifics come from `.claude/nightly-backlog.md` in the repository, if it exists — read it in full first. Its sections, referred to below as **Profile → Section**: *Off limits* (extra prohibitions), *Not a night issue* (extra drop criteria), *Worktree* (how to create and remove one), *Tests* (how to run them, traps), *Deny* (tool rules the runner passes to `--disallowedTools`). A template sits at `${CLAUDE_PLUGIN_ROOT}/profile-template.md`. A missing section falls back to the generic behaviour below.

## Prohibitions on top of the usual ones

- Nothing committed or pushed to the default branch. Work only in your own worktree `nightly-<N>-<slug>`.
- Do not merge; do not edit, label, comment on or close issues (`Closes #N` in the PR body is the only link); do not trigger CI workflows or touch repository secrets.
- No messaging or tracking tools (chat, e-mail, boards), no cloud CLIs, no `ssh` to any host.
- Production is off limits: no production databases, logs, consoles or runbooks.
- Other people's worktrees and branches are not touched.
- Tests — targeted only, in the foreground, output redirected to a file. Never the full suite.
- Plus everything in **Profile → Off limits**.

## 1. Look around

```bash
git -C <repo> fetch origin && git -C <repo> pull --ff-only   # the default branch must be fresh
git -C <repo> worktree list
gh pr list --state open --json number,title,headRefName,body --limit 100
git -C <repo> branch -r --sort=-committerdate | head -30
```

An issue is **taken** if its number appears in a branch or worktree name, or as `#N` in the body of an open PR. Taken issues are not picked.

## 2. Pick an issue

If an issue number is given, take that issue (still run the "taken" check); otherwise pick by the criteria below.

Labels on issues:
- `nightly:ok` — a human allowed it to be taken at night;
- `nightly:no` — not to be taken (the reason is in a comment or the body).

```bash
gh issue list --state open --label "nightly:ok" --json number,title,createdAt,body --limit 50
```

### Selection criteria

The main criterion: the issue goes from description to PR **without a single architectural decision**. The decision is already made — in the issue itself, or in the code as an existing pattern that only has to be repeated. If you would have to choose between options along the way, it is work for two, with a human, not night work.

Candidates — only issues labelled `nightly:ok`. Even with the label, drop an issue if:
- the fix introduces a new mechanism, abstraction, layer, module or pattern that the code does not have yet;
- the issue lists options, says "needs a decision", "discuss", "product question first" or "waiting";
- the fix changes a public API contract or generated client types;
- the fix needs a database schema migration;
- the fix is visible in the UI (a frontend change with nothing visible is fine);
- the issue does not name a concrete file / function to start from;
- anything in **Profile → Not a night issue** applies.

Of those left — the oldest by `createdAt`. No suitable issue is a normal outcome: go to step 4.

## 3. Do it

The ordinary cycle, as by day, no shortcuts:

1. A worktree `nightly-<N>-<slug>` from the fresh default branch, made as **Profile → Worktree** says (generic: `git worktree add <repo>/.worktrees/nightly-<N>-<slug> -b nightly/<N>-<slug> origin/<default branch>`, then install what the package needs).
2. Test first, watched red, then the fix — run as **Profile → Tests** says.
3. 2–4 logical commits, explicit `git add` paths (never `-A`).
4. Review. If the `pre-pr-review` skill is available, run it in full. Night specifics:
   - step 1: an issue has no spec, so the contract is the issue body — any name the issue does not call for is a finding; if the gate needs the user's decision, the issue was not a night one: see "Stuck" below;
   - step 2 (if UI code was touched): run E2E via the subagent, but do not leave an app running for the human — write in the PR which screens to look at.

   Without that skill: read the whole diff against the repo's own conventions, and run its lint / type-check over the changed files.
5. `REVIEWED=1 gh pr create --draft`, title prefixed `[nightly]`, body: `Closes #N`, the review summary, open questions.

Stuck — stop, do not open a PR. Stuck means: a red baseline; the test does not reproduce the problem; the fix pulls in a module the issue does not name; a choice between two designs appeared that no existing pattern settles. Remove the worktree (Profile → Worktree; generic: `git worktree remove` + delete the branch), and put in the report the reason and which question a human has to settle for the issue to become a night one.

## 4. Triage

Take up to 10 open issues with **neither** label, oldest first, and for each propose a label by the main criterion of step 2: `nightly:ok?` (the decision is made, only execution is left) or `nightly:no — <which decision is not made>`, one line of reasoning. Do **not** label them — report only; a human applies labels.

```bash
gh issue list --state open --json number,title,labels,createdAt --limit 100 \
  --jq '[.[] | select([.labels[].name] | any(startswith("nightly:")) | not)] | sort_by(.createdAt) | .[:10]'
```

## 5. Report

At the report path:

```
# Night <date>
Taken: #N <title> → PR #M (draft) | nothing taken: <why>
Open questions for the morning: …
Stopped at: … (if stuck)
Labels (proposed):
- #N <title> — nightly:ok? — <why>
- #N <title> — nightly:no — <why>
```

The last message is the same as the report.
