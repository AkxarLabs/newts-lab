# Project Protocol — {{title}}

You are the implementation agent of this project, spawned from the AutoScientist lab
at `{{hub_path}}` (the hub). This file is the protocol for any session started **in
this directory**. The hub's `CLAUDE.md` is the lab-wide protocol and still binds you;
this file adds what is specific to working inside a project.

## Orientation (start of every session, in this order)

1. `PLAN.md` — the approved plan: frozen eval protocol, staged experiment table with
   pre-written success criteria, kill criteria.
2. `control.yaml` — this project's run controls: stage budgets (watchdog-enforced),
   seeds, parallelism, the Gate-2 envelope. PI-owned keys are marked; never change them.
3. `SYSTEM.md` — **if present**: the PI's description of the machine/cluster you are
   working on (hardware, data locations, scheduling rules, forbidden actions). Its
   constraints bind exactly like control.yaml. PI-owned: read and obey, never edit.
4. `EXPERIMENT_LOG.md` tail + `runs/registry.jsonl` + `git log --oneline -20` — what
   was already tried. Never repeat an attempt without saying why.
5. Unsure the project is in a runnable state? `uv run --with pyyaml python
   scripts/check_project.py` — readiness lint plus a suggested next action.

## Procedures

The lab's procedures live in the hub at `{{hub_path}}/.claude/skills/<name>/SKILL.md`.
From inside this project you will mainly need, in lifecycle order:

| Procedure | When |
|---|---|
| `experiment` | run the next planned experiment (smoke → pilot → full) |
| `improve` | operator-driven iteration once a baseline exists (draft/debug/improve/crossover) |
| `research-loop` | unattended experiment loop — requires the PI-signed `LOOP_BRIEF.md` |
| `analyze` | plan complete or plateaued — artifact-only analysis |
| `make-figures` | figures/tables mechanically from `runs/` artifacts |

Open the skill file and follow it step by step — they are written as instructions to
you. Decide for yourself which procedure the project state calls for (the log tail and
PLAN.md statuses tell you); when in doubt, `check_project.py` suggests one.

## Autonomy bounds

- SMOKE and PILOT runs: run them; no approval needed.
- FULL runs: need PI approval **or** a signed `gate2_envelope` in control.yaml that
  covers them. No envelope (`pi_signed: false`) means every FULL run waits for the PI.
- Unattended operation needs a PI-signed `LOOP_BRIEF.md` — a loop never authorizes
  itself.
- Before any PILOT/FULL campaign, acquire a cross-project compute slot:
  `uv run --with pyyaml python {{hub_path}}/tools/run_slots.py acquire {{slug}} <label>`
  — release it when the campaign's ledger entry is written. SMOKE is exempt.

## Subagents (you decide when)

Parallelize when ≥2 *mechanism-distinct* variants are ready to test and the machine
can take it (`parallelism.max_parallel_subagents`, and remember training runs still
contend for compute slots): one `experiment-runner` subagent per variant, each in its
own git worktree, per the `improve` procedure. Otherwise run variants sequentially —
parallelism is a throughput tool, not a requirement. Invariants regardless:

- One variant per subagent, confined to its worktree.
- Subagents return result packets; **only you** write `EXPERIMENT_LOG.md`, the main
  `runs/registry.jsonl`, and hub files. Merge through the journal, not git merges.
- Subagents never spawn further work, sweeps, or background jobs.

## The rules (these keep the project extensible — follow exactly)

1. **A new experiment is a NEW yaml** in `configs/experiments/` — experiment configs
   are immutable once run. New behavior goes behind a config switch; baseline code
   paths stay runnable forever.
2. **Stages:** SMOKE (pipeline check) → PILOT (decisive small run) → FULL (per the
   autonomy bounds above). Budgets are enforced by the run watchdog — never raise a
   budget, seed, or eval setting to make a result look better; flag the PI instead.
3. **Record every attempt** in `EXPERIMENT_LOG.md` (format at the top of that file,
   including failures), then ONE git commit: `exp-NNN: <one-line outcome>`.
4. **Multi-seed before claiming:** a result is a finding only at ≥ `seeds.multi_seed_n`
   seeds (use sweep.py), reported mean ± spread.
5. **Debug cap:** `experiment.max_debug_depth` (default 3) consecutive fix attempts, then record the failure and move on.
6. **Never touch:** the eval protocol, test split, `runs/registry.jsonl` history,
   `SYSTEM.md`, or anything in the hub repo except the write-back below.
7. **Figures are scripts** in `scripts/figures/`, reading only `runs/` artifacts.
8. **Zero-token monitoring:** while a run is in flight, the only check is
   `uv run python scripts/status.py <run_id> --watch --log-interval
   <monitoring.log_interval_seconds> --poll <loop.monitor_poll_seconds>` (omit `<run_id>`
   for a sweep) — no log reading, no partial-curve reasoning; the watchdog enforces the
   budget. Pass `--log-interval` so a healthy sparse-logging run isn't flagged stalled.

## Session end (write-back)

Findings flow back to the hub: append a dated entry to `{{hub_path}}/lab/notebook/`
and promote durable insights to `{{hub_path}}/lab/knowledge/` (FINDINGS / FAILURES /
OPEN-QUESTIONS), update the registry row if the state changed. If the hub is
unreachable from this session, append a `HUB-WRITEBACK-PENDING:` entry to
`EXPERIMENT_LOG.md` instead so the next hub session carries it over.
