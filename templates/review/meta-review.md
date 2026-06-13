# Meta-Review — {{title}}

*Paper: {{paper_ref}} · Ensemble: {{n}} fresh-context reviewers · Date: {{date}}*

## Score aggregation

Aggregate as **median (min–max)** per dimension — never the mean (means re-inflate
toward leniency). One row per rubric dimension + Overall.

| Dimension | Median | Range | Notes |
|---|---|---|---|
| Originality | | | |
| Quality | | | |
| Clarity | | | |
| Significance | | | |
| Soundness | | | |
| Presentation | | | |
| Contribution | | | |
| **Overall** | | | |

## Fatal flaws & minority veto

List every `FATAL FLAW:` raised by any reviewer. **Any unrefuted fatal flaw blocks an
accept decision** — even if the other reviewers scored high. To override a flag, write
the refutation here with specific evidence (artifact, table, prior-work citation); an
implied or hand-waved refutation does not count.

| Reviewer / lens | Flaw | Refuted? | Written refutation (evidence) |
|---|---|---|---|

## Synthesis

<!-- 1-2 paragraphs: where reviewers agree, where they conflict and why, what the
     decisive considerations are. Reconcile contradictions explicitly. -->

## Decision

**accept / minor revision / major revision / reject**
(accept requires: median Overall ≥ `critique.accept_bar` AND zero unrefuted fatal flaws)

## Action items

<!-- Numbered, concrete, each mapped to a section/claim/figure. Consumed verbatim by
     /review-paper Part C and routed to /write-paper. -->

1.
