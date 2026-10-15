# instruction-feedback

A correction you make once should not be needed twice. When your message reads as
a correction to the implementation — "why is this here?", "no need", "remove it",
"revert", "I didn't ask for…", "over-engineered" — a `UserPromptSubmit` hook adds a
note: fix it, then end the reply with **one line** about the instructions:

- a concrete proposed amendment — the file and the wording, or
- "one-off, no rule follows".

Claude proposes; it never amends instructions silently.

The markers are deliberately narrow so the hook doesn't fire every turn. Widen
them from real transcripts, not by guessing.

## The project profile

A checked-in `.claude/instruction-feedback.md` overrides any of the hook's three
parts — start from [`profile-template.md`](profile-template.md):

| Section | Overrides | Default |
|---|---|---|
| `## Markers` | when the hook fires — regexes, one per bullet; `- **Mode:** replace` drops the built-in ones, otherwise they are extended | English markers only |
| `## Reply` | what Claude is told to do, in the project's language | one line: an amendment (file + wording) or "one-off, no rule follows" |
| `## Map` | where each kind of lesson belongs | project conventions → the instructions file; process and preferences → memory |

A section left out keeps its default. A profile from 0.1 (a plain list, no
sections) is still read as the map.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install instruction-feedback@redsteep
```
