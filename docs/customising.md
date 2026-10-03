# Customising the lab

Everything that says how this lab works is yours to change: the stages a study moves through and where
each happens, the procedures agents run at each step, the subagent roles, the rooms of the building, the
rules, the checks that enforce them, and the kinds of project. It is all defined in files (`workflow/`,
`.claude/skills/`, `agent-roles/`, `checks/`, `templates/`, `lab/`), and the dashboard's **Compose** page
shows every one of them and edits every one of them.

## Compose

**Compose** (top nav) opens on a map of the lab: the **pipeline** (the stages left to right, their states
and procedures, the gates between them) and the **building** (the rooms, floor by floor, and the states
that stand in each). Every card opens into an editor. The side list has the rest: stages, procedures,
roles, rooms, rules, checks and project types, plus agents' suggestions and what you have published.

Each editor gives you a form for what a form makes easy and the files for everything else:

- **A procedure**: its title, what it does, when it stops, the stages it serves, whether it is offered in
  *Start something*, how it runs. Then:
  - **Method**: how the work is done. Rewrite it for the whole lab, compare yours with the default, or go
    back to the default. If the default changes after you replaced it (a template update), it says so. A
    procedure you made yourself has its method as its own file.
  - **Your instructions**: added every time it runs, on top of its method.
  - **Files**: its `SKILL.md` (the contract every run follows) and anything beside it.
- **A stage**: its title, its procedures in order, its states (their names and the room each stands in),
  and instructions for every procedure of the stage. **New stage** adds one after any other, with its
  first state, in a room you pick.
- **A room**: its sign, its column name on the Studies board, its floor and position, which states stand
  in it, and its art (a small script; start from any room's art).
- **A role**: its name, what it is for, your instructions for it (added for every agent CLI), its files.
- **Rules**: each rule's text and the checks that enforce it; add rules to any list.
- **Checks** and **project types**: their files.

### Adding something: copy the closest thing

**New …** on any list starts from a copy of the closest thing the lab already has: a quicker variant of
*Review the literature*, a data room like *The Lab*, a role like the experiment runner. The copy keeps
everything; you change what makes yours different. (The same, from a terminal:
`tools/new.py skill|room|role|check|type|rule <name> --like <existing>` — see [Extending the lab](extending.md).)

### A draft, then publish

Nothing you change in Compose reaches the lab or a run until you publish it:

1. The first edit starts a **draft**: a private copy of the lab's definition (`lab/.bus/compose/`). Every
   later edit changes the draft only. A bar on every Compose page says so, and how many files changed.
2. **Review & publish** shows each changed file with its diff, and whether the lab still reads
   consistently: no stage names a procedure that is gone, every state has a room, no study is left in a
   state that no longer exists, and nothing locked was touched. Problems must be fixed first.
3. **Publish** writes the files into the lab, regenerates the agent manuals and the role files, and
   records the change. Runs already going finish with what they started with; the next run uses the new
   definition.
4. **Published** lists every publish. The latest can be **undone**, which puts the files back as they
   were.

**Discard** drops the draft and leaves the lab as it is. If something in the lab changed while you had a
draft open (an agent's suggestion you accepted, a file edited by hand), publishing refuses rather than
overwrite it.

### The one-minute tour

The setup wizard's last step, Home's first screen and the Compose page all offer a short tour: copy a
procedure, change how it works, publish it. That is the whole idea, and every other part of the lab works
the same way.

## One study's own instructions

A study's page has an **Instructions** tab: per procedure, add instructions or replace the method for that
study alone, plus instructions for every procedure of a stage. These save at once (they are about one
study, not the lab's design) and are added on top of the lab's.

## What stays fixed (on purpose)

A few things no customisation changes, because the lab's guarantees rest on them. Compose shows them with a
lock and refuses a draft that changes them:

- **the three gates**: where each is signed and what it opens (you can rename, add and move stages
  around them);
- **the tables the safety code reads** in `workflow/rules.yaml`: what a headless run may never write,
  which settings only you change, the rigor floors, and the audits a delegated Gate 3 re-runs;
- **the hard rules' numbering**: skills cite them by number, so edit their text or add new ones at the
  end, but don't remove or reorder them;
- **/finalize** only ever starts from a Gate 3 signature.

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

The proposal appears in **Needs you** and in Compose under **Agents' suggestions**, with a diff. **Accept** writes it;
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
| `lab/.bus/compose/` | your draft, while one is open, and what each publish replaced (for undo) |

`uv run --with pyyaml python tools/workflow.py brief <procedure> [--study <slug>]` prints what an agent
reads. `tools/workflow.py show` lists what is customised. `tools/workflow.py check` validates the
definition.
