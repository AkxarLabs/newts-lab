---
name: scope
description: Deep project scoping — enumerate every key design decision, deliberate each branch (optionally with parallel advocate subagents), record an ADR-style decisions.md, and re-verify the project is valuable before proposing. Argument; the idea slug.
---

# Scope (design deliberation)

Input: idea in state `lit-review` with a novel/incremental verdict. Output:
`studies/<slug>/decisions.md` (from `templates/idea/decisions.md`) with every key design
decision deliberated and settled — the raw material `/propose` builds on. Depth knobs:
`scoping.*`.

This file is the procedure's **contract**: the decision record, the `Headline` flag, the OPEN cap, the
kill checkpoint and the hand-off always bind. *How* to enumerate and deliberate is the stage's
**method**, which step 0 loads (the default `METHOD.md` beside this file, or the PI's replacement, plus
the PI's own instructions for this stage).

**Advocates are the named `scoping-advocate` role** (`.claude/agents/scoping-advocate.md`, rendered by
`tools/role_sync.py` with `agents.critic_model`/`critic_effort` already resolved). Spawn them with
`subagent_type: scoping-advocate` so the model binding and the dashboard's trace come for free, and start
each spawn's description with the decision + option (e.g. "D-003 tokenizer: BPE"). Backends without role
files: `uv run --with pyyaml python tools/role_sync.py resolve critic` prints the `model=`/`effort=` to
pass per spawn; otherwise advocates run at the session model.

## 0. Load this stage's brief

`uv run --with pyyaml python tools/workflow.py brief scope --study <slug>`. Skip this if a
`NEWTS STAGE BRIEF /scope` block is already in your context. Follow its method and instructions within
this contract.

Then set state → `scoping` (frontmatter + registry).

## 1. Enumerate the decision branches

Read `IDEA.md` (with the reflection summary), `lit-review.md` (especially positioning) and, if present,
the `/discuss scope` session doc(s) in `studies/<slug>/sessions/`, which are the PI-settled starter
decision list; never re-derive a decision the PI already framed. Enumerate the decisions as the method
describes.

## 2. Deliberate each branch — in order

Deliberate each decision as the method describes. If `scoping.advocate_subagents` is set, run one
**`scoping-advocate`** subagent per option in parallel (see the header note); otherwise argue each side
yourself, in writing, before choosing. Every decision is then recorded like this:

1. A written rationale, a **rejected-because** line per alternative, and a **revisit-if** condition.
2. **`Headline: yes`** if the choice is load-bearing for the central hypothesis the project's novelty
   rests on (what the paper fundamentally claims); else **`Headline: no`**, a supporting decision. This
   flag is the autonomy boundary downstream: an `explore`-mode loop may reopen a `Headline: no` decision
   itself when the revisit-if trigger fires, but reopening a `Headline: yes` one escalates to the PI.
3. A D-NNN entry in `decisions.md` (with its `Headline` flag). Decisions are append-only after Gate 1:
   reopening one is a new entry referencing the old.
4. For a settled **`Headline: no`** decision, also fill the **`Revisit predicate:`** line, the
   machine-checkable form of its `Revisit if:` trigger (grammar + example in the template). Lint with
   `uv run --with pyyaml python tools/guard.py decisions <slug>` before `/propose` (BLOCKS on a malformed
   predicate; WARNs on a missing one).

A decision that genuinely cannot be settled without data may be left **OPEN** with the pilot experiment
that will settle it named — but at most `scoping.max_open_questions`; more means the idea isn't ready to
propose.

## 3. Value re-verification (the kill checkpoint)

With all decisions on the table, re-verify the value as the method describes (is it still novel,
valuable and feasible?).

Any "no" → kill or park NOW: record the reason in IDEA.md, harvest surviving threads into
`OPEN-QUESTIONS.md`, update the registry. (`FAILURES.md` only if the scoping produced a substantive
negative finding worth transferring.) This is the cheapest place in the lifecycle to stop a doomed
project — killing here is success, not failure.

## 4. Hand off

- Summarize: the decision list (one line each), open questions, and the value verdict.
- Update IDEA.md state log; registry next action = "/propose".
- `/propose` consumes `decisions.md` directly: §3 Method and §4 Experimental design are assembled from
  settled decisions, and OPEN decisions become explicit pilot rows in the experiment table.
