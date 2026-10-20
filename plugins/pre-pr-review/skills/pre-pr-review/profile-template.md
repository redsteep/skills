# Pre-PR review profile

<!--
Project profile for the pre-pr-review skill. Save as `.claude/pre-pr-review.md`
and check it in. Every section is optional — a missing one falls back to the
skill's generic behaviour — but each one you fill turns a guess into a command.
Keep section names as they are: the skill and its reviewers refer to them.
-->

## Layout

- **Base branch:** <the branch PRs target, e.g. `origin/main` — default: the remote's default branch>
- **Source:** <globs of production code, e.g. `src/**`, `app/**`, `migrations/**`>
- **Tests:** <globs of test code, e.g. `tests/**`, `**/__tests__/**`>
- **Tests covering a unit:** <how to find them, e.g. `grep -rln "<symbol>" tests/`>
- **Worktrees:** <where feature worktrees live and how they are made, if any>

The agents' input generator reads this block (path prefixes of production code; directory names
that hold tests). Without it, every changed file that is not a test, doc or config counts as source.

```yaml pre-pr-review-layout
source_prefixes: [<e.g. src/, app/, migrations/>]
test_dirs: [tests, __tests__]
```

## Targeted tests

One command per package, from that package's directory, over the given files:

```bash
<e.g. cd <worktree>/api && poetry run pytest <files> -q > <scratch>/tests-api.out 2>&1; tail -30 <scratch>/tests-api.out>
```

Traps:
- <tests skipped unless a switch is set — the switch, and when the diff makes it necessary>
- <commands that never return (watch mode) and their one-shot form>

## Extensions

<!-- Points: after-setup · before-pr · pr-body · after-pr (see SKILL.md § Extension points).
     Unattended: run (default) · draft · skip. -->

### <point>: <name, e.g. after-setup: Migrations>

- **When:** <paths in the diff, e.g. `migrations/**` — omit to always run>
- **Do:** <commands, or the skill / doc to follow>
- **Gate:** <what output passes>
- **Unattended:** <omit for `run` | `draft` | `skip`>

## Contract

- **Specs live in:** <dir>
- **Contract section:** <e.g. `## Delta`, `## Scope`> — template: <path, if any>

## Guidelines

- **Code rules:** <path(s)>
- **Testing rules:** <path(s)>
- Rules may be path-scoped (`.claude/rules/*.md` with `paths:`): they load when a matching file is opened. List them here anyway — a reviewer reads what the profile names.
- New rules proposed by reviewers go to: <those files / an issue / the user>

## E2E

- **Applies when:** <e.g. any change under `web/`, or an API response the UI renders>
- **Start the app:** <commands, ports, env, seed data>
- **Auth:** <how a test session logs in — never production credentials>
- **Browser tool:** <e.g. Playwright MCP>
- **Visual reference:** <prototype / design files and how to serve them>
- **Screenshots:** <absolute dir>

## Review context

- **Duplicate shapes:** <abstractions that already exist and get re-invented here>
- **Layer → rules sections:** <path → section of the code-rules file>
- **Severities:** <what counts as Critical / Important here>
- **Mutation families:** <codebase-specific examples>

## Final checks

```bash
<lint / type-check / pre-commit over the branch>
```

- Regenerated artifacts that must be committed: <e.g. generated API client>

## PR

- **Body carries:** <ticket link, skipped steps, mutation counts, extension verdicts>
- **Hand-over:** <how the app is left running for the user, ports to free afterwards>
- **Never:** <e.g. `git add -A` because of symlinked env files>
