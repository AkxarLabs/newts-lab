# AGENTS.md — {{title}}

Operating manual for ANY coding agent working in this project repo (spawned from the
AutoScientist lab at `{{hub_path}}`; full protocol in the hub's `CLAUDE.md`/`AGENTS.md`).

## Orientation (always, before acting)

1. `PLAN.md` — the approved experiment plan: frozen eval protocol, staged experiment
   table with pre-written success criteria, kill criteria.
2. `control.yaml` — this project's run controls: stage budgets (watchdog-enforced),
   seeds, parallelism, the Gate-2 envelope. PI-owned keys are marked; never change them.
3. `EXPERIMENT_LOG.md` tail + `runs/registry.jsonl` + `git log --oneline -20` — what
   was already tried. Never repeat an attempt without saying why.

## Running experiments

```bash
uv sync                                                          # once
uv run python scripts/run.py --config configs/experiments/<exp>.yaml [--seed N]
uv run python scripts/sweep.py --config <exp>.yaml --seeds 0,1,2   # multi-seed
uv run python scripts/compare.py best --metric <m> [--minimize]    # query results
uv run python scripts/status.py                                    # check a live run
uv run pytest                                                      # keep green forever
```

## The rules (these make the project extensible — follow exactly)

1. **A new experiment is a NEW yaml** in `configs/experiments/` — experiment configs
   are immutable once run. New behavior goes behind a config switch; baseline code
   paths stay runnable forever.
2. **Stages:** SMOKE (pipeline check) → PILOT (decisive small run) → FULL (requires PI
   approval or the signed envelope in `control.yaml`). Budgets are enforced by the
   run watchdog — never raise a budget, seed, or eval setting to make a result look
   better; flag the PI instead.
3. **Record every attempt** in `EXPERIMENT_LOG.md` (format at the top of that file,
   including failures), then ONE git commit: `exp-NNN: <one-line outcome>`.
4. **Multi-seed before claiming:** a result is a finding only at ≥ `seeds.multi_seed_n`
   seeds (use sweep.py), reported mean ± spread.
5. **Debug cap:** 3 consecutive fix attempts, then record the failure and move on.
6. **Never touch:** the eval protocol, test split, `runs/registry.jsonl` history, or
   anything in the hub repo from inside this project.
7. **Figures are scripts** in `scripts/figures/`, reading only `runs/` artifacts.
