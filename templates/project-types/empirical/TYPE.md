# Project type: `empirical`

Data + estimation: econometrics, applied micro, social-science empirics — regressions /
specifications on a dataset (R, Stata, or Python). Selection discipline maps *unusually well*
here: the validation-overfitting rule is exactly the **p-hacking / specification-search** problem.

- **An experiment is:** a **specification run** — a model/estimator on the data (e.g. an OLS/IV/DiD
  spec, a robustness variant), producing coefficients, standard errors, and fit/test statistics.
- **Runner:** `shell-command` for R/Stata (`runner_command: ["Rscript", "spec.R"]`) — it writes a
  flat metrics dict (point estimates, SEs, p-values, N) to `$RUN_DIR/result.json`; or
  `python-import` if estimation is in Python (statsmodels/linearmodels). Same artifact contract,
  so **claim→artifact traceability (hard rule 1) is unchanged** — every reported number lives in a
  run's `result.json`/`metrics.json`.
- **Staged scale:** SMOKE (tiny subsample, pipeline check) → PILOT (a sample/period that's decisive)
  → FULL (full sample). Budget unit = minutes (data jobs) or a "sample fraction" cap.
- **Multi-seed analogue:** regressions are deterministic given data — so the analogue is
  **bootstrap / Monte-Carlo SEs and specification multiplicity**, not random seeds. Set
  `seeds.multi_seed_n` to the bootstrap count (or note "deterministic" and report CIs instead).
- **Frozen eval / selection discipline:** **pre-register the primary specification + outcome** in
  PLAN.md; report a held-out **out-of-sample / placebo / hold-out-period** check that the search
  never tuned on. Robustness checks ↔ ablations (each a planned row).
- **Output:** a paper; venues from the `econ` (or relevant) domain profile (AER/QJE/Econometrica/
  AEJ/JPE…), not the ML venue list. Tables emitted from artifacts; numbers never typed into prose.
- **Skills:** all apply; read "experiment" as "specification" and "multi-seed" as "bootstrap".
