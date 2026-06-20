# templates/compete/ — the target-driven overlay

A thin overlay applied **on top of** `templates/project/` by `/compete` to turn a standard
project into a **target-driven project**: a task with a fixed, straightforward target (a
benchmark to beat, a metric to hit, a leaderboard to climb, an internal KPI) instead of a
paper. It reuses the entire project engine — staged scale (SMOKE→PILOT→FULL), frozen eval,
budgets + watchdog, multi-seed, append-only ledger, git-as-memory, `/experiment`,
`/improve`, `/ideate --in-project`, `/research-loop` — and adds only the target-specific
glue. It does **not** replace any base file except `experiment.py` (the target toy).

`/compete` copies `templates/project/` first, then drops these files in, then appends the
control block. **Nothing here is specific to any host or tool** — Kaggle is just one instance;
the agent learns and records the task's specifics in `TARGET.md` / `control.yaml`.

## What it adds

| File (→ destination in the project) | Purpose |
|---|---|
| `TARGET.md` → project root | PI-owned brief: the target, metric, data, **rules** (binding like SYSTEM.md), deadline, and (if scored externally) the output contract. The human source of truth. |
| `control.target.yaml` → appended to `control.yaml` | machine-readable mirror: the `target:` block (metric, done-condition, deadline, optional output contract, scoring command, `score_envelope`). |
| `src/project_pkg/output_io.py` → `src/<package>/` | stdlib-only `write_output(...)` so a run emits `runs/<run_id>/submission.csv` (or any CSV) in the scorer's schema (+ `toy_output(...)` for the smoke). Only used when the target has an output artifact. |
| `src/project_pkg/experiment.py` → `src/<package>/` | the target SMOKE: returns a local metric and (if `target.output` is set) writes a valid output. Replace the toy with the real model; keep the contract. |
| `scripts/check_output.py` → `scripts/` | validates an output artifact against the contract (header, exact row count, no empty cells, deadline). The output analogue of `check_project.py`. |
| `scripts/report_score.py` → `scripts/` | the **outward-action gate**: when scoring is external, enforces the PI-signed `score_envelope` (per-day / total caps, deadline), then appends to `runs/scores.jsonl` (append-only) and mirrors `runs/<run_id>/score.json`. `--via command` runs whatever `target.scoring.score_command` the agent filled (any tool). |
| `configs/experiments/exp-001-smoke.yaml` → `configs/experiments/` | the target SMOKE config. |

## The loop this enables

After scaffold, the project **iterates toward the target** with the lab's normal engine,
reframed as a climb (there is no headline-hypothesis boundary — the method space is open):

- `/experiment` — run the next planned line (SMOKE→PILOT→FULL), logged in `EXPERIMENT_LOG.md`
  + `runs/registry.jsonl` + one git commit per attempt.
- `/improve` (mode `explore`) — fan out variants and **expand the frontier** toward the metric.
- `/ideate --in-project <slug>` — generate **divergent approaches** inside the project (scoped
  to the frozen set: task/metric/output/rules/deadline). Fully in-bounds here.
- `/research-loop` (mode `explore`) — unattended climbing, with the **target done-condition**
  and the **deadline** as stop conditions, under the Gate-2 budget envelope.

## The contract a run satisfies

Alongside `metrics.json` (its **local** score on the frozen metric — the selection signal), a
run that targets an external scorer writes a **validated output file**. Minimal wiring in
`src/<package>/experiment.py` (already done for the toy):

```python
from .output_io import write_output            # stdlib; or df.to_csv(ctx.run_dir/"submission.csv")

def run(cfg, ctx):
    model = train(cfg)                          # tune on the LOCAL validation split only
    cv = evaluate(model, local_val)             # the frozen metric — the citable selection number
    preds = predict(model, held_out_input)      # never trains on / peeks at the scorer's labels
    write_output(ctx.run_dir, preds, id_column="id", target_columns=["target"])
    return {cfg["target"]["metric"]: cv}        # local; the external score is read only via report_score.py
```

## The discipline (why this stays honest)

- **An external scorer is the held-out test** (hard rule 5): tune/select on local CV, treat each
  external read as scarce. `report_score.py` caps reads to the PI-signed envelope.
- **Sending output to an external scorer is an outward action** → PI-signed `score_envelope` (a
  Gate-2 analogue). **Selecting the final output** for the hidden/final split is a **Gate-3**
  action, done by the PI in a session — never automated, never dashboard-signed.
- **The frozen set** = `{task data/resources, metric, output contract, rules, deadline}`; there
  is no headline-hypothesis boundary, so model/feature/approach changes are all in-bounds.
- **Rules in TARGET.md bind** like SYSTEM.md: a run that would break a task rule (banned data,
  runtime limit) is blocked, not attempted.

Full guide: `docs/compete.md`. The on-ramp: `.claude/skills/compete/SKILL.md`.
