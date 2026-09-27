# Customising the workflow

The lab does research in a fixed sequence of stages: ideas → literature → scoping → proposal (Gate 1) →
experiments (Gate 2 per FULL run) → analysis → writing → internal review (Gate 3) → finalization. The
sequence is defined once, in `workflow/stages.yaml`. The guard, the executor and the dashboard all read
it (see [The workflow](workflow.md)).

The sequence stays fixed. **How** each stage is done is yours to change, in two ways:

- **Add instructions** to any procedure or stage. They are read every time it runs. Examples: "always
  compare against the 2024 baseline", "log GPU-hours in every ledger entry", "use dataset Y for this
  study", "never use dataset X".
- **Replace the method** of a procedure entirely. This is for when you want a stage done your own way
  (a different literature-search strategy, a different way to deliberate a design, your own drafting
  order).

Either works **lab-wide** or **for one study** (the study's own instructions add to the lab's).

## Where to do it

- **Workflow** (top nav) shows the stages in order, with the gates between them. Pick a stage to see its
  procedures; pick a procedure to open its sheet:
  - **Your instructions**: what gets added every time it runs. A picker sets whether they apply to the
    whole lab or only to one study.
  - **Method**: the default method, or yours. From here you can:
    - replace it;
    - edit your version;
    - compare it with the default;
    - go back to the default.

    If the default changes after you replaced it (a template update), the sheet says so.
  - **Always applies**: the procedure's contract and what it must still produce. Read-only.
  - **What the agent reads**: the exact text an agent gets for this stage, and its short hash. Every run
    records which version it used (`brief_sha`).

  Below the procedures are **stage-wide** instructions (for every procedure of the stage) and
  instructions for the **subagent roles** (critics, reviewers, the experiment runner, the overseer). Role
  instructions are added to the role for every backend.
- **A study's page → Instructions** lists every stage with that study's own customisations.

## What you can't change (on purpose)

Each procedure's `SKILL.md` is its **contract**:

- the guard calls;
- the ledgers and commits;
- the gates and stop points;
- the evidence rules (numbers trace to artifacts, citations come from the lit review, multi-seed before
  a finding);
- the write-back;
- the run footer.

The default **method** lives in `METHOD.md` beside it, and that is the part a replacement swaps out. A
test proves the split lost no rule and that no method file carries one, so replacing a method can never
switch off a gate or a check.

When your text conflicts with the rules, this order decides:

1. the contract and `AGENTS.md`'s hard rules;
2. the project's `TYPE.md`;
3. the study's instructions;
4. the lab's instructions;
5. the method.

If you restate a fixed rule in your instructions, the dashboard warns you that it can't change it.

## Agents suggest, you decide

Agents never edit their own instructions, procedures or roles; the signature guard refuses it. When an
agent thinks something should change, for example in `/finalize`'s retrospective, it files a proposal:

```bash
uv run --with pyyaml python tools/workflow.py propose --proc lit-review --mode add --file draft.md --why "…"
```

The proposal appears in **Needs you** and on the Workflow page, with a diff. **Accept** writes it;
**Decline** drops it.

## The files

The dashboard writes these for you, but they are plain Markdown and PI-owned:

| File | What |
|---|---|
| `lab/workflow/<procedure>.add.md` | instructions added to a procedure, lab-wide |
| `lab/workflow/<procedure>.method.md` | your replacement for its method |
| `lab/workflow/stage.<stage>.add.md` | instructions for every procedure of a stage |
| `lab/workflow/roles/<role>.add.md` | instructions added to a subagent role |
| `studies/<slug>/workflow/…` | the same, for one study |

`uv run --with pyyaml python tools/workflow.py brief <procedure> [--study <slug>]` prints what an agent
reads. `tools/workflow.py show` lists what is customised. `tools/workflow.py check` validates the
definition.
