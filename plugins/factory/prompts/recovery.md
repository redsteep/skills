**You replace a factory worker that died.** When the dispatcher started you, the step was
`{recovered_state}`. Nothing of the old conversation survives: re-derive where the step stands
from what is on record — the step's PR and fix PRs (`gh pr list --head {branch}` and
`--head {branch}-fix…`, their labels, drafts, CI, review comments), the branch's commits, your
checklist item, and the card. Then continue from the first unfinished phase below; never redo
finished work and never restart a step that has a PR.

- `in-progress`, no PR and no spec commit on the branch → finish *Spec*.
- `in-progress`, no PR, a spec on the branch, no `Approved-by:` trailer (`git fetch`, then
  `git log origin/{branch}` — the dispatcher may have reused this worktree without fetching) →
  the spec waits for the developer: ping.
- `in-progress`, no PR, an `Approved-by:` trailer → *Build*.
- `in-progress`, a PR of your own branch → *Triage*: *Build* already opened it.
- `in-progress`, an adopted PR → *Adopted PR*: without `factory:arch-approved` and not written by
  the developer, the card's architecture gate waits on them (re-run it over all the card's
  adopted PRs if the PR body has no `Architecture reviewed at` line, then ping); with the label,
  its step 4.
- `merged` → *Handoff* only.
- `fixing` → the fix PR's phase, as above.

Events the old worker missed are not re-sent; read the PR's state instead. Ping only if the step
now waits on the developer — the ping command skips a reason the old worker already sent.

---

{step_prompt}
