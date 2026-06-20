# templates/project-types/ — the methodology type registry

A **project type** is the *methodology* a project uses — what an "experiment" is and how the
lab's hard rules map onto it. It is one of **two orthogonal axes** that shape a spawned project:

- **Methodology type** (here): `ml` · `target-driven` · `empirical` · `simulation` · `theory`.
  Decides the runner, what a "run" produces, and how staged scale / multi-seed / frozen eval /
  selection discipline are realized. **Structure.**
- **Domain profile** (`templates/domain-profiles/`): econ, biology, physics, … — venues, data
  sources, field conventions. **Content**, attached on top of a type. So *math-econ theory* =
  `theory` × the `econ` profile, not a separate type.

Each type is **one light card** — `TYPE.md` — read by the agent at spawn and copied into the
project root so an in-project session knows its own rules. Cards are intentionally thin: they
state the *contract*; the agent designs the concrete `run.py` body / configs / analysis per
project (it already does this for the `ml` toy). Add a new type by writing a new `TYPE.md`
(a PI-owned act) — no engine change needed.

## How a type is realized (no per-type scaffolding to maintain)

Every project is stamped from the **same** `templates/project/` base. A type changes only:

1. **`control.yaml`** — `project_type:` + `runner:` (`python-import` for Python work, or
   `shell-command` for R/Stata/Julia/…). `runner: shell-command` reuses the whole engine
   (config layering, seeding, the budget watchdog, artifacts, the append-only registry); the
   external tool's only obligation is the **artifact contract**: write a flat JSON dict of final
   metrics to `$RUN_DIR/result.json` (it also gets `$CONFIG_PATH` and `$SEED`). See
   `templates/project/scripts/run.py`.
2. **The smoke** — a tiny run of the right shape (a 20-row regression / one sim draw / a
   proof-checker no-op) that the agent writes so `scripts/check_project.py` + the smoke pass.
3. **`target-driven` only** — also applies the existing `templates/compete/` overlay (that type
   *is* `/compete`).

`ml` is the default and needs nothing beyond the base. The selection happens in
`/spawn-project` (latest binding): the agent reads the approved proposal, matches it to a card,
the **PI confirms** the type, and the card is dropped into the project root.

| Type | An "experiment" is… | Runner | Headline rigor mapping |
|---|---|---|---|
| `ml` | a model training/eval run | python-import | multi-seed = seeds; staged scale = data/compute; frozen test split |
| `target-driven` | a run that emits a scored output | python-import | frozen set = task/metric/output/rules/deadline; external scorer = held-out test |
| `empirical` | a specification run (regressions on data) | shell-command (R/Stata/py) or python-import | multi-seed → bootstrap; staged scale → subsample→full; held-out = out-of-sample/placebo |
| `simulation` | a seeded simulation draw | python-import or shell-command | multi-seed = draws; staged scale → coarse→full; calibration target = frozen metric |
| `theory` | a derivation / proof step | python-import (proof-assistant) or none | artifact = a machine-checked proof OR a flagged human-checked claim (see card) |
