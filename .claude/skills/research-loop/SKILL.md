---
name: research-loop
description: Unattended autonomous experiment loop on a project — never-stop-within-budget, zero-token monitoring, anti-burn backoff. Requires a PI-authorized LOOP_BRIEF.md. Argument; the idea slug.
---

# Research Loop (unattended operation)

For overnight/long sessions while the PI is away. Tunables from the project's
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
  authorizes itself.
- The brief's authorization line is Gate 2 for this loop; everything above the Loop Log is
  frozen.
- **Read the brief's `Mode:`** (default `execute` from `loop.mode`). `execute` = run the
  approved plan, then stop when it's exhausted (cycle step 2 below). `explore` = also allowed
  to **expand the frontier** and **reopen non-headline design decisions** within the frozen set
  and the envelope. Note the brief's `Headline hypothesis` and `Explore caps` (else
  `loop.explore_*`). A loop never switches its own mode.

## 0.5 Single-loop guard + resume check (before the first cycle, and on every re-entry)

This skill is re-entered by `/loop` after a crash, so reconcile the previous
session before new work. **Run `uv run --with pyyaml python scripts/reconcile.py` first** —
it surfaces dead/stalled runs, orphan run dirs, and a stale loop lock in one command (add `--fix` to
clear a stale `.bus/.loop-active`); act on what it reports, then confirm:
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

1. **Read memory:** `EXPERIMENT_LOG.md` tail, `NOTES.md` in full (distilled gotchas +
   tried-and-abandoned), `runs/registry.jsonl`, `git log -20`, the Loop Log (+ `SYSTEM.md`
   once at loop start, if present — machine constraints bind every cycle), and the directive
   inbox (`scripts/lab_bus.py inbox` — a PI directive is acted on within the protocol, then
   acked). Never repeat a tried variant.
   **In `explore` mode, also read `studies/<slug>/decisions.md`** and check each settled
   decision's `Revisit if:` trigger (machine form: its `Revisit predicate:`) against the
   artifacts — a fired trigger queues a `revisit` action (step 2f).
2. **Pick the next action** by fixed priority:
   a. unfinished planned experiments in `PLAN.md` (in order),
   b. ablation-plan rows,
   c. multi-seed confirmation of the current best (`scripts/sweep.py`),
   d. `/improve` operators (draft/debug/improve within this cycle's budget slice).
   **`explore` mode only** — when (a)–(d) are all exhausted (rather than stopping):
   e. **frontier expansion** — the `/improve` `expand` operator: propose ≤
      `explore_max_new_lines_per_round` results-grounded new lines (with criteria) into
      PLAN.md, capped at `explore_max_expansion_rounds` total rounds. After appending rows, run
      `tools/guard.py plan-trace <slug>` — a BLOCKED (a row reads as a headline change) routes to
      `/propose`, not PLAN.md. Each fresh expand round that yields no progress counts toward the
      no-progress backoff.
   f. **decision revisit** — if step 1 found a fired `Revisit if:` trigger: the `/improve`
      `revisit` operator (reopen the decision, retire dependent lines, seed replacements).
      Subject to the **escalation boundary** below — a fired `Headline: yes` trigger does not
      re-plan in place; it routes to `/ideate --in-project <slug>` (see the boundary rule).
   **Before selecting, check fit:** the action's `budget.max_minutes` must fit the loop's
   remaining wall-clock, and a FULL run must fit the `gate2_envelope` (see *Envelope
   accounting* below). FULL work outside the envelope, or any action that doesn't fit
   remaining wall-clock, is written as a **PI note** in the Loop Log. If *nothing* fits the
   remaining wall-clock (in `explore`: nothing planned AND expansion rounds spent), that IS a
   stop condition (budget exhausted): exit, don't idle.
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
   written (hard rule 13), refresh `.bus/.loop-active`, and emit
   `scripts/lab_bus.py emit cycle --detail "<action> → <outcome>"`.

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
  written diagnosis in the Loop Log.
- **Kill criteria** from the brief are checked every cycle; firing one stops the loop
  immediately — that's a result, record it as such.
- **Wall-clock expiry mid-run:** if the loop's wall-clock runs out while a run is in
  flight, let the watchdog-bounded run finish and record it, then exit — never launch a
  *new* run once expired.
- All frozen things stay frozen (eval, test set, seeds policy, budgets). A loop that
  needs to change one stops and queues a PI note instead.
- **Explore-mode escalation boundary:** the boundary and its routing are **exactly `/improve`'s
  `revisit` operator — follow it, don't re-derive it here**: reopening a `Headline: no` decision is
  autonomous (within the frozen set + envelope); a **`Headline: yes`** reopen, abandoning the
  brief's headline hypothesis, exceeding the envelope, or any change to the frozen set is the
  boundary and routes to `/ideate --in-project` (with its `ideation.in_project*` gates, or — under a
  signed `/autopilot` campaign — the campaign-delegation + overseer `support` check like a Gate-1
  self-approval, then continue with other in-bounds work). Never pivot the headline silently.
  **Loop-specific deltas only:** at the boundary, queue a **PI note** and escalate **mid-run** —
  `uv run python scripts/lab_bus.py escalate --detail "<what & why>"` (so the PI sees it before loop
  exit; an escalation never grants a gate); record every `revisit`/`expand` in PLAN.md's Re-planning
  log + `decisions.md`; and emit `replan` (plus `approach_ideate --idea <slug>` when an in-project
  round runs) **mid-cycle, not only at loop exit**.

## Exit (any stop condition)

0. Release any compute slot still held (`run_slots.py release <slot-id>`) and clear
   `.bus/.loop-active`.
1. Final Loop Log row with the stop reason.
2. `EXPERIMENT_LOG.md` summary: what the loop tried, kept, abandoned; current best with
   run ids. (`oversight.level: strict`: spawn an `overseer` `support` check on each
   Loop Log row claiming progress — the claim + its run-artifact paths.) **Distill any durable
   within-project lesson into `NOTES.md`** (gotcha+fix / approach tried-and-abandoned / settled
   result — one line + evidence pointer).
3. Hub write-back (hard rule 11): notebook entry, registry update (state AND a fresh
   "next action" — never leave the loop's stale one), promote durable insights to
   `lab/knowledge/`.
4. Leave a "PI morning report" at the top of the notebook entry: best result, decisions
   queued for the PI (unauthorized FULL runs, budget flags), and the recommended next
   command.
