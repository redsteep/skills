# spec-delta

A design spec that describes its changes in prose can't be checked against the
code. One that **lists** them can: every new name in the domain, storage, contract
and flow, one line each with its justification, plus what was rejected. Then a
review (e.g. [`design-review`](../design-review)'s drift mode) subtracts the diff
from the list, and anything left over is surface nobody asked for.

This plugin keeps specs honest about that:

- [`spec-template.md`](spec-template.md) — a template with a mandatory **Delta**
  (Domain / Storage / Contract / Flow / Rejected), plus Why, Scope, Tests, Open questions.
- A `PostToolUse` hook on `Write|Edit` — when a **new** spec (not on the default
  branch yet) misses a section of the template, or leaves one empty, the write is
  flagged back to Claude with what's missing. Older specs stay editable without a
  retrofit.

The required sections are read from the project's template itself — every `##`
and `###` heading outside code fences — so renaming or adding a section is a change
to the template only.

## Configure

Opt in per project with a checked-in `.claude/spec-delta.md`:

```markdown
- **Specs:** `docs/specs/*-design.md`
- **Template:** `docs/specs/_TEMPLATE.md`
```

`Specs` is a glob relative to the repo root; `Template` is the project's copy of
[`spec-template.md`](spec-template.md), adapted. Files named `_*` are exempt.
Without the profile, the hook does nothing.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install spec-delta@redsteep
```
