# Project type: `simulation`

Computational modeling: agent-based models, DSGE / structural macro, Monte-Carlo studies,
calibration. This is the **closest non-ML fit to the base engine** — a simulation is already a
seeded, budgeted, metric-emitting job, so most of the machinery transfers with only the language
swapped (or kept, in Python).

- **An experiment is:** a **seeded simulation draw / sweep** — run the model under a config,
  emit summary statistics or calibration error.
- **Runner:** `python-import` (e.g. `mesa`/numpy) or `shell-command` for Julia/MATLAB/C++
  (`runner_command: ["julia", "model.jl"]`) writing the metrics dict to `$RUN_DIR/result.json`.
- **Staged scale:** SMOKE (short horizon / coarse grid) → PILOT → FULL (full horizon, fine grid).
  Budget unit = minutes (watchdog-enforced) — the native fit.
- **Multi-seed:** = **independent simulation draws** (a perfect fit); ≥ `seeds.multi_seed_n` draws
  via `scripts/sweep.py`; report mean ± spread / CIs.
- **Frozen eval / selection discipline:** the **calibration target / moments** are the frozen
  metric (calibration-to-moments is literally `/compete`'s "chase a metric"). Report on
  **out-of-sample moments / a held-out regime** the calibration loop never fit.
- **Output:** a paper (relevant venues via the domain profile) — or, if it's pure
  calibration-to-a-target, consider the `target-driven` type instead.
- **Skills:** all apply as written; "multi-seed" = draws, "staged scale" = horizon/grid.
