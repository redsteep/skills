---
name: after-merge-handoff
description: What happens after a factory PR merges — check the commit is live, offer the developer a manual check, record the step on its card, and on the card's last step draft the move to the testing list and the reply to whoever asked. Use only as the factory's handoff, called with step=<n>/<total> or issue=<n>; the dispatcher owns the worktree cleanup, never this skill.
---

# After-merge handoff

The step merged. This is everything between that merge and the card being someone else's problem
again. Two modes, by the argument you were called with.

**Everything project-shaped comes from the profile** the factory already reads,
`.claude/factory.md` — its deploy commands, its board, its channel. This skill is the shape of a
handoff; the profile says what the words mean here. Sections referred to below as **Profile →
Section → Key**. A key the profile does not define is a step you do not take: say so in your
report rather than inventing a command.

## Both modes: is the merge live?

A merged PR is not a finished step. The step is finished when that commit is serving — "deployed
and green" means whatever **Profile → Deploy → Pipeline** says it means, which for a project with
no staging is production itself.

Cloud CLIs are denied to you. That denial matches the **text** of a command, so the project's own
scripts — which reach the cloud inside themselves — are the way through, and each has a narrow
surface on purpose. Ask the one the profile declares:

```bash
SHA=$(gh pr view <n> --json mergeCommit --jq .mergeCommit.oid)
<Profile → Deploy → Live check, with the sha>
```

Exit 0 is the only green. Everything else prints one reason and exits non-zero. Four shapes, and
what each means for your step:

- **no build yet** — the push has not been picked up. Wait and ask again; a push that changes only
  paths the deploy trigger ignores never builds at all, and then the change is live by definition
  — say which of the two it is rather than waiting forever.
- **queued or running** — in flight. Wait the time the profile says a deploy takes, then ask again.
- **failed** — **the deploy is broken, not your step.** Do not tick anything, and do not ping yet:
  look first, with **Profile → Deploy → Failed build** and **→ Build log**. Read the failing
  step's log and say *what* broke. Then:
  - *a flake* — a timeout, a pull that failed, an infrastructure error, anything unrelated to the
    diff: re-run it with **Profile → Deploy → Retry build**, if the profile declares one. Re-running
    deploys the same commit the developer already merged, so it ships nothing new; the project's
    command is what decides when a re-run is allowed, and its refusal is an answer, not an obstacle.
  - *the code* — the failure names a test, a type, a migration: that is a fix PR (your prompt's
    *Handoff* step), and the retry door is not for it. Re-running will fail again.
  - *still red, or you cannot tell which it is* — ping with the failing step, the log tail and the
    build URL. That is a question for the developer, and it now arrives with an answer attached.
- **green but something older is serving** — usually two merges racing, and the pipeline aborting
  its own rollout because the live revision is newer. Ping it; do not tick.

## Mode `step=<n>/<total>`: the card

Only after the deploy check is green.

1. **Offer the manual check first.** Ping (**Profile → Settings → Ping command**) with
   `step <n>/<total> live — test it by hand first, or shall I close it out?`, then end your turn.
   The developer may want to click through it before the card moves. Their answer decides whether
   you go on now or later; **a silence is not a yes**.

2. **Record it on the card** with the Trello connector (`mcp__claude_ai_Trello__*`). You have it
   through the developer's account, so there is no token to find and nothing to read from the
   profile. What is denied to you is the board's *structure* — lists, the board, the Inbox, the
   planner: you write on a card, you do not rearrange the board around it.

   **Read the card first, then write by ARI.** `trelloReadCard`, action `get`, field `cardIdOrUrl`
   — give it the card's **full url**; a bare shortlink is refused. The answer carries the card's
   ARI as `id`, and the ARIs of its checklists and every check item. Those ARIs are what the writes
   take:

   - the PR link: `trelloWriteCard`, action `add_comment`, field `cardId`, text
     `PR #<n> merged and live: <pr url>`;
   - your step: `trelloWriteChecklist`, action `update_item`, field `checklistId` — the ARI of the
     checklist **Profile → Trello → Checklist** names, and your item's.

   Find your item by what it says, never by position: a step's item gets renamed `[dropped] …` or
   `[skipped] …` and is never removed, so match the text after any such prefix. **If two items
   could be yours, stop and ping** — do not tick one of them. The ticked item is what tells the
   dispatcher this step is done: it is the record, it is why ticking the wrong one sends another
   step to handoff, and it is why you never tick an item whose deploy is broken.

   Both write tools take their `action` from a fixed list and report their required fields one at a
   time — a wrong action prints the list, which is the fastest way to check yourself.

3. **The last step only** (`<n>` = `<total>`): the card is finished, and two things go to people.
   Draft both **in this conversation** and post neither without the developer's explicit yes.

   - **The card moves to the testing list**, never to done — done is the developer's call, later:
     `trelloWriteCard`, action `move`, to the list **Profile → Trello → Testing** names.

   - **Whoever asked for this hears back**, through **Profile → Announce**: it says the channel,
     how to reach it, and how the card points at the message that asked (so your answer lands under
     the question rather than beside it). No `## Announce` in the profile → draft the text, hand it
     to the developer in your report, and say it was not sent.

     Two or three sentences in the language of the person who asked, no markdown theatre: what now
     works, and anything they should check on their side. No PR links, no commit hashes, no talk of
     steps, specs or reviews — none of that is their vocabulary. Such a message is seen by everyone
     in that channel and cannot be unsent quietly, so it goes out only on an explicit yes, and you
     post **exactly** the text that was approved.

4. End your turn once your item is ticked. **Do not clean up**: the dispatcher removes the worktree
   and the branch, and it is the only thing that may.

## Mode `issue=<n>`: the deploy check alone

An issue has no card, no requester and nothing to announce. Run the deploy check, report its line,
and stop — your prompt closes the issue when it is green and opens a fix PR when it is not. No ping
on success: nobody is waiting for the news that a lint fix is live.
