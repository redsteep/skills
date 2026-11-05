# Reviewer eval profile

<!--
Profile for the reviewer-eval plugin. Save as `.claude/reviewer-eval.md` and check it in.
Every section is optional; without one, the skill asks.
-->

## Reviewers

<!-- One bullet per reviewer: what it covers → how it is dispatched (an agent type, or a skill
     and the prompt its caller fills) → the rules files it reads. -->

- <class of defect> → `<plugin>:<agent>`, sent what `<caller>` sends → `<rules file>`

## Overlay

<!-- The files copied from the main checkout onto every replay worktree: the rules files and
     whatever imports them. -->

- `<rules file>`

## Cases

<!-- Where cases, results and the case-format description live; the tag pattern. -->

- Cases: `.claude/evals/<reviewer>/cases/<date>-<slug>.yaml`
- Results: `.claude/evals/<reviewer>/results.md`
- Tags: `eval/<reviewer>/<case-id>/before` and `/after`, pushed to origin

## Landing

<!-- How an instruction change and its eval files land: straight to the default branch, or a PR. -->
