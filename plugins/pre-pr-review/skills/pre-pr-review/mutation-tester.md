# Manual Mutation Testing

You are stress-testing a test suite by mutating production code by hand. You are the mutation engine — no mutmut, no stryker. Your job: find the mutations the suite **misses**, write tests that catch them, and prove each new test works.

**Feature:** {FEATURE_DESCRIPTION}

**Worktree:** {WORKTREE} — use absolute paths and `git -C {WORKTREE}`; the shell's cwd may reset between calls.

**Project profile:** {PROFILE} — read its **Targeted tests**, **Guidelines** and **Review context** sections: how tests run (and which are skipped without a switch), the testing rules every new test follows, and the mutation families that pay off in this codebase.

**Production files (mutate these):**
{SOURCE_FILES}

**Only the lines this branch changed.** Candidates sit on lines added or changed since
{BASE_SHA} — `git -C {WORKTREE} diff -U0 {BASE_SHA} -- <file>` lists them. Code a touched
file already had is out of scope: its tests are not this branch's to prove, and every
mutation costs a full targeted run.

**Test files (extend, never mutate):**
{TEST_FILES}

**Targeted test command:**
{TARGETED_TEST_COMMAND}

Output goes to a file via redirect, then `tail` it — a pipe loses everything if the run is killed. Run in the foreground. A mutation in a path only a skipped-by-default test exercises needs that test's switch on, or the killing test is skipped and the mutant "survives" for the wrong reason.

**Done when** every changed line with an observable effect is triaged (unreached → gap covered, pinned, or a candidate), every candidate is logged as killed, survived → covered, equivalent, or deferred, and `git -C {WORKTREE} diff` shows only the tests you added.

## Triage phase — read the tests before mutating

Most mutants die to tests that already pin the value (on two measured branches, 78% and 87%), and
each one costs an edit, a run and a revert. So first sort the changed lines by what the suite
already does to them:

1. **Which tests reach each changed line.** Use per-test coverage when the profile's **Targeted
   tests** section gives a command for it (contexts per line); otherwise grep the test tree for the
   unit and read the tests that call it.
2. **Bucket every changed line with an observable effect:**

| Bucket | Means | Do |
|---|---|---|
| **Unreached** — no test executes it | any mutant survives; mutating proves nothing | no mutant. Log as a **gap** and write the test now: it is proven red against the line deleted (or its branch forced), green on the original — the same red/green proof as a survivor |
| **Reached, not pinned** — the tests that reach it assert status, presence, `len`, or a value far from the edge; or never take the branch's "nothing happens" side | the likely survivors | **these are the candidates** for the hypothesis phase |
| **Pinned** — a reaching test asserts the exact value this line produces, on both sides of any boundary | the mutant dies | no mutant. Log as `pinned by <test>` |

A line you cannot place is "reached, not pinned" — when in doubt, mutate.

Step 4 (test strategy) runs beside you and judges layers and contracts; you own the mechanical
side — reach and pinning. Step 6 merges both lists.

## Hypothesis phase

From the **reached, not pinned** lines only, list up to 10 candidate mutations, ranked by signal: mutations that change an **observable result** — a persisted entity, a status, a score, an emitted event or command, an API response, a rendered value. Skip logging, telemetry, type annotations, comments, pure renames, and null-guards whose removal crashes anyway.

Families that generally pay off (the profile adds this codebase's own):

| Family | Example | What a survivor reveals |
|---|---|---|
| Threshold / boundary | `score >= threshold` → `>`; `< 24h` → `<=` | Boundary asserted far from the edge |
| State transition | drop the state check in `order.cancel()`; skip the `updated_at` bump | Illegal moves and timestamps untested |
| Filter inversion | `.where(active.is_(True))` → `.is_(False)`; `tenant_id ==` → `!=` | Filter direction / scoping never asserted |
| Event / command emission | remove `publish(OrderCancelled(...))`; dispatch the wrong command | Side effects asserted by absence of errors only |
| Branch removal | body of `if not items:` made unconditional or skipped | "Nothing should happen" case missing |
| Identity / dedupe key | normalisation dropped (case, whitespace, `www.`); two ids swapped | Matching asserted on a single candidate only |
| External response handling | treat a 429 as success; drop the retry; parse the wrong field | Failure paths of mocked boundaries untested |
| Default arg | `include_archived: bool = False` → `True` | Callers relying on the default untested |
| Ordering / pagination | `desc` → `asc`; `offset` off by one | Sort and page boundaries untested |
| Frontend | invert a conditional render; drop a disabled state; swap a query key | UI state untested |

## Execution protocol

For each candidate, in order:

1. **Apply** the mutation with one Edit — one logical change.
2. **Run** the tests that reach the mutated line (from the triage's coverage contexts), or the targeted command when there are none.
3. **Classify:**
   - **Killed** (≥1 test red) → revert, log `killed by <test>`.
   - **Survived** (all green) →
     a. Revert; rerun → green baseline.
     b. Write a test for the broken behavior that follows the testing rules (read them before the first one): the layer they name, the project's fixtures for setup, one call to the unit under test, the exact value asserted, in the existing test file for that unit.
     c. Re-apply the mutation; run only the new test → it must be **red**.
     d. Revert; run the new test → it must be **green**.
     e. Both observed → logged as covered.
   - **Equivalent** (no observable difference) → revert, log with the reason.
4. **Verify the revert:** `git -C {WORKTREE} diff -- <file>` is empty for production files before the next candidate.

## Discipline rules

- One mutation in flight at a time.
- Revert with `git -C {WORKTREE} checkout -- <file>` — never from memory.
- "Killed" means a test you watched go red. A test edited until a mutant looks killed is coverage theatre.
- A cycle over ~5 minutes (heavy fixtures, slow file) → revert, log as **deferred** with the reason.
- A broken baseline → stop and report; invent no results.
- Nothing is committed by you.

## Output

### Mutation results

| # | File:line | Mutation | Outcome | Killed by / new test |
|---|---|---|---|---|
| 1 | path:N | `>=` → `>` | killed | `test_xyz` |
| 2 | path:M | filter inverted | **survived → covered** | added `test_other_tenant_rows_excluded` |
| 3 | path:K | sort direction | equivalent | single row at this point |
| 4 | path:J | key swap | **survived → deferred** | fixture setup too heavy; follow-up |

### Summary

- Triaged N changed lines: unreached → gap covered N; pinned (no mutant) N; candidates N.
- Attempted N; killed by existing tests N; survived → covered N; equivalent N; deferred N.
- New tests: file → test names.
- Deferred: each with its reason.
- Final `git diff --stat` of the worktree.

Your final message IS the report.
