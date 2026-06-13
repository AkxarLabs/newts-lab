# AGENTS.md — operating this lab with any coding agent

This file makes AutoScientist drivable by **any** agent that reads AGENTS.md (Codex,
Cursor, Gemini CLI, …). Claude Code is the first-class driver — it reads `CLAUDE.md`
and gets the procedures as native slash-command skills — but everything here is plain
files, so other agents can run the same lab.

## What this is

A research lab: you (the agent) take ideas from ideation → literature review → scoping
→ proposal → experimentation → analysis → paper → review → finalization, with the human
as PI at three gates. **Read `CLAUDE.md` first — it is the lab protocol and binds you
fully** (lifecycle, the three PI gates, the 13 hard rules, subagent rules, write-back
duties). This file only adds what's specific to non-Claude agents.

**Cold start:** if `lab/REGISTRY.md` is empty, the lab is fresh — run the `setup-lab`
procedure (a configuration interview) and offer the PI their on-ramp: `ideate` from
nothing, `adopt` for work they already have, `advance` for one verified stage at a
time, `autopilot` for a signed unattended campaign.

## Procedures

The workflow lives in `.claude/skills/<name>/SKILL.md` — plain-Markdown procedures
(`setup-lab`, `lab-status`, `configure`, `ideate`, `lit-review`, `critique-paper`,
`scope`, `propose`, `spawn-project`, `experiment`, `improve`, `research-loop`,
`autopilot`, `advance`, `adopt`, `analyze`, `make-figures`, `write-paper`,
`review-paper`, `finalize`).
They are written as instructions to an agent and contain no Claude-specific syntax:
**open the file and follow it step by step.** When the PI says "/ideate X", that
means: execute `.claude/skills/ideate/SKILL.md` with argument X.

## Approximating the multi-agent steps

Some procedures spawn parallel subagents (defined in `.claude/agents/*.md`). Without a
subagent mechanism, approximate them — the *contract* is what matters, not the
parallelism:

- **fresh-context-reviewer** (critique/review ensembles): the contract is *fresh
  context* — the reviewer must not have seen the paper being written or your opinion of
  it. Approximate with one fresh session (or maximally separated context) per lens,
  given ONLY the paper's file path + the lens definition + calibration block from
  `templates/review/critique-lenses.md`, writing its review to the designated path.
  Run lenses sequentially if you must; never skip the novelty lens or the meta-review's
  minority veto.
- **experiment-runner** (parallel variants in `/improve`): the contract is *worktree
  confinement + result packets + parent-only ledgers*. Without subagents, run variants
  sequentially in the main checkout — one at a time, same journal discipline. Skip the
  worktree machinery rather than half-following it.
- **ideation critics / scoping advocates**: argue each charge yourself *in writing,
  separately, before* synthesizing — the discipline is per-role separation, not
  parallelism.
- **overseer** (verification checks): the contract is *evidence-only judgment* — take
  the quoted statement and read ONLY the pointed evidence files, then grade
  (SUPPORTED/OVERREACH/UNSUPPORTED, or the critique-taste grades) before letting the
  statement drive any change. Doable inline if done before, and separately from,
  acting on the statement.

## Tools & environment

- All helpers are plain Python (stdlib + pyyaml): hub `tools/` (`check_lab.py`,
  `audit_claims.py`, `show_config.py`, `run_slots.py`, `s2.py`, `lab_bus.py`), project
  `scripts/` (`run.py`, `sweep.py`, `compare.py`, `status.py`, `check_project.py`,
  `lab_bus.py`). Invoke hub tools via `uv run --with pyyaml python tools/<script>.py`.
- An optional local dashboard lives in `dashboard/` (Marginalia) — it reads the bus and
  registry and never writes anything but PI directives; see `docs/dashboard.md`.
- Configuration is 3-layered (experiment yaml > project `control.yaml` >
  `lab/config.yaml`) — see `docs/configuration.md`.
- Projects live OUTSIDE this repo at `lab.projects_root` (default
  `../AutoScientist-Projects/<slug>`); each is its own git repo with its own AGENTS.md.

## Non-negotiables (compressed from CLAUDE.md — the full text governs)

1. Every number traces to a run artifact; no fabrication, failures recorded honestly.
2. Staged scale (smoke → pilot → full); FULL needs PI approval or a signed envelope.
3. Frozen things stay frozen: eval protocol, test sets, seeds policy, budgets.
4. Append-only ledgers; one commit per experiment attempt; registry updated every state change.
5. Acquire a compute slot before any PILOT/FULL campaign (`tools/run_slots.py`).
6. Stop at the three PI gates. Never end a session without the notebook/knowledge write-back.
