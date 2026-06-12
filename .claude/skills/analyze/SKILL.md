---
name: analyze
description: Analyze a project's results — verify against artifacts, decide ablations/follow-ups, distill findings into lab knowledge. Argument; the idea slug.
---

# Analyze

Input: project in state `analysis` (or mid-`active` for an interim read). Output: an analysis written into the project + distilled knowledge in the hub + a go/no-go on writing.

## Procedure

1. **Reconstruct from artifacts only.** Load `runs/registry.jsonl` and the relevant `runs/<id>/metrics.json`. Every number in the analysis carries its run id. If a remembered result has no artifact, it does not exist.
2. **Answer the proposal's questions.** For each experiment row in PLAN.md: was the pre-written criterion met? Compute effect sizes vs the baseline with multi-seed spread — an improvement within seed noise is NOT a finding. Be explicit about which comparisons were selected on validation and confirm test was touched only for final reporting.
3. **Interrogate the result** (the interpretive step is where AI-written research is weakest — slow down here):
   - Alternative explanations: could the gain come from a confound (extra compute/params/data, eval artifact, lucky seeds)?
   - Which ablations from the plan are now load-bearing? Are any kept-but-unablated changes stacked in the winning config?
   - What's the cheapest experiment that could *break* the favored interpretation?
   - **Oversight pass** (`oversight.level` ≠ off): spawn one `overseer` subagent
     (`support` check) per headline interpretation, giving it the statement + artifact
     paths only. OVERREACH → adopt its supported version verbatim; UNSUPPORTED →
     it is not a finding, whatever it felt like.
4. **Decide and route:**
   - Missing ablations / confound checks → add rows to PLAN.md and return to `/experiment`. (Ablations are complete when every row of PLAN.md's ablation plan has a multi-seed result or a recorded failure — no kept change without its removal test.)
   - Hypothesis confirmed with honest effect → state → `writing`, next action "/write-paper".
   - Null/negative → that can still be a paper (decide with the PI); otherwise kill/park with reasons.
5. **Write it down:** `analysis-YYYY-MM-DD.md` in the project root (claims → run ids throughout). Distill to the hub: `FINDINGS.md` (confirmed, with evidence pointers), `FAILURES.md` (what didn't work + diagnosis), `OPEN-QUESTIONS.md` (new threads). Update registry + notebook.
6. Report to the user: the headline result (with uncertainty), the interpretation risks, and your routing recommendation.
