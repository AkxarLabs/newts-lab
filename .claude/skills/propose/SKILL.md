---
name: propose
description: Write a full research proposal (staged experiment plan, budgets, kill criteria) for an idea that passed lit review, and present it at PI Gate 1. Argument; the idea slug.
---

# Propose

Input: idea in state `scoping` with a completed `decisions.md` (from `/scope`). Output: `studies/<slug>/proposal.md` presented for **PI Gate 1**.

This file is the procedure's **contract**: the proposal's required sections, Gate 1 and the routing always bind. *How* to write a strong proposal is the stage's **method**, which step 0 loads (the default `METHOD.md` beside this file, or the PI's replacement, plus the PI's own instructions for this stage).

## Procedure

0. **Load this stage's brief:** `uv run --with pyyaml python tools/workflow.py brief propose --study <slug>`. Skip this if a `NEWTS STAGE BRIEF /propose` block is already in your context. Follow its method and instructions within this contract.
1. Read `IDEA.md`, `lit-review.md`, and `decisions.md`. Set state → `proposal`. The proposal is assembled from the settled decisions.
2. Fill `templates/idea/proposal.md`. Whatever the method, these sections are **required**, because later procedures and guards read them:
   - **Headline hypothesis**, consistent with `decisions.md`. `/spawn-project` copies it into PLAN.md and a LOOP_BRIEF, and it is the autonomy boundary: an `explore`-mode loop may reopen supporting decisions and expand the frontier under it, but abandoning it escalates to the PI.
   - **Frozen eval protocol**: primary metric, validation (selection) vs held-out test (reporting), defined now. The experiment loop will never read test.
   - **The baseline** the comparison is against.
   - **Staged experiment table** with a promotion/success criterion on every row, written now. FULL runs are PI-gated (Gate 2).
   - **Ablation plan**.
   - **Budgets** (compute + calendar) and **kill criteria**, concrete enough to apply mechanically.
3. Self-review the proposal once, as the method describes.
4. **PI Gate 1**: present the proposal summary (hypothesis, plan table, budget, kill criteria) to the user and STOP — wait for approval (emit `lab_bus.py emit gate_waiting --idea <slug> --detail "Gate 1"`). Also offer the **Gate 2 envelope** (proposal §5): does the PI want to pre-authorize a batch of FULL runs (count, per-run cap, total, expiry) so unattended loops and batch work aren't blocked per-run? Default is no envelope. Record the decision in the proposal's gate section. *Headless (`NEWTS_RUN_ID` set):* end with the run footer `needs_pi=gate1 next="/spawn-project <slug>"` — the PI signs Gate 1 in the dashboard; ask the envelope question as one `AskUserQuestion` (no / yes-with-caps) before stopping.
5. On approval: update IDEA.md + registry (next action = "/spawn-project"). On rejection/park: record reasons, harvest salvageable threads into `OPEN-QUESTIONS.md`, update registry.
