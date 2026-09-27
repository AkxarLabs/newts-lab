# Analysis: the method

How this lab interrogates results by default. The PI can add to it or replace it (dashboard → Workflow).
The contract (SKILL.md) fixes the evidence rules (artifacts only, multi-seed spread, validation vs test),
the oversight check and the routing; this file is how to think.

The interpretive step is where AI-written research is weakest. Slow down here.

## Answering the plan's questions

- Go row by row through PLAN.md's experiment table: was the pre-written criterion met?
- Compute effect sizes against the baseline, with the spread the project's `TYPE.md` prescribes: seeds
  for `ml`, bootstrap for `empirical`, draws for `simulation`, N/A for `theory`.

## Interrogating the result

- **Alternative explanations.** Could the gain come from a confound: extra compute, parameters or data,
  an eval artifact, lucky seeds?
- **Load-bearing ablations.** Which ablations from the plan are now load-bearing? Are there kept but
  never-ablated changes stacked in the winning config?
- **Try to break it.** What is the cheapest experiment that could break the favoured interpretation?
- **Founding assumptions.** Read `studies/<slug>/decisions.md` and ask whether the evidence now meets
  any settled decision's `Revisit if:` trigger, i.e. a design choice made at scoping time that now looks
  wrong.

## Writing the analysis

- State the headline result together with its uncertainty.
- Name the interpretation risks plainly, and the evidence that would resolve each one.
