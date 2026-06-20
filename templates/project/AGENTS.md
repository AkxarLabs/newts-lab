# AGENTS.md — {{title}}

Operating notes for ANY coding agent working in this project repo (spawned from the
Kartr Lab at `{{hub_path}}`). **Read `CLAUDE.md` in this directory first — it
is the project protocol and binds you fully** (orientation order, autonomy bounds,
subagent policy, the extensibility rules, session write-back). This file adds the
command crib and what's specific to non-Claude agents.

## Cold-start readiness checklist

Before the first experiment in a fresh clone or a just-spawned project, verify:

- [ ] `PLAN.md` filled from the approved proposal (not template placeholders)
- [ ] `NOTES.md` read in full (distilled gotchas / tried-and-abandoned / what's settled — don't repeat past mistakes)
- [ ] `control.yaml` parses; budgets set; if FULL work is expected, `gate2_envelope.pi_signed: true`
- [ ] `SYSTEM.md` read, if present (machine constraints — binding)
- [ ] `uv sync` clean, then smoke green:
      `uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml` + `uv run pytest`

…or just run the lint, which checks all of this and suggests the next action:

```bash
uv run --with pyyaml python scripts/check_project.py
```

## Running experiments

```bash
uv sync                                                          # once
uv run python scripts/run.py --config configs/experiments/<exp>.yaml [--seed N]
uv run python scripts/sweep.py --config <exp>.yaml --seeds 0,1,2   # multi-seed
uv run python scripts/compare.py best --metric <m> [--minimize]    # query results
uv run python scripts/status.py                                    # check a live run
uv run pytest                                                      # keep green forever
```

## Without a subagent mechanism

`CLAUDE.md`'s subagent policy assumes parallel worktree subagents. Without them, run
variants **sequentially in this checkout** — one at a time, same journal discipline
(one config, one ledger entry, one commit per attempt). Skip the worktree machinery
rather than half-following it.

## Skills in this repo (works for any agent — Claude or Codex)

Two sets of procedures, both plain Markdown — **reading the file IS invoking the skill; there
is no runtime to install:**

- **Local engineering skills** at `.claude/skills/<name>/SKILL.md` — these ship in *every*
  project so they work standalone, even detached from the hub:
  - `grill-with-docs` — sharpen a plan/design via a relentless one-question-at-a-time grilling
    loop, recording a glossary (`CONTEXT.md` at the repo root) + ADRs (in `adr/`). Composes
    `grilling` + `domain-modeling`. Vendored, MIT — see `grill-with-docs/NOTICE`. Reach for it
    before a non-trivial refactor or new-module design (distinct from the hub's *research* design
    records).
- **Research-lifecycle procedures** live in the HUB at `{{hub_path}}/.claude/skills/<name>/SKILL.md`
  (`experiment`, `improve`, `ideate --in-project`, `analyze`, `make-figures`, …) — same convention:
  open the file and follow it step by step.

**For Codex (or any non-Claude agent):** you discover the local skills via this `AGENTS.md` (you
read it natively); a Claude session discovers them via `.claude/skills/`. Either way the `SKILL.md`
*is* the instruction.

## Dual-agent file conventions

- One change = one experiment = one `EXPERIMENT_LOG.md` entry + one commit (rule 3; hub hard rules 7–8, 11).
- `NOTES.md` is the shared distilled-memory file — read it in full at session start; append one line
  per durable local lesson. Both agents.
- PI-owned files are **read-only**: `control.yaml`'s marked keys, `SYSTEM.md`, and the frozen rows of
  `PLAN.md`. Never edit the hub repo except via the `hub_writeback.py` write-back.
