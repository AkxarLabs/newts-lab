---
name: spawn-project
description: Instantiate a project repo under projects/<slug>/ from templates/project/ for an approved proposal. Argument; the idea slug.
---

# Spawn Project

Input: idea in state `proposal` with PI Gate 1 approval recorded. Output: a runnable, committed project repo.

## Procedure

1. Verify Gate 1 approval in `ideas/<slug>/proposal.md`. If absent, stop and route back to `/propose`.
2. Copy `templates/project/` → `projects/<slug>/`. Substitute `{{slug}}`, `{{title}}`, `{{date}}` in README.md, pyproject.toml, PLAN.md, EXPERIMENT_LOG.md. (Keep the `project_pkg` package name unless the project will be published standalone — renaming is optional polish, not required.)
3. Fill `PLAN.md` from the approved proposal: frozen eval protocol, budgets, kill criteria, the staged experiment table, the ablation plan.
4. Add the project's real dependencies to `pyproject.toml` (minimal set; pin via lock).
5. Initialize: `git init`, then `uv sync`, then run the smoke pipeline:
   - `uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml`
   - `uv run pytest tests/`
   Commit only once both pass ("scaffold: spawn from AutoScientist template, smoke green"). Commit the `uv.lock`.
6. Update hub state: IDEA.md → `active`, registry row gains the project path, next action = "/experiment exp-002". Append a lab notebook entry.
7. Report to the user: project path, smoke/test status, first planned experiment.

## Rules

- The template's toy experiment stays until the first real experiment replaces it — the smoke test must always pass.
- Never start domain experiments in the same session-step as scaffolding; spawn cleanly, then `/experiment`.
