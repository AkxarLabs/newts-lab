---
name: autopilot
description: Authorize and run an unattended end-to-end campaign — multiple ideas carried from ideation through experiments to reviewed paper drafts while the PI is away. One setup conversation, then the lab runs itself within a signed brief; re-enter a running campaign with `continue <campaign-file>`.
---

# Autopilot Campaign

The full-autonomy mode: "one signature before bed, papers in the morning." The campaign
delivers papers at **`internal-review`** — fully drafted, claims-audited,
ensemble-reviewed — for the PI's Gate 3 read; or, **only if the PI ticked the brief's "Papers may
finalize without me" box**, finalized by the executor's campaign keeper after its own audits (never by
an agent — see "Under the campaign keeper" below). Nothing is ever sent outside the lab.

**Started from the dashboard** (the usual way): the PI signs the brief in the campaign form and the
executor's **campaign keeper** carries it — it starts each `/autopilot continue` cycle, restarts after
timeouts, usage limits and transient failures, runs the steps you dispatch, and stops at the deadline
or budget. Follow **"Under the campaign keeper"** below. The authorization conversation (§1) and the
`launch-many` path are for campaigns started by hand in a session.

## 1. Authorization conversation (10 minutes, the only interactive part)

1. Ask the PI: direction(s); how many ideas to carry; total compute/wall-clock budget; the
   Gate 1 delegation bounds. **Project concurrency** is `autopilot.max_concurrent_projects`
   (default **1** — one project carried end-to-end before the next). >1 means concurrent
   multi-project, which **requires** `agents.programmatic.enabled: true` (see §2's concurrent
   path); confirm both with the PI and record the chosen value + whether programmatic launching is
   exercised in the brief, so the signature scopes it.
