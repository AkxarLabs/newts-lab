---
name: research-loop
description: Unattended autonomous experiment loop on a project — never-stop-within-budget, zero-token monitoring, anti-burn backoff. Requires a PI-authorized LOOP_BRIEF.md. Argument; the idea slug.
---

# Research Loop (unattended operation)

For overnight/long sessions where the PI is away. Tunables from the project's
`control.yaml` (`loop.*`, `budgets.*`, `gate2_envelope`), falling back to
`lab/config.yaml`.

## 0. Entry gate — the brief IS the approval

- The project's `LOOP_BRIEF.md` (at `<projects_root>/<slug>/`) must exist with the PI authorization box checked; its envelope numbers live in the project's `control.yaml` (`gate2_envelope`, `pi_signed: true`).
- If missing: instantiate `templates/loop/LOOP_BRIEF.md`, fill it from the proposal
  (goal/metric, kill criteria verbatim, proposed envelope), present it to the PI, and
  **STOP**. A loop never authorizes itself.
- The brief's FULL authorization line is Gate 2 for this loop; everything above the
  Loop Log is frozen.

## Cycle (repeat until a stop condition)

1. **Read memory:** `EXPERIMENT_LOG.md` tail, `runs/registry.jsonl`, `git log -20`,
   the Loop Log. Never repeat a tried variant.
2. **Pick the next action** by fixed priority:
   a. unfinished planned experiments in `PLAN.md` (in order),
   b. ablation-plan rows,
   c. multi-seed confirmation of the current best (`scripts/sweep.py`),
   d. `/improve` operators (draft/debug/improve within this cycle's budget slice).
   FULL-stage work is permitted only within the brief's envelope; outside it, write the
   run as a **PI note** in the Loop Log and continue with other work.
3. **Launch** via `scripts/run.py` (or `sweep.py`) as a background process.
4. **Monitor at zero tokens:** while the run is alive, the ONLY check is
   `python scripts/status.py <run_id>` every `loop.monitor_poll_seconds`. No log
   reading, no reasoning about partial curves — the run.py watchdog enforces the
   budget; your judgment is needed at completion, not during. `stalled` twice in a
   row → treat as failed, kill the process.
5. **Record:** ledger entry (+ `Parent:` fields if an operator produced it), one commit,
   PLAN.md table update, one Loop Log row (cycle, action, run ids, best metric,
   progress?, note).

## Hard loop rules

- **Never stop within budget:** while the envelope has budget and no stop condition
  holds, you MUST select an action. Ending a cycle idle is a protocol violation; if
  blocked, pick the next-priority action and say why in the Loop Log.
- **Anti-burn backoff:** "progress" is defined in the brief (metric improvement beyond
  seed noise OR a planned question resolved — clean negatives count, crashes don't).
  `loop.no_progress_backoff_cycles` consecutive no-progress cycles → stop with a
  written diagnosis in the Loop Log (the lab-level analogue of the debug-depth cap).
- **Kill criteria** from the brief are checked every cycle; firing one stops the loop
  immediately — that's a result, record it as such.
- All frozen things stay frozen (eval, test set, seeds policy, budgets). A loop that
  needs to change one stops and queues a PI note instead.

## Exit (any stop condition)

1. Final Loop Log row with the stop reason.
2. `EXPERIMENT_LOG.md` summary: what the loop tried, kept, abandoned; current best with
   run ids.
3. Hub write-back (hard rule 11): notebook entry, registry update, promote durable
   insights to `lab/knowledge/`.
4. Leave a "PI morning report" at the top of the notebook entry: best result, decisions
   queued for the PI (unauthorized FULL runs, budget flags), and the recommended next
   command.
