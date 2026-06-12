---
name: improve
description: Operator-driven iteration on a project after initial implementation — draft/debug/improve/crossover over experiment variants, optionally in parallel via worktree subagents. Argument; the idea slug (and optionally a focus, e.g. an experiment id).
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
     them as the parent before spawning; subagents never manage slots, commit in their
     branch, return a result packet, and never touch shared ledgers.
  3. **Merge through the journal, not git merges:** for each packet — append its
     `ledger_draft` to `EXPERIMENT_LOG.md` (keep AND revert decisions both get entries);
     for kept variants, merge the branch (configs + new modules only — conflict-free if
     extensibility rule 10 held), copy its `runs/<id>/` dirs + registry lines into the
     main tree, commit `exp-NNN: <outcome>`. Then
     `git worktree remove ../<slug>-wt-exp-NNN` and delete the branch (kept branches:
     delete after merge).

## Stage & gates

Operators run at SMOKE/PILOT scale. A variant that earns a FULL run goes through Gate 2
(PI approval or a recorded envelope) like any other experiment. Before declaring a new
best, confirm at `multi_seed_n` seeds via `scripts/sweep.py`.

## Exit

Stop when `loop.no_progress_backoff_cycles` consecutive cycles produce no progress
(best metric unmoved beyond seed noise and no planned question resolved), or the
phase's budget is spent. Summarize the tree (lines, best node, what was abandoned and
why) in `EXPERIMENT_LOG.md`, update PLAN.md and the registry, recommend `/analyze`.
