---
name: research-loop
description: Unattended autonomous experiment loop on a project — never-stop-within-budget, zero-token monitoring, anti-burn backoff. Requires a PI-authorized LOOP_BRIEF.md. Argument; the idea slug.
---

# Research Loop (unattended operation)

For overnight/long sessions where the PI is away. Tunables from the project's
`control.yaml` (`loop.*`, `budgets.*`, `gate2_envelope`), falling back to
`lab/config.yaml`.

## 0. Entry gate — the brief IS the approval

- The project's `LOOP_BRIEF.md` (at `<projects_root>/<slug>/`) must exist with the
  authorization box filled. The signature is one of: the **PI** directly, OR — under a
  PI-signed `/autopilot` campaign brief — **"PI via campaign brief `lab/campaigns/<file>`"**
  (the campaign signature carries the PI's authority within its delegation bounds).
- A loop that intends **FULL** work needs a signed `gate2_envelope` (`pi_signed: true`) in
  `control.yaml` covering it. A loop with no envelope (all zeros) is still valid — FULL
  work just queues as a PI note (see cycle step 2); SMOKE/PILOT proceed.
- If the brief is missing **and** there is no campaign authority to derive it from:
  instantiate `templates/loop/LOOP_BRIEF.md`, fill it from the proposal (goal/metric, kill
  criteria verbatim, proposed envelope), present it to the PI, and **STOP**. A loop never
  authorizes itself — but a PI-signed campaign brief is the PI's authorization.
- The brief's authorization line is Gate 2 for this loop; everything above the Loop Log is
  frozen.

## 0.5 Single-loop guard + resume check (before the first cycle, and on every re-entry)

This skill is re-entered by `/loop` after a crash, so it must reconcile the previous
session before starting new work:
- **One loop per project.** Check `.bus/.loop-active` (gitignored): if it holds a
  heartbeat fresher than `2 × loop.monitor_poll_seconds`, another loop is live on this
  project — STOP (two loops double-spend the envelope and interleave the ledger). If it is
  stale or absent, claim it (write your session start time) and refresh it at every status
  poll; clear it on exit.
- **Reconcile orphans from a crashed session:** (a) list `runs/*/meta.json` with
  `status: running` — if the process is alive, re-attach monitoring (step 4) instead of
  launching; if dead, record it failed in the ledger. (b) Diff `runs/registry.jsonl`
  against `EXPERIMENT_LOG.md` run ids and write catch-up ledger + Loop Log rows for any
  completed run with no entry (the crash hit between completion and step 5). (c)
  `run_slots.py status` — if this project holds a slot whose campaign already concluded,
  release it (else PILOT/FULL work is blocked until stale reclaim).

## Cycle (repeat until a stop condition)

1. **Read memory:** `EXPERIMENT_LOG.md` tail, `runs/registry.jsonl`, `git log -20`,
   the Loop Log (+ `SYSTEM.md` once at loop start, if present — machine constraints
   bind every cycle), and the directive inbox (`scripts/lab_bus.py inbox` — a PI directive
   is acted on within the protocol, then acked). Never repeat a tried variant.
2. **Pick the next action** by fixed priority:
   a. unfinished planned experiments in `PLAN.md` (in order),
   b. ablation-plan rows,
   c. multi-seed confirmation of the current best (`scripts/sweep.py`),
   d. `/improve` operators (draft/debug/improve within this cycle's budget slice).
   **Before selecting, check fit:** the action's `budget.max_minutes` must fit the loop's
   remaining wall-clock, and a FULL run must fit the `gate2_envelope` (see *Envelope
   accounting* below). FULL work outside the envelope, or any action that doesn't fit
   remaining wall-clock, is written as a **PI note** in the Loop Log — and if *nothing*
   planned fits the remaining wall-clock, that IS a stop condition (budget exhausted): exit,
   don't idle.
3. **Launch** via `scripts/run.py` (or `sweep.py`) as a background process. PILOT/FULL
   campaigns acquire a compute slot first (hard rule 13); a DENIED slot is not idleness —
   log it, do CPU-light work (analysis, planning, ledger hygiene), and retry next cycle.
4. **Monitor at zero tokens:** while the run is alive, the ONLY check is
   `python scripts/status.py <run_id> --watch --log-interval <monitoring.log_interval_seconds>
   --poll <loop.monitor_poll_seconds>` (for a sweep, omit `<run_id>` — `--watch` follows the
   latest run dir). Pass `--log-interval` so a healthy run that logs sparsely is not flagged
   stalled. No log reading, no partial-curve reasoning — the run.py watchdog enforces the
   budget; `--watch` returns on terminal status (act) or two consecutive stalls (treat as
   failed, kill the process). Touch the slot (`run_slots.py touch <slot-id>`) each poll so a
   long-but-live campaign isn't reclaimed.
5. **Record:** ledger entry (+ `Parent:` fields if an operator produced it), one commit,
   PLAN.md table update, one Loop Log row (cycle, action, run ids, best metric,
   progress?, note), **release the compute slot** if the campaign's ledger entry is now
   written (hard rule 13), refresh `.bus/.loop-active`, and emit a bus event
   (`scripts/lab_bus.py emit cycle --detail "<action> → <outcome>"`).

**Envelope accounting** (a FULL launch "fits" iff ALL hold): each run's `budget.max_minutes`
≤ `gate2_envelope.per_run_max_minutes`; FULL runs already in `runs/registry.jsonl` (stage
FULL) + the runs about to launch ≤ `full_runs` (a sweep counts as N runs); booked minutes
(prior FULL `wall_seconds` + new runs' budgets) ≤ `total_max_minutes`; and today ≤
`expires`. Anything failing a clause queues as a PI note.

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
- **Wall-clock expiry mid-run:** if the loop's wall-clock runs out while a run is in
  flight, let the watchdog-bounded run finish and record it, then exit — never launch a
  *new* run once expired.
- All frozen things stay frozen (eval, test set, seeds policy, budgets). A loop that
  needs to change one stops and queues a PI note instead.

## Exit (any stop condition)

0. Release any compute slot still held (`run_slots.py release <slot-id>`) and clear
   `.bus/.loop-active`.
1. Final Loop Log row with the stop reason.
2. `EXPERIMENT_LOG.md` summary: what the loop tried, kept, abandoned; current best with
   run ids. (`oversight.level: strict`: spawn an `overseer` `support` check on each
   Loop Log row claiming progress — the claim + its run-artifact paths.)
3. Hub write-back (hard rule 11): notebook entry, registry update (state AND a fresh
   "next action" — never leave the loop's stale one), promote durable insights to
   `lab/knowledge/`.
4. Leave a "PI morning report" at the top of the notebook entry: best result, decisions
   queued for the PI (unauthorized FULL runs, budget flags), and the recommended next
   command.
