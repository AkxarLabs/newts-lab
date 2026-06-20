---
name: autopilot
description: Authorize and run an unattended end-to-end campaign — multiple ideas carried from ideation through experiments to reviewed paper drafts while the PI is away. One setup conversation, then the lab runs itself within a signed brief.
---

# Autopilot Campaign

The full-autonomy mode: "one command before bed, drafts in the morning." The campaign
delivers papers at **`internal-review`** — fully drafted, claims-audited,
ensemble-reviewed — for the PI's Gate 3 read. Gate 3 is never delegated.

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
   `lab/campaigns/<file>`"; Gate 3 is explicitly excluded. This is how the campaign satisfies
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
`agents.programmatic.enabled: true`): do **not** cram many projects into this one context. Instead
this session becomes a **coordinator/dispatcher**: for each project, launch **one independent
headless top-level session** via `uv run --with pyyaml python tools/agent_runner.py launch --project
<slug> --role orchestrator --prompt-file <brief>` (default backend `claude`; one session per project,
each fully operable because spawned projects ship their own `CLAUDE.md`/`AGENTS.md`). Launch up to
`min(autopilot.max_concurrent_projects, agents.programmatic.max_concurrent)`, run each `agent_runner`
call in the **background** so they proceed in parallel, and coordinate purely through the **existing
compute-slot ledger** (`tools/run_slots.py` — training stays capped at `compute.max_concurrent_runs`;
CPU-light stages run in parallel across sessions). The coordinator's job is narrow: launch, then
monitor each project's Campaign Log / `lab/REGISTRY.md` / `.bus` (and `agent_runner.py
list/reconcile`) for completion or escalation, and write the unified morning report. Each launched
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
- Kill criteria fire exactly as in interactive mode; a night that kills 3 ideas cheaply and ships
  1 strong draft beats 4 weak drafts.
- NEEDS-EXPERIMENT review items are followed within remaining budget; otherwise queued.
- **Explore-mode pivots** (if the campaign authorized `explore`): a project loop may reopen
  `Headline: no` decisions and expand the frontier autonomously within its envelope. A
  `Headline: yes` reopen (abandoning the central hypothesis) is **not a dead end** — it routes to
  **`/ideate --in-project <slug>`** (divergent method-ideation scoped to the frozen set) when
  `ideation.in_project: true`; **if `false`, that route is OFF — fall back to a successor hub
  `/ideate`**. Under the campaign the approval default is `ideation.in_project_approval:
  campaign_auto`: a surviving approach is checked against the campaign's Gate-1 delegation bounds +
  an overseer `support` pass — **exactly like a Gate-1 self-approval**; within bounds → record the
  auto-approval and route the approach through `/propose` → `/spawn-project`/re-plan; outside
  bounds (or `in_project_approval: pi`) → queue for the PI and move on. A surviving approach that
  changes the headline hypothesis **always** re-enters `/propose` (a mini-proposal) or spawns a
  successor idea — never experiments on a bare PI note. Emit `approach_ideate` for the round and
  `replan` when an approach re-plans the project (mid-campaign, not only at exit). Frozen-set
  changes, envelope overruns, and **Gate 3 are never delegated**.
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

## Keeping it running

Within one session this skill just runs. For resilience across a long night, pair it with Claude
Code's built-in scheduler: `/loop 30m /autopilot continue <campaign-file>` re-enters the campaign
on an interval (the Re-entry path above). The brief + append-only logs make every step
recoverable. The session must stay open with a permission mode that won't prompt mid-night — see
docs/autonomy.md for the exact invocation and its limits.
