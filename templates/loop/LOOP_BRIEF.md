# Loop Brief — {{title}}

*Project: `{{slug}}` · Created: {{date}} · Everything above the Loop Log is
FROZEN once authorized — changes require fresh PI sign-off.*

## Goal (frozen)

- **Primary metric:** <!-- one metric + direction, e.g. "minimize val_loss" -->
- **Target / done condition:** <!-- e.g. "beat exp-002 baseline by >= X beyond seed noise" -->
- **Headline hypothesis (frozen):** <!-- the central claim the proposal's novelty rests on,
  copied from proposal.md. The loop may reopen NON-headline design decisions autonomously in
  explore mode; reopening this / abandoning it is the escalation boundary (PI note). -->

## Loop mode (frozen)

- **Mode:** `execute` <!-- execute | explore -->
  - `execute` — run the approved PLAN.md (planned experiments → ablations → multi-seed →
    /improve operators), then stop when exhausted. The conservative default.
  - `explore` — autonomous in-project iteration: when the plan is exhausted with budget left,
    the loop may **expand the frontier** (propose results-grounded new lines) and **reopen
    non-headline design decisions** (`decisions.md` whose `Revisit if:` trigger fired), all
    within the frozen set + the Gate-2 envelope. The PI signature below authorizes this wider
    action space. See docs/autonomy.md.
- **Explore caps** (apply only in explore mode; default from control.yaml `loop.explore_*`):
  - Max expansion rounds: ___  ·  Max new lines per round: ___

## Budget envelope

- **Total wall-clock for the loop:** <!-- e.g. 8 hours -->
- **Max cycles:** <!-- e.g. 40 -->
- **Max runs:** <!-- e.g. 60 -->
- **FULL-stage authorization:** see `control.yaml` → `gate2_envelope` (the canonical
  machine-readable record; the PI signature below covers those values as of signing).
  "No envelope" (all zeros) means FULL work queues as a PI note.

## Stop conditions (any one stops the loop)

1. Goal met (confirmed at `experiment.multi_seed_n` seeds).
2. Budget envelope exhausted (wall-clock, cycles, or runs).
3. Any kill criterion below fires.
4. `loop.no_progress_backoff_cycles` consecutive cycles without progress (see contract).
5. Unrecoverable environment failure (env broken after `experiment.max_debug_depth` fix attempts).

## Kill criteria

<!-- copied VERBATIM from PLAN.md — do not soften them for the loop -->

## Monitoring contract

- While a run is in flight, the only permitted check is
  `python scripts/status.py <run_id> --watch --log-interval <monitoring.log_interval_seconds>
  --poll <loop.monitor_poll_seconds>` (omit `<run_id>` for a sweep) — no log reading, no
  reasoning about partial curves (the run.py watchdog enforces the budget). `--watch`
  returns on terminal status or two consecutive stalls; `--log-interval` must match the
  experiment's logging cadence so a healthy sparse-logging run isn't killed.
- **Progress** = best-primary-metric improvement beyond seed noise, OR a planned
  question resolved (a clean negative counts; a crash does not).

## PI authorization (Gate 2 for this loop)

- [ ] Authorized as scoped above
- **PI:** ______ · **Date:** ______ · **Scope notes:**
  <!-- Signed directly by the PI, OR — under a PI-signed /autopilot campaign — record
       "PI via campaign brief lab/campaigns/<file>" here and set the same path in
       control.yaml gate2_envelope.signed_via. The campaign brief carries PI authority
       within its delegation bounds; a loop never authorizes itself. -->

## Loop Log (append-only)

| cycle | started | action | run id(s) | best {{metric}} | progress? | note |
|---|---|---|---|---|---|---|
