---
name: spawn-project
description: Instantiate a project repo at <projects_root>/<slug> (outside the hub) from templates/project/ for an approved proposal. Argument; the idea slug.
---

# Spawn Project

Input: idea in state `proposal` with PI Gate 1 approval recorded. Output: a runnable,
committed project repo at `<projects_root>/<slug>` — **outside the hub**, so the hub
stays lean and the project is independently cloneable.

## Procedure

1. Verify Gate 1 approval in `ideas/<slug>/proposal.md`. If absent, stop and route back to `/propose`.
2. Resolve `lab.projects_root` from `lab/config.yaml` (default `../AutoScientist-Projects`,
   relative to the hub). If the container directory doesn't exist, create it with a
   one-paragraph README ("Projects spawned by the AutoScientist lab at <hub path>; each
   is an independent git repo — see the hub's lab/REGISTRY.md for the index").
3. Copy `templates/project/` → `<projects_root>/<slug>`. Substitute `{{slug}}`,
   `{{title}}`, `{{date}}`, `{{hub_path}}` in README.md, pyproject.toml, PLAN.md,
   EXPERIMENT_LOG.md, **control.yaml**, **AGENTS.md**. (Keep the `project_pkg` package
   name unless the project will be published standalone — renaming is optional polish,
   not required.)
4. **Configure `control.yaml`** (this IS the project's end-to-end run config, created at
   setup): fill budgets/seeds/loop values from the approved proposal; if the PI approved
   a Gate 2 envelope at Gate 1, record it in `gate2_envelope` (with `pi_signed: true`)
   — control.yaml is the canonical machine-readable envelope.
5. Fill `PLAN.md` from the approved proposal: frozen eval protocol, kill criteria, the
   staged experiment table, the ablation plan (budgets live in control.yaml — reference,
   don't duplicate).
6. Add the project's real dependencies to `pyproject.toml` (minimal set; pin via lock).
7. Initialize: `git init`, then `uv sync`, then run the smoke pipeline:
   - `uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml`
   - `uv run pytest tests/`
   Commit only once both pass ("scaffold: spawn from AutoScientist template, smoke green"). Commit the `uv.lock`.
8. Update hub state: IDEA.md → `active`, registry row's Project column = the relative
   path (e.g. `../AutoScientist-Projects/<slug>`), next action = "/experiment exp-002".
   Append a lab notebook entry.
9. Report to the user: project path, smoke/test status, control.yaml summary, first
   planned experiment.

## Rules

- The template's toy experiment stays until the first real experiment replaces it — the smoke test must always pass.
- Never start domain experiments in the same session-step as scaffolding; spawn cleanly, then `/experiment`.
