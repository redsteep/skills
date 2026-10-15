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
| [review-mode](plugins/review-mode) | While you read a PR, Claude answers and runs things but queues change requests instead of editing |

## Enabling for a whole repo

Check this into the repo's `.claude/settings.json` and everyone working in it is
offered the plugin:

```json
{
  "extraKnownMarketplaces": {
    "redsteep": { "source": { "source": "github", "repo": "redsteep/skills" } }
  },
  "enabledPlugins": { "review-mode@redsteep": true }
}
```

## Layout

```
.claude-plugin/marketplace.json   lists every plugin
plugins/<name>/
  .claude-plugin/plugin.json
  README.md
  skills/ commands/ agents/ hooks/ scripts/   whatever the plugin needs
```
