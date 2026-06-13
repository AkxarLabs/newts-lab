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

**Loop mode for spawned projects:** `execute` <!-- execute | explore -->. In `explore`,
each project's loop may autonomously expand the frontier and reopen NON-headline design
decisions within its envelope (caps: ___ expansion rounds, ___ new lines/round → written into
each LOOP_BRIEF). Reopening a project's **headline** decision, touching the frozen set, or
exceeding the envelope is checked against these delegation bounds + an overseer `support` pass
(like Gate-1 self-approval); out of bounds → queue for the PI. Never silent.

## What is NEVER delegated

- **Gate 3.** Papers end the campaign at `internal-review` — drafts with morning
  reports, never "final", never sent anywhere.
- Changes to frozen settings; budgets beyond this envelope; resurrection of killed ideas.

## Campaign budget & stop conditions

- **Total wall-clock:** ___ (e.g. "tonight, 8h") · **Total compute:** ___
- Stops when: budget exhausted · all target ideas reach internal-review/killed ·
  `loop.no_progress_backoff_cycles` applied campaign-wide · environment failure.
- **Campaign cycle / progress (so the backoff is measurable):** one campaign cycle = one
  `/autopilot continue` (re-)entry, i.e. one full portfolio pass. *Progress* in that cycle =
  any idea advanced a lifecycle state, OR any project loop logged `progress=yes`, OR an idea
  was killed (a kill is knowledge, not a stall). `loop.no_progress_backoff_cycles`
  consecutive cycles with none of those → stop with a written diagnosis.

## PI authorization

- [ ] Authorized as scoped above · **PI:** ______ · **Date/time:** ______

## Campaign Log (append-only)

| time | idea | lifecycle step | outcome / route | progress? | note |
|---|---|---|---|---|---|
