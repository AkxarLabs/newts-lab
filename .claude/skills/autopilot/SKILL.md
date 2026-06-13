---
name: autopilot
description: Authorize and run an unattended end-to-end campaign — multiple ideas carried from ideation through experiments to reviewed paper drafts while the PI is away. One setup conversation, then the lab runs itself within a signed brief.
---

# Autopilot Campaign

The full-autonomy mode: "one command before bed, drafts in the morning" — though a
campaign can just as well run a weekend. Honest semantics up front: the campaign
delivers papers at **`internal-review`** — fully drafted, claims-audited,
ensemble-reviewed — for the PI's Gate 3 read. Gate 3 is never delegated; that's
what keeps the lab's name worth something.

## 1. Authorization conversation (10 minutes, the only interactive part)

1. Ask the PI: direction(s); how many ideas to carry (1–4 is realistic per night);
   total compute/wall-clock budget; the Gate 1 delegation bounds.
2. Fill `templates/loop/CAMPAIGN.md` → `lab/campaigns/<date>-<slug>.md` and present it.
   **The signed brief is the campaign's gate record and the PI's signature carrier** —
   Gate 1 is delegated *within its bounds*; Gate 2 envelopes derive from it (written into
   each spawned project's `control.yaml` with `pi_signed: true` and `signed_via:
   lab/campaigns/<file>`), and each project's `LOOP_BRIEF` authorization line is filled
   "PI via campaign brief `lab/campaigns/<file>`"; Gate 3 is explicitly excluded. This is
   how the campaign legally satisfies `/research-loop`'s entry gate unattended — the brief
   IS the PI signature, within its bounds. A run outside the bounds still queues for the
   PI; the agent never widens an envelope or signs beyond what the brief covers.
3. PI signs → begin. No brief, no campaign.

## 2. The campaign loop (unattended)

Work ideas as a portfolio — while one idea's training run is in flight (zero-token
monitoring, slot rules), advance another idea's CPU-light stages:

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
- **All ordinary machinery applies unchanged** — slots, watchdogs, ledgers, oversight
  checks, author-response triage, claims audits. A campaign is normal operation minus
  the wait for the PI, never a relaxed mode.
- Kill criteria fire exactly as in interactive mode; a night that kills 3 ideas cheaply
  and ships 1 strong draft beats 4 weak drafts.
- NEEDS-EXPERIMENT review items are followed within remaining budget; otherwise queued.
- **Explore-mode pivots** (if the campaign authorized `explore`): a project loop may reopen
  `Headline: no` decisions and expand the frontier autonomously within its envelope. A
  `Headline: yes` reopen (abandoning a project's central hypothesis) is checked against the
  campaign's Gate-1 delegation bounds + an overseer `support` pass — exactly like a Gate-1
  self-approval; within bounds → record it and continue, outside → queue for the PI and move
  on. Frozen-set changes and envelope overruns are never delegated.
- Every lifecycle step appends a Campaign Log row **and** emits a bus event
  (`tools/lab_bus.py emit cycle --idea <slug> --detail "<step> → <outcome>"`); at the start
  of each portfolio pass, check `tools/lab_bus.py inbox` and act on any PI directive.

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
3. **Reconcile the crashed session before launching anything:** `run_slots.py status` (a
   slot this campaign holds whose run already finished → release it); run `scripts/status.py`
   in each active project (an in-flight run → re-attach monitoring instead of launching new
   work; a dead run → record it failed). Treat the last Campaign Log row as possibly
   half-done: confirm its artifacts exist before re-running the step.
4. **If a stop condition already holds** (wall-clock expired, environment failure logged,
   all ideas terminal), go straight to §3 and write the morning report — an empty or
   crashed night still gets a report with budget-spent and a one-line diagnosis. Otherwise
   resume §2 from the first incomplete step.

Campaign Log rows are appended **on each step's completion, before starting the next** —
so the row after the last one is the resume point, and a missing row means re-verify.

## Keeping it running

Within one session this skill just runs. For resilience across a long night, pair it
with Claude Code's built-in scheduler: `/loop 30m /autopilot continue <campaign-file>`
re-enters the campaign on an interval (the Re-entry path above). The brief + append-only
logs make every step recoverable. The session must stay open with a permission mode that
won't prompt mid-night — see docs/autonomy.md for the exact invocation and its limits.
