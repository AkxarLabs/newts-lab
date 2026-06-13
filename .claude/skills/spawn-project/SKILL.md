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
3. **If `<projects_root>/<slug>` already exists, STOP before copying.** If it has any
   commits or a non-empty `runs/`, never overwrite — report the collision to the PI (a
   reused slug; pick a distinct one). If it is an incomplete prior spawn (no commits,
   `check_project.py` failing), either resume filling it in place or delete it with a
   note, then continue. Otherwise copy `templates/project/` → `<projects_root>/<slug>`. Substitute `{{slug}}`,
   `{{title}}`, `{{date}}`, `{{hub_path}}` in README.md, pyproject.toml, PLAN.md,
   EXPERIMENT_LOG.md, **control.yaml**, **CLAUDE.md**, **AGENTS.md** — the last two
   make the project directory autonomously operable: a session started inside it gets
   the full project protocol. (Keep the `project_pkg` package name unless the project
   will be published standalone — renaming is optional polish, not required.)
   If `lab/SYSTEM.md` exists in the hub, copy it to the project root as `SYSTEM.md`
   (the PI may tailor the copy per-project); otherwise mention to the PI that one can
   be created from `templates/SYSTEM.md` any time.
4. **Configure `control.yaml`** (this IS the project's end-to-end run config, created at
   setup): fill budgets/seeds/loop values from the approved proposal. If a Gate 2 envelope
   was authorized, record it in `gate2_envelope` with `pi_signed: true` — control.yaml is
   the canonical machine-readable envelope. Provenance: if the PI approved the envelope
   directly at Gate 1, leave `signed_via: null`; if the envelope is derived from a
   PI-signed `/autopilot` campaign brief (unattended spawn), set `signed_via:
   lab/campaigns/<file>` — the campaign signature carries the PI's authority within its
   delegation bounds (see `/autopilot`).
5. Fill `PLAN.md` from the approved proposal: frozen eval protocol, kill criteria, the
   staged experiment table, the ablation plan (budgets live in control.yaml — reference,
   don't duplicate).
6. Add the project's real dependencies to `pyproject.toml` (minimal set; pin via lock).
7. Initialize: `git init`, then `uv sync`, then run the smoke pipeline:
   - `uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml`
   - `uv run pytest tests/`
   - `uv run --with pyyaml python scripts/check_project.py` (readiness lint — exit 0)
   Commit only once all pass ("scaffold: spawn from AutoScientist template, smoke green"). Commit the `uv.lock`.
   If `uv sync` / smoke / tests / check_project fail: debug up to `experiment.max_debug_depth`
   attempts; still red → leave the directory **uncommitted**, set the registry next action
   back to "/spawn-project" with the failure noted, and report to the PI — never commit a
   red scaffold.
8. Update hub state: IDEA.md → `active`, registry row's Project column = the relative
   path (e.g. `../AutoScientist-Projects/<slug>`), next action = "/experiment exp-002".
   Append a lab notebook entry.
9. Report to the user: project path, smoke/test status, control.yaml summary, first
   planned experiment.

## Rules

- The template's toy experiment stays until the first real experiment replaces it — the smoke test must always pass.
- Never start domain experiments in the same session-step as scaffolding; spawn cleanly, then `/experiment`.
