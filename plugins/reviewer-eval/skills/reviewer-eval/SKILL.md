---
name: reviewer-eval
description: Turn a defect a reviewer missed into a kept eval case, and prove the instruction that should catch it — the reviewer must miss it under today's rules, catch it with the amended rule, and stay quiet on the fixed commit, each run in its own subagent on throwaway worktrees. Use when the user asks to "create an eval case for the reviewer", "make the reviewer catch this", or "eval this rule", and to offer after proposing an amendment that a reviewer would check.
---

# Reviewer eval

A rule that reads well can still change nothing. The mistake it answers already happened, in
commits that still exist, so the test is a replay: put the amended instructions next to the old
code and see whether the reviewer that missed it now doesn't. The replay is kept as an eval case,
so the next edit to the same rules can be checked against it.

**Any rule a reviewer reads** — naming, layering, placement, how a test is written. A rule about
process or the user's preferences has no reviewer to replay and gets no offer.

**Propose first, run on a yes.** The runs cost subagents (see "Cost"). Start only when the user
agrees to the proposal below.

## Profile — `.claude/reviewer-eval.md`

Everything project-specific (start from `profile-template.md`): which reviewers exist, how each is dispatched and which rules files
it reads, where cases, results and tags live, how instruction changes land. Without a profile,
cases go to `.claude/evals/<reviewer>/` and you ask the rest.

## 1. Propose (in chat, before any run)

| Name | What | Where it comes from |
|---|---|---|
| **Defect** | what the user flagged, quoted, and one sentence naming it as a reviewer would report it | the review or correction |
| **BEFORE** | the commit where the defect is in the code | `git log -S` / `git log -p` on the lines the fix changed |
| **AFTER** | the commit with the fix | the fix |
| **BASE** | the reviewer's diff base: `git merge-base BEFORE <default branch>` | git |
| **Spec** | the feature's spec, if it had one | the branch |
| **Reviewer** | the one whose rules cover this class of defect, and why that one | the profile's reviewer list |
| **Rule** | file + wording | see below |
| **Case** | one `expected` entry per defect (file, lines, `match`: what a report must say to count), plus `not_expected_on_after` | the defect |

**The rule.** Name the class of mistake, not this incident's trigger, and check it on a sibling:
a different mistake of the same class must fall under it. Illustrate it in generic terms, never
with the incident's own names — those go in the commit message. A rule quoting its case hands
the case its answer, and the eval then proves only that the reviewer can read.

**The match.** Say which reasons count ("'listed' has a second meaning, or the class is named
for an action it doesn't take — any one counts") and what doesn't ("'names could be clearer'
with no reason this one misleads is no match"). Adjacent is a miss.

End with the plan: the three runs below, the commits, the subagent count.

## 2. Set up

```bash
git worktree add --detach <scratch>/eval-before BEFORE
git worktree add --detach <scratch>/eval-after  AFTER
```

In the session's scratchpad, never inside another session's or the user's worktree. Each run
overlays rules files from the main checkout onto its worktree — the profile names which; at
least every file the reviewer reads, plus whatever `@`-imports them. Write the amended rule into
a scratch copy of its file, not into the main checkout, until the runs pass.

Draft the case file now; its `match` lines are the grading contract and don't change after the
red run.

## 3. Run — each in its own subagent, red before green

Dispatch the reviewer as its caller does: the plugin's own agent type where it has one, with
exactly the message the real caller sends (worktree, spec, base, …). **Never name the defect**
to the reviewer — a replay that points at the bug tests reading comprehension, not the rule.

| Run | Code | Rules | Passes when |
|---|---|---|---|
| **red** | BEFORE | today's (committed) | every `expected` entry is **missed** |
| **green** | BEFORE | today's + the amendment | every `expected` entry is **caught** |
| **quiet** | AFTER | today's + the amendment | nothing in `not_expected_on_after` is flagged |

Red first, alone. If red already catches an entry, the rule is not what is missing — stop and
tell the user (the reviewer may be flaky there, or the defect is already covered). Then green
and quiet in parallel.

**A run is invalid** when the reviewer read the rules from git (`git show HEAD:<rules file>`)
instead of the overlaid copy — its report says the rule is missing, or quotes the old text.
Before dispatch, `grep` the worktree's copy for the new rule; after, check the report. Re-run an
invalid run; it never counts as a miss.

Grade each report yourself, binary per entry: does an issue name this defect at this place, for a
reason `match` accepts. On quiet, also list every other finding the new rule provoked: a rule
that reads names harder may raise real ones elsewhere, or noise.

**On a green fail:** say what the reviewer found instead, sharpen the wording (still generic,
still passing the sibling check) and re-run only green, then quiet. Don't add a second rule to
make the first pass. Stop after two rewrites and bring it to the user.

### Spec runs (placement lessons only, optional)

When the lesson is about where things live and the spec planned the mistake, two more runs
apply. Offer them separately; they cost more and answer a different question:

- **Reviewer on BEFORE's spec** — the spec as it stood at BEFORE, with the amendment overlaid;
  passes when a finding says the spec plans the defect.
- **Spec from BASE** — one subagent in a BASE worktree with the amendment overlaid writes the
  spec for the original task (quoted from the card or issue), answering its own questions from a
  fixed brief: the task plus GOOD's product decisions, "your call" on anything architectural. A
  separate grader sees only that spec and 3–6 binary checks drawn from AFTER's architecture
  (shown to the user before running), describes the architecture it proposes, and answers each
  check quoting the spec line it relied on.

## 4. Report

Details first, verdict last — the user judges the rule by what the reviewer actually said.

```
Rule: <file> — "<wording>"         Reviewer: <agent>
Case: <id>   BEFORE <sha>   AFTER <sha>   BASE <sha>

| Run | Code | Rules | <entry 1> | <entry 2> |
|---|---|---|---|---|
| 1 | before | today's | missed (red, as intended) | missed |
| 2 | before | + v1 | caught — "<finding, quoted, file:line>" | missed |
| 3 | after | + v1 | not flagged | not flagged |
…
Invalid runs: <which, why>
Side effects on after: <other findings the rule raised; real or noise>

Overall: passes / passes after rewrite N / doesn't change the reviewer — <next step>
```

One run per arm proves passing, not stable; say so.

## 5. Keep it — on the user's go-ahead

Land together, the way the profile says instruction changes land:

- the rule, into its file in the main checkout;
- the case file, into the reviewer's eval directory (with a README if the directory is new: what
  it gates, the case format, how to run it);
- the run table, appended to that directory's `results.md` with the date, reviewer version, rules
  revision and model;
- tags on BEFORE and AFTER, pushed to origin, so squash-merged commits stay reachable:
  `eval/<reviewer>/<case-id>/before` and `/after`.

Then remove the worktrees (`git worktree remove --force`).

## Cost

Red, green, quiet: 3 reviewer subagents, graded inline; +2 per rewrite. Spec runs: +1 reviewer,
+1 writer, +1 grader. Say the count when proposing.
