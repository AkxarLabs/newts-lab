---
name: experiment
description: Run the experiment loop in a project — staged scale (smoke/pilot/full), ledger + git as memory, debug caps, kill-criteria checks. Argument; idea slug and optionally an experiment id.
---

# Experiment Loop

Operates inside the project repo at `<projects_root>/<slug>` (path in the registry row). The project's `control.yaml` carries its run controls (budgets, seeds, parallelism). What a *run*, a *stage*, and *multi-seed* concretely mean is set by the project's **`TYPE.md`** (default `ml`; e.g. for `empirical`, "multi-seed" = bootstrap and a "run" is a `runner: shell-command` spec via `scripts/run.py`).

This file is the procedure's **contract**: the checkpoints, gates, runner, ledger, frozen set, kill criteria and multi-seed rule always bind — follow them exactly. *How* to use the stages, debug and plan is the stage's **method**, which step 0 loads (the default `METHOD.md` beside this file, or the PI's replacement, plus the PI's own instructions for this stage and this study).

## 0. Load this stage's brief

`uv run --with pyyaml python <hub>/tools/workflow.py brief experiment --study <slug>` (`<hub>` = this project's `control.yaml` `hub_path`). Skip this if a `NEWTS STAGE BRIEF /experiment` block is already in your context. Follow its method and instructions within this contract.

## Before each experiment: read memory

**Check the inbox** (AGENTS.md's per-attempt checkpoint): `uv run --with pyyaml python scripts/lab_bus.py inbox` — a PI directive may request/steer/stop the next run; act within the protocol and ack (a directive that would touch a frozen/PI-owned setting is acked `blocked`). Then read `PLAN.md` (what's next + its criterion), `NOTES.md` **in full** (distilled gotchas + approaches tried-and-abandoned — avoids re-running a known dead end), `SYSTEM.md` if present (PI machine constraints — binding like control.yaml, never edited), the tail of `EXPERIMENT_LOG.md`, `runs/registry.jsonl`, and `git log --oneline -20`. Never re-run something already tried without saying why.

## Per experiment attempt

1. **Config first.** New YAML in `configs/experiments/` (immutable once run; variants = new files).
2. **Stage discipline** (how to use each stage well is the method's):
   - SMOKE is required for any new code path.
   - PILOT tests the row's pre-written criterion.
   - FULL: **PI Gate 2 — stop and get explicit approval before launching**, UNLESS covered by a recorded, PI-signed envelope (proposal §5 or `LOOP_BRIEF.md`) within its scope/caps. This is **enforced at the runner boundary**: `scripts/run.py`/`sweep.py` call the hub guard before any FULL run and refuse to start one that doesn't fit the signed envelope (with per-run/total/count *accounting* against prior FULL rows) — so you cannot bypass Gate 2 by invoking the runner directly. Use the guard yourself as a **preflight**: `uv run --with pyyaml python <hub>/tools/guard.py full-run <slug> --config <yaml> --planned-runs N --planned-minutes M` — exit 0 = the envelope covers this request; nonzero = stop and get fresh PI approval. Alongside it, run `uv run --with pyyaml python <hub>/tools/guard.py frozen <slug>` — confirms `eval_frozen` + the PI-owned blocks are intact before any FULL run. Runs outside an envelope's scope always need fresh approval.
3. **Run** via `scripts/run.py` (long runs: background with output capture). PILOT/FULL runs **acquire a compute slot mechanically** — `run.py`/`sweep.py` grab a cross-project slot (hard rule 13) before starting and refuse to run if the cap is full; a `sweep` holds ONE campaign slot its child runs inherit (`AUTOSCIENTIST_SLOT_HELD`). You can still check/queue by hand (`uv run --with pyyaml python <hub>/tools/run_slots.py status`); touch a long campaign's slot on the monitoring cadence. Stage budgets come from `control.yaml`, enforced by the watchdog — a run needing more budget is a PI flag, not a config tweak. On a machine with a job scheduler (the hub's `compute.scheduler`, set in the dashboard → Settings → System), `run.py` **submits** PILOT/FULL runs and **waits** for them — same run dir, artifacts, exit codes and slot; the run shows `status=queued` while it waits (never "stalled"). **Never call `sbatch`/`qsub` yourself**, and follow `SYSTEM.md`'s site rules.
4. **Record** in `EXPERIMENT_LOG.md` (template entry format): outcome with run ids, decision (keep/revert/debug/move on), reasoning. Then **one git commit per attempt** — message `exp-NNN: <one-line outcome>`. If the change isn't kept, revert the code but keep the ledger entry and registry line. (`run.py` already emitted the run's bus events; a kill or stage promotion warrants its own `scripts/lab_bus.py emit` event.) After the append + commit, run `uv run --with pyyaml python <hub>/tools/guard.py append-only <slug>` — confirms the ledger was only appended (never rewritten) and refreshes its baseline.
5. **Update PLAN.md** experiment table (status, result run ids).

## Hard constraints

- **Debug cap:** max `experiment.max_debug_depth` (default 3) consecutive fix attempts on a failing experiment; then record the failure (with diagnosis) and move to the next planned item.
- **Frozen things:** eval protocol, test set, seeds policy, budgets. If a result requires touching any of them, stop and flag the PI. Changing the seed/timeout/eval to make a number better — never.
- **Kill criteria:** check PLAN.md's kill criteria after every PILOT. If triggered, stop the loop and report to the PI with the evidence — recommendation kill/park, their call (headless: run footer `needs_pi=kill_criteria` with the evidence path in `summary`).
- **Multi-seed:** before any result is treated as a finding (analysis/paper), re-run the winning config at ≥ `seeds.multi_seed_n` (default 3) seeds via `scripts/sweep.py`, report mean ± spread.
- **Plan drift:** new experiment ideas go into PLAN.md as new rows (with criteria) before they run.

## Parallelism (optional) — the parallel path

Independent configs may run as parallel background processes or isolated **`experiment-runner`** subagents (model: `agents.runner_model`, tier-resolved; same contract as `/improve`'s parallel path — worktree confinement, result packets, parent-only ledgers) — but ledger entries and commits remain one-per-experiment, written by you after reading each result.

## Exit

When the planned table for the current stage is done (or kill criteria fired), summarize state in `EXPERIMENT_LOG.md`, **distill any durable within-project lesson into `NOTES.md`** (a gotcha+fix, an approach tried-and-abandoned, or a settled result — one line + evidence pointer; the index a future session reads at orientation), append a lab notebook entry, and route:
- Planned questions answered but the headline metric still needs pushing → `/improve` (same ledger, same rules — its operators just generate the next attempts).
- Program complete (or killed) → registry state `active` → `analysis`, next action "/analyze".
