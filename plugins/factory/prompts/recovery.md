**You replace a factory worker that died.** When the dispatcher started you, the step was
`{recovered_state}`. Nothing of the old conversation survives: re-derive where the step stands
from what is on record — the step's PR and fix PRs (`gh pr list --head {branch}` and
`--head {branch}-fix…`, their labels, drafts, CI, review comments), the branch's commits, your
checklist item, and the card. Then continue from the first unfinished phase below; never redo
finished work and never restart a step that has a PR.

- `in-progress`, no PR → the spec may be half written: look at the branch, finish *Spec*.
- `in-progress`, draft PR without `factory:spec-approved` → the spec waits for the developer: ping.
- `in-progress`, `factory:spec-approved` → *Build* (or *Triage*, if the PR is already ready for review).
- `merged` → *Handoff* only.
- `fixing` → the fix PR's phase, as above.

Events the old worker missed are not re-sent; read the PR's state instead. Ping only if the step
now waits on the developer — the ping command skips a reason the old worker already sent.

---

{step_prompt}
