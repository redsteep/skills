Decide from the finished change whether the developer needs to read the code before it merges.

- **The change:** `{DIFF}` — and whatever around the changed lines you need to judge it.
- **Its description**, with pre-pr-review's results: {DESCRIPTION}
- **Its spec:** {SPEC}

**Auto-merge** only when all hold: the change is tiny and plainly safe; pre-pr-review ended with
nothing open; the spec had no open questions when it was approved. Any doubt → review. Your
judgement may only send a PR to review, never past it: after you, a hook checks the project's own
gate — the excluded paths and the profile's `Precondition` — and refuses whatever breaks it.

Answer with a paragraph starting `Triage:` that says why, in a sentence or two a reviewer could
check, then a last line that is exactly `Verdict: auto-merge` or `Verdict: review`.
