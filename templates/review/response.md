# Author Response — {{title}}, review cycle {{n}}

*Paper: `papers/{{slug}}/` · Responding to: `reviews/review-{{n}}.md` · Date: {{date}}*

Review feedback is **validated, never obeyed**. Every action item gets exactly one
verdict below, with evidence. A reviewer point contradicted by the artifacts or the
lit-review notes is REBUTTED — changing the paper to satisfy a wrong critique is how
confabulation cascades start.

| # | Action item (verbatim) | Verdict | Evidence / plan |
|---|------------------------|---------|-----------------|
| 1 | | ACCEPT | what will change, grounded in which artifact/note |
| 2 | | REBUT | the artifact / lit note / decision record that contradicts the point |
| 3 | | NEEDS-EXPERIMENT | the new PLAN.md row (exp-NNN) that will answer it — never answered by prose |

## Verdict rules

- **ACCEPT** — the point is correct and addressable in writing. The change may only
  re-present existing evidence; it may not introduce any number or experiment that
  lacks an artifact.
- **REBUT** — the point is wrong or out of scope. State the contradicting evidence
  explicitly. A rebuttal without evidence is not a rebuttal; if you can't point at
  anything, the verdict is ACCEPT or NEEDS-EXPERIMENT.
- **NEEDS-EXPERIMENT** — the point is valid and requires new evidence. It becomes a
  planned experiment (criteria written in advance, normal gates apply) — the paper
  returns to the project, not to the thesaurus.

## Escalations

- An item REBUTTED in two consecutive cycles that reviewers re-raise → **PI decides**;
  stop relitigating it internally.
- Reviewer demands touching anything frozen (eval protocol, test set, budgets) → PI,
  always.
