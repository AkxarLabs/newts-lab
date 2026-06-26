---
name: finalize
description: Close out a finished project — final reproducibility pass, knowledge write-back, registry to final. Argument; the idea slug. Requires PI Gate 3 approval.
---

# Finalize

Input: idea in `internal-review` with PI Gate 3 approval. Output: everything closed, reproducible, and harvested.

**Target-driven projects** (`/compete`, `control.yaml` `target.active: true`) finalize from `active`, not `internal-review`, and have no paper: Gate 3 is the PI **selecting the final output** for the hidden/final split (never automated). For them, step 2's reproducibility pass is on the **winning run** (the one whose output is selected — its `submission`/`metrics.json` regenerable from config + seed), and the paper-specific sub-steps (figure sync, claim hash-locking, `audit_claims.py`, paper-cited run ids) are **N/A** — instead record the selected run id + the final `score.json` / `runs/scores.jsonl` line as the deliverable. Step 3 harvests into knowledge as usual; the registry `paper` column stays empty.

## Procedure

1. Verify Gate 3 approval is recorded (review file or PI message). If not, stop.
2. **Reproducibility pass on the project repo** (so others can build on it):
   - `uv run pytest` green; smoke config runs clean from a fresh `uv sync`.
   - README's Reproduce section accurate; every paper-cited run id present in `runs/registry.jsonl`; figure scripts regenerate the paper's figures.
   - **Venue mode switch:** if the paper targets a non-`generic` venue, confirm the official style file is present in `studies/<slug>/paper/` and flip the preamble from drafting → camera-ready per that venue's header comment (NeurIPS `preprint`→`final`, ACL `review`→final, ICLR add `\iclrfinalcopy`, ICML add `[accepted]`) — de-anonymizing the author block. Re-compile; confirm page count is within the venue limit (`templates/paper/venues/README.md`). If no style file / no LaTeX toolchain, record it as a queued PI note (a camera-ready PDF is the PI's to produce).
   - **Secure the evidence in the hub** so the paper stays auditable even if the project is later moved or cleaned: `tools/sync_figures.py <slug> --check` (hub figures match their project sources), then `tools/lock_artifacts.py <slug>` (archives each cited `metrics.json` into `studies/<slug>/paper/artifacts/` and records `artifact_sha256`), then `tools/audit_claims.py studies/<slug>/paper --verify-hashes --rel-tol <critique.claim_rel_tol>` — after this the paper audits from the hub alone.
   - Final commit + tag `paper-v1` **in the project repo**. If publishing, this repo + the tag are the artifact.
3. **Hub close-out:**
   - `FINDINGS.md`: final confirmed findings with evidence pointers (paper section + run ids).
   - `FAILURES.md` / `OPEN-QUESTIONS.md`: harvest everything the project learned that didn't make the paper — future-work threads are next cycle's `/ideate` fuel.
   - **Procedure retrospective:** one paragraph in the lab notebook — where did the procedures (skills) fight you or fail? Propose concrete edits to the relevant SKILL.md files to the PI. This is how the lab itself improves.
4. IDEA.md + registry → `final`, with pointers to paper PDF and project tag. Notebook entry. Emit `tools/lab_bus.py emit gate_resolved --idea <slug> --detail "Gate 3 → final"`.
5. Report: deliverable paths, the findings recorded, and proposed procedure improvements. Anything beyond the lab (arXiv, submission) is the PI's action — AI involvement must be disclosed per venue policy.
