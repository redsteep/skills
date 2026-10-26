---
name: pre-pr-review
description: Gated review of a finished feature branch — E2E, architecture, test strategy, mutation testing, refactor, PR. Use when implementation is done, before `gh pr create` or a merge.
---

# Pre-PR Review

Gated review after a feature lands on its branch: behavior, architecture, tests, then cleanup. Every step ends on a gate with evidence; a gate passes on output you saw, not on judgement.

**Announce at start:** "I'm using the pre-pr-review skill to review this feature."

**Not for:** trivial fixes, docs-only changes, dependency bumps — review them lightly, then open the PR with the `REVIEWED=1` prefix and name the exemption in the PR body.

This plugin's `PreToolUse` hook denies `gh pr create` without the `REVIEWED=1` prefix, so this review is the road to every PR.

## Dispatching this plugin's agents

Steps 2–4 dispatch the plugin's own agents: `pre-pr-review:architecture-reviewer`, `pre-pr-review:test-reviewer`, `pre-pr-review:mutation-tester` (`agents/` in this plugin — each one's procedure is its definition). You do not write their prompt. Call the Agent tool with the agent's `subagent_type` and a prompt of `key: value` lines only:

```
worktree: <absolute path>            # required — step 4: the mutation copy
spec: <path relative to the worktree> # the feature's spec, when it has one
base: <sha>                          # re-review rounds: the `Reviewed at` sha
test_command: <one line>             # mutation-tester only, required
```

A `PreToolUse` hook replaces that prompt with the input `scripts/reviewer-inputs.py` generates — feature (the spec's title and path), worktree, profile, base, head, the source and test files as step 0 builds them — and drops everything else. A summary of the change, what an earlier round fixed, where to look: none of it reaches the agent, by design. In replays of real rounds, that framing made the test reviewer miss what it found every time from its bare procedure. A dispatch without the required keys is denied, with the format in the reason.

## The project profile

Everything project-specific — which paths are production code, how to run a targeted test, which steps it attaches at the extension points, where the rules live, how to bring the app up — comes from the **project profile**, `.claude/pre-pr-review.md` in the repository. Its sections are named; this skill refers to them as **Profile → Section**:

| Section | Holds |
|---|---|
| Layout | source paths, test paths, how to find the tests covering a unit — and a `pre-pr-review-layout` block the input generator reads (`source_prefixes`, `test_dirs`) |
| Targeted tests | the command per package, and the traps that make a run look green when it is not |
| Extensions | the project's own steps, attached to the skill's extension points (migrations, generated code, a check against production data…) |
| Contract | where specs live and which section of a spec is the contract |
| Guidelines | the code-rules file, the testing-rules file, and where new rules go |
| E2E | when it applies, how to start the app, auth, tools, visual reference, where screenshots go |
| Review context | project-shaped hints for the reviewers: duplicate shapes, layer → rules map, mutation families |
| Final checks | lint / type-check / pre-commit, regenerated artifacts |
| PR | how the PR is opened, what its body carries, what to hand over after |

**Read the profile in full before step 0.** A section the profile leaves out falls back to the generic behaviour described below.

## Extension points

A project adds its own steps without editing this skill: each entry in **Profile → Extensions** is attached to one named point, and runs there.

| Point | Runs | Typical use |
|---|---|---|
| `after-setup` | end of step 0, on the baseline | migrations round-trip, schema or codegen checks |
| `before-pr` | end of step 6, on the code that ships | slow or expensive checks — a regen against production data, a long build |
| `pr-body` | step 7, while writing the body | what the project's PRs must carry |
| `after-pr` | after the PR is open | hand-over, cleanup |

Each entry has:

- **When** — a path list matched against the diff; omitted, the entry always runs. Intersect mechanically — a list, not a judgement made once per branch ("this change can't move the numbers" is what the step is for).
- **Do** — the commands, or the runbook (a skill, a doc) to follow.
- **Gate** — what output passes. An extension's gate is a gate of this review like any other: it passes on output you saw, and a failure stops the review.
- **Unattended** — what a run nobody is watching (a headless or scheduled session) does with it: `run` (default), `draft` — do not run it; open the PR as a draft that names it as the open gate (step 7), or `skip` — do not run it; say so in the PR body.

Several entries at one point run in the order the profile lists them.

**No profile?** Infer what you can from the repo (`package.json`, `pyproject.toml`, `Makefile`, CI workflows, `CONTRIBUTING.md`, `CLAUDE.md`), tell the user what you inferred, and offer to write it as `.claude/pre-pr-review.md` from `profile-template.md` in this skill's directory — a profile is checked in so the next review does not re-infer it. Do not run the review on guessed commands without saying they are guessed.

## Step 0: Setup — Main Agent

Work in the feature's worktree when there is one; address it with `git -C <worktree>` and absolute paths (a shell's cwd may reset between calls).

