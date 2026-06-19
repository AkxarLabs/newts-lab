---
name: ideate
description: Phased idea pipeline — research, generate, multi-agent reflection, evolve, combine, tournament-rank, triage into ideas/<slug>/. Takes an optional direction/topic; otherwise mines lab knowledge. Depth controlled by lab/config.yaml (ideation.*). With `--in-project <slug>`: divergent METHOD-approach ideation INSIDE an active project (scoped to the frozen set; output = candidate approaches, not experiments).
---

# Ideate (phased pipeline)

Goal: end with 1–3 ideas in state `triaged` that have already survived adversarial
reflection — not a long list of shallow ones. Depth knobs: `ideation.*` in
`lab/config.yaml` (`candidates`, `reflection_rounds`, `critics_per_idea`,
`enable_combination`); critic model: `agents.critic_model`.

## Phase 0 — Fuel

- Read `lab/knowledge/OPEN-QUESTIONS.md`, `FINDINGS.md`, `FAILURES.md` — the lab's
  compounding pipeline. Failures are fuel: "X failed because Y" suggests "avoid Y" ideas.
- Read `lab/REGISTRY.md` to avoid duplicating live or killed ideas.
- **Research scan**: if the user gave a direction, do a focused web/arXiv sweep of it
  (recent papers, what's saturated vs open — 15–25 minutes, logged queries); this is
  fuel, NOT the lit review.
- **Keep all working state** (scan queries, candidate sketches, every critique, parentage,
  tournament records) in a single session worksheet at `lab/notebook/<date>-ideation.md`.
  Only finalists graduate to `ideas/<slug>/` (Phase 6); everything else stays in the
  worksheet — so a crashed/compacted session is resumable and nothing lives only in chat.

## Phase 1 — Generate

Produce `ideation.candidates` candidates. For each, force the IDEA-template discipline
*before* falling in love: one-sentence falsifiable hypothesis, cheapest decisive
experiment, how it fails fast. Discard anything that can't produce all three. Seek
**mechanism diversity** — candidates that differ only in degree count as one.

## Phase 2 — Reflect (multi-agent self-feedback)

For each candidate, spawn `ideation.critics_per_idea` critic subagents **in parallel**
(fresh context — each receives only the candidate's hypothesis/sketch text, never your
enthusiasm for it). Distinct charges:

- **Novelty skeptic**: "Assume someone has done this. Search for them. Name the closest
  work and what delta, if any, survives."
- **Feasibility skeptic**: "Find the reason this fails in practice on a solo-researcher
  compute budget: data unavailable, effect too small to detect at pilot scale, baseline
  impossible to reproduce, metric confounded."
- (3rd+ critic if configured: **Value skeptic** — "who would care, and would they care
  enough to change what they do?")

Record each critique in the candidate's section of the ideation worksheet (Phase 0).

## Phase 3 — Evolve

Revise each candidate to answer its critiques (sharpen the hypothesis, swap the
infeasible component, narrow the claim). A candidate whose core is refuted — not just
bruised — is killed now; harvest any surviving thread into `OPEN-QUESTIONS.md`.
**Repeat Phases 2–3 `ideation.reflection_rounds` times** (later rounds reuse cheaper
single critics; stop early if a round produces no substantive critique).

## Phase 4 — Combine (crossover)

If `ideation.enable_combination`: look for complementary survivors (mechanism from A +
evaluation insight from B; A's method on B's underexplored setting). Propose up to 2–3
combinations as new candidates; each gets ONE reflect pass (combinations inherit their
parents' known critiques — check those first). Mark parentage in the worksheet.

## Phase 5 — Tournament

Pairwise comparison of all survivors (round-robin if ≤6, bracket otherwise): argue both
sides briefly (novelty, feasibility on available compute, impact, cost-to-signal), pick
a winner, record win/loss. Rank by record; break ties on **cost-to-signal** (cheaper
decisive experiments win).

## Phase 6 — Triage & persist

- Top 1–3: create `ideas/<slug>/IDEA.md` from `templates/idea/IDEA.md` — scores,
  tournament record, AND a "Reflection summary" in the triage notes (the strongest
  surviving critique of each idea, so /lit-review and /scope start with eyes open).
  State `triaged`. **The slug must not already exist in `lab/REGISTRY.md` or `ideas/`** —
  slugs of killed/parked ideas are never reused (that would overwrite the recorded kill
  reason = silent resurrection, forbidden); pick a distinct slug for a successor idea and
  link the old one in the triage notes.
- Promising-but-not-now: one-line entries in `OPEN-QUESTIONS.md` (no directories).
- Update `lab/REGISTRY.md` (next action = "/lit-review").
- Report: the ranking, each finalist's hypothesis + strongest surviving critique, and
  which to take to lit review first.

## `--in-project <slug>` — divergent method-ideation inside an active project

The one first-class way to ideate **divergent new approaches** *inside* an active project
(the incremental, within-hypothesis generator is `/improve`'s `expand` operator — this is the
divergent counterpart). Requires `ideation.in_project: true`. Same engine as above —
generate → fresh-context critic ensemble → tournament → triage — but **scoped to method
approaches**, and its output is **candidate approaches, NOT experiments**. This is
`active → active`: it produces no new lifecycle state on its own; only a `/propose` re-entry
crosses Gate 1.

**Scope & the frozen-set constraint (binds every phase).** Read the project's `PLAN.md`,
`control.yaml`, `decisions.md`, `EXPERIMENT_LOG.md` tail, and `SYSTEM.md` (if present). Every
candidate must hold the project's **frozen set constant** — the problem/task, eval protocol,
test split, seeds policy, and budgets are NEVER varied by an approach candidate (hard rules
4–6); a candidate that needs to move any of them is out of scope here (route it to a hub
`/ideate` or a `/propose` re-entry). Candidates are *methods*: a different mechanism, model
family, training objective, or representation that attacks the SAME frozen problem.

1. **Generate** `ideation.in_project_candidates` mechanism-distinct **approach** candidates,
   each grounded in the project's results digest (best node + outcome per line from
   `EXPERIMENT_LOG.md`; the idea's `FINDINGS.md`/`FAILURES.md`) and the **headline hypothesis
   verbatim** from PLAN.md. For each: one-sentence statement of the approach, why the results so
   far make it promising, the cheapest decisive experiment under the frozen budgets, and —
   explicitly — **whether it changes the headline hypothesis** (`Headline-change: yes/no`).
2. **Reflect** — fresh-context critic ensemble (`ideation.critics_per_idea`, charges
   novelty/feasibility/value exactly as Phase 2) on each candidate; critics receive only the
   candidate text + the frozen-set description, never your enthusiasm.
3. **Tournament & triage** — rank survivors as in Phase 5; then route each by the gate rule
   below. Keep all working state in `lab/notebook/<date>-<slug>-inproject-ideation.md` (nothing
   lives only in chat).

**Gate discipline (the routing rule — never bypassable):**
- A survivor with **`Headline-change: no`** (a new method still *within* the headline
  hypothesis) is an in-hypothesis line: hand it to `/improve`'s `expand` to enter PLAN.md with a
  pre-written promotion criterion and run through the normal operators (still inside the frozen
  set + Gate-2 envelope). It does **not** by itself need Gate 1.
- A survivor that would **change the headline hypothesis** (`Headline-change: yes`) must
  **re-enter `/propose`** — a mini-proposal: the new hypothesis framing + kill-criteria +
  budget — **OR** spawn a **successor hub idea** (a fresh `/ideate` slug, the old idea linked
  in its triage notes). It **NEVER** enters experiments on a bare PI note; only the `/propose`
  re-entry crosses Gate 1. This preserves the `Headline: yes` autonomy boundary.

**Approval (`ideation.in_project_approval`, PI-owned).**
- **Manual / PI-driven run** (`/ideate --in-project <slug>` typed by the PI, or any non-campaign
  invocation): always **PI-gated** — surviving headline-changing approaches are queued at
  `/propose` for human **Gate 1**; report them and stop, do not self-approve.
- **Under a signed `/autopilot` campaign** with `in_project_approval: campaign_auto` (the
  campaign default): a surviving approach may be **auto-approved WITHIN the campaign's Gate-1
  delegation bounds** (budget caps, kill-criteria present, etc.) **+ an overseer `support`
  check** (`oversight.level` ≠ off) — exactly like an `/autopilot` Gate-1 self-approval — then
  proceeds to `/propose` → `/spawn-project`/re-plan. Outside the bounds, or with
  `in_project_approval: pi` on the campaign, it queues for the PI **and emits `uv run python
  scripts/lab_bus.py escalate --detail "in-project approach needs PI"`** so the hub/PI sees it
  mid-campaign (an escalation requests attention, never grants a gate). `campaign_auto` never
  relaxes manual runs, never touches the frozen set, and **never delegates Gate 3**.

**Caps & cost.** At most `ideation.in_project_rounds` ideation rounds (so divergence terminates
by config, not convention); under a loop/campaign the round charges its minutes against the loop
envelope (or the project's iteration budget). Emit `approach_ideate`
(`tools/lab_bus.py emit approach_ideate --idea <slug> --detail "<n candidates → m routed>"`),
optionally set the registry next-action token to `active (approach-ideation)`, and — when a
survivor re-plans the project — emit `replan` so a mid-campaign approach pivot is visible at the
hub (not only at loop exit). Record the round in the project's PLAN.md Re-planning log.
