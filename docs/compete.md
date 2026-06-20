# Target-driven projects (`/compete`)

Most of the lab is built to turn a question into a **paper**: ideate → lit-review → scope →
propose → experiment → analyze → write. But sometimes the goal isn't a claim — it's a
**number**. A benchmark to beat, a metric to hit, a leaderboard to climb, an internal KPI to
reach. `/compete` is the on-ramp for that: it spins off a **target-driven project** and sets up
the loop to **iterate toward the target** — run experiments, fan out ideas inside the project,
log everything, move the metric.

Nothing here is specific to any host or tool. **Kaggle is one instance**; so is "beat SOTA on
benchmark X", "get this model to RMSE < 0.4 on our grader", or "win the leaderboard at host Y".
If the task *is* a Kaggle competition, the agent learns and records the Kaggle specifics itself
— the lab never hardcodes them.

## When to use it

| You want… | On-ramp |
|---|---|
| A paper from a research question | `/ideate` → … → `/write-paper` |
| To continue work you already have (idea / design / repo / draft) | `/adopt` |
| **To hit a fixed target — a metric, benchmark, leaderboard, KPI** | **`/compete`** |

Use `/compete` when the success criterion is a number you can name in advance.

## What's different from a paper project

`/compete` **reuses the whole engine** (staged scale SMOKE→PILOT→FULL, frozen eval, budgets +
watchdog, multi-seed, append-only ledger, git-as-memory, `/experiment`, `/improve`,
`/ideate --in-project`, `/research-loop`) and **skips the paper layer**:

- **No `/ideate→/lit-review→/scope→/propose`.** The project enters **directly at `active`**.
  Those stages are recorded `N/A (target-driven)` in `IDEA.md` — not silently skipped.
- **No novelty gate.** You're trying to *win*, not to be first.
- **No headline-hypothesis boundary.** This is the big one. A paper project freezes a central
  claim and *escalates* if the agent wants to reopen it. A target project has no such claim —
  the "headline" is just *move the metric* — so the **method space is fully open**: swapping
  architectures, features, or whole approaches, and running `/ideate --in-project`, are all
  **in-bounds**. That makes in-project ideation the main engine of the climb.
- **The frozen set is reinterpreted** as `{the task data/resources, the metric + direction, the
  output contract, the rules, the deadline}`. `eval_frozen: true` still holds — the metric plus
  your **local** validation split is the frozen eval. Selection discipline (hard rule 5) binds
  *harder*: when scoring is external, **the scorer is the held-out test**, read sparingly.

## The loop

After scaffold, you climb with the normal procedures, reframed:

```
/experiment <slug>          # next planned line, SMOKE→PILOT→FULL; logged + one commit per attempt
/improve <slug> explore     # fan out variants, expand the frontier toward the metric
/ideate --in-project <slug> # divergent APPROACHES inside the project (in-bounds; needs ideation.in_project: true)
/research-loop <slug>       # unattended climb; target.done + deadline are stop conditions
```

Every attempt lands in `EXPERIMENT_LOG.md` + `runs/registry.jsonl` + a git commit (rules 7, 8,
11). External score reads go through `scripts/report_score.py` under the PI-signed envelope.

## Scoring: internal vs external

- **Internal** — you compute the metric locally on a held-out split you hold. No data leaves the
  lab; the score *is* a normal run metric in `metrics.json`. No outward action, no envelope.
- **External** — you send an output (a submission/predictions file) to a scorer or leaderboard
  and read a score back. That **sends data outside the lab**, so it is an outward action:
  - The output is written into the run dir and validated by `scripts/check_output.py` against the
    `target.output` contract (header, exact row count, no empty cells).
  - The read runs under the PI-signed `target.score_envelope` (per-day / total caps + deadline),
    enforced by `scripts/report_score.py`, which appends to the append-only `runs/scores.jsonl`.
  - `report_score.py --via command` runs whatever `target.scoring.score_command` the agent filled
    for this task (a CLI, an HTTP call, a grader) — **any tool, none assumed**.

## Gates

| Gate | For a target project |
|---|---|
| **Gate 1** | the `/compete` interview *is* the PI authorization to spawn + spend compute (recorded in `IDEA.md`) |
| **Gate 2** | FULL runs follow the `control.yaml` `gate2_envelope`, exactly as any project (`guard.py full-run`) |
| **Gate 2 (analogue)** | sending output to an *external* scorer runs under `target.score_envelope` — no envelope ⇒ every external read waits for the PI |
| **Gate 3** | **never delegated, never dashboard-signed**: *selecting the final output* for the hidden/final split, declaring the target met, and sending anything outside the lab are done by the PI in a session. Close out with `/finalize`. |

## The files it scaffolds

`/compete` copies `templates/project/` (the base contract), then the `templates/compete/`
overlay, then appends the `target:` block to `control.yaml`:

| File | Purpose |
|---|---|
| `TARGET.md` | PI-owned brief: target, metric, data, **rules** (binding like `SYSTEM.md`), deadline, output contract |
| `control.yaml` → `target:` | machine-readable mirror (metric, done, deadline, output contract, scoring, `score_envelope`) — see [Configuration](configuration.md) |
| `src/<pkg>/output_io.py` | stdlib `write_output(...)` → a valid output file in `runs/<run_id>/` |
| `src/<pkg>/experiment.py` | the target SMOKE: local metric (+ output if configured). Replace the toy; keep the contract |
| `scripts/check_output.py` | validate an output against the contract |
| `scripts/report_score.py` | the outward-action gate + append-only score ledger |

## Adopting an existing repo as a target project

Already have a starter kernel or a baseline repo? Don't restructure it — **wrap it** (see
[Projects → adopting a repo](projects.md)). Register its path as the project, set `package:` in
`control.yaml` to its own package name (so `scripts/run.py`/`sweep.py` drive it **without a
rename** — the runner autodetects the package under `src/`, and `package:` pins it), and adapt
`experiment.py` to call its entry point and `write_output(...)` the scorer's artifact.
`scripts/check_project.py --adopt` must exit 0.

## A worked example (Kaggle, but the shape is general)

1. `/compete titanic-survival` → interview: metric `accuracy`, maximize, done `public >= 0.80`,
   deadline `2026-07-31`; data via the Kaggle CLI (auth env-var named in `TARGET.md`); output
   `submission.csv` with `PassengerId,Survived`, 418 rows; scoring **external** via command;
   score envelope **5/day, 50 total, PI-signed**.
2. Scaffold → smoke green (toy emits a valid 418-row `submission.csv`; `check_output.py` passes).
3. Climb: `/experiment` baselines → `/improve explore` + `/ideate --in-project` fan out features
   and models → `/research-loop` for unattended iteration, stopping at `done` or the deadline.
4. Read the public LB sparingly: `report_score.py --run-id <id> --via command` (the agent filled
   `score_command` with the Kaggle submit+fetch commands itself) — capped by the envelope, logged
   append-only.
5. `/finalize`: the PI selects the final submission (Gate 3) and the winning run is made
   reproducible.

See also: the `/compete` skill (`.claude/skills/compete/SKILL.md`) and the overlay README
(`templates/compete/README.md`).
