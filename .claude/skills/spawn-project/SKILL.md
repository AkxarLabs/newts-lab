---
name: spawn-project
description: Instantiate a project repo at <projects_root>/<slug> (outside the hub) from templates/project/ for an approved proposal. Argument; the idea slug.
---

# Spawn Project

Input: idea in state `proposal` with PI Gate 1 approval recorded. Output: a runnable,
committed project repo at `<projects_root>/<slug>` — **outside the hub**, independently cloneable.

## Procedure

1. Verify Gate 1 approval — mechanically: `uv run --with pyyaml python tools/guard.py spawn <slug>` (checks the Gate-1 marker in `studies/<slug>/proposal.md`, the registry state, and that no existing project would be overwritten). A nonzero exit stops the spawn and routes back to `/propose`.
2. Resolve `lab.projects_root` from `lab/config.yaml` (default `../kartr-lab-projects`,
   relative to the hub). If the container directory doesn't exist, create it with a
   one-paragraph README ("Projects spawned by the Kartr Lab at <hub path>; each
   is an independent git repo — index in the hub's lab/REGISTRY.md").
3. **If `<projects_root>/<slug>` already exists, STOP before copying.** If it has any
   commits or a non-empty `runs/`, never overwrite — report the collision to the PI (a
   reused slug; pick a distinct one). If it is an incomplete prior spawn (no commits,
   `check_project.py` failing), either resume filling it in place or delete it with a
   note, then continue. Otherwise copy `templates/project/` → `<projects_root>/<slug>`. Substitute `{{slug}}`,
   `{{title}}`, `{{date}}`, `{{hub_path}}` in README.md, pyproject.toml, PLAN.md,
   EXPERIMENT_LOG.md, **NOTES.md**, **control.yaml**, **CLAUDE.md**, **AGENTS.md** — the
   last two make a session started inside the project directory fully operable; `NOTES.md`
   is its distilled-memory file (ships empty — `(none yet)` — and accretes lessons as the
   project runs). The copied `.claude/skills/` (the vendored
   `grilling`/`domain-modeling`/`grill-with-docs` engineering skills) need **no**
   substitution — domain-agnostic plain Markdown; they ship in every project so grilling
   works standalone for any agent (Claude or Codex, which finds them via `AGENTS.md`).
   Keep the `project_pkg` package name unless the project will be published standalone
   (renaming is optional polish).
   If `lab/SYSTEM.md` exists in the hub, copy it to the project root as `SYSTEM.md`
   (the PI may tailor it per-project); otherwise mention one can be created from
   `templates/SYSTEM.md` any time.
3b. **Select & apply the project TYPE** (the methodology axis — bound here, at spawn). Read the
   approved proposal (`studies/<slug>/proposal.md`, `decisions.md`, the frozen eval protocol) and
   the cards in `{{hub_path}}/templates/project-types/*/TYPE.md`. Pick the best-fit type —
   `ml` (default) | `empirical` | `simulation` | `theory` | `target-driven` — plus, for a non-ML
   field, an optional **domain profile** from `templates/domain-profiles/` (or draft one). If none
   fits, propose a NEW type (a `TYPE.md` card) — a PI-owned act. **Present the chosen {type, domain}
   to the PI and get confirmation** before proceeding (it shapes the whole project — Gate-1-adjacent;
   under a signed `/autopilot` campaign, decide within its delegation bounds). Then apply it:
   - Set `control.yaml` `project_type:` and `runner:` — `python-import` for `ml`/`target-driven`/
     Python work; `shell-command` + `runner_command:` for an R/Stata/Julia/proof-checker tool (that
     path writes the metrics dict to `$RUN_DIR/result.json` — same artifact contract, so hard rule 1
     holds across languages).
   - Copy the chosen `TYPE.md` (and the domain profile as `DOMAIN.md`, if any) into the project root
     so an in-project session knows its own rules.
   - `target-driven`: also apply the `templates/compete/` overlay (what `/compete` does) — or just
     run `/compete` for that type instead of `/spawn-project`.
   - Non-`ml` type: write the **smoke** in the type's shape (a tiny regression / one sim draw / a
     proof-checker no-op) so step 7's smoke + `check_project.py` pass. `ml` keeps the base toy.
4. **Configure `control.yaml`** (the project's end-to-end run config): fill
   budgets/seeds/loop values from the approved proposal. If a Gate 2 envelope was
   authorized, record it in `gate2_envelope` with `pi_signed: true` — control.yaml is the
   canonical machine-readable envelope. Provenance: PI approved directly at Gate 1 → leave
   `signed_via: null`; derived from a PI-signed `/autopilot` campaign brief (unattended
   spawn) → set `signed_via: lab/campaigns/<file>` (the campaign signature carries the PI's
   authority within its delegation bounds — see `/autopilot`).
5. Fill `PLAN.md` from the approved proposal: frozen eval protocol (including the
   **headline hypothesis** — the central claim, the explore-mode autonomy boundary), kill
   criteria, the staged experiment table, the ablation plan (budgets live in control.yaml —
   reference, don't duplicate). Leave `control.yaml` `loop.mode: execute` unless an
   `/autopilot` campaign authorized `explore` for spawned projects (then set it + the caps).
6. Add the project's real dependencies to `pyproject.toml` (minimal set; pin via lock).
7. Initialize: `git init`, then `uv sync`, then run the smoke pipeline:
   - `uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml`
   - `uv run pytest tests/`
   - `uv run --with pyyaml python scripts/check_project.py` (readiness lint — exit 0)
   Commit (with `uv.lock`) only once all pass ("scaffold: spawn from Kartr Lab template, smoke green").
   If any of `uv sync` / smoke / tests / check_project fail: debug up to `experiment.max_debug_depth`
   attempts; still red → leave the directory **uncommitted**, set the registry next action
   back to "/spawn-project" with the failure noted, and report to the PI — never commit a
   red scaffold.
8. Update hub state: IDEA.md → `active`, registry row's Project column = the relative
   path (e.g. `../kartr-lab-projects/<slug>`), next action = "/experiment exp-002".
   Append a lab notebook entry.
9. Report to the user: project path, smoke/test status, control.yaml summary, first
   planned experiment.

## Rules

- The template's toy experiment stays until the first real experiment replaces it — the smoke test must always pass.
- Never start domain experiments in the same session-step as scaffolding; spawn cleanly, then `/experiment`.