2. Fill `templates/loop/CAMPAIGN.md` → `lab/campaigns/<date>-<slug>.md` and present it.
   **The signed brief is the campaign's gate record and the PI's signature carrier:** Gate 1 is
   delegated *within its bounds*; Gate 2 envelopes derive from it (written into each spawned
   project's `control.yaml` with `pi_signed: true` and `signed_via: lab/campaigns/<file>`), and
   each project's `LOOP_BRIEF` authorization line is filled "PI via campaign brief
   `lab/campaigns/<file>`"; Gate 3 is excluded unless the PI ticks its box (in the dashboard). This is how the campaign satisfies
   `/research-loop`'s entry gate unattended. A run outside the bounds still queues for the PI; the
   agent never widens an envelope or signs beyond what the brief covers.
3. PI signs → begin. No brief, no campaign.

## 2. The campaign loop (unattended)

**Default — one project end-to-end at a time** (`autopilot.max_concurrent_projects: 1`): carry one
idea fully through the pipeline below (or to a kill) **before** spawning the next. This keeps a
single project's frozen set / envelope / ledgers in working memory — aligned with
`compute.max_concurrent_runs: 1` (training is serial regardless). Within that project you still
interleave *its own* CPU-light stages around *its* in-flight training (zero-token monitoring, slot
rules).

**Concurrent multi-project** (`autopilot.max_concurrent_projects > 1` **and**
`agents.programmatic.enabled: true`): do **not** cram many projects into this one context, and do
**not** hand-background per-project shell commands. Instead this session becomes a
**coordinator/dispatcher** and hands the whole fleet to ONE launcher call:

```bash
uv run --with pyyaml python tools/agent_runner.py launch-many \
  --projects <slug1,slug2,slug3> --role orchestrator \
  --prompt-file <brief> --campaign lab/campaigns/<campaign>.md
```

`launch-many` runs one independent headless top-level session per project (default backend `claude`;
each fully operable because spawned projects ship their own `CLAUDE.md`/`AGENTS.md`), caps concurrency
at `min(autopilot.max_concurrent_projects, agents.programmatic.max_concurrent)` **itself** (no shell
backgrounding, platform-agnostic), isolates per-project failures, and writes a campaign manifest at
`lab/.bus/campaign-agents/<id>.json` (per-project status, agent ids, escalation counts). The
prompt-file's `{{slug}}`/`{{project}}`/`{{campaign}}` are substituted per project. Coordination is
still purely through the **existing compute-slot ledger** (`tools/run_slots.py` — training stays
capped at `compute.max_concurrent_runs`; CPU-light stages run in parallel across sessions). The
coordinator's job is narrow: `launch-many`, then monitor each project's Campaign Log /
`lab/REGISTRY.md` / `.bus` (and the campaign manifest / `agent_runner.py list/reconcile`) for
completion or escalation, `kill-campaign` to stop the fleet, and write the unified morning report. Each launched
session is **top-level** (it writes its OWN project ledgers — the parent-only-ledger rule is about
*worktree subagents*, untouched), runs exactly the per-idea pipeline below, and **inherits every
gate** — Gate 3 still never delegated, FULL runs still bound by the project's `gate2_envelope`, the
launcher is depth-capped so a launched agent can't launch more. **Build the launch prompt-file to
state the brakes explicitly** — "stop the pipeline at `internal-review`; **never `/finalize`** (Gate
3 is the PI's); FULL runs only under the signed `gate2_envelope`; escalate via `lab_bus.py` rather
than widening anything" — so the Gate-3 brake is asserted where the prompt is built, not only
inherited from the project's `CLAUDE.md`. Programmatic launching is **PI-owned and OFF by default**;
see `docs/autonomy.md` and `tools/agent_runner.py`.

The per-idea pipeline (run by this session, or by each launched session):

```
per idea:  /ideate(direction) → /lit-review → /scope → /propose
           → self-check against the delegation bounds:
               within bounds → record auto-approval in the proposal + Campaign Log
                               (oversight.level ≠ off: an overseer `support` check
                                confirms "proposal is within bounds" first)
               outside      → queue for PI, take the next idea
           → /spawn-project (envelope from the brief into control.yaml, pi_signed: true,
                             signed_via: the campaign file)
           → /research-loop (its LOOP_BRIEF authorized "PI via campaign brief …",
                             Mode + explore caps from the campaign's "Loop mode for spawned
                             projects" line)
           → /analyze → /make-figures → /write-paper → /review-paper cycles
           → stop at internal-review (or earlier kill — kills are fine outcomes)
```

Campaign rules (in addition to every standing hard rule):
- **All ordinary machinery applies unchanged** — slots, watchdogs, ledgers, oversight checks,
  author-response triage, claims audits. A campaign is normal operation minus the wait for the PI,
  never a relaxed mode.
- **Preflight every state transition** in the per-idea pipeline: before writing a registry state
  change, run `uv run --with pyyaml python tools/guard.py state <slug> <from> <to>` (exit 1 =
  illegal — stop, don't force it; the guard confirms, never grants).
- Kill criteria fire exactly as in interactive mode; a night that kills 3 ideas cheaply and ships
  1 strong draft beats 4 weak drafts. On each idea's kill or completion, run
  `uv run --with pyyaml python tools/guard.py evolve <slug>` — a BLOCK means the kill left no
  CORRECTION (or a results-stage exit no RECIPE); write the FAILURES/FINDINGS + NOTES entry before
  taking the next idea.
- NEEDS-EXPERIMENT review items are followed within remaining budget; otherwise queued.
- **Explore-mode pivots** (if the campaign authorized `explore`): a project loop may reopen
  `Headline: no` decisions and expand the frontier autonomously within its envelope — the routing
  rule is `/improve`'s `revisit`/`expand`, don't re-derive it here. A `Headline: yes` reopen routes
  to **`/ideate --in-project <slug>`** (or, if `ideation.in_project: false`, a successor hub
  `/ideate`). **Campaign delta:** under `ideation.in_project_approval: campaign_auto` a surviving
  approach is checked against the campaign's Gate-1 delegation bounds + an overseer `support` pass —
  **exactly like a Gate-1 self-approval** — then routes through `/propose` → re-plan; outside bounds
  (or `in_project_approval: pi`) it queues for the PI. Emit `approach_ideate` (per round) and
  `replan` (when an approach re-plans the project, mid-campaign — not only at exit). Frozen-set
  changes and envelope overruns are never delegated; Gate 3 only by the brief's own box, through the keeper.
- Every lifecycle step appends a Campaign Log row **and** emits a bus event
  (`tools/lab_bus.py emit cycle --idea <slug> --detail "<step> → <outcome>"`); at the start of each
  portfolio pass, check `tools/lab_bus.py inbox` and act on any PI directive.

## 3. Morning report (campaign exit)

Write at the top of the notebook entry, in this order:
1. **Drafts awaiting Gate 3** — per paper: title, headline result (with run ids),
   ensemble median Overall, unresolved review items.
2. **Killed/parked ideas** with one-line reasons (knowledge, not failure).
3. **Queued PI decisions** — proposals outside delegation, frozen-setting requests.
4. Budget actually spent vs the brief; recommended next command.
Then the standard write-back (registry, knowledge promotion) for everything touched.

## Re-entry — `/autopilot continue <campaign-file>`

Invoked with `continue <campaign-file>` (the form `/loop` fires), this is a **resume**,
not a fresh start — **skip §1 entirely** (never interview an absent PI at 3am):

1. Read the named brief. If its PI authorization box is **not** checked, STOP with a note
   — never self-authorize.
2. Rebuild state from written record: the Campaign Log tail + `lab/REGISTRY.md` + each
   spawned project's `runs/registry.jsonl` and `EXPERIMENT_LOG.md`.
3. **Reconcile the crashed session before launching anything:** `run_slots.py status` (a slot
   this campaign holds whose run already finished → release it); run `scripts/status.py` in each
   active project (in-flight run → re-attach monitoring instead of launching new work; dead run →
   record it failed). **If the campaign launched headless agents** (`agents.programmatic.enabled`),
   also run `tools/agent_runner.py reconcile --project <slug>` for each — it marks any launched
   session whose process died (manifest stuck `running`) as failed and emits `agent_finished`, so
   you don't relaunch over a phantom (`agent_runner.py list` shows what's still alive). Treat the
   last Campaign Log row as possibly half-done: confirm its artifacts exist before re-running the
   step.
4. **If a stop condition already holds** (wall-clock expired, environment failure logged,
   all ideas terminal), go straight to §3 and write the morning report — an empty or
   crashed night still gets a report with budget-spent and a one-line diagnosis. Otherwise
   resume §2 from the first incomplete step.

Campaign Log rows are appended **on each step's completion, before starting the next** —
so the row after the last one is the resume point, and a missing row means re-verify.

## Under the campaign keeper (a dashboard-started campaign)

The run's preamble says `CAMPAIGN CYCLE n of <campaign>`. Then:

1. **One cycle = one portfolio pass**, the Re-entry path below (never §1): rebuild state, reconcile,
   decide each idea's next step.
2. **Dispatch, don't do.** Start each step as its own run:
   `python tools/lab_bus.py emit campaign_dispatch --run-id $NEWTS_RUN_ID --data skill=<procedure> --data target=<slug or hub>`
   (optional `--data args="<args>"`). The keeper validates it (a launchable procedure, the study belongs
   to this campaign and isn't waiting for the PI, no duplicate, the brief's parallelism) and runs it with
   retries; its result is in the study's files and the run's footer by your next cycle. Short CPU-light
   bookkeeping (the Campaign Log, the notebook, a registry fix) you may do yourself.
3. **Membership:** append the idea's Campaign Log row **before** dispatching its first step — the log is
   how the keeper knows the study is part of this campaign.
4. **The PI is away.** Ask only what you can't decide within the brief: ONE question, concrete options,
   your recommendation first — if nobody answers in time the recommendation is taken and shown to the PI
   as assumed. A step that needs a decision outside the brief (a proposal out of bounds, a kill decision,
   a frozen-set change) is never assumed: that step's own run reports it (`needs_pi`, `study=<slug>`) and
   only that study waits; carry on with the others. Read PI directives (`tools/lab_bus.py inbox`) and the
   answers in your preamble each pass.
5. **Gate 3:** never dispatch `/finalize`. If the brief delegates Gate 3, the keeper records it for a
   paper whose `/review-paper` reported `needs_pi=gate3`, after re-running the paper audits itself, and
   starts `/finalize`; otherwise the paper waits for the PI.
6. **Footer:** end every cycle with the run footer plus `--data campaign=continue|idle|done` (`done` when
   every target idea is at internal-review / final / killed, or a stop condition holds). A cycle marked
   FINAL (deadline, budget, or the PI's Stop) dispatches nothing and writes the morning report (§3).

The keeper is the scheduler: don't `/loop`, don't background yourself, don't `launch-many`.

## Keeping it running (a campaign started by hand in a session)

Within one session this skill just runs. For resilience across a long night, pair it with Claude
Code's built-in scheduler: `/loop 30m /autopilot continue <campaign-file>` re-enters the campaign
on an interval (the Re-entry path above). The brief + append-only logs make every step
recoverable. The session must stay open with a permission mode that won't prompt mid-night — see
docs/autonomy.md for the exact invocation and its limits.
