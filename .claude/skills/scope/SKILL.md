---
name: scope
description: Deep project scoping — enumerate every key design decision, deliberate each branch (optionally with parallel advocate subagents), record an ADR-style decisions.md, and re-verify the project is valuable before proposing. Argument; the idea slug.
---

# Scope (design deliberation)

Input: idea in state `lit-review` with a novel/incremental verdict. Output:
`studies/<slug>/decisions.md` (from `templates/idea/decisions.md`) with every key design
decision deliberated and settled — the raw material `/propose` builds on. Depth knobs:
`scoping.*`; advocate model: `agents.critic_model`.

Set state → `scoping` (frontmatter + registry).

## 1. Enumerate the decision branches

Read `IDEA.md` (with the reflection summary) and `lit-review.md` (especially
positioning). List every decision that shapes the project — typically:

- **Problem framing** — exact question, scope boundaries, what's explicitly out
- **Dataset / benchmark** — which, what split policy, licensing/availability
- **Model family & scale** — what to run at pilot vs full; what scale the claim needs
- **Baseline set** — which baselines the field will demand (from lit positioning)
- **Primary metric + eval protocol** — metric, val/test design, seeds policy
- **Method recipe** — the core technical choices inside the proposed method
- **Ablation axes** — which components get removal tests
- **Compute plan** — stage budgets, what fits the hardware

Add idea-specific branches; drop irrelevant ones. Order by how much downstream the
decision constrains (framing first).

## 2. Deliberate each branch — in order, strongly

For each decision:

1. Generate `scoping.options_per_decision` genuinely distinct options (an option you'd
   never pick is filler — replace it).
2. **If `scoping.advocate_subagents`**: spawn one advocate subagent per option in
   parallel (fresh context: the hypothesis, the lit positioning, the option — not your
   leaning). Charge: "argue the strongest case for this option AND name its two most
   likely failure modes." Otherwise argue each side yourself, in writing, before choosing.
3. Decide with a written rationale, an explicit **rejected-because** line per
   alternative, and a **revisit-if** condition (what evidence reopens this — written so a
   later session can check it mechanically against run artifacts).
4. Mark **`Headline: yes`** if the choice is load-bearing for the central hypothesis the
   project's novelty rests on (what the paper fundamentally claims); else **`Headline: no`**
   — a supporting decision. This flag is the autonomy boundary downstream: an `explore`-mode
   loop may reopen a `Headline: no` decision itself when the revisit-if trigger fires, but
   reopening a `Headline: yes` one escalates to the PI.
   Most decisions are `no`; typically only the method recipe / framing are `yes`.
5. Record as a D-NNN entry in `decisions.md` (with its `Headline` flag). Decisions are
   append-only after Gate 1 — reopening one is a new entry referencing the old.
   For a settled **`Headline: no`** decision, also fill the **`Revisit predicate:`** line — the
   machine-checkable form of its `Revisit if:` trigger (grammar + example in the template). Lint
   with `uv run --with pyyaml python tools/guard.py decisions <slug>` before `/propose` (BLOCKS on
   a malformed predicate; WARNs on a missing one).

A decision that genuinely cannot be settled without data may be left **OPEN** with the
pilot experiment that will settle it named — but at most `scoping.max_open_questions`;
more means the idea isn't ready to propose.

## 3. Value re-verification (the kill checkpoint)

With all decisions on the table, step back and re-ask — adversarially:

- **Still novel?** Do the settled choices land on something the closest prior work
  already did? (Check lit-review notes, not memory.)
- **Still valuable?** With this dataset/scale/metric, would a skeptical reviewer call
  the eventual result meaningful — or "toy setting, unsurprising"?
- **Still feasible?** Do the compute plan and budgets cover the experiment table this
  implies?

Any "no" → kill or park NOW: record the reason in IDEA.md, harvest surviving threads
into `OPEN-QUESTIONS.md`, update the registry. (`FAILURES.md` only if the scoping
produced a substantive negative finding worth transferring.) This is the cheapest place
in the lifecycle to stop a doomed project — killing here is success, not failure.

## 4. Hand off

- Summarize: the decision list (one line each), open questions, and the value verdict.
- Update IDEA.md state log; registry next action = "/propose".
- `/propose` consumes `decisions.md` directly: §3 Method and §4 Experimental design are
  assembled from settled decisions, and OPEN decisions become explicit pilot rows in
  the experiment table.
