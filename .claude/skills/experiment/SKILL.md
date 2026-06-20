---
name: experiment
description: Run the experiment loop in a project — staged scale (smoke/pilot/full), ledger + git as memory, debug caps, kill-criteria checks. Argument; idea slug and optionally an experiment id.
---

# Experiment Loop

Operates inside the project repo at `<projects_root>/<slug>` (path in the registry row). The project's `control.yaml` carries its run controls (budgets, seeds, parallelism). The operators below are the quality bottleneck — follow them exactly. What a *run*, a *stage*, and *multi-seed* concretely mean is set by the project's **`TYPE.md`** (default `ml`; e.g. for `empirical`, "multi-seed" = bootstrap and a "run" is a `runner: shell-command` spec via `scripts/run.py`).

## Before each experiment: read memory

`PLAN.md` (what's next + its criterion), `NOTES.md` **in full** (distilled gotchas + approaches tried-and-abandoned — avoids re-running a known dead end), `SYSTEM.md` if present (PI machine constraints — binding like control.yaml, never edited), the tail of `EXPERIMENT_LOG.md`, `runs/registry.jsonl`, and `git log --oneline -20`. Never re-run something already tried without saying why.

## Per experiment attempt

1. **Config first.** New YAML in `configs/experiments/` (immutable once run; variants = new files). New behavior goes behind a config switch, baseline path untouched.
2. **Stage discipline.**
   - SMOKE: minutes; proves pipeline + artifacts. Required for any new code path.
   - PILOT: smallest run that can meet/fail the pre-written criterion.
   - FULL: **PI Gate 2 — stop and get explicit approval before launching**, UNLESS covered by a recorded, PI-signed envelope (proposal §5 or `LOOP_BRIEF.md`) within its scope/caps. **Gate it mechanically:** `uv run --with pyyaml python <hub>/tools/guard.py full-run <slug>` — exit 0 means a signed, unexpired, non-empty envelope covers it; nonzero means stop and get fresh PI approval. Either way, confirm budget, expected wall-clock, and what decision the run informs; runs outside an envelope's scope always need fresh approval.
3. **Run** via `scripts/run.py` (long runs: background with output capture). PILOT/FULL campaigns first acquire a compute slot (hard rule 13: `uv run --with pyyaml python <hub>/tools/run_slots.py acquire <slug> exp-NNN` — hub-relative, so anchor it at the hub repo this skill lives in; release when the ledger entry is written). Stage budgets come from `control.yaml`, enforced by the watchdog — a run needing more budget is a PI flag, not a config tweak.
4. **Record** in `EXPERIMENT_LOG.md` (template entry format): outcome with run ids, decision (keep/revert/debug/move on), reasoning. Then **one git commit per attempt** — message `exp-NNN: <one-line outcome>`. If the change isn't kept, revert the code but keep the ledger entry and registry line. (`run.py` already emitted the run's bus events; a kill or stage promotion warrants its own `scripts/lab_bus.py emit` event.) After the append + commit, run `uv run --with pyyaml python <hub>/tools/guard.py append-only <slug>` — confirms the ledger was only appended (never rewritten) and refreshes its baseline.
5. **Update PLAN.md** experiment table (status, result run ids).

## Hard constraints

- **Debug cap:** max `experiment.max_debug_depth` (default 3) consecutive fix attempts on a failing experiment; then record the failure (with diagnosis) and move to the next planned item. When debugging, look at the *ancestral chain* (this experiment's previous attempts), not unrelated history.
- **Frozen things:** eval protocol, test set, seeds policy, budgets. If a result requires touching any of them, stop and flag the PI. Changing the seed/timeout/eval to make a number better — never.
- **Kill criteria:** check PLAN.md's kill criteria after every PILOT. If triggered, stop the loop and report to the PI with the evidence — recommendation kill/park, their call.
- **Multi-seed:** before any result is treated as a finding (analysis/paper), re-run the winning config at ≥ `seeds.multi_seed_n` (default 3) seeds via `scripts/sweep.py`, report mean ± spread.
- **Plan drift:** new experiment ideas discovered mid-loop go into PLAN.md as new rows (with criteria) — not executed ahead of planned work unless cheaper AND more decisive.

## Parallelism (optional)

Independent configs (e.g. a seed sweep, disjoint ablations) may run as parallel background processes or isolated subagents — but ledger entries and commits remain one-per-experiment, written by you after reading each result.

## Exit

When the planned table for the current stage is done (or kill criteria fired), summarize state in `EXPERIMENT_LOG.md`, **distill any durable within-project lesson into `NOTES.md`** (a gotcha+fix, an approach tried-and-abandoned, or a settled result — one line + evidence pointer; the index a future session reads at orientation), append a lab notebook entry, and route:
- Planned questions answered but the headline metric still needs pushing → `/improve` (same ledger, same rules — its operators just generate the next attempts).
- Program complete (or killed) → registry state `active` → `analysis`, next action "/analyze".
