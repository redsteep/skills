# Design review profile

<!--
Project profile for the design-review skill. Save as `.claude/design-review.md`
and check it in. Every section is optional — a missing one falls back to the
skill's generic behaviour — but each one you fill turns a guess into a command.
Keep section names as they are: the skill and its reviewer refer to them.
-->

## Spec

- **Specs live in:** <e.g. `docs/specs/*-design.md`>
- **Current model section:** <the heading holding the model as it is now, e.g. `### Как сейчас`>
- **Change section:** <the heading holding the same model with markers, e.g. `### Что меняется`>
- **Paths section:** <the heading holding the interaction diagrams, if any>
- **Rejected section:** <where an answered finding is recorded, e.g. `### Отвергнуто`>

## Layers

Every layer a business rule can be spread over, with its paths — the reviewer
reads the slice, not one of them:

- **<name, e.g. domain>:** <paths> — <what lives here in one phrase>
- **<name, e.g. services>:** <paths> — <…>
- **<name, e.g. repositories / adapters>:** <paths> — <…>

## Containment

A command that prints the containment tree of one root, so the "as it is now"
picture can be checked instead of trusted:

```bash
<e.g. python3 scripts/containment.py <Root> 2 — the plugin ships one for Python
dataclasses at ${CLAUDE_PLUGIN_ROOT}/scripts/containment.py>
```

## Already enforced

Principles a tool already checks on every commit — the reviewer skips them
instead of spending findings on them:

- <e.g. import-linter contracts: layer direction, ORM confined to repositories, services depend on ports — so DIP and layer direction are not this review's job>
- <e.g. a linter rule, a type checker, a schema check>

## Known failures

This project's own type cases, one line each. They are what make the tests
concrete: a reviewer that can say "this is the `<X>` case again" is believed, one
that reasons from first principles every time is not.

- **Test 1 (value object / no state):** <e.g. a six-field address type that was given data belonging to what it points at>
- **Test 2 (aggregate boundary):** <e.g. the same amount booked twice because two layers each enforced "once">
- **Test 3 (language):** <e.g. a column named for a settlement date that holds the payment time>
- **Test 4 (anti-corruption):** <e.g. an external provider's vocabulary reaching the domain>
- **Test 5 (stages):** <e.g. one concept in four representations across four stages>
- **Test 6 (OCP):** <e.g. a second entry point beside an existing one; or a new case that required editing shared code>
- **Test 7 (LSP):** <e.g. an implementation whose callers must know which one they got>