The base is the branch the PR will target — **Profile → Layout** names it; generic: the remote's default branch, `git -C <worktree> symbolic-ref --short refs/remotes/origin/HEAD` (e.g. `origin/main`).

```bash
BASE_SHA=$(git -C <worktree> merge-base HEAD <base>)
HEAD_SHA=$(git -C <worktree> rev-parse HEAD)
git -C <worktree> diff --stat $BASE_SHA..$HEAD_SHA
```

From the diff build three lists, reused by the steps you run yourself (the agents get the same lists from the input generator):

- **SOURCE_FILES** — changed production files, per **Profile → Layout** (generic: everything that is not a test, doc, fixture or config).
- **TEST_FILES** — changed test files, plus the existing test files covering each changed source module (find them by the unit under test: grep the test tree for the handler, class or function name).
- **TARGETED_TEST_COMMAND** — the test runner over TEST_FILES, built per **Profile → Targeted tests**: one command per package, each from its own directory and environment, output redirected to a file and `tail`ed — a pipe loses everything if the run is killed.

**An empty TEST_FILES is the trap.** Most runners given no paths run the whole suite and report green, so an accidental full run looks exactly like a passing targeted one. Never run the command with an empty list, and read the scope out of the output (e.g. `pytest --collect-only -q <files> | tail -1`) rather than assuming it.

**Skipped is not passed.** When the profile names tests that are skipped unless some switch is set (a real database, a service, a credential), and the diff touches what they cover, rerun with the switch and read the skip count in the summary.

Run in the foreground; the full suite belongs to CI.

**Gate:** the targeted command runs green on HEAD. A broken baseline stops the review.

### Extension point: `after-setup`

Run the triggered `after-setup` entries now and hold each to its gate. Reading a migration or a schema change is not running it.

## Steps 1–3: one dispatch — three subagents at once

Nothing connects them: step 1 feeds nothing, step 2 feeds step 6, step 3 feeds step 5. Send all three in a single message so they run concurrently — and step 4 in the same message, in its own worktree (see step 4). E2E is the long pole of this block; mutation waiting for it doubles the wall time for nothing.

Start the app before dispatching — step 1 needs a URL to open. Steps 2 and 3 only read.

### Step 1: E2E in the browser — subagent

**Skip only when** the branch changes nothing a user can see — per **Profile → E2E** (generic: no frontend files changed) — and still run it when a backend change alters a response the UI renders.

Bring the app up from the worktree as **Profile → E2E** describes (ports, auth, data, which dev-server script). Never point a dev backend at production.

Dispatch a `general-purpose` agent with: the feature description, the app URL, the prototype/spec if any, and these instructions:

1. Use the browser tool the profile names (generic: Playwright MCP). Hard-reload before the first check.
2. Compare the UI against the spec/prototype; flag discrepancies.
   **Styling vs the visual reference** (its own pass — a behaviour walk-through never catches it): when **Profile → E2E** names a reference (a prototype app, a design file, screenshots), screenshot the same element in both at the same viewport, then list every difference under: copy, layout and spacing, typography (size/weight per text role), colour and tone per state, icons and control style, interactions. A deviation is a finding unless the PR names it as deliberate.
