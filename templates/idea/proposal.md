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
- **Baseline tuning budget:** <!-- the same tuning budget, seeds and eval as the method; "budget-matched" or why not -->

### Analysis plan (FROZEN once approved)
<!-- Decided now, before any result exists. Anything not named here is exploratory and is labelled so in
     the analysis note and the paper (claims.yaml status: exploratory). -->
- **Primary comparison:** <!-- method vs which baseline, on which metric, on which split -->
- **Uncertainty:** <!-- how spread is reported (CI over seeds, bootstrap, paired difference) and how many
     replicates; 3 seeds is the floor, the number comes from the pilot's variance -->
- **Exclusion rules:** <!-- which runs are excluded from the comparison and why, decided now -->
- **Decision rule:** <!-- which result patterns mean supports / refutes / inconclusive, and the pre-agreed
     action for each (write up, kill or park, more seeds) -->
- **Sanity controls:** <!-- a shuffled-label or random-feature control, a train/test leakage check, the
     metric on a trivial baseline; each with its expected range -->

### Planned experiments (staged)

| ID | Question it answers | Stage | Est. cost | Promotion / success criterion (written NOW, not after) |
|----|---------------------|-------|-----------|--------------------------------------------------------|
| exp-001 | pipeline works end-to-end | SMOKE | minutes | runs clean, artifacts written, metric computed |
| exp-002 | baseline reproduces expected range | PILOT | | within X of published/expected value |
| exp-003 | core hypothesis, small scale | PILOT | | effect ≥ Y over baseline |
| exp-004 | core hypothesis, target scale | FULL (PI Gate 2) | | |
| exp-005 | final evaluation: the selected config on the held-out test split, read once | FULL (PI Gate 2) | | reported with the plan's uncertainty; no selection after this |

### Planned ablations
<!-- Every component of the method gets a removal test. Stacked, un-ablated changes are banned. -->

## 5. Budget

- **Compute:** <!-- GPU-hours / wall-clock cap per stage; total cap in minutes (control.yaml budgets.total_minutes). -->
- **Data:** <!-- source, version, hash, split seed, licence (control.yaml data:); a dataset change is a new version. -->
- **Time:** <!-- calendar budget before mandatory go/kill review. -->
- These budgets are frozen; changing them requires PI approval, not an edit.

### Gate 2 envelope (optional — pre-authorized FULL runs)

<!-- Default is per-FULL-run approval. To enable unattended loops or batch FULL work,
     the PI may pre-authorize an envelope here; at spawn it is recorded in the project's
     control.yaml (gate2_envelope, pi_signed: true) — the canonical machine-readable copy. -->
- **Envelope:** none / up to ___ FULL runs, each ≤ ___ min, total ≤ ___, expires ___
- **PI sign-off:** ______ · **Date:** ______
- Runs outside this scope always require fresh approval.

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
