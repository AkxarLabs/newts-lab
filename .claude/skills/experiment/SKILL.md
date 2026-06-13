---
name: experiment
description: Run the experiment loop in a project — staged scale (smoke/pilot/full), ledger + git as memory, debug caps, kill-criteria checks. Argument; idea slug and optionally an experiment id.
---

# Experiment Loop

Operates inside the project repo at `<projects_root>/<slug>` (path in the registry row; `projects_root` from `lab/config.yaml`). The project's `control.yaml` carries its run controls (budgets, seeds, parallelism). The operators below are the quality bottleneck (AIRA's lesson) — follow them exactly.

## Before each experiment: read memory

`PLAN.md` (what's next + its pre-written criterion), `SYSTEM.md` if present (the PI's machine constraints — binding like control.yaml, never edited), the tail of `EXPERIMENT_LOG.md`, `runs/registry.jsonl`, and `git log --oneline -20`. Never re-run something already tried without saying why.

## Per experiment attempt

1. **Config first.** New YAML in `configs/experiments/` (immutable once run; variants = new files). Any new behavior goes behind a config switch, baseline path untouched.
2. **Stage discipline.**
   - SMOKE: minutes; proves pipeline + artifacts. Required for any new code path.
   - PILOT: smallest run that can meet/fail the pre-written criterion.
   - FULL: **PI Gate 2 — stop and get explicit approval before launching**, UNLESS the run is covered by a recorded, PI-signed envelope (proposal §5 or `LOOP_BRIEF.md`) and fits its scope/caps. Either way, confirm budget, expected wall-clock, and what decision the run will inform; runs outside an envelope's scope always need fresh approval.
3. **Run** via `scripts/run.py` (long runs: background with output capture). PILOT/FULL campaigns first acquire a compute slot (hard rule 13: `uv run --with pyyaml python <hub>/tools/run_slots.py acquire <slug> exp-NNN` — the command is hub-relative, but this skill runs in the project cwd, so anchor it at the hub repo this skill lives in; release when the ledger entry is written). Stage budgets come from `control.yaml` and are enforced by the watchdog — a run that needs more budget is a PI flag, not a config tweak.
4. **Record** in `EXPERIMENT_LOG.md` (template's entry format): outcome with run ids, decision (keep/revert/debug/move on), reasoning. Then **one git commit per attempt** — message `exp-NNN: <one-line outcome>`. If the change isn't kept, revert the code but keep the ledger entry and registry line.
5. **Update PLAN.md** experiment table (status, result run ids).

## Hard constraints

- **Debug cap:** max `experiment.max_debug_depth` (default 3) consecutive fix attempts on a failing experiment; then record the failure (with diagnosis) and move to the next planned item. When debugging, look at the *ancestral chain* (this experiment's previous attempts), not unrelated history.
- **Frozen things:** eval protocol, test set, seeds policy, budgets. If a result requires touching any of them, stop and flag the PI. Changing the seed/timeout/eval to make a number better is the canonical failure of this whole field — never.
- **Kill criteria:** check PLAN.md's kill criteria after every PILOT. If triggered, stop the loop and report to the PI with the evidence — recommendation kill/park, their call.
- **Multi-seed:** before any result is treated as a finding (analysis/paper), re-run the winning config at ≥ `seeds.multi_seed_n` (default 3) seeds via `scripts/sweep.py`, report mean ± spread.
- **Plan drift:** new experiment ideas discovered mid-loop go into PLAN.md as new rows (with criteria) — not executed on impulse ahead of planned work unless they're cheaper AND more decisive.

## Parallelism (optional)

Independent configs (e.g., a seed sweep, disjoint ablations) may run as parallel background processes or isolated subagents — but ledger entries and commits remain one-per-experiment, written by you after reading each result.

## Exit

When the planned table for the current stage is done (or kill criteria fired), summarize state in `EXPERIMENT_LOG.md`, append a lab notebook entry, and route:
- Planned questions answered but the headline metric still needs pushing → `/improve` (same ledger, same rules — its operators just generate the next attempts).
- Program complete (or killed) → registry state `active` → `analysis`, next action "/analyze".
