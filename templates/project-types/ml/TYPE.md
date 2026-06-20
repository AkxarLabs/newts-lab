# Project type: `ml` (default)

Machine-learning / deep-learning research: train a model, measure it, ablate it. This is the
base type — the `templates/project/` scaffold is already shaped for it; no overlay.

- **An experiment is:** a training/eval run fully specified by a config under
  `configs/experiments/`, returning a metrics dict.
- **Runner:** `python-import` — `<package>.experiment.run(cfg, ctx)`; artifact = `runs/<id>/metrics.json`.
- **Staged scale:** SMOKE (toy data/steps) → PILOT (small, informative) → FULL (real scale).
  Budget unit = wall-clock minutes (watchdog-enforced).
- **Multi-seed:** ≥ `seeds.multi_seed_n` seeds via `scripts/sweep.py`; report mean ± spread.
- **Frozen eval / selection discipline:** tune/select on the validation split; report on a
  held-out **test set** the loop never reads.
- **Output:** a paper (`writing.venue` = neurips/icml/iclr/aclarr/aaai); figures from artifacts.
- **Skills:** all lifecycle skills apply as written.