3. Walk the happy path, then edge cases, empty states, boundaries and error paths.
4. Report concrete evidence: accessibility-tree nodes, the exact URL after each step, evaluated DOM values. Screenshots go under an **absolute** path that is never committed (Profile → E2E, generic: the session's scratch directory) — a relative name lands wherever the browser tool's process happens to run.
5. "Your final message IS the report."

### Step 2: Architecture review — `pre-pr-review:architecture-reviewer`

Dispatch it with `worktree:` and `spec:` (see "Dispatching this plugin's agents").

### Step 3: Test strategy — `pre-pr-review:test-reviewer`

Dispatch it with `worktree:` and `spec:`.

Step 3 owns the judgement on tests — the right layer, each contract once, the testing rules. Step 4 owns the mechanical side — which changed lines no test reaches, which values no assertion pins. They run side by side and may name the same gap; step 5 fixes it once.

### Joint gate — all three reports in hand

A partial dispatch is not a pass: wait for all three, then check each criterion.

- **Step 1** — every flow works and matches the spec, backed by the evidence above.
- **Step 2** — no Critical or Important violations. **Findings go to step 6.**
- **Step 3** — each contract tested once, at the right layer. **Findings go to step 5.**

One failed criterion stops the review; the other two reports stay valid and are not re-run when that one is fixed.

A report's **issue count is not its content**: an observation a reviewer raised and then labelled acceptable, deliberate or out of scope is a finding without a verdict, so decide it in step 5 or 6 and say the decision, or carry it to the user — never relay the count and drop the note.

The reviewers check against the rules files in **Profile → Guidelines** — the same files the project loads while the code is written. Their **Missing rules** go to the user as proposed amendments to those files (file + wording), not into the PR and not into a reviewer prompt; a rule that lives only in a reviewer is invisible while the code is written.

## Step 4: Manual mutation testing — `pre-pr-review:mutation-tester`

Mutation edits production code, and steps 1–3 read the feature's worktree — the E2E app serves from it. So step 4 runs in **a second worktree at the same commit**, dispatched together with steps 1–3:

```bash
git -C <worktree> worktree add --detach <worktree>-mutation HEAD
```

prepared the way **Profile → Layout** says a new worktree is (env files, package installs). Dispatch the agent with `worktree:` that path, `spec:`, and `test_command:` the targeted command pointed at the copy. When the agent is done, bring its tests back and drop the copy:

```bash
git -C <worktree>-mutation diff HEAD > <scratch>/mutation.patch   # tests only — the gate checks no residue
git -C <worktree> apply <scratch>/mutation.patch
git -C <worktree> worktree remove --force <worktree>-mutation
```

then run the targeted command in the feature's worktree — the tests must pass there, not only in the copy. If a second worktree cannot be prepared (the profile says how, or it fails), run step 4 after the joint gate in the feature's worktree, alone.

Step 5 starts only after the patch is applied — both write tests.

The agent is the mutation engine (not mutmut or stryker): it applies the mutations the suite is most likely to miss, one at a time, and for every survivor writes a test proven **red** on the mutant and **green** on the original. The discipline rules in its definition are the protocol; if one slips, restart the step.

The subagent triages before it mutates: changed lines no test reaches become gaps with a test written straight away (no mutant needed), lines a test already pins are skipped, and only the rest are mutated — up to about 10. On two measured branches 78% and 87% of mutants died to existing tests; those runs are what the triage removes.

**Gate:** every gap and every survivor has a test proven red/green, or is justified as equivalent / deferred with a reason; `git diff` shows no mutation residue. **Save findings for step 5.**

## Step 5: Refactor tests — Main Agent

Apply findings from steps 3 and 4, then read every TEST_FILE against the testing rules (Profile → Guidelines) yourself: dedup, naming, shared setup through the project's fixtures/factories, assertions on values rather than presence, tests moved up to the public entry point. Behavior stays fixed. Rerun the targeted command after each change.

**Gate:** targeted tests green after the last change.

## Step 6: Refactor production code — Main Agent

Apply findings from step 2, then read every SOURCE_FILE yourself against the code rules (Profile → Guidelines) and for naming, structure and simplification. Behavior stays fixed. Rerun the targeted command after each change.

**Gate:** targeted tests green, and every command in **Profile → Final checks** clean over the branch — they are what CI runs (generic: the repo's pre-commit / lint / type-check over the changed files). Regenerated artifacts the profile names are committed in the branch.

Then run the triggered `before-pr` entries — last, because they check the code that ships, not code steps 4–6 were still changing.

## Step 7: Open the PR — Main Agent

All gates above passed with evidence → commit the step 4–6 changes (logical commits, not one per mutation), push, and open the PR with the prefix the hook expects:

```bash
cd <worktree> && REVIEWED=1 gh pr create --title "..." --body "..."
```

`git add` explicit paths, never `-A` — nothing stray (local env files, scratch output) rides into the PR. Put a short review summary in the PR body: the ticket or issue, steps skipped and why (e.g. "no UI → step 1 skipped"), mutation counts (killed / covered / equivalent / deferred), each extension's verdict — plus anything **Profile → PR** and the `pr-body` entries ask for.

### The PR exists as a spec-only draft → finish it

A workflow that opens the PR before any code — a draft holding only the design spec, opened
for the spec's approval (the `factory` plugin does this) — reaches the first round with the PR
already there. End it like the first round, except: commit, push, replace the draft's body
with the review summary (keep its spec link and approval record), then `gh pr ready`
instead of `gh pr create`. `enter-review-after-pr.sh` fires only on `gh pr create`, so turn
review mode on yourself when the caller wants it. A draft that still holds only the spec is
the one case where the PR predates the review; everything else about step 7 holds.

### The PR already exists → update it

A re-review round (after a review iteration's queued fixes landed) ends the same way except
for the last command: commit, push, and append this round's summary to the PR body with
`gh pr edit --body` — no `gh pr create`. End every summary, first round included, with
`Reviewed at <HEAD_SHA>`: the next round starts from it. Then hand the branch back to review
mode (`review-mode.sh on <worktree>`) when that plugin is enabled.

## Re-review rounds — review what the round changed

The first round reviews the branch. A later round reviews the **round's diff**: from the
`Reviewed at` SHA in the PR body (ROUND_BASE) to HEAD. Everything outside it was reviewed
and has not moved; re-running a step on it pays the step's full cost to re-confirm a
verdict already on record — and the browser and mutation steps are most of what a round
costs.

Build ROUND_SOURCE_FILES and ROUND_TEST_FILES from `git diff ROUND_BASE..HEAD` as step 0
does for the branch. Then each step runs only when its trigger is in the round's diff, over
that diff:

| Step | Runs when the round's diff… | Scope |
|---|---|---|
| 0 | always | targeted command over the branch's TEST_FILES — the round can break old tests |
| 1 E2E | meets step 1's own trigger (user-visible files, a response the UI renders) | the flows those files drive |
| 2 Architecture | touches ROUND_SOURCE_FILES | dispatched with `base:` ROUND_BASE |
| 3 Test strategy | touches ROUND_SOURCE_FILES or ROUND_TEST_FILES | dispatched with `base:` ROUND_BASE — the round's files |
| 4 Mutation | touches ROUND_SOURCE_FILES | dispatched with `base:` ROUND_BASE, so only the round's lines |
| 5–6 | always | the round's files |
| Extensions | their **When** list matches the round's diff | as defined |

A test-only round is steps 0, 3 and 5. Name every skipped step and its reason in the
round's summary, as step 7 does.

**Back to the whole branch** when the round changes the public API surface (endpoint,
response shape, generated types) or a shared module many files depend on, or when the PR
body has no `Reviewed at` line — the same bar as Re-verification below.

### Architecture only — `only=architecture`, then a normal first round

For code that exists before anyone signed off its shape — a PR adopted by the `factory` plugin,
written outside the workflow — the caller may ask for the architecture verdict alone first, so
a reviewer's verdict on the shape comes before money is spent testing code that may be
restructured. Run **step 2 alone**: no step 0 baseline, no E2E, no test reviewer, no
mutation, no fixes. Dispatch `pre-pr-review:architecture-reviewer` with `worktree:` (and
`spec:` if the PR has one) — its input generator builds the file lists itself. Report the
findings to the caller, add `Architecture reviewed at <HEAD_SHA>` to the PR body, and stop.
Several PRs that are one design (a stack): run it once, in a worktree of the top PR's branch —
its diff from the base holds them all — and attribute each finding to the PR it lands in.

The later full review is a normal first round, except for step 2: it runs only when production
code changed since that SHA, and then over that diff only (`base:` the SHA), as a re-review round
does.

### An extension marked `Unattended: draft` → a draft PR, not a held branch

When an unattended run reaches step 7 with such an extension triggered and not run, it opens the PR with `--draft`. The body names it in as many words — which extension, which paths triggered it, what was not run — and undrafting requires it, clean. A draft cannot be merged, so the gate has moved from before the PR to before the merge, not away. This is the only gate that may stand open at PR time, and only as a draft: a finished branch held without a PR leaves its reports unread and blocks whoever comes next.

### Hand the app over — whenever step 1 ran

A passing E2E subagent is not the user seeing it. Right after the PR is open, leave the step 1 app up (or start it again) and hand over the URL — the user looks with their own eyes before the merge.

- Run it in the background so it outlives the turn; report the URLs and ports.
- Name the screens and flows the branch changed, and anything it cannot show (a state that needs production data, a flow behind a feature flag). "The app is up" without a route to click is not a hand-off.
- Leave it running until the user says they are done, then stop the **processes** — a dev server outlives its worktree and holds the port. Prove it is gone (`lsof -nP -iTCP -sTCP:LISTEN` on the ports you used).

Then run the triggered `after-pr` entries.

## Re-verification

- Default: rerun only the failed gate.
- Rerun steps 1–4 when a fix changes the public API surface (endpoint, response shape, generated types) or touches more than 3 files.

## Gate discipline

| Excuse | Reality |
|--------|---------|
| "Unit tests cover the UI" | They miss wiring, auth and render paths |
| "Architecture looks fine from the diff" | Read the files the diff touches |
| "Step 3 already covered the tests" | Step 4 measures it — watch what survives |
| "Nothing to refactor" | Decide after reading every SOURCE_FILE |
| "The reviewer reported 0 issues" | Read the report, not its count — a note it cleared is still your call |
| "This change can't trigger that extension" | Its path list decides, not the reviewer |
| "Green" (with skips) | Skipped tests are not passing ones — count them |

## Integration

**Called after:** implementation is done — a plan executed by agents or a hand-built feature branch.
**Called again:** after each review iteration's queued fixes are applied — a round over what the iteration changed ("Re-review rounds"), ending in "The PR already exists".
**Followed by:** review mode, if the `review-mode` plugin is enabled — it turns on automatically after `gh pr create`.
