---
name: propose
description: Write a full research proposal (staged experiment plan, budgets, kill criteria) for an idea that passed lit review, and present it at PI Gate 1. Argument; the idea slug.
---

# Propose

Input: idea in state `scoping` with a completed `decisions.md` (from `/scope`). Output: `ideas/<slug>/proposal.md` presented for **PI Gate 1**.

## Procedure

1. Read `IDEA.md`, `lit-review.md`, and `decisions.md`. Set state → `proposal`. The proposal is assembled FROM the settled decisions: §3 Method and §4 Experimental design follow decisions.md directly; OPEN decisions become explicit pilot rows whose criterion is "settles D-NNN".
2. Fill `templates/idea/proposal.md`. The non-negotiables:
   - **Headline hypothesis**: state the single central claim the project's novelty rests on, in one sentence — it must be consistent with the `Headline: yes` decisions in `decisions.md`. This is what `/spawn-project` copies into PLAN.md and a LOOP_BRIEF, and it is the autonomy boundary: an `explore`-mode loop may reopen supporting decisions and expand the frontier under it, but abandoning it escalates to the PI.
   - **Frozen eval protocol**: primary metric, validation (selection) vs held-out test (reporting) defined now. The experiment loop will never read test — design the split so that's physically easy to honor.
   - **Strongest fair baseline** from the lit review's positioning section — not the convenient one.
   - **Staged experiment table**: exp-001 is always a SMOKE; pilots answer the hypothesis cheaply; FULL runs are few and PI-gated. Every row gets its promotion/success criterion written NOW — criteria invented after seeing results are not criteria.
   - **Ablation plan**: every method component gets a removal test. If the method has one component, plan the sanity ablations (e.g., vs. random/shuffled control).
   - **Budgets** (compute + calendar) and **kill criteria** concrete enough that a future session can apply them mechanically.
3. Self-review the proposal once against the lit review: would the closest-work authors consider the comparison fair? Is the cheapest decisive experiment actually in the pilot stage?
4. **PI Gate 1**: present the proposal summary (hypothesis, plan table, budget, kill criteria) to the user and STOP — wait for approval (emit `lab_bus.py emit gate_waiting --idea <slug> --detail "Gate 1"`). Also offer the **Gate 2 envelope** (proposal §5): does the PI want to pre-authorize a batch of FULL runs (count, per-run cap, total, expiry) so unattended loops and batch work aren't blocked per-run? Default is no envelope. Record the decision in the proposal's gate section.
5. On approval: update IDEA.md + registry (next action = "/spawn-project"). On rejection/park: record reasons, harvest salvageable threads into `OPEN-QUESTIONS.md`, update registry.
