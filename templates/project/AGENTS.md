# AGENTS.md — {{title}}

Operating notes for ANY coding agent working in this project repo (spawned from the
AutoScientist lab at `{{hub_path}}`). **Read `CLAUDE.md` in this directory first — it
is the project protocol and binds you fully** (orientation order, autonomy bounds,
subagent policy, the extensibility rules, session write-back). This file adds the
command crib and what's specific to non-Claude agents.

## Cold-start readiness checklist

Before the first experiment in a fresh clone or a just-spawned project, verify:

- [ ] `PLAN.md` filled from the approved proposal (not template placeholders)
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
rather than half-following it. The procedures themselves are plain Markdown at
`{{hub_path}}/.claude/skills/<name>/SKILL.md` — open and follow step by step.
