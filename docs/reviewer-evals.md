# Reviewer evals

How to measure a reviewer skill (`design-review`, the `pre-pr-review` reviewers) on cases where
the answer is already known. The plugin owns the format and the assertions that test its own
contract; the project owns the cases, because a case is a commit in that project's history.

## Where things live

| Part | Where |
|---|---|
| This format | here |
| Generic assertions — the skill's contract, added to every case | the plugin's README, "Evals" |
| Cases, the frozen profile they run with | the project: `.claude/evals/<skill>/` |
| Run outputs (transcripts, grading, viewer) | the project's gitignored scratch, e.g. `.tmp/evals/<skill>/iteration-N/` |

Nothing case-specific goes into the plugin: it ships to every project that installs it.

## A case

A mistake the project actually made and later corrected, replayed at the commit before the
correction. `cases.json`:

```json
{
  "skill": "design-review",
  "profile": "profile.md",
  "cases": [
    {
      "id": "model-override-env-var",
      "sha": "82bc9f40b",
      "mode": "proposal",
      "input": "docs/superpowers/specs/2026-04-29-per-campaign-model-override-design.md",
      "prompt": "per-campaign model override design is done (…) — check it before I commit",
      "must_flag": ["Flags that … a second mechanism beside LeadCollectionTask.model …"],
      "must_not_flag": [],
      "fixed_by": "4d615b16a"
    }
  ]
}
```

- **`sha`** — the commit the reviewer sees; the run gets a detached worktree there.
- **`input`** — what is under review: a spec path, or a `base..head` range for a diff reviewer.
- **`prompt`** — phrased the way the user would say it, without naming the skill or the answer:
  the case measures triggering and finding together.
- **`must_flag`** — one sentence per known mistake, specific enough that a grader can say yes or
  no from the report alone.
- **`must_not_flag`** — the false alarm a reviewer is tempted into. Each set carries at least one
  **control**: the same input at its corrected commit (the other case's `fixed_by`; the control
  names it in `control_for`), where the mistake is gone and `must_flag` is empty.
- **`profile`** — frozen with the set. The live profile changes, and at an old `sha` it may not
  exist yet. Its known-failures list must not describe any case's answer: a case whose lesson
  was later written into the profile is retired, not kept with the answer in its prompt.

## Grading

Binary: each assertion passed or failed, with the evidence quoted. No scores. A case passes when
every `must_flag`, every `must_not_flag` and every generic assertion pass.

An assertion that passes in both arms on every case measures nothing — drop it from the generic
list rather than keep it for reassurance.

## Running

The `skill-creator` loop, per case: a worktree at `sha`, the profile copied in, one run with the
skill and one without it (or with the previous version when the change is to the skill),
three runs per arm when deciding whether a change helped. Grade, aggregate, compare the arms.

A runner script waits until the loop has been run by hand often enough to know which steps
repeat.
