---
name: configure
description: View and edit the lab's 3-layer configuration — lab defaults, a project's control.yaml, or experiment values — with provenance. Usage; /configure [project-slug] [set key=value].
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

1. Determine the right layer for the key:
   - lab-wide keys (`lab.*`, `critique.*`, and defaults under `experiment.*`/`loop.*`) → `lab/config.yaml`
   - project keys (`budgets.*`, `seeds.*`, `parallelism.*`, `loop.*`, `gate2_envelope.*`, `eval_frozen`) → the project's `control.yaml`
   - per-experiment values → tell the user to edit/add the experiment yaml instead (experiment configs are immutable once run — a change means a NEW config file).
2. **PI-owned keys** — `budgets.*` (after Gate 1), `gate2_envelope.*`, `eval_frozen`, and anything under `critique.*`: if the request did not come explicitly from the PI in this session, STOP and ask for confirmation before editing. `eval_frozen: false` and `gate2_envelope.pi_signed: true` may ONLY ever be set by the PI.
3. Apply the edit preserving comments where possible; re-run the view to confirm; note
   the change in the lab notebook (config changes are decisions — hard rule 11).

## Retrofit

For a project that predates control.yaml: copy `templates/project/control.yaml`,
substitute `{{slug}}`, fill values from the project's proposal/PLAN.md, commit it in
the project repo, then proceed.
