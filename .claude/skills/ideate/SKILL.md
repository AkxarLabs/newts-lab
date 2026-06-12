---
name: ideate
description: Generate, tournament-rank, and triage research ideas into ideas/<slug>/. Takes an optional direction/topic as argument; otherwise mines lab knowledge for directions.
---

# Ideate

Goal: end with 1–3 ideas in state `triaged` worth a lit review — not a long list of shallow ones.

## 1. Gather fuel

- Read `lab/knowledge/OPEN-QUESTIONS.md`, `FINDINGS.md`, `FAILURES.md` — the lab's compounding pipeline. Failures are fuel: "X failed because Y" suggests "avoid Y" ideas.
- Read `lab/REGISTRY.md` to avoid duplicating live or killed ideas.
- If the user gave a direction, treat it as the brief. Optionally do a quick web/arXiv scan of the direction for very recent developments (this is NOT the lit review — 15 minutes max).

## 2. Generate candidates (target 6–10)

For each candidate, force the discipline of the IDEA template *before* falling in love with it: one-sentence falsifiable hypothesis, cheapest decisive experiment, how it fails fast. Discard anything that can't produce all three. Seek diversity: vary the mechanism, not just the parameters (candidates that differ only in degree count as one).

## 3. Tournament ranking

Absolute scoring is unreliable; pairwise comparison is robust (Google co-scientist's Elo result). Run a single-elimination-with-consolation bracket or round-robin if ≤6:

- For each pair, argue both sides briefly (novelty, feasibility on available compute, impact, cost-to-signal), then pick a winner. Record win/loss counts.
- Rank by record; break ties on **cost-to-signal** (cheaper decisive experiments win — RE-bench: many cheap shots beat one long run).

## 4. Triage & persist

- For the top 1–3: create `ideas/<slug>/IDEA.md` from `templates/idea/IDEA.md`, fill scores + tournament record + triage notes, state `triaged`.
- For promising-but-not-now candidates: add one-line entries to `lab/knowledge/OPEN-QUESTIONS.md` instead of creating directories.
- Update `lab/REGISTRY.md` (new rows, next action = "/lit-review").
- Report the ranking and rationale to the user; recommend which idea to take to lit review first.
