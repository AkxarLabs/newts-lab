---
name: configure
description: View and edit the lab's 3-layer configuration — lab defaults, a project's control.yaml, or experiment values — with provenance; and apply/save budget-tier & engine config profiles. Usage; /configure [project-slug] [set key=value] (slug first), or /configure profile <list|show|diff|apply|save> <name>.
---

# Configure

The configuration has 3 layers, resolved **experiment yaml > project `control.yaml` >
hub `lab/config.yaml`**. Full key reference: `docs/configuration.md`.

## View (default)

- `/configure` — run `uv run --with pyyaml python tools/show_config.py` and present it.
- `/configure <slug>` — same with the project path (resolve via the registry row /
  `lab.projects_root`): shows control.yaml and the effective skill values with sources.
- `/configure <slug> <exp-NNN.yaml>` — adds the fully resolved run config (layer that
  set each key, including the stage-budget mapping).

## Edit — `set key=value`

1. Determine the right layer for the key (full ownership + layer table: `docs/configuration.md`):
   - lab-wide keys (any top-level section in `lab/config.yaml` — `lab.*`, `compute.*`, `agents.*`, `oversight.*`, `ideation.*`, `scoping.*`, `writing.*`, `critique.*`, and defaults under `experiment.*`/`loop.*`) → `lab/config.yaml`
   - project keys (`budgets.*`, `seeds.*`, `parallelism.*`, `loop.*`, `figures.*`, `gate2_envelope.*`, `eval_frozen`) → the project's `control.yaml`
   - per-experiment values → tell the user to edit/add the experiment yaml instead (experiment configs are immutable once run — a change means a NEW config file).
2. **PI-owned keys** — anything marked PI-owned in `lab/config.yaml`'s comments or `docs/configuration.md`'s Owner column: `lab.*`, `compute.*`, `agents.*`, `oversight.level`, `critique.*`, `writing.page_limit`, `budgets.*` (after Gate 1), `gate2_envelope.*`, `eval_frozen`, and `loop.mode` / `loop.explore_*` (they widen the agent's in-project autonomy). Note that the rest of `loop.*` (`no_progress_backoff_cycles`, `monitor_poll_seconds`) is agent-readable — only the mode/explore keys are PI-owned. If the request did not come explicitly from the PI in this session, STOP and ask for confirmation before editing. `eval_frozen: false` and `gate2_envelope.pi_signed: true` carry PI authority only: set them directly when the PI asks in-session, OR transitively under a PI-signed `/autopilot` campaign brief whose bounds cover the change — in the transitive case record `gate2_envelope.signed_via: <campaign-brief path>`. Never set either on the agent's own initiative.
3. Apply the edit preserving comments where possible; re-run the view to confirm; note
   the change in the lab notebook (config changes are decisions — hard rule 11).
4. **`agents.*` keys** also require updating the `model:` frontmatter of the mapped agent
   file (that is the only mechanism Claude Code honors): `reviewer_model →
   .claude/agents/fresh-context-reviewer.md`, `runner_model → experiment-runner.md`,
   `overseer_model → overseer.md`. `critic_model` maps to no file (inline subagents) — tell
   the PI it cannot take effect.

## Profiles & budget tiers — `profile <verb> <name>`

Named bundles of `lab/config.yaml` overrides (built-ins live in `lab/profiles/`; full reference:
`docs/configuration.md` → "Profiles & budget tiers"). **Budget tiers** (`low` / `medium` / `high`)
scale *exploration* — agent/subagent counts, parallelism, per-role model strength; **engine presets**
(`claude-opus` · `claude-balanced` · `claude-fast` · `codex` · `opencode` · `mixed`) set the headless
backend. They compose — apply a tier, then an engine preset.

- `/configure profile list` — `uv run --with pyyaml python tools/profiles.py list`.
- `/configure profile show|diff <name>` — the profile, or exactly what `apply` would change.
- `/configure profile apply <name>` — **always `diff` first and show it to the PI** (this rewrites
  `lab/config.yaml`); then `tools/profiles.py apply <name>`. The tool stamps each value **in place
  (comments preserved)**, **syncs the `.claude/agents/*.md` `model:` frontmatter** for any per-role
  model change (so you don't do step 4 above by hand), and **refuses** any profile that would lower an
  integrity floor (`multi_seed_n` < 3, `oversight: off`, touching `eval_frozen`/`gate2_envelope`) —
  budget scales exploration, never rigor. Note the change in the notebook (hard rule 11).
- `/configure profile save <name>` — snapshot the current budget/model settings as a new named
  profile in `lab/profiles/` (the "make your own" path: apply the closest tier, tweak with
  `set …`, then `save`).

A profile is **PI-owned** (it moves PI-owned keys like `oversight.level` and the model choices): only
apply/save on explicit PI request, or transitively under a signed `/autopilot` campaign brief.

## Retrofit

For a project that predates control.yaml: copy `templates/project/control.yaml`,
substitute `{{slug}}`, fill values from the project's proposal/PLAN.md, commit it in
the project repo, then proceed.
