# Scoping: the method

How this lab deliberates a study's design by default. The PI can add to it or replace it (dashboard →
Workflow). The contract (SKILL.md) fixes the decision record, the `Headline` flag, the OPEN-question cap
and the kill checkpoint; this file is how to deliberate well.

## Enumerating the decisions

Seed the list from the PI's `/discuss scope` session docs when there are any. Otherwise list every
decision that shapes the project, typically:

- **Problem framing**: the exact question, the scope boundaries, what is explicitly out.
- **Dataset / benchmark**: which one, the split policy, licensing and availability.
- **Model family & scale**: what to run at pilot vs full, and what scale the claim needs.
- **Baseline set**: the baselines the field will demand (from the lit review's positioning).
- **Primary metric + eval protocol**: the metric, the val/test design, the seeds policy.
- **Method recipe**: the core technical choices inside the proposed method.
- **Ablation axes**: which components get removal tests.
- **Compute plan**: stage budgets, and what fits the hardware.

Add branches specific to this idea and drop irrelevant ones. Order them by how much of what follows each
decision constrains, framing first.

## Deliberating each decision, in order

1. Generate `scoping.options_per_decision` genuinely distinct options. An option you would never pick is
   filler; replace it.
2. Argue each option before choosing:
   - **With advocates:** each advocate gets a fresh context: the hypothesis, the lit positioning and its
     option, never your leaning. Its charge: *argue the strongest case for this option AND name its two
     most likely failure modes.*
   - **Without advocates:** argue each side yourself, in writing.
3. Decide with a written rationale, a **rejected-because** line for each alternative, and a
   **revisit-if** condition. Write the condition so a later session can check it mechanically against
   run artifacts.
4. Most decisions are supporting ones. Typically only the method recipe and the framing are load-bearing
   for the headline.

## Re-verifying the value (adversarially)

With every decision on the table, step back and ask:

- **Still novel?** Do the settled choices land on something the closest prior work already did? Check the
  lit-review notes, not memory.
- **Still valuable?** With this dataset, scale and metric, would a sceptical reviewer call the eventual
  result meaningful, or "toy setting, unsurprising"?
- **Still feasible?** Do the compute plan and the budgets cover the experiment table this implies?
