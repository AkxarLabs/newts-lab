---
name: lit-review
description: Ground an idea in the literature — search log, per-paper notes, novelty verdict, positioning. Argument; the idea slug. Produces studies/<slug>/lit-review.md.
---

# Literature Review

Input: an idea in state `triaged`. Output: `studies/<slug>/lit-review.md` (from `templates/idea/lit-review.md`) and a novelty verdict that gates progression.

This file is the procedure's **contract**: its records, rules and routing always bind. *How* to search, read and judge is the stage's **method**, which step 0 loads (the default `METHOD.md` beside this file, or the PI's replacement, plus the PI's own instructions for this stage).

## Procedure

0. **Load this stage's brief:** `uv run --with pyyaml python tools/workflow.py brief lit-review --study <slug>`. Skip this if a `NEWTS STAGE BRIEF /lit-review` block is already in your context. Follow its method and instructions within this contract.
1. Read `studies/<slug>/IDEA.md`. Set state → `lit-review` (frontmatter + registry).
2. **Search** as the method describes. The rules:
   - Use `tools/s2.py search "<query>" [--year 2022:]` for replayable, logged Semantic Scholar queries (OpenAlex fallback built in).
   - Log EVERY query in the search log table.
   - The live search phase stops at `litreview.max_minutes` (`lab/config.yaml`; 0 = unbounded) even if the method's own stopping rule hasn't fired. If the cap stops you, **log what was NOT covered** in the search log.
   - **A query that errors or exits 3 (both backends unreachable — see s2.py) does not count** toward any "nothing new" stopping rule. An empty result from it is not evidence of absence.
   - If the APIs are down and web search can't compensate, record the review as *blocked* in the search log and stop. Never issue a `novel` verdict from an empty or failed search (under `/autopilot` that would self-approve a proposal on a blind search).
3. **Read and note** the relevant papers as the method describes. The rules:
   - Each note records what the paper *actually shows*. These notes are the only permitted citation source later.
   - For the load-bearing papers the verdict hinges on, run `/critique-paper <link>` (external mode) and store the output under `studies/<slug>/critiques/`.
   - The deep notes stay in this `lit-review.md`. Also promote a **one-line pointer** for each keeper to the shared `lab/knowledge/REFERENCES.md` (`| bibkey | Authors, "Title", venue year — link | one-line what-it-shows | <slug> |`). Skip any bibkey already in the index (add this `<slug>` to its `seen-for` instead), so the next idea's ideation reuses the reading instead of re-fetching it.
4. **Novelty verdict**: record the closest prior work and the delta, then one of:
   - `not novel` → recommend kill/park; record the reason in IDEA.md and update the registry. Harvest any surviving variant into `OPEN-QUESTIONS.md`. (`FAILURES.md` is for things *tried* that failed — not for ideas killed before any experiment.)
   - `incremental` → flag to PI: proceed only if the increment is cheap and useful.
   - `novel` → proceed.
5. **Positioning** (the lit-review's positioning section, which the proposal's baselines and risks are built from): the baselines the field will demand, the expected metrics/benchmarks, and the closest works' reported pitfalls.
6. Update IDEA.md state log and `lab/REGISTRY.md` (next action = "/scope" or the kill/park outcome). Report the verdict + the 3 most load-bearing papers to the user.
