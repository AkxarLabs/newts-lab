# Research Proposal — {{title}}

*Idea: `{{slug}}` · Date: {{date}} · Status: draft → **awaiting PI Gate 1***

## 1. Hypothesis

<!-- One falsifiable sentence, refined from IDEA.md by the lit review. -->

## 2. Background & positioning

<!-- 1–2 paragraphs grounded in lit-review.md: gap, closest work, our delta. -->

## 3. Method

<!-- What we will build/change, precisely enough to implement. Interfaces it must respect. -->

## 4. Experimental design

### Metrics & evaluation protocol (FROZEN once approved)
- **Primary metric:**
- **Validation set** (selection signal):
- **Held-out test set** (reporting only — the experiment loop never reads it):
- **Seeds:** config-controlled; headline results require ≥3 seeds.

### Baselines
<!-- Including the strongest fair baseline from the lit review, not just the convenient one. -->

### Planned experiments (staged)

| ID | Question it answers | Stage | Est. cost | Promotion / success criterion (written NOW, not after) |
|----|---------------------|-------|-----------|--------------------------------------------------------|
| exp-001 | pipeline works end-to-end | SMOKE | minutes | runs clean, artifacts written, metric computed |
| exp-002 | baseline reproduces expected range | PILOT | | within X of published/expected value |
| exp-003 | core hypothesis, small scale | PILOT | | effect ≥ Y over baseline |
| exp-004 | core hypothesis, target scale | FULL (PI Gate 2) | | |

### Planned ablations
<!-- Every component of the method gets a removal test. Stacked, un-ablated changes are banned. -->

## 5. Budget

- **Compute:** <!-- GPU-hours / wall-clock cap per stage; total cap. -->
- **Time:** <!-- calendar budget before mandatory go/kill review. -->
- These budgets are frozen; changing them requires PI approval, not an edit.

## 6. Kill criteria (checked after every pilot)

<!-- Concrete conditions under which this project is killed or parked, e.g.
     "pilot effect < Z after exp-003", "baseline cannot be reproduced within budget". -->

## 7. Success criteria & deliverable

<!-- What result pattern justifies writing the paper; intended venue/format. -->

## 8. Risks

| Risk | Likelihood | Mitigation / early detection |
|------|------------|------------------------------|

## PI Gate 1 decision

- [ ] Approved as-is
- [ ] Approved with changes (noted below)
- [ ] Rejected / parked

**PI notes:**
