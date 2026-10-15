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
The built-in ones are English; a project writing in another language adds its own
with a `- **Markers:** \`<regex>\`` line in its profile (below).

## Where lessons go

Each project says where each kind of lesson belongs in a checked-in
`.claude/instruction-feedback.md`, shown to Claude verbatim (see
[`profile-template.md`](profile-template.md)). Without one, the map is generic:
project conventions → the instructions file the project loads; process and
preferences → memory.

## Install

```
/plugin marketplace add redsteep/skills
/plugin install instruction-feedback@redsteep
```
