# reviewer-eval

A reviewer missed something you caught in review. A new rule might fix that — or read well and
change nothing. This plugin's skill turns the miss into a kept eval case and proves the rule, red
before green:

| Run | Code | Rules | Passes when |
|---|---|---|---|
| red | the commit with the defect | today's | the reviewer **misses** it — the case really tests the rule |
| green | the commit with the defect | today's + the new rule | the reviewer **catches** it |
| quiet | the commit with the fix | today's + the new rule | the fixed code isn't flagged |

Each run is the reviewer itself in its own subagent, on a throwaway worktree with the rules
overlaid, never told what to look for. A failed green gets the rule sharpened (twice at most), never
a second rule. Kept afterwards: the rule, the case file, the run table in `results.md`, and tags so
the commits stay reachable after a squash merge.

For a placement lesson, two optional runs go further: the reviewer on the spec that planned the
mistake, and a spec rewritten from the pre-feature commit, graded against the fix's architecture.

Ask for it in words — "create an eval case for the reviewer to catch these names", "eval this
rule" — or as `/reviewer-eval`. With `instruction-feedback@redsteep` installed, a correction that
ends in a reviewer-facing amendment also offers it.

## The project profile

`.claude/reviewer-eval.md` (start from [`profile-template.md`](profile-template.md)): the
reviewers and the rules each reads, the files overlaid on a replay, where cases, results and tags
live, and how instruction changes land.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install reviewer-eval@redsteep
```
