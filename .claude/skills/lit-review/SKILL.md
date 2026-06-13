---
name: lit-review
description: Ground an idea in the literature — search log, per-paper notes, novelty verdict, positioning. Argument; the idea slug. Produces ideas/<slug>/lit-review.md.
---

# Literature Review

Input: an idea in state `triaged`. Output: `ideas/<slug>/lit-review.md` (from `templates/idea/lit-review.md`) and a novelty verdict that gates progression.

## Procedure

1. Read `ideas/<slug>/IDEA.md`. Set state → `lit-review` (frontmatter + registry).
2. **Search iteratively** — `tools/s2.py search "<query>" [--year 2022:]` for replayable, logged Semantic Scholar queries (OpenAlex fallback built in), plus web search/fetch for arXiv/Scholar coverage. Start from the hypothesis's key terms, then expand: synonyms, the methods cited by the first good hits, "cited by" chains of the closest works. Log EVERY query in the search log table. Stop when two consecutive searches surface nothing new and relevant (loop-until-dry), typically 8–15 queries. **A query that errors or exits 3 (both backends unreachable — see s2.py) does NOT count toward loop-until-dry**, and an empty result from it is not evidence of absence; if the APIs are down and web search can't compensate, record the review as *blocked* in the search log and stop — never issue a `novel` verdict from an empty/failed search (under `/autopilot` that would self-approve a proposal on a blind search).
3. **Read and note** the relevant papers (typically 5–15). For each: fetch the actual abstract/paper — record what it *actually shows* (scale, conditions, numbers), not what its title implies. These notes become the only permitted citation source later; sloppy notes now = hallucinated citations later. For the 1–3 load-bearing papers the novelty verdict hinges on, run `/critique-paper <link>` (external mode — adversarial lens ensemble) and store the output under `ideas/<slug>/critiques/`; a "SOTA" that doesn't survive critique changes your baseline obligations.
4. **Novelty verdict** — be adversarial with yourself: the default assumption is that someone has done this. State the closest prior work and the precise delta. Verdicts:
   - `not novel` → recommend kill/park; record the reason in IDEA.md and update the registry. Harvest any surviving variant into `OPEN-QUESTIONS.md`. (`FAILURES.md` is for things *tried* that failed — not for ideas killed before any experiment.)
   - `incremental` → flag to PI: proceed only if the increment is cheap and useful.
   - `novel` → proceed.
5. **Positioning**: list the baselines the field will demand, expected metrics/benchmarks, and pitfalls reported by the closest works (these feed the proposal's risks section).
6. Update IDEA.md state log and `lab/REGISTRY.md` (next action = "/scope" or the kill/park outcome). Report the verdict + the 3 most load-bearing papers to the user.
