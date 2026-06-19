---
name: improve
description: Operator-driven iteration on a project after initial implementation — draft/debug/improve/crossover over experiment variants, optionally in parallel via worktree subagents. Argument; the idea slug, then optional tokens — a focus (e.g. an experiment id) and/or the mode token `explore` to enable the expand/revisit operators (default `execute`).
---

# Improve (operator loop)

Iterates on the project repo at `<projects_root>/<slug>` to push the primary metric,
AIDE/AIRA-style: the quality lives in the **operators**, not in clever search.
Defaults from the project's `control.yaml` (`parallelism.*`, `seeds.*`), falling back
to `lab/config.yaml` (`experiment.*`): `max_debug_depth`, `num_drafts`,
`max_parallel_subagents`, `multi_seed_n`. If the project has a `SYSTEM.md`, its machine
constraints bind every variant (and are passed to runner subagents' context packets).

## The journal is the tree

`EXPERIMENT_LOG.md` entries with `Parent:`/operator fields + `runs/registry.jsonl` +
`git log` form the experiment tree — **one namespace shared with `/experiment`**: every
attempt from either skill is a node here, so sibling tables and "already tried" checks
see everything. Before every operator decision, reconstruct from the journal: the
solution **lines** (chains of kept changes), each line's best node, and which attempts
failed. Never act without reading the journal first.

## Operator selection (per cycle)

1. **debug** — if the most promising line's latest attempt failed AND its consecutive
   debug count < `max_debug_depth`. Context packet = that experiment's **ancestral chain
   only** (its ledger entries, `error.txt`, resolved config) — nothing else. Hitting the
   depth cap → record the failure with diagnosis, abandon the line.
2. **draft** — if fewer than `num_drafts` mechanism-distinct lines exist (lines differing
   only in parameters count as one). Context packet = the **sibling table**: one row per
   existing line (config delta, best metric, one-line outcome) with the instruction
   "propose something on a different mechanism — do not repeat any row".
3. **improve** — otherwise: mutate the best node of the most promising line. Context
   packet = sibling table of that line's prior attempts (diversity pressure) + the
   node's config and metrics.
4. **crossover** (optional) — only when ≥2 lines each beat the baseline: combine their
   kept components into one variant. The combination **immediately enters PLAN.md's
   ablation plan** — stacked, un-ablated changes are banned (hard rule).

**Complexity-adaptive prompting:** every packet states `children_explored: N` for the
node being extended. N ≥ 3 → "simple variants are exhausted; propose structurally
different / more advanced approaches." Low N → "prefer the minimal change that tests
the mechanism."

## Explore-mode operators (expand / revisit)

These two operators **change the plan itself** rather than extend it, so they are gated:
available only when the project is being driven in **explore** mode — either a PI ran
`/improve <slug> [focus] explore` (the `explore` mode token, default `execute`), or
`/research-loop` is sequencing them under a LOOP_BRIEF whose `Mode: explore` (see that skill).
In `execute` mode they are off and `/improve` behaves exactly as the four operators above.
The **manual `/improve <slug> explore` path honors the same checks as the loop path**: the
`loop.explore_*` caps (`explore_max_expansion_rounds`/`…_new_lines_per_round`), the **frozen
set** (eval/test/seeds/budgets/kill-criteria — never touched), and the **Gate-2 envelope** all
bind identically — a manual `explore` does not get more rope than the loop, and a `Headline: yes`
reopen escalates the same way (below). Default `execute`, so absent the token nothing changes.

5. **expand** (results-grounded frontier expansion) — when the planned table, its ablation
   rows, and the `num_drafts` lines are all exhausted but budget remains. Context packet =
   a **results digest** (each line's best node + metric + one-line outcome from
   `EXPERIMENT_LOG.md`, the hub's `FINDINGS.md`/`FAILURES.md` for this idea, and the
   **headline hypothesis** verbatim from PLAN.md) + the instruction "propose up to
   `loop.explore_max_new_lines_per_round` *mechanism-distinct* lines that the results so far
   make promising, each WITHIN the headline hypothesis — do not repeat any prior line."
   Each proposed line is appended to PLAN.md tagged `(expand Rn)` **with a pre-written
   promotion criterion** (no criterion → not a valid row), then runs through the four
   operators above like any planned work. This is `draft`'s generative spirit, seeded by
   evidence instead of capped at `num_drafts`. Emit `frontier_expand`.
6. **revisit** (reopen a design decision — "discard a pre-conceived idea") — when artifacts
   satisfy the **`Revisit if:`** trigger of a settled decision in the idea's `decisions.md`.
   - **Boundary check first (mechanical):** if that decision is `Headline: yes`, this is the
     escalation boundary — do NOT execute the reopen as an in-place re-plan. This is the entry
     point to **divergent method-ideation, not a dead end**: route to `/ideate --in-project <slug>`
     (under `ideation.in_project_approval`) — or a successor hub `/ideate` — whose surviving
     approaches re-enter `/propose` (a mini-proposal crossing Gate 1) or spawn a successor idea,
     never entering experiments on a bare PI note. In a manual run, stop and write a PI note that
     names this route; under `/research-loop`, queue that PI note **and emit `uv run python
     scripts/lab_bus.py escalate --detail "headline reopen — needs PI"`** so it reaches the hub
     mid-run (not only at loop exit) — or, under a signed `/autopilot` campaign, run the
     campaign-delegation check + overseer `support` pass exactly as for a Gate-1 self-approval,
     then hand off to `/ideate --in-project`. A `Headline: no` decision, with the
     frozen set intact and the envelope not exceeded, is **autonomous**.
   - **Overseer gate** (`oversight.level` ≠ off): before reopening, spawn one `overseer`
     `support` check giving it the `Revisit if:` text + the contradicting run-artifact paths
     only — UNSUPPORTED means the trigger did **not** fire, leave the decision settled.
   - **Action:** append a new `D-NNN` to `decisions.md` referencing the old (the old stays —
     append-only), set the dependent PLAN.md experiment rows to `retired-by-revision` (the
     project continues; their artifacts and ledger entries remain as evidence), record a
     Re-planning-log row, and seed replacement line(s) under the new choice (which then flow
     through the operators above). Emit `decision_revisit` and `replan`.

## Execution — sequential or parallel

- **Sequential** (default): apply the operator yourself per the `/experiment` rules
  (new config, smoke→pilot, ledger entry with `Parent:` fields, one commit).
- **Parallel** (independent variants, e.g. several drafts or disjoint improves): up to
  `max_parallel_subagents` at once —
  1. Per variant: `git -C <projects_root>/<slug> worktree add ../<slug>-wt-exp-NNN -b exp-NNN`
     (worktrees are siblings inside the projects root, next to the project repo;
     check_lab.py ignores `-wt-` dirs).
  2. Spawn one `experiment-runner` subagent per variant (model: `agents.runner_model`)
     with: the worktree path, the operator type, the context packet, and the stage
     budget. PILOT-running variants each need a compute slot (hard rule 13) — acquire
     them as the parent before spawning. **Spawn at most as many PILOT-running variants
     as slots granted**; with the default `max_concurrent_runs: 1`, that is one — run the
     rest SMOKE-only in parallel (SMOKE needs no slot) or queue them for the next batch,
     and never spawn a PILOT-running runner without holding its slot. Subagents never
     manage slots, commit in their branch, return a result packet, and never touch shared
     ledgers.
  3. **Merge through the journal, not git merges** (CLAUDE.md subagent rule 3) — for each
     packet, in this order:
     - Append its `ledger_draft` to `EXPERIMENT_LOG.md` (keep AND revert both get entries).
     - **Copy `runs/<id>/` dirs + the variant's new `runs/registry.jsonl` lines into the
       main tree — for EVERY packet, keep or revert.** A reverted variant's artifacts are
       evidence too (hard rules 1, 2; `/experiment` step 4: revert the code but keep the
       ledger entry and registry line). Do this *before* removing the worktree, because
       `runs/*` is gitignored and `git worktree remove` would delete it permanently.
     - For **kept** variants only, take the code by path — `git -C <projects_root>/<slug>
       checkout exp-NNN -- configs/ src/` (configs + new modules; never a full `git merge`,
       which would conflict/duplicate on the tracked `registry.jsonl`) — then commit
       `exp-NNN: <outcome>`.
     - Then `git worktree remove ../<slug>-wt-exp-NNN` and delete the branch (`-D`).

## Stage & gates

Operators run at SMOKE/PILOT scale. A variant that earns a FULL run goes through Gate 2
(PI approval or a recorded envelope) like any other experiment. Before declaring a new
best, confirm at `multi_seed_n` seeds via `scripts/sweep.py`.

## Exit

Stop when `loop.no_progress_backoff_cycles` consecutive cycles produce no progress
(best metric unmoved beyond seed noise and no planned question resolved), or the budget
allotted to this iteration phase is spent (the compute note in the proposal/`PLAN.md`, or
— under `/research-loop` — the cycle's slice of the loop envelope). **In explore mode**,
"the operators are exhausted" is not yet a stop: run an `expand` round first (up to
`loop.explore_max_expansion_rounds`), and only stop when the rounds cap is reached or the
no-progress backoff fires (an expand round that yields no progress counts toward it).
Summarize the tree (lines, best node, what was abandoned and why) in `EXPERIMENT_LOG.md`,
update PLAN.md and the registry, recommend `/analyze`.

**Selection discipline (louder during exploration):** every expanded or replacement line is
tuned on validation and reported on the **frozen test**, and needs `multi_seed_n` seeds before
any number is paper-grade. The more expansion rounds you run, the more validation overfits
(hard rule 5) — that is exactly why the rounds are capped.
