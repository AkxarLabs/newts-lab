---
name: propose
description: Write a full research proposal (staged experiment plan, budgets, kill criteria) for an idea that passed lit review, and present it at PI Gate 1. Argument; the idea slug.
---

# Propose

Input: idea in state `lit-review` with a novel/incremental verdict. Output: `ideas/<slug>/proposal.md` presented for **PI Gate 1**.

## Procedure

1. Read `IDEA.md` and `lit-review.md`. Set state → `proposal`.
2. Fill `templates/idea/proposal.md`. The non-negotiables:
   - **Frozen eval protocol**: primary metric, validation (selection) vs held-out test (reporting) defined now. The experiment loop will never read test — design the split so that's physically easy to honor.
   - **Strongest fair baseline** from the lit review's positioning section — not the convenient one.
   - **Staged experiment table**: exp-001 is always a SMOKE; pilots answer the hypothesis cheaply; FULL runs are few and PI-gated. Every row gets its promotion/success criterion written NOW — criteria invented after seeing results are not criteria.
   - **Ablation plan**: every method component gets a removal test. If the method has one component, plan the sanity ablations (e.g., vs. random/shuffled control).
   - **Budgets** (compute + calendar) and **kill criteria** concrete enough that a future session can apply them mechanically.
3. Self-review the proposal once against the lit review: would the closest-work authors consider the comparison fair? Is the cheapest decisive experiment actually in the pilot stage?
4. **PI Gate 1**: present the proposal summary (hypothesis, plan table, budget, kill criteria) to the user and STOP — wait for approval. Record the decision in the proposal's gate section.
5. On approval: update IDEA.md + registry (next action = "/spawn-project"). On rejection/park: record reasons, harvest salvageable threads into `OPEN-QUESTIONS.md`, update registry.
