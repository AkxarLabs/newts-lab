# Internal Review — {{title}}

*Paper: `papers/{{slug}}/` · Reviewer pass: {{n}} · Date: {{date}}*

## Part A — Claims audit (mechanical; blocks everything else)

For EVERY entry in `claims.yaml`: open the referenced artifact and verify the number appears there (within rounding stated in the claim).

| Claim ID | Number in paper | Artifact | Verified? | Notes |
|----------|----------------|----------|-----------|-------|

- [ ] All claims verified against artifacts
- [ ] All figures/tables regenerated from committed scripts (spot-check at least 2)
- [ ] Multi-seed requirement met for all headline numbers (≥3 seeds, variance reported)
- [ ] Every citation checked against `lit-review.md` notes (no from-memory citations)
- [ ] Val/test discipline: nothing in the paper was selected on the test set

**A paper with ANY unverified claim is returned to /write-paper before qualitative review.**

## Part B — Qualitative review (NeurIPS-form)

**Summary** (what the paper claims, in the reviewer's words):

**Strengths:**

**Weaknesses:**

**Interpretive-reasoning check** (the weakest link in AI-written papers — review separately):
Do the conclusions actually follow from the results shown? Are effect sizes honestly characterized? Are alternative explanations addressed by the ablations?

**Questions for the authors:**

**Limitations** (acknowledged adequately?):

### Scores

| Dimension | Score |
|---|---|
| Originality (1–4) | |
| Quality (1–4) | |
| Clarity (1–4) | |
| Significance (1–4) | |
| Soundness (1–4) | |
| Presentation (1–4) | |
| Contribution (1–4) | |
| **Overall (1–10)** | |
| Confidence (1–5) | |

**Decision:** accept / minor revision / major revision / reject

## Part C — Action items

<!-- Numbered, concrete, each mapped to a section/claim. /write-paper consumes this list. -->
