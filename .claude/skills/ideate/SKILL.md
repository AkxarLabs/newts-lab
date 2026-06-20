---
name: ideate
description: Phased idea pipeline — research, generate, multi-agent reflection, evolve, combine, tournament-rank, triage into studies/<slug>/. Takes an optional direction/topic; otherwise mines lab knowledge. Depth controlled by lab/config.yaml (ideation.*). With `--in-project <slug>`: divergent METHOD-approach ideation INSIDE an active project (scoped to the frozen set; output = candidate approaches, not experiments).
---

# Ideate (phased pipeline)

Goal: end with 1–3 ideas in state `triaged` that have already survived adversarial
reflection — not a long list of shallow ones. Depth knobs: `ideation.*` in
`lab/config.yaml` (`candidates`, `reflection_rounds`, `critics_per_idea`,
`enable_combination`); critic model: `agents.critic_model`.

## Phase 0 — Fuel

- *Optional human pre-step:* `/discuss direction [topic]` grills the PI (researching live)
  and seeds `OPEN-QUESTIONS.md` + a direction doc in `lab/ideation/` this phase reads as its
  research-scan seed. Skip silently in autonomous / `/autopilot` runs.
- Read `lab/knowledge/OPEN-QUESTIONS.md`, `FINDINGS.md`, `FAILURES.md`. Failures are fuel:
  "X failed because Y" suggests "avoid Y" ideas.
- Read `lab/REGISTRY.md` to avoid duplicating live or killed ideas.
- **Research scan**: if the user gave a direction, do a focused web/arXiv sweep (recent
  papers, saturated vs open — 15–25 min, logged queries); fuel, NOT the lit review.
- **Keep all working state** (scan queries, sketches, every critique, parentage, tournament
  records) in one worksheet at `lab/ideation/<date>-<HHMMSS>-ideation.md` (`HHMMSS` keeps
  same-day reruns collision-free; create `lab/ideation/` if absent). Only finalists graduate
  to `studies/<slug>/` (Phase 6); everything else stays in the worksheet, so a crashed/compacted
  session is resumable and nothing lives only in chat.

## Phase 1 — Generate

Produce `ideation.candidates` candidates. For each, force the IDEA-template discipline
*before* falling in love: one-sentence falsifiable hypothesis, cheapest decisive
experiment, how it fails fast. Discard anything that can't produce all three. Seek
**mechanism diversity** — candidates that differ only in degree count as one.

## Phase 2 — Reflect (multi-agent self-feedback)

For each candidate, spawn `ideation.critics_per_idea` critic subagents **in parallel**
(fresh context — each receives only the candidate's hypothesis/sketch text, never your
enthusiasm). Distinct charges:

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
combinations as new candidates; each gets ONE reflect pass (check parents' known critiques
first — combinations inherit them). Mark parentage in the worksheet.

## Phase 5 — Tournament

Pairwise comparison of all survivors (round-robin if ≤6, bracket otherwise): argue both
sides briefly (novelty, feasibility on available compute, impact, cost-to-signal), pick
a winner, record win/loss. Rank by record; break ties on **cost-to-signal** (cheaper
decisive experiments win).

## Phase 6 — Triage & persist

- Top 1–3: create `studies/<slug>/IDEA.md` from `templates/idea/IDEA.md` — scores,
  tournament record, AND a "Reflection summary" in the triage notes (each idea's strongest
  surviving critique, so /lit-review and /scope start with eyes open). State `triaged`.
  **The slug must not already exist in `lab/REGISTRY.md` or `studies/`** — killed/parked
  slugs are never reused (that overwrites the recorded kill reason = silent resurrection,
  forbidden); pick a distinct slug for a successor and link the old one in the triage notes.
- Promising-but-not-now: one-line entries in `OPEN-QUESTIONS.md` (no directories).
- Update `lab/REGISTRY.md` (next action = "/lit-review").
- Report: the ranking, each finalist's hypothesis + strongest surviving critique, and
  which to take to lit review first.

## `--in-project <slug>` — divergent method-ideation inside an active project

