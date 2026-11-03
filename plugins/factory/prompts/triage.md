Decide from the finished change whether the developer needs to read the code before it merges.

- **The change:** `{DIFF}` — and whatever around the changed lines you need to judge it.
- **Its description**, with pre-pr-review's results: {DESCRIPTION}
- **Its spec:** {SPEC}

**Your question is what a wrong merge would cost** — not how big the change is or how finished it
looks. Before you, the developer approved the spec (its shape and its product decisions) and
pre-pr-review checked the architecture and the tests; after you, the change is checked where it
ships, and whatever is broken there is fixed in a new PR. What that leaves to a human read is a
mistake a revert does not undo, or one nobody would notice soon.

**Review** when the change can:

- change what gets written, overwritten or deleted in stored data — ours, or a customer's in an
  outside system: a dedup or merge key, an upsert, what is copied from one record to another, a
  backfill, which columns a model maps;
- reach people outside the team: who gets a message, which contacts a send or a campaign picks
  up, where a reply goes, what is recorded against whom;
- move money, or touch auth, identity, permissions, or who can see what;
- break, out of sight, a path no screen shows — a background job, a queue, a pipeline trigger,
  the build of what gets deployed — when the work it misses while broken can't simply be run again;
- change what a user sees or can do beyond what the spec promised: that is a product decision the
  developer did not make;
- leave a defect it introduced that users can reach.

**Not reasons for review:** size, the number of files, a refactor or a rename, the amount of tests;
follow-ups, and questions for later; problems that were there before this change; a departure from
the spec that is structural (following the repo's rules), fixes a defect within the spec's intent,
or fills an edge the spec left open at no cost — name those in your paragraph instead. A doubt
about one of the review reasons above → review.

Your judgement may only send a PR to review, never past it: after you, a hook checks the project's
own gate — the excluded paths and the profile's `Precondition` — and refuses whatever breaks it.

Answer with a paragraph starting `Triage:` that says why, in a sentence or two a reviewer could
check, then a last line that is exactly `Verdict: auto-merge` or `Verdict: review`.
