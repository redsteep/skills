# Instruction feedback profile

<!--
Profile for the instruction-feedback plugin. Save as `.claude/instruction-feedback.md`
and check it in. Every section is optional: a missing one keeps the built-in
behaviour. Keep the section names — the hook reads them.
-->

## Markers

<!-- Extended regexes, one per backticked bullet, matched case-insensitively.
     Mode: extend (default) adds them to the built-in English markers; replace drops those.
     Measure them on real transcripts — a marker that fires every turn is noise. -->

- **Mode:** extend
- `<e.g. why on earth|take it out>`

## Reply

<!-- What Claude is told when a marker fires. Default: end the reply with one line —
     a proposed amendment (file + wording) or "one-off, no rule follows". -->

## Map

- code convention, layer, type → <path to the code rules file>
- how a test is written or where it lives → <path to the testing rules file>
- what a spec must declare → <path to the spec template>
- what a reviewer should look for → <the rules files above, if reviewers read them>
- process and the user's preferences → memory