The one first-class way to ideate **divergent new approaches** *inside* an active project (the
incremental, within-hypothesis generator is `/improve`'s `expand`). Same engine as above —
generate → fresh-context critic ensemble → tournament → triage — but **scoped to method
approaches**; output is **candidate approaches, NOT experiments**, and it is `active → active`
(only a `/propose` re-entry crosses Gate 1). Full policy in CLAUDE.md ("In-project
method-ideation"); this skill is its **single enforcement point for the ENABLE flag**
`ideation.in_project`: if `false`, the capability is OFF — do not run it; tell the caller the
headline-reopen route must fall back to a **successor hub `/ideate`**.

**Scope & the frozen-set constraint (binds every phase).** Read the project's `PLAN.md`,
`control.yaml`, `decisions.md`, `EXPERIMENT_LOG.md` tail, and `SYSTEM.md` (if present). Every
candidate must hold the **frozen set constant** — problem/task, eval protocol, test split,
seeds policy, budgets are NEVER varied (hard rules 4–6); a candidate that needs to move any is
out of scope here (route to a hub `/ideate` or `/propose` re-entry). Candidates are *methods*: a
different mechanism, model family, training objective, or representation on the SAME frozen problem.

*Optional human pre-step:* `/discuss in-project <slug>` scopes candidate approaches with the PI
(held to the frozen set); its session doc in `studies/<slug>/sessions/` seeds the candidate
framing below. Skip silently in autonomous / `/autopilot` runs.

1. **Generate** `ideation.in_project_candidates` mechanism-distinct **approach** candidates,
   each grounded in the results digest (best node + outcome per line from `EXPERIMENT_LOG.md`;
   the idea's `FINDINGS.md`/`FAILURES.md`) and the **headline hypothesis verbatim** from PLAN.md.
   For each: one-sentence approach statement, why results so far make it promising, the cheapest
   decisive experiment under the frozen budgets, and — explicitly — **whether it changes the
   headline hypothesis** (`Headline-change: yes/no`).
2. **Reflect** — fresh-context critic ensemble (`ideation.critics_per_idea`, charges
   novelty/feasibility/value exactly as Phase 2) on each candidate; critics receive only the
   candidate text + the frozen-set description, never your enthusiasm.
3. **Tournament & triage** — rank survivors as in Phase 5; then route each by the gate rule
   below. Keep all working state in `lab/ideation/<date>-<HHMMSS>-<slug>-inproject-ideation.md`
   (`HHMMSS` keeps same-day reruns collision-free; nothing lives only in chat).

**Gate discipline (the routing rule — never bypassable):**
- A survivor with **`Headline-change: no`** (a new method still *within* the headline
  hypothesis): hand it to `/improve`'s `expand` to enter PLAN.md with a pre-written promotion
  criterion and run through the normal operators (still inside the frozen set + Gate-2 envelope).
  It does **not** by itself need Gate 1.
- A survivor that would **change the headline hypothesis** (`Headline-change: yes`) must
  **re-enter `/propose`** — a mini-proposal: new hypothesis framing + kill-criteria + budget —
  **OR** spawn a **successor hub idea** (a fresh `/ideate` slug, the old idea linked in its triage
  notes). It **NEVER** enters experiments on a bare PI note; only the `/propose` re-entry crosses
  Gate 1. This preserves the `Headline: yes` autonomy boundary.

**Approval** (`ideation.in_project_approval`, PI-owned — full rule in CLAUDE.md):
- **Manual / PI-driven run:** always **PI-gated** — queue surviving headline-changing approaches
  at `/propose` for human Gate 1; report and stop, never self-approve.
- **Under a signed `/autopilot` campaign** with `campaign_auto`: a survivor may auto-approve
  **within the campaign's Gate-1 delegation bounds + an overseer `support` check** — exactly like
  an `/autopilot` Gate-1 self-approval — then proceeds to `/propose` → re-plan. Outside the bounds
  (or `in_project_approval: pi`) it queues for the PI **and emits `uv run python
  scripts/lab_bus.py escalate --detail "in-project approach needs PI"`** (escalation requests
  attention, never grants a gate). `campaign_auto` never relaxes manual runs, never touches the
  frozen set, and **never delegates Gate 3**.

**Caps & cost.** At most `ideation.in_project_rounds` rounds (divergence terminates by config,
not convention); under a loop/campaign the round charges its minutes against the loop envelope
(or the project's iteration budget). Emit `approach_ideate`
(`tools/lab_bus.py emit approach_ideate --idea <slug> --detail "<n candidates → m routed>"`),
optionally set the registry next-action token to `active (approach-ideation)`, and — when a
survivor re-plans the project — emit `replan` so a mid-campaign pivot is visible at the hub (not
only at loop exit). Record the round in the project's PLAN.md Re-planning log.
