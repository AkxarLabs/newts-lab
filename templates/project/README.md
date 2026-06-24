# {{title}}

*Spawned from Newts' Lab `templates/project/` on {{date}} · Idea: `{{slug}}` · Proposal: `studies/{{slug}}/proposal.md` in the hub repo.*

## What this is

<!-- One paragraph: the hypothesis and the experiment program (copy from the proposal). -->

## Layout

```
├── PLAN.md                  # the approved experiment plan (from the proposal)
├── NOTES.md                 # distilled memory: gotchas+fixes, tried-and-abandoned, what's settled
├── EXPERIMENT_LOG.md        # append-only narrative ledger — read this first
├── configs/
│   ├── base.yaml            # shared defaults
│   └── experiments/         # ONE FILE PER EXPERIMENT — never edited after running, only added
├── src/project_pkg/         # library code (config, seeding, tracking, experiment logic)
├── scripts/
│   ├── run.py               # the single entry point: python scripts/run.py --config <yaml>
│   └── figures/             # scripts that generate every figure/table from runs/ artifacts
├── runs/                    # per-run artifact dirs (gitignored) + registry.jsonl (committed)
└── tests/                   # smoke test: pipeline runs end-to-end on toy settings
```

## Reproduce

```bash
uv sync                                                  # exact env from uv.lock
uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml
uv run pytest tests/                                     # smoke test
```

Every past experiment is re-runnable from its config: `uv run python scripts/run.py --config configs/experiments/<exp>.yaml --seed <seed>`. The run writes `runs/<run_id>/` containing the resolved config, git SHA, seed, logs, and `metrics.json`, and appends one line to `runs/registry.jsonl`.

## Extending this project

1. **New experiment** = new YAML in `configs/experiments/` (+ new code behind a config switch if needed). Never edit an already-run config or change the behavior of existing config values.
2. **New method variant** = new module/function selected by config, alongside — not replacing — the baseline path.
3. The evaluation protocol (metrics, val/test split, seeds policy) in `base.yaml` is **frozen**; changes require a new explicitly-named config key and a note in `EXPERIMENT_LOG.md`.
4. Log every attempt in `EXPERIMENT_LOG.md`, one commit per experiment attempt.
