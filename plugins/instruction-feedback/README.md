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

## Proving an amendment works

A rule can read well and change nothing. With an amendment that changes an architectural
guideline (and only then), the note also has Claude **offer** the `verify-amendment` skill, which replays the past in throwaway worktrees with
the amendment overlaid:

1. **Reviewer** — on the commit that made the mistake, the review must now flag it in the
   code and (if it was planned there) in the spec; on the fixed commit it must stay quiet.
2. **Spec writer** (architectural lessons only) — one run designs the feature again from
   the pre-feature commit with a scripted user who leaves architecture to the agent; a grader
   describes the architecture it proposed and checks it against binary checks taken from the
   fixed commit.

The report shows what each agent actually found or proposed, then a pass/fail verdict. It
runs on your yes, not by default.

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
