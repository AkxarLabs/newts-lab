# Experiment Plan — {{title}}

*Copied from the approved proposal (`studies/{{slug}}/proposal.md`, PI Gate 1: {{date}}). The staged
table below is the working checklist for `/experiment`. The eval protocol, budgets, and kill
criteria here are FROZEN — changes require PI approval and a logged note.*

## Frozen evaluation protocol

- Primary metric:
- Validation set (selection):
- Held-out test set (reporting only):
- Seeds policy: seed is a config field; headline numbers need ≥3 seeds.
- **Headline hypothesis:** <!-- the central claim the proposal's novelty rests on. An
  explore-mode loop may reopen supporting (non-headline) design decisions autonomously;
  abandoning THIS is the PI-escalation boundary. Mirrors decisions.md `Headline: yes`. -->

## Analysis plan (frozen)

<!-- copied from the proposal; an analysis not named here is EXPLORATORY and is labelled so -->
- **Primary comparison:**
- **Uncertainty:**
- **Exclusion rules:**
- **Decision rule:**
- **Sanity controls:**

## Budgets

- Per-stage wall-clock caps: SMOKE ≤ ___ · PILOT ≤ ___ · FULL ≤ ___
- Total compute budget (minutes, `control.yaml` `budgets.total_minutes`):

## Kill criteria

<!-- from the proposal -->

## Experiments

*Status vocabulary: `todo` · `running` · `done` · `failed` · `dropped` (debug cap hit) ·
`retired-by-revision` (a design decision this line depended on was reopened in explore mode —
the line is retired, not killed; the project continues). Rows added by an explore-mode
`expand` round are tagged `(expand Rn)` in the Question and still need a pre-written criterion.
A row added after Gate 2 or after the first analysis entry is tagged `(post-hoc)`: its result is
exploratory. A repeat of a run's configuration with new seeds after seeing its result says
`rerun_of: exp-NNN` and why.*

*Provenance (checked by `tools/guard.py plan-trace <slug>`): every non-baseline row should name its
origin in the Question — a `decisions.md` decision (`D-NNN`) or an `(expand Rn)` tag with a matching
Re-planning-log row. A row that would **change the headline hypothesis** (`Headline-change: yes`)
must re-enter `/propose` first — it never enters this table on a bare note.*

| ID | Question | Stage | Status | Promotion/success criterion | Result (run ids) |
|----|----------|-------|--------|------------------------------|------------------|
| exp-001 | pipeline end-to-end | SMOKE | todo | runs clean, artifacts written | |

## Test-split access log

<!-- project rule test-once: the held-out test split (or the TYPE card's analogue) is read by one
     final-evaluation run per selected configuration, after selection on validation is finished.
     Every read is a row here. A second row for the same configuration is a re-open: give the
     reason, and treat what it produces as exploratory. checks/audit_prereg.py reads this table. -->

| date | configuration (exp id / yaml) | run ids | reason (blank for the planned final evaluation) |
|---|---|---|---|

## Ablation plan

<!-- one row per kept change; filled in as the method accretes components -->

## Re-planning log (explore mode only)

<!-- append-only; one row each time the loop reopens a decision or expands the frontier.
     The decision record of truth is decisions.md (new D-NNN entries); this is the index. -->

| date | event | detail | evidence (run ids / D-NNN) |
|---|---|---|---|
<!-- e.g. | 2026-… | decision_revisit | reopened D-003 (dataset) → D-007 | exp-006, D-007 | -->
<!-- e.g. | 2026-… | frontier_expand   | round 1: +2 lines (curriculum, distill) | exp-009..010 | -->
