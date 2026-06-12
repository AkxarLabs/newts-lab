# Loop Brief — {{title}}

*Project: `projects/{{slug}}` · Created: {{date}} · Everything above the Loop Log is
FROZEN once authorized — changes require fresh PI sign-off.*

## Goal (frozen)

- **Primary metric:** <!-- one metric + direction, e.g. "minimize val_loss" -->
- **Target / done condition:** <!-- e.g. "beat exp-002 baseline by >= X beyond seed noise" -->

## Budget envelope

- **Total wall-clock for the loop:** <!-- e.g. 8 hours -->
- **Max cycles:** <!-- e.g. 40 -->
- **Max runs:** <!-- e.g. 60 -->
- **FULL-stage authorization:** <!-- "N runs of <= X minutes each, total <= Y GPU-hours,
  expires YYYY-MM-DD" — or "none: FULL work queues as a PI note". This line IS Gate 2
  for unattended operation. -->

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
  `python scripts/status.py <run_id>` every `loop.monitor_poll_seconds` — no log
  reading, no reasoning about partial curves (the run.py watchdog enforces the budget).
- **Progress** = best-primary-metric improvement beyond seed noise, OR a planned
  question resolved (a clean negative counts; a crash does not).

## PI authorization (Gate 2 for this loop)

- [ ] Authorized as scoped above
- **PI:** ______ · **Date:** ______ · **Scope notes:**

## Loop Log (append-only)

| cycle | started | action | run id(s) | best {{metric}} | progress? | note |
|---|---|---|---|---|---|---|
