---
name: review-paper
description: Internal review of a paper — mechanical claims audit, then NeurIPS-form qualitative review with scores and action items. Argument; the idea slug.
---

# Review Paper

Input: idea in state `internal-review`. Output: `papers/<slug>/reviews/review-N.md` (from `templates/review/rubric.md`) and a route decision.

## Procedure

1. **Fresh eyes.** Review from the PDF + artifacts, not from memory of writing it. Best practice: run this in a fresh session or delegate Part B to a subagent that has NOT seen the writing process, prompted to find reasons to reject.
2. **Part A — claims audit (mechanical, blocking).** For every `claims.yaml` entry: open the artifact, find the number, check the derivation. Check figure scripts exist and are committed. Check multi-seed coverage of headline numbers. Check every citation against lit-review notes. **Any failure → return to `/write-paper` with the list; do not proceed to Part B.**
3. **Part B — qualitative review.** Fill the rubric. Give the interpretive-reasoning check real effort: do conclusions follow from the evidence shown? Then score (1–4 dimensions, Overall 1–10, Decision). Calibrate: a typical solid workshop paper is ~5–6 Overall; reserve 7+ for results you'd defend to a hostile expert.
4. **Part C — action items**: numbered, concrete, each mapped to a section or claim.
5. **Route:**
   - Decision `accept` (typically after 1–2 revision cycles) → **PI Gate 3**: present the PDF + review to the user for final sign-off; on approval, next action "/finalize".
   - Otherwise → state back to `writing` with the action-item list; cap at 3 review cycles, then escalate to the PI with the residual gaps.
6. Update registry + notebook with the scores and route.
