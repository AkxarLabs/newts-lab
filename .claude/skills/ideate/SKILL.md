---
name: ideate
description: Phased idea pipeline — research, generate, multi-agent reflection, evolve, combine, tournament-rank, triage into ideas/<slug>/. Takes an optional direction/topic; otherwise mines lab knowledge. Depth controlled by lab/config.yaml (ideation.*).
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
