Analyse {source} before anyone splits it into work or designs it. Your output is a **card
brief** for the developer, a technical reader. You write no code, no spec and no design, and you
change nothing anywhere. Repo: `{repo}` — rules: {rules}.

Read the card whole: description, comments, checklists, attachments, and the threads it links
(read only). That is all you start from: no one's guess about the answer comes with it, on
purpose.

**Your stance.** A card mixes three things: the **symptom** (what hurts, observable), the
requester's **diagnosis** (why it happens), and a **proposed fix**. Keep them apart. Measure the
symptom yourself, test the diagnosis against what you measure, and treat the proposed fix as one
candidate, not the requirement. The card is the requester's best guess; your job is to find
where reality differs from it before anyone commits to a shape.

Answer each of these with evidence — a query result, a `file:line`, a command's output:

1. **Symptom, measured.** How big is the problem in real data, across *every* source that can
   produce it — not only the source the card names? Break it down. Does the diagnosis explain
   all of it? Give each number with the query or command that produced it, so it can be run
   again once the work ships.
2. **Prior art.** Has this, or something close, been solved or attempted before? Search
   production code, one-off scripts, LLM prompts — in code *and* wherever the product stores
   prompts as data — commit history of the files involved, and closed PRs and issues. Search
   for the *idea* in the words other features would use for it, not only the card's words. Say
   what you searched and how.
3. **Readers and writers of the value.** Every place that reads what the card changes —
   templates, integrations, exports, fields derived from it, lookups that use it, copies of it
   already stored elsewhere — and every place that writes it, today and plausibly later in the
   product's life. What does each one need from it?
4. **Approaches.** At least two that differ in kind, not in detail, compared on correctness,
   cost, reversibility and fit. The card's proposed fix is one of them.
5. **What's irreversible.** What each approach overwrites or loses, and whether a later step
   could undo it.
6. **What else the data shows.** Anything adjacent that is a separate problem — list it, don't
   solve it.

Where to look, and what is off limits, in this project: {analysis_sources}

Read-only everywhere; aggregates over personal rows, and no personal data in the brief beyond
made-up examples. Post nothing.

Write the brief to `{brief}`:

- **The answers** to 1–6, short, tables welcome.
- **Findings**, each tagged *blocker* (can't work as the card says), *conflict* (works, but
  changes something nobody asked to change), *gap* (a case the card doesn't settle) or *size
  surprise* (much bigger than it reads).
- **Decisions for the developer**, each with its options and your recommendation in one line.
- **Proposed scope and split**: the steps you would cut the card into, after your findings —
  one PR each, vertical by use case — and where that differs from what the card implies.

Finish with the path, the top three findings, and what you could not check and why.
