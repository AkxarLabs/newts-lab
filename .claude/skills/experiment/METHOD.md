# Experiments: the method

How this lab runs experiments by default. The PI can add to it or replace it (dashboard → Workflow). The
contract (SKILL.md) fixes the inbox checkpoint, config immutability, the stage gates and preflights, the
runner, the ledger and commits, the frozen set, the kill criteria and the multi-seed rule. This file is
how to use the stages well.

## Using the stages

- **SMOKE**: minutes. It proves the pipeline and the artifacts end to end on a new code path, and nothing
  more.
- **PILOT**: the smallest run that can meet, or fail, the pre-written criterion. If a pilot can't
  possibly fail, it is too small or measures the wrong thing.
- **FULL**: only after a pilot justified it. Before launching, state the budget, the expected wall-clock,
  and what decision the run informs.

## Working from memory

- Read the ledger and notes before each attempt so you never re-run a known dead end.
- New behaviour goes behind a config switch; the baseline path stays untouched. A variant is a new config
  file.

## Debugging

- When an attempt fails, look at its *ancestral chain* (this experiment's previous attempts), not at
  unrelated history.
- Fix one thing per attempt, and write down the diagnosis even when the fix fails.

## Plan drift

- A new experiment idea discovered mid-loop goes into PLAN.md as a new row, with its criterion.
- Run it ahead of planned work only if it is cheaper AND more decisive.

## Parallel work

- Independent configs (a seed sweep, disjoint ablations) may run as parallel background processes, or as
  isolated experiment-runner subagents (the contract's parallel path).
- Parallelize only work that doesn't depend on another's result.
