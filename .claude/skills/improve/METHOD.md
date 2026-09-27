# Improving the method: the operators

How this lab picks the next attempt by default, in the AIDE/AIRA style: the quality lives in the
**operators**. The PI can add to this or replace it (dashboard → Workflow). The contract (SKILL.md) fixes
the shared journal, the explore-mode operators (expand, revisit), parallel execution and merging, the
gates, the exit and selection discipline. This file is how to choose and brief each attempt.

## Reading the journal

Before every operator decision, reconstruct from the journal:
- the solution **lines** (chains of kept changes);
- each line's best node;
- which attempts failed.

Lines that differ only in parameters count as one mechanism.

## Picking the operator (once per cycle)

1. **debug**: if the most promising line's latest attempt failed AND its consecutive debug count is
   below `max_debug_depth`.
   - Context packet: that experiment's **ancestral chain only** (its ledger entries, `error.txt` and
     resolved config), nothing else.
   - Hitting the depth cap means recording the failure with its diagnosis and abandoning the line.
2. **draft**: if fewer than `num_drafts` mechanism-distinct lines exist.
   - Context packet: the **sibling table**, one row per existing line (config delta, best metric,
     one-line outcome).
   - Instruction: "propose something on a different mechanism — do not repeat any row".
3. **improve**: otherwise, mutate the best node of the most promising line.
   - Context packet: the sibling table of that line's prior attempts (for diversity pressure), plus the
     node's config and metrics.
4. **crossover** (optional): only when at least 2 lines each beat the baseline. Combine their kept
   components into one variant.

## Complexity-adaptive prompting

Every packet states `children_explored: N` for the node being extended:
- **N ≥ 3**: "simple variants are exhausted; propose structurally different / more advanced approaches."
- **Low N**: "prefer the minimal change that tests the mechanism."

## Proposing new lines in an `expand` round

- Propose lines that the results so far make promising.
- Each must use a different mechanism from every prior line.
- Each must stay within the headline hypothesis.
