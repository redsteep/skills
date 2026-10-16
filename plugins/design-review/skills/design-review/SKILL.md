---
name: design-review
description: Adversarial review of where a design puts things — seven placement tests (value object vs entity, aggregate boundary, ubiquitous language, anti-corruption layer, translation between stages, OCP, LSP) read as a slice across every layer of the code it lands in. Use it whenever a design spec has just been written, edited or had its Delta amended, before the spec is committed and before any code is written for it — even when the user only says "commit the spec", "the delta looks done" or "let's start implementing", that is exactly the moment (mode `proposal`). Also use it when someone asks whether a field, type or rule sits on the right entity or layer, whether a new mechanism duplicates an existing one, or whether an external system's vocabulary leaks into the domain. On an implemented branch that has a spec, run it before the pre-PR review to check the code kept the promised shape (mode `drift`). Not for writing a spec, reviewing tests, hunting bugs in a diff, or judging whether a feature is worth building.
---

# Design review

The review most pipelines are missing. A diff-vs-spec subtraction catches a name
nobody asked for — but the spec is the author's own claim, so a field on the
wrong class is written down, approved as prose, and confirmed as matching. Three
green gates, wrong placement. This is the adversary that contract needs.

**Announce at start:** "I'm using the design-review skill on <spec>."

**One question only: structure.** Whether the feature is worth doing is the
owner's call; whether every surface is declared is the subtraction's job; tests
and style belong to later reviewers. Narrowing it is what makes it sharp.

**Not for:** a change with no spec. If the design fit in a chat message, it was
small enough not to need this.

## Profile

Everything project-specific comes from **`.claude/design-review.md`** in the
repository — copy `profile-template.md` and fill it in. Without a profile the
skill still runs, but it guesses the spec's sections and has no containment
command, no known failures and no list of what tools already enforce, so expect
weaker findings.

## Run it

1. Find the spec: changed in this branch, or named by the user. The profile says
   where specs live and which section holds the model.
2. Read `design-reviewer.md`, fill `{SPEC_PATH}`, `{REPO}`, `{PROFILE}` and
   `{MODE}` (`proposal` before code, `drift` on the implemented branch), and
   dispatch one `general-purpose` agent. One agent: the seven tests read the same
   slice of code, and splitting them multiplies the reading for nothing.
3. Put the report in front of the user, findings first. Do **not** act on it in
   `proposal` mode: the findings are about a design they have not approved yet,
   and the point is that they decide.

## Gate

The spec is ready when every finding is either applied to it or answered in it —
a rejected finding goes into the spec's "rejected" section with its reason, so
the next reader does not raise it again.

A finding on the current-model picture is special: if it is wrong, everything
derived from it is suspect. Fix the picture and re-run rather than answering the
downstream findings one by one.

In `drift` mode a divergence is either brought back to the spec during the
branch's refactor step, or the spec is amended out loud in the same branch —
never left silent.

## Calibration

Point it at corrections the owner has already made, where the answer is known,
before trusting it on a fresh design. On the project it was built for, nine known
placement errors gave five clear hits, one weak, two misses and one case
deliberately out of scope — and the two misses (a redundant method, a second
mechanism beside an existing one) are why tests 1 and 6 read as they do.
