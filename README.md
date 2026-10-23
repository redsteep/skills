# redsteep/skills

A personal collection of [Claude Code](https://claude.com/claude-code) plugins.
Each plugin lives in its own folder under `plugins/` and is installed on its own,
so a project picks up only the skills — and hooks — it enables.

```
/plugin marketplace add redsteep/skills
/plugin install <plugin>@redsteep
```

## Plugins

| Plugin | What it does |
|---|---|
| [design-review](plugins/design-review) | Before a spec is committed, seven placement tests against the code it lands in — is each new name on the class that owns it; again on the branch for drift |
| [instruction-feedback](plugins/instruction-feedback) | A correction to the implementation ends with a proposed one-line amendment to the instructions, and an offer to prove it by replaying the reviewer and spec writer on the commits that made the mistake |
| [nightly-backlog](plugins/nightly-backlog) | Unattended night run — one allowed backlog item (GitHub issues by default, any store via the profile) to a draft PR, markings proposed for a few more |
| [pr-when-done](plugins/pr-when-done) | A clean worktree ahead of the default branch with no PR gets one nudge per commit to review and open it |
| [pre-pr-review](plugins/pre-pr-review) | Gated review of a finished branch — surface, E2E, architecture, tests, mutation testing — before `gh pr create` is allowed |
| [review-mode](plugins/review-mode) | While you read a PR, Claude answers and runs things but queues change requests instead of editing |
| [spec-delta](plugins/spec-delta) | Design specs list their Delta — every new name, one line each — and a hook blocks new specs that miss a template section |

## Enabling for a whole repo

Check this into the repo's `.claude/settings.json` and everyone working in it is
offered the plugin:

```json
{
  "extraKnownMarketplaces": {
    "redsteep": { "source": { "source": "github", "repo": "redsteep/skills" } }
  },
  "enabledPlugins": { "pre-pr-review@redsteep": true, "review-mode@redsteep": true }
}
```

## Layout

```
.claude-plugin/marketplace.json   lists every plugin
plugins/<name>/
  .claude-plugin/plugin.json
  README.md
  skills/ commands/ agents/ hooks/ scripts/   whatever the plugin needs
docs/reviewer-evals.md            how a reviewer plugin is measured; cases live in the project
tools/agent-eval/run.py        the runner for those evals (adapters: plugins/<name>/evals/)
```
