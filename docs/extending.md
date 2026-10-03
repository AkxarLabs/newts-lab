# Extending the lab

Every moving part is a small, named registry. Extending the lab means adding an entry to one of them,
never editing the engine around it. The table below is the map; each section says what "adding one"
takes.

| To add or change | Where it lives | Checked by |
|---|---|---|
| How a stage is done | the Workflow page → `lab/workflow/`, `studies/<slug>/workflow/` | [Customising](customising.md) |
| A procedure or a stage | `workflow/stages.yaml` + `.claude/skills/<name>/` | `tools/workflow.py check` (also in `check_lab`) |
| A subagent role | `agent-roles/<role>.yaml` + `.md` | `tools/role_sync.py check` |
| A kind of project | a folder `templates/project-types/<type>/` with its `TYPE.md` | [Project types](project-types.md) |
| How training runs on a machine | `lab/config.yaml` → `compute.scheduler` (+ `lab/SYSTEM.md`) | [Machines & compute](compute.md) |
| An agent CLI (backend) | one module in `tools/executor/backends/` | `tests/test_live_backends.py` |
| A machine | the dashboard → Labs & machines | — |

## A procedure

1. Write `.claude/skills/<name>/SKILL.md`: its **contract**, meaning inputs, outputs, guard calls,
   ledgers, stop points and the run footer.
   - If its method should be replaceable, also write `METHOD.md` (how the work is done, with no tool
     calls or gates), and make step 0 load the brief:
     `uv run --with pyyaml python tools/workflow.py brief <name> --study <slug>`.
2. Add it under `procedures:` in `workflow/stages.yaml`:
   - `kind`, `level` (hub or project), `mode` (headless or interactive), `args`;
   - `launchable` (may the dashboard start it?) and `replaceable`;
   - `title`, `does`, `stops`, `outputs`.
3. List it in a stage's `procedures` (so it shows on the Workflow page and in "Work on it…"), and in
   `offer_for_state` / `next_for_state` if it should be offered or be the default next step. Set
   `dispatchable: false` if a campaign pass must not start it as its own run.
4. Run `uv run --with pyyaml python tools/workflow.py render-docs`, then `tools/workflow.py check`.
5. If it has a `METHOD.md`, add its contract's system lines to `tests/fixtures/skill_system_tokens.json`
   (the test that proves replacing a method can't drop a rule).
6. Describe it for people: a row in the README's skill table and a section in `docs/skills.md`.

The executor's launch list, the dashboard's labels, the docs table and the skill list in `AGENTS.md`
all follow from the manifest. `finalize` can never be made launchable: Gate 3 is its only door.

## A stage

A stage is a group of registry states with procedures, a room in the dashboard's world, and optionally
a gate. The lifecycle's order and its back edges are in `workflow/stages.yaml` too, and the guard derives
legal transitions from them. The stage set is validated as the shipped one for now. Opening it up (new
stages, reordering) is a change to the manifest plus the world's room art, not to the engine. Keep the
three gates fixed: `check` refuses a manifest without exactly Gates 1, 2 and 3.

## A subagent role

Add `agent-roles/<role>.yaml` (description, `tools_claude`, model tier, codex settings) and
`agent-roles/<role>.md` (its instructions). Then run
`uv run --with pyyaml python tools/role_sync.py render`. The role is rendered for Claude Code
(`.claude/agents/`), Codex (`.codex/agents/`) and opencode (`.opencode/agents/`). List it under `roles:`
in the manifest so the PI can add instructions to it.

## A scheduler

A site scheduler (PBS, LSF, a wrapper) needs no code. Describe it with command templates in
`compute.scheduler.custom` (`submit`, `state`, `cancel`, `header`, `setup`), as
[Machines & compute](compute.md) shows. Code is only needed for a scheduler with a genuinely new model:
add an adapter class next to `Slurm` and `Custom` in `templates/project/scripts/_scheduler.py` and
register it in `ADAPTERS`; to set it from the dashboard too, give it a section in Settings → System
(`_clean_scheduler` in `dashboard/system.py`, the form in `static/ui/settings.js`).

## A kind of project

Add a folder `templates/project-types/<type>/` with its `TYPE.md` (what an experiment is, its runner,
its staged scale, its selection discipline), as [Project types](project-types.md) describes.
`/spawn-project` offers every folder there. A type with no literal held-out test split says so in its
`TYPE.md` with `<!-- newts: split=analogue -->`, and the eval-discipline audit then reports that check as
manual.

## A backend (another agent CLI)

One module in `tools/executor/backends/` (`claude.py`, `codex.py` and `opencode.py` are the examples)
with a `Backend` subclass, plus its line in `REGISTRY` (`backends/__init__.py`). The class says
everything about its CLI, and nothing outside the package branches on a backend's name:

- `prepare(a)`: its env and per-run sidecars (how the tracer and the signature guard are installed:
  hooks, flags, a plugin);
- `command(a)`: the argv for an attempt, live or one-shot;
- `session(a)`: the live session, a `live.Session` subclass speaking the CLI's own protocol and
  translating it to the one-shot line shape (omit it for a one-shot-only backend);
- `parse(obj)`: one stream line → the normalized events;
- `auth(out)` with `auth_args`, and `sign_in_hint`, `ask_tool`, `env_auth`, `forbid` (flags
  `extra_args` may not set).

The supervisor, the scheduler, campaigns and the dashboard stay as they are. `tests/test_live_backends.py`
and `tests/test_backend_tracing.py` show the contract each backend meets, with a fake CLI per backend.
