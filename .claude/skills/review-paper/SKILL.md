---
name: review-paper
description: Internal review of a paper — mechanical claims audit (tools/audit_claims.py), then a fresh-context critique ensemble via /critique-paper, with scores, minority veto, and action items. Argument; the idea slug.
---

# Review Paper

Input: idea in state `internal-review`. Output: `papers/<slug>/reviews/review-N.md`
consolidating the cycle, and a route decision. Cycle cap: `critique.max_review_cycles`
in `lab/config.yaml`.

## Part A — Claims audit (mechanical, blocking)

1. Run `uv run --with pyyaml python tools/audit_claims.py papers/<slug> --check-commits`.
   - Any **FAIL** → return to `/write-paper` with the failure table. Part B does not run.
   - Any **MANUAL** → verify each by hand against the stated derivation now; an
     unresolvable MANUAL is a FAIL.
2. Manual checks the script can't do:
   - Figure/table scripts exist in `projects/<slug>/scripts/figures/`, are committed,
     and regenerate the paper's figures (spot-check ≥2).
   - Multi-seed coverage (`experiment.multi_seed_n`) for all headline numbers, variance reported.
   - Every citation has a corresponding note in `ideas/<slug>/lit-review.md`.
   - Val/test discipline: nothing in the paper was selected on the test set.

**A paper failing any Part A check goes back to `/write-paper` before any qualitative review.**

## Part B — Fresh-context critique ensemble

Invoke `/critique-paper <slug>` (own-draft mode: full ensemble, meta-review with
median scores and minority veto). Do not review the paper yourself in this session —
you've seen it written; that's exactly the bias the ensemble exists to remove.

## Part C — Consolidate & route

1. Write `papers/<slug>/reviews/review-N.md`: pointer to the critique directory, the
   meta-review's score table, decision, veto table, and its action items verbatim.
2. Route:
   - Meta-review **accept** AND zero unrefuted fatal flaws → **PI Gate 3**: present the
     PDF + meta-review to the user for final sign-off; on approval, next action "/finalize".
   - Otherwise → state back to `writing` with the action items; after
     `critique.max_review_cycles` cycles, escalate to the PI with the residual gaps.
3. Update registry + notebook with scores and route.
