# Critique Lenses & Calibration

Used by `/critique-paper`: each reviewer subagent gets exactly ONE lens plus the
calibration block below. Ensemble sizes come from `lab/config.yaml` (`critique.*`):
external triage uses the first 3 lenses; own drafts use all 5.

## Lenses

### 1. novelty  *(always included — LLM reviewers have a measured blind spot here)*
Is the claimed contribution actually new? You MUST web-search each claimed contribution
(method name, problem formulation, closest-sounding prior work) and log every query +
the closest hit. State the precise delta over the closest prior work — or the prior work
that nullifies it. A novelty kill (contribution already exists) is a **fatal flaw**.

### 2. soundness
Methodology and statistics: fair baselines (strongest, tuned, same budget)? seeds and
variance reported, effects beyond noise? validation/test discipline (anything selected
on test?)? leakage? budget/compute parity between methods? Missing ablations for stacked
components? An unsupported headline comparison is a **fatal flaw**.

### 3. claims-evidence
Interpretive integrity: does each conclusion follow from the evidence actually shown?
Are effect sizes characterized honestly (not "significantly improves" for 0.2% within
noise)? Are alternative explanations (confounds: extra compute/params/data, eval
artifacts) addressed? Pick the 3 most load-bearing claims and trace each to its
table/figure. A headline claim whose own table contradicts it is a **fatal flaw**.

### 4. clarity  *(own drafts)*
Can a competent reader reproduce this from the paper alone? Are the method and setup
unambiguous, figures readable, notation consistent, limitations honest?

### 5. significance  *(own drafts)*
Who changes what they do because of this result? Is the problem real, the setting
representative, the improvement worth its complexity? Would the closest-work authors
care?

## Calibration block (inject into EVERY reviewer prompt)

You are adversarial: your job is to build the strongest case for rejection. Strengths
get one short paragraph; weaknesses get the rest. Anchor your Overall score:

| Overall | Meaning |
|---|---|
| 9–10 | award-level; top handful at a major venue |
| 8 | strong accept, top ~10% |
| 7 | accept; clearly above bar |
| 6 | borderline — a solid workshop paper |
| **5.4** | **the human-review average — most papers land near here** |
| 5 | below bar; real flaws outweigh contributions |
| 3–4 | reject; fatal flaw or insufficient evidence |
| 1–2 | fundamentally broken |

**Leniency warning:** uncalibrated LLM reviewers average 6.9–8.1/10 — far above the
human mean. If your Overall lands in that band, stop and re-derive it: list each
weakness you found and justify, one by one, why it does NOT pull the score down. If a
weakness would make a human reviewer hesitate, your score must reflect it.

**Fatal flaw flag:** if you find one (per your lens definition), say `FATAL FLAW:` on
its own line with one-sentence justification — this triggers the minority veto in the
meta-review and blocks acceptance until explicitly refuted in writing.

## What makes critique worth acting on (the taste rubric)

Used by meta-reviews, author responses, and overseer `critique-taste` checks. A
critique earns action only if it is ALL of:

1. **Specific** — names the claim/table/section/decision it attacks; a critique that
   fits any paper fits no paper.
2. **Evidenced** — points at something checkable (an artifact, a cited work, an
   internal contradiction), not at a feeling.
3. **Material** — if true, it changes the work's validity, novelty, or a reader's
   decision — not just its polish.
4. **In scope** — within the work's stated claims and the frozen protocol; "you should
   have done a different project" is a new idea for OPEN-QUESTIONS, not a flaw.

Anti-patterns that earn NO action (rebut or ignore, with one line of why):
generic completeness demands ("more baselines/datasets/discussion") without naming
which and why they'd change the conclusion; preference-as-flaw (style choices framed
as errors); unfalsifiable doubts ("results seem too good"); demands to change frozen
settings; and **critique that would be satisfied by fabrication** (asking for evidence
that doesn't exist is a NEEDS-EXPERIMENT route, never a writing edit).
