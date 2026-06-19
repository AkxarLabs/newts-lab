---
name: review-paper
description: Internal review of a paper — mechanical claims audit (tools/audit_claims.py), then a fresh-context critique ensemble via /critique-paper, with scores, minority veto, and action items. Argument; the idea slug.
---

# Review Paper

Input: idea in state `internal-review`. Output: `papers/<slug>/reviews/review-N.md`
consolidating the cycle, and a route decision. Cycle cap: `critique.max_review_cycles`
in `lab/config.yaml`.

## Part A — Claims audit (mechanical, blocking)

1. **Figures in sync:** `uv run --with pyyaml python tools/sync_figures.py <slug> --check` —
   a stale (project regenerated, not re-synced) or hand-edited hub figure is a blocking FAIL;
   re-run `tools/sync_figures.py <slug>` then re-check before continuing.
2. Run `uv run --with pyyaml python tools/audit_claims.py papers/<slug> --check-commits`.
   - Any **FAIL** → return to `/write-paper` with the failure table. Part B does not run.
     (FAIL now includes the completeness scan: any numeral in main.tex body prose with no
     `% CNNN` annotation — a number with no claims entry.)
   - Any **MANUAL** → verify each by hand against the stated derivation now; an
     unresolvable MANUAL is a FAIL.
3. Run `uv run --with pyyaml python tools/s2.py verify papers/<slug>/references.bib --threshold <writing.citation_match_threshold>` —
   **any nonzero exit blocks**: NOT-FOUND, RETRACTED, *and* MISMATCH (below-threshold title
   or wrong year — the near-miss-fabrication case).
4. Manual checks the scripts can't do:
   - Figure/table scripts exist in the project repo's `scripts/figures/`, are committed,
     and regenerate the paper's figures (spot-check ≥2).
   - Multi-seed coverage (`experiment.multi_seed_n`) for all headline numbers, variance reported.
   - Every citation has a corresponding note in `ideas/<slug>/lit-review.md`.
   - Val/test discipline: nothing in the paper was selected on the test set.
   - **Phantom-experiment sweep**: audited AI-written papers hide fabricated experiments
     in ablation/analysis subsections (not main results), especially after revision
     rounds — walk those subsections claim by claim against the project's ledger. At
     `oversight.level` ≠ off, spawn an `overseer` `support` check per ablation/analysis
     experimental claim (statement = the claim; evidence = `EXPERIMENT_LOG.md` +
     `runs/registry.jsonl` paths) — this sweep is the judgment check most exposed to author
     rationalization, and you wrote (or just saw written) this paper.

**A paper failing any Part A check goes back to `/write-paper` before any qualitative review.**

## Part B — Fresh-context critique ensemble

Invoke `/critique-paper <slug>` (own-draft mode: full ensemble, meta-review with
median scores and minority veto). Do not review the paper yourself in this session —
you've seen it written; that's exactly the bias the ensemble exists to remove.

## Part C — Author response & route

1. Write `papers/<slug>/reviews/review-N.md`: pointer to the critique directory, the
   meta-review's score table, decision, veto table, and its action items verbatim.
2. **Author-response triage** (`templates/review/response.md` → `reviews/response-N.md`):
   every action item gets ACCEPT / REBUT / NEEDS-EXPERIMENT **with evidence**. Feedback
   is validated, never obeyed — reviewers confabulate too, and revising to satisfy a
   wrong critique (or inventing support for a demanded ablation) is the documented
   failure mode of review-driven revision. Apply the taste rubric
   (`critique-lenses.md`): GENERIC and MISDIRECTED items earn no action. Rebuttals
   without evidence don't count; items rebutted twice but re-raised, and anything
   touching frozen settings, escalate to the PI.
3. **Oversight pass** (`oversight.level` ≠ off): spawn one `overseer` subagent per
   triage verdict — `critique-taste` on the original item, `support` on the verdict's
   evidence (paths only, never your reasoning). An overseer-rejected verdict is redone
   against the cited evidence or escalated; this is the circuit-breaker between a wrong
   review point and a wrong "improvement".
4. Route on the triage:
   - Any **NEEDS-EXPERIMENT** items → **one coordinated cross-repo step**: append the new
     rows to the project's `PLAN.md` (criteria written now) AND set the hub registry row
     `state → active` in the same checkpoint; then commit the project and emit
     `tools/lab_bus.py emit replan --idea <slug> --detail "review NEEDS-EXPERIMENT → active"`.
     Next action "/experiment" — then `/analyze` → `/write-paper` and the next review cycle.
     New claims require new runs; nothing gets "addressed" in prose that needed an experiment.
   - Only ACCEPT items remain → state → `writing` with that worklist.
   - Meta-review **accept** AND zero unrefuted fatal flaws → **PI Gate 3**: present the
     PDF + meta-review to the user for final sign-off (state stays `internal-review`
     until then; `/finalize` sets `final`); on approval, next action "/finalize".
   - After `critique.max_review_cycles` cycles, escalate to the PI with the residual gaps.
5. Update registry + notebook with scores, the triage tally, and the route. Emit a bus
   event: `tools/lab_bus.py emit review_verdict --idea <slug> --detail "median <X>, <route>"`
   (and `gate_waiting --detail "Gate 3"` if the route is the Gate-3 stop).
