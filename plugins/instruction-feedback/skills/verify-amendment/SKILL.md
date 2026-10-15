---
name: verify-amendment
description: Test a proposed instruction amendment by replaying the past — the reviewer must now catch the mistake on the commit that made it, and (for an architectural lesson) spec writing from the pre-feature commit must now land on the right architecture. Use after proposing a rule from a correction, before or right after adding it.
---

# Verify an instruction amendment

A rule that reads well can still change nothing. The mistake it answers already happened, in
commits that still exist, so the test is a replay: put the amended instructions next to the old
code and see whether the agents that missed it now don't.

**Propose first, run on a yes.** The replay costs subagents (3–6, see "Cost"). End the
amendment line with an offer that names the checks you'd run and the commits; start only when
the user agrees.

## Inputs — establish before proposing

| Name | What | Where it comes from |
|---|---|---|
| **Amendment** | file + wording, as proposed | the correction you just handled |
| **Issue** | one sentence naming the mistake, as a reviewer would report it | the correction |
| **BAD** | the commit where the mistake is in the code (and, if it was planned, in the spec) | `git log -S`/`git log -p` on the lines the fix changed |
| **GOOD** | the commit with the fix — the reference answer | the fix you just committed |
| **BASE** | the last commit before the feature started (`git merge-base BAD <default branch>`) | git |
| **Task** | the original request the feature came from — card text, issue, the user's first message | tracker / transcript; quote it, don't paraphrase |
| **Architectural?** | yes when the lesson is about where things live: which class owns which dependency, which layer or phase does what, which entity holds a field | judgement — say which and why |

If BAD's spec already contained the mistake, the spec is a target too (check 1b). If the
feature had no spec, skip 1b and say so.

## Setup — throwaway worktrees with the amendment overlaid

Each replay runs on an old commit that doesn't have the new rule. Give it one:

```bash
git worktree add --detach <scratch>/replay-bad  BAD
cp <amended files from the working tree> <scratch>/replay-bad/<same paths>
```

Same for GOOD and BASE when their checks run. Overlay **only** the files the amendment changes
(plus anything they import, e.g. a CLAUDE.md that `@`-imports the guidelines). Put the worktrees
in the session's scratchpad, never inside another session's or the user's worktree, and remove
them at the end (`git worktree remove --force`).

## Check 1 — the reviewer now catches it (always)

Dispatch in parallel. Each reviewer subagent gets the project's normal review prompt (for
`pre-pr-review`: the reviewer prompt files plus the project profile, filled exactly as a real
review fills them) pointed at its worktree. **Never tell a reviewer what the issue is** — a
replay that names the bug tests reading comprehension, not the rule.

| Run | Range / target | Passes when |
|---|---|---|
| **1a** code, BAD | BASE..BAD diff | a finding names the Issue (any severity at or above the one the rule implies) |
| **1b** spec, BAD | the spec as it stood at BAD (`git log` for the spec file's last change ≤ BAD) | a finding says the spec plans the Issue |
| **1c** control, GOOD | BASE..GOOD diff | the Issue is **not** raised — the rule produces no false positive on the fixed code |

Grade it yourself or with a separate grader subagent that sees only the reviewer's report and
the Issue sentence: each run is **pass / fail**, no scores. A finding that is adjacent but not
the Issue is a fail.

## Check 2 — spec writing lands on the right architecture (architectural lessons only)

The question: had this rule existed when the feature was designed, would the spec have planned
GOOD's architecture?

1. **Reference checks.** From GOOD, write 3–6 binary checks that a correct spec satisfies, each
   about the lesson's architecture, never about wording. Example (phase-separated LLM task):
   "every DB read in the Flow is under `load`"; "what crosses into `execute` is a built value,
   not repositories or a resolver"; "scope resolution is owned by one collaborator, not free
   functions taking repositories". Add one check per other decision the correction touched
   ("`call_script` is a field on `Lead`, not inside `NextAction`"). Show the checks to the user
   before running — they are the grading contract.
2. **Run.** One subagent in a BASE worktree with the amendment overlaid, told: "Design the spec
   for this task, following this repo's spec process" + the Task quote. It writes the spec to a
   file in its worktree. One run shows what the rule steers the writer to; run it once more
   only when the verdict is borderline.
3. **Scripted user.** The spec process asks questions. The subagent answers them itself from a
   fixed brief you hand it: the Task quote plus the product decisions recorded in GOOD's spec
   (scope, copy, what's in or out). For any **architectural** question the brief says
   "your call" — the point is to see what the agent chooses unaided.
4. **Grade.** A separate grader subagent sees only the spec and the checklist. It first
   describes the architecture the spec proposes for the lesson's area, then answers pass / fail
   per check, quoting the spec line it relied on. It never sees GOOD's code.

Pass: every check holds.

## Report

Details first, verdict last — the user judges the rule by what the agents actually did, not by
the tally.

```
Amendment: <file> — "<wording>"
Issue: <one sentence>        BAD <sha>   GOOD <sha>   BASE <sha>

1a  Reviewer on BAD code
    Found: <the finding, quoted, with severity and file:line — or "nothing on this">
    Verdict: pass / fail — <why, one line>

1b  Reviewer on BAD spec
    Found: <quoted>
    Verdict: pass / fail — <why>

1c  Reviewer on GOOD (control)
    Raised on the Issue's area: <quoted, or "nothing">
    Verdict: pass / fail

2   Spec from BASE
    Proposed architecture (for the lesson's area):
      <the classes / collaborators the spec introduces and what each holds>
      <its flow for that area — phases, which reads run where, what crosses between them>
      <where the other decisions the correction touched landed, e.g. which entity holds the field>
    Checks:
      ✓/✗ <check> — "<spec line relied on>"
      …
    Verdict: pass / fail — <how it differs from GOOD, if it does>

Overall: the rule works / works for review only / doesn't change behaviour — <next step>
```

On a fail: say what the agent did instead, sharpen the wording (name the concrete shape, give
the example from this feature), and re-run **only the failed run**. Don't add a second rule to
make the first one pass. Stop after two rewrites and bring it to the user.

## Cost

Check 1: 3 reviewers (+3 graders if not graded inline). Check 2: 1 writer + 1 grader. Say the
count when proposing; drop 1b or 2 when they don't apply rather than running them empty.
