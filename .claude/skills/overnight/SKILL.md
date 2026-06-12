---
name: overnight
description: Authorize and run an unattended end-to-end campaign — multiple ideas carried from ideation through experiments to reviewed paper drafts while the PI sleeps. One setup conversation, then the lab runs itself within a signed brief.
---

# Overnight Campaign

"One command before bed, drafts in the morning." Honest semantics up front: the
campaign delivers papers at **`internal-review`** — fully drafted, claims-audited,
ensemble-reviewed — for your morning Gate 3 read. Gate 3 is never delegated; that's
what keeps the lab's name worth something.

## 1. Authorization conversation (10 minutes, the only interactive part)

1. Ask the PI: direction(s); how many ideas to carry (1–4 is realistic per night);
   total compute/wall-clock budget; the Gate 1 delegation bounds.
2. Fill `templates/loop/CAMPAIGN.md` → `lab/campaigns/<date>-<slug>.md` and present it.
   **The signed brief is the campaign's gate record** — Gate 1 is delegated *within its
   bounds*, Gate 2 envelopes derive from it (written into each spawned project's
   `control.yaml`), Gate 3 is explicitly excluded.
3. PI signs → begin. No brief, no campaign.

## 2. The campaign loop (unattended)

Work ideas as a portfolio — while one idea's training run is in flight (zero-token
monitoring, slot rules), advance another idea's CPU-light stages:

```
per idea:  /ideate(direction) → /lit-review → /scope → /propose
           → self-check against the delegation bounds:
               within bounds → record auto-approval in the proposal + Campaign Log
               outside      → queue for PI, take the next idea
           → /spawn-project (envelope from the brief into control.yaml)
           → /research-loop (its LOOP_BRIEF derives from the campaign brief)
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
- Every lifecycle step appends a Campaign Log row.

## 3. Morning report (campaign exit)

Write at the top of the notebook entry, in this order:
1. **Drafts awaiting Gate 3** — per paper: title, headline result (with run ids),
   ensemble median Overall, unresolved review items.
2. **Killed/parked ideas** with one-line reasons (knowledge, not failure).
3. **Queued PI decisions** — proposals outside delegation, frozen-setting requests.
4. Budget actually spent vs the brief; recommended next command.
Then the standard write-back (registry, knowledge promotion) for everything touched.

## Keeping it running

Within one session this skill just runs. For resilience across a long night, pair it
with the harness's looping: `/loop /overnight continue <campaign-file>` re-enters the
campaign on an interval and each entry resumes from the Campaign Log (the brief +
logs make every step recoverable — that's why they're append-only).
