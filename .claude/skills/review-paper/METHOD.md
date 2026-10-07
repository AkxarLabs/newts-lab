# Internal review: the method

How this lab reviews its own paper by default. The PI can add to it or replace it (dashboard → Compose).
The contract (SKILL.md) fixes the blocking audits, the fresh-context ensemble, the oversight checks, the
routing and the final sign-off stop. This file is how to do the judgement parts well.

## The phantom-experiment sweep

AI-written papers hide fabricated experiments in ablation and analysis subsections, not in the main
results, and especially after revision rounds. So:

- Walk those subsections claim by claim against the project's ledger.
- For each experimental claim, find the ledger entry and the registry line. Check that the configuration
  described is the one that ran.
- Spot-check that at least two figure scripts regenerate their figures.

## Triaging the reviewers' action items

- **Validate feedback; never just obey it.** Reviewers confabulate too. Revising to satisfy a wrong
  critique, or inventing support for a demanded ablation, is the documented failure mode of
  review-driven revision.
- A good **REBUT** cites specific evidence: the table, the run, the lit-review note. "We disagree" is not
  a rebuttal.
- A good **ACCEPT** names the concrete change and where it goes.
- A good **NEEDS-EXPERIMENT** names the experiment, its pre-written criterion, and what it would settle.
