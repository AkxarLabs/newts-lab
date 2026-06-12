---
name: finalize
description: Close out a finished project — final reproducibility pass, knowledge write-back, registry to final. Argument; the idea slug. Requires PI Gate 3 approval.
---

# Finalize

Input: idea in `internal-review` with PI Gate 3 approval. Output: everything closed, reproducible, and harvested.

## Procedure

1. Verify Gate 3 approval is recorded (review file or PI message). If not, stop.
2. **Reproducibility pass on the project repo** (this is what makes "others can build on it" true):
   - `uv run pytest` green; smoke config runs clean from a fresh `uv sync`.
   - README's Reproduce section accurate; every paper-cited run id present in `runs/registry.jsonl`; figure scripts regenerate the paper's figures.
   - Final commit + tag `paper-v1`. If publishing, this repo + the tag are the artifact.
3. **Hub close-out:**
   - `FINDINGS.md`: final confirmed findings with evidence pointers (paper section + run ids).
   - `FAILURES.md` / `OPEN-QUESTIONS.md`: harvest everything the project learned that didn't make the paper — future-work threads are next cycle's `/ideate` fuel.
   - **Procedure retrospective:** one paragraph in the lab notebook — where did the procedures (skills) fight you or fail? Propose concrete edits to the relevant SKILL.md files to the PI. This is how the lab itself improves.
4. IDEA.md + registry → `final`, with pointers to paper PDF and project tag. Notebook entry.
5. Report: deliverable paths, the findings recorded, and proposed procedure improvements. Anything beyond the lab (arXiv, submission) is the PI's action — AI involvement must be disclosed per venue policy.
