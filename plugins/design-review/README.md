# design-review

The review most pipelines are missing: whether a change **sits where it belongs**.

A diff-vs-spec subtraction catches a name nobody asked for. It cannot catch a
field on the wrong class — because the spec is the author's own claim, so the
wrong owner is written down, approved as prose, and confirmed as matching. Three
green gates, wrong placement. This plugin is the adversary that contract needs.

## Seven tests

| | Test | Catches |
|---|---|---|
| 1 | value object / entity / no state of its own | data given to a key that merely locates it; a type or method with nothing of its own |
| 2 | aggregate boundary — the invariant in one place | the same rule enforced twice, and derived values that get stored |
| 3 | ubiquitous language | a name that does not say what the thing is; one word, two meanings |
| 4 | anti-corruption layer | a foreign system's vocabulary reaching past the boundary |
| 5 | translation between stages | one concept in N representations, and the N+1'th |
| 6 | OCP — extend, do not duplicate | a new case that edits shared code; a second mechanism beside an existing one |
| 7 | LSP — honest to the port | an implementation whose callers must know which one they got |

Deliberately **not** covered: whether the feature is worth doing · completeness of
declarations · tests · style · file size · anything a tool already enforces on
every commit (list those in the profile and the reviewer skips them).

## Two modes

- **`proposal`** — before any code. Starts itself: a `PostToolUse` hook sees a new spec
  (one matching the profile's **Specs live in** and not yet on the base branch) and tells
  the agent to run the review now — once per spec per worktree, so the review's own edits
  don't start another. Nobody announces the moment between "spec written" and "spec
  committed"; left to the skill's description, the review was skipped. First checks that the spec's "as it is now"
  picture matches the code, because everything derived from a wrong picture is
  unanswerable.
- **`drift`** — on the implemented branch. The names may all be present and the
  shape still differ: a field on a neighbouring node, a promised change-in-place
  that became a new type, a stage inserted where no seam was named.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install design-review@redsteep
```

Then copy `skills/design-review/profile-template.md` to `.claude/design-review.md`
and fill it in: where specs live, the layers and their paths, a command that
prints a containment tree, what your tools already enforce, and your own known
failures. A bundled extractor for Python dataclasses is at
`scripts/containment.py`; for anything else, write an equivalent that prints a
tree and name it in the profile.

## Measured, once

On the spec it was first run against, three arms on the same input:

| | findings | blocking | the duplication axis |
|---|---|---|---|
| open brief | 18 | 4 | — |
| open brief + profile | 17 | 4 | partly |
| this skill | 9 | 3 | **3 findings nobody else produced** |

Read it as what it is: the skill owns one axis — "this already exists in the
codebase for this very purpose" — and two strong unstructured reviewers did not
produce a single finding on it. It owns no other axis. Run it **after** an
ordinary review, never instead of one.

The same run exposed a flaw worth knowing about in any rubric-shaped reviewer:
correctness was nowhere forbidden, yet both blocking arithmetic errors were
dropped — because every finding had to carry a test number and a "where it
belongs", and a figure that computes to zero has neither. The output schema
filtered harder than the instructions. Hence the "Outside the tests" section.

## Calibrate before you trust it

Point it at corrections you have already made, where the answer is known. On the
project it was built for, nine known placement errors gave five clear hits, one
weak, two misses and one case deliberately out of scope — and the two misses are
why tests 1 and 6 read the way they do.

## Evals

Cases live in the project that made the mistakes (format: [`docs/reviewer-evals.md`](../../docs/reviewer-evals.md));
`evals/design_review.py` is the adapter for the shared runner, `tools/agent-eval/run.py`.
Every case also carries the skill's own contract (the adapter's `CONTRACT`):

- **Every finding is a placement finding** — one of the seven tests, or "Outside the tests"
  for a correctness error. No findings about tests, typed ids, wording, counts, undeclared
  surface, or whether the feature is worth doing.

This is the assertion that separated the skill from an unstructured review on the first
measured set (skill 100%, baseline 50%): the baseline's misses were findings about tests,
typing and prose mixed in with the placement ones. "Cites file:line" and "changes nothing in the repo" passed in both
arms every time and were dropped.
