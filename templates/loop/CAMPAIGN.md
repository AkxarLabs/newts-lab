# Campaign Brief — {{date}}-{{slug}}

*Created by `/autopilot` · Everything above the Campaign Log is FROZEN once signed.*

## Direction & targets

- **Research direction(s):** <!-- from the PI -->
- **Target:** carry up to ___ ideas end-to-end (ideation → … → internal-review draft)
- **Parallelism:** ≤ ___ ideas in flight (compute slots still cap training runs)

## Gate 1 delegation (the PI pre-authorizes proposal approval WITHIN these bounds)

A proposal may be self-approved by the agent only if ALL hold:
- [ ] Compute budget ≤ ___ total, FULL runs ≤ ___ × ___ min (becomes each project's envelope)
- [ ] Kill criteria + frozen eval protocol + held-out test present (mechanical check)
- [ ] Novelty verdict from /lit-review is `novel` (not `incremental`)
- [ ] Scoping value re-verification passed with ≤ ___ open questions
Anything outside these bounds queues for the PI and the campaign moves to the next idea.

## What is NEVER delegated

- **Gate 3.** Papers end the campaign at `internal-review` — drafts with morning
  reports, never "final", never sent anywhere.
- Changes to frozen settings; budgets beyond this envelope; resurrection of killed ideas.

## Campaign budget & stop conditions

- **Total wall-clock:** ___ (e.g. "tonight, 8h") · **Total compute:** ___
- Stops when: budget exhausted · all target ideas reach internal-review/killed ·
  `loop.no_progress_backoff_cycles` applied campaign-wide · environment failure.

## PI authorization

- [ ] Authorized as scoped above · **PI:** ______ · **Date/time:** ______

## Campaign Log (append-only)

| time | idea | lifecycle step | outcome / route | note |
|---|---|---|---|---|
