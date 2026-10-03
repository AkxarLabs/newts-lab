# Ideation: the method

How this lab generates and sharpens ideas by default: a phased pipeline that ends with 1–3 ideas that
have already survived adversarial reflection, not a long list of shallow ones. The PI can add to it or
replace it (dashboard → Compose). The contract (SKILL.md) fixes the critic role, the worksheet, the
`ideation.*` knobs, triage and the in-project gate rules. This file is how to think.

## Phase 0 — Sources

- *Optional human pre-step:* a `/discuss direction [topic]` session seeds a direction doc that this phase
  reads as its research-scan seed. Skip this in autonomous runs.
- Read the lab's open questions, findings and failures. Failures are useful: "X failed because Y"
  suggests "avoid Y" ideas.
- Skim the shared reading index. A paper already logged for a prior idea is grounding here, not something
  to re-fetch.
- Check the registry, so you don't duplicate live or killed ideas.
- **Research scan:** if the PI gave a direction, do a focused web/arXiv sweep (recent papers; what is
  saturated vs open), about 15–25 minutes with logged queries. This scan supplies raw material; it is
  not the lit review.

## Phase 1 — Generate

Produce `ideation.candidates` candidates. Before falling in love with any, force the IDEA-template
discipline on each:
- a one-sentence falsifiable hypothesis;
- the cheapest decisive experiment;
- how it fails fast.

Discard anything that can't produce all three. Seek **mechanism diversity**: candidates that differ only
in degree count as one.

## Phase 2 — Reflect (multi-agent critique)

Critique each candidate with `ideation.critics_per_idea` critics, each with a distinct charge:
- **Novelty sceptic:** "Assume someone has done this. Search for them. Name the closest work and what
  delta, if any, survives."
- **Feasibility sceptic:** "Find the reason this fails in practice on a solo-researcher compute budget:
  data unavailable, effect too small to detect at pilot scale, baseline impossible to reproduce, metric
  confounded."
- A 3rd+ critic, if configured, is the **Value sceptic:** "who would care, and would they care enough to
  change what they do?"

## Phase 3 — Evolve

- Revise each candidate to answer its critiques: sharpen the hypothesis, swap the infeasible component,
  narrow the claim.
- A candidate whose core is refuted (not just bruised) is killed now.
- Repeat Phases 2–3 `ideation.reflection_rounds` times. Later rounds can use single cheaper critics.
  Stop early if a round produces no substantive critique.

## Phase 4 — Combine (crossover)

If `ideation.enable_combination` is set:
- look for complementary survivors: A's mechanism with B's evaluation insight, or A's method on B's
  underexplored setting;
- propose up to 2–3 combinations as new candidates;
- give each one reflect pass. Check the parents' known critiques first: a combination inherits them.

## Phase 5 — Tournament

- Compare all survivors in pairs: round-robin if there are 6 or fewer, a bracket otherwise.
- For each pair, argue both sides briefly (novelty, feasibility on the available compute, impact,
  cost-to-signal), pick a winner and record the win or loss.
- Rank by record. Break ties on **cost-to-signal**: cheaper decisive experiments win.

## In-project ideation (`--in-project`)

- Ground each approach candidate in the results digest:
  - the best node and outcome of each line;
  - the idea's findings and failures;
  - the reading index;
  - the headline hypothesis, verbatim.
- For each candidate, write:
  - a one-sentence approach statement;
  - why the results so far make it promising;
  - the cheapest decisive experiment under the frozen budgets.
- Candidates are *methods* on the same frozen problem: a different mechanism, model family, training
  objective or representation.
- Critique and rank them as in Phases 2 and 5.
