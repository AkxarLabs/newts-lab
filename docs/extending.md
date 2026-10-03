# Extending the lab

Every moving part is a small, named registry. Extending the lab means adding an entry to one of them,
never editing the engine around it. The table below is the map; each section says what "adding one"
takes.

| To add or change | Where it lives | Checked by |
|---|---|---|
| How a stage is done | the Workflow page → `lab/workflow/`, `studies/<slug>/workflow/` | [Customising](customising.md) |
| A procedure | a folder `.claude/skills/<name>/` (its frontmatter defines it) | `tools/workflow.py check` (also in `check_lab`) |
| A stage, a state | `workflow/stages.yaml` | `tools/workflow.py check` |
| A subagent role | `agent-roles/<role>.yaml` + `.md` | `tools/role_sync.py check` |
| A rule (prose or mechanical) | `workflow/rules.yaml` (+ a check in `checks/`) | `tools/workflow.py check`, `tools/guard.py --list` |
| A kind of project | a folder `templates/project-types/<type>/` with its `TYPE.md` | [Project types](project-types.md) |
| Your own version of any template | the same path under `lab/templates/` (a proposal, the lenses, a project file, a type, a domain) | — |
| How training runs on a machine | `lab/config.yaml` → `compute.scheduler` (+ `lab/SYSTEM.md`) | [Machines & compute](compute.md) |
| An agent CLI (backend) | one module in `tools/executor/backends/` | `tests/test_live_backends.py` |
| A machine | the dashboard → Labs & machines | — |

## A procedure

A procedure is a skill folder, `.claude/skills/<name>/`. Adding one is adding the folder; nothing else is
required.

1. Write `.claude/skills/<name>/SKILL.md`: its **contract**, meaning inputs, outputs, guard calls,
   ledgers, stop points and the run footer.
   - Its frontmatter's `newts:` block defines the procedure for the lab. Without one, it is a launchable
     utility (headless, hub-level, free-text argument), titled by its name. The keys:

     ```yaml
     ---
     name: survey
     description: Survey the field for a topic.
     newts:
       kind: stage            # stage | driver | entry | utility
       level: hub             # hub | project — where the session runs
       mode: headless         # headless | interactive
       args: slug             # "" | slug | slug? | text? | campaign | "slug text?"
       launchable: true       # may the dashboard, a chain or a campaign start it?
       replaceable: true      # may the PI replace its method? (then write METHOD.md)
       dispatchable: true     # false: a campaign pass may not start it as its own run
       title: Survey the field
       does: One sentence for the launcher.
       stops: where it stops for the PI
       outputs: [what it must produce, whatever the method]
     ---
     ```
   - If its method should be replaceable, also write `METHOD.md` (how the work is done, with no tool
     calls or gates).
2. Put a `<!-- newts:contract … --><!-- /newts:contract -->` pair under its title and run
   `uv run --with pyyaml python tools/workflow.py render-docs`: it writes the procedure's head (load the
   brief, what it must produce) from the frontmatter. Then `tools/workflow.py check`.
3. To place it in the lifecycle, list it in a stage's `procedures` in `workflow/stages.yaml`, and in
   `offer_for_state` / `next_for_state` if it should be offered or be the default next step.
4. Describe it for people: a row in the README's skill table and a section in `docs/skills.md`.

The executor's launch list, the dashboard's labels and launcher, the docs table and the skill list in
`AGENTS.md` all follow from the skills. `finalize` can never be made launchable: Gate 3 is its only door.

## A stage

A stage is a group of registry states with procedures, a room in the dashboard's world, and optionally
a gate. The lifecycle's order and its back edges are in `workflow/stages.yaml` too, and the guard derives
legal transitions from them. The stage set is validated as the shipped one for now. Opening it up (new
stages, reordering) is a change to the manifest plus the world's room art, not to the engine. Keep the
three gates fixed: `check` refuses a manifest without exactly Gates 1, 2 and 3.

## A rule

The lab's rules are one PI-owned file, `workflow/rules.yaml`: the hard rules every session follows, the
subagent rules, and the project rules. `render-docs` writes them into `AGENTS.md`, the project template's
`AGENTS.md` and the experiment runner's role, so a rule added there reaches every agent. Append, because
the skills cite hard rules by number.

The same file holds what the code enforces from it: the config keys only the PI changes
(`pi_owned_config`), the rigor floors no profile may lower, the paths a headless run may never write
(`protected_paths`), and the paper audits a delegated Gate 3 must pass (`gate3_audits`).

To make a rule mechanical, give it a check in `checks/` (see `checks/README.md`): a guard check is
`NAME`, `add_args` and `run(args, guard)`, and `tools/guard.py <name>` finds it by itself. Then call it
from the skills that need it. The three gates and the lifecycle transitions are built into the guard and
can't be removed; every other check can be.

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

## Your own templates

Every template — `templates/idea/proposal.md`, `templates/review/critique-lenses.md`, `templates/loop/*`, a
file of `templates/project/`, a project type, a domain profile — can be made the lab's own: put your version
at the same path under `lab/templates/`. The code (`labfiles.template`) and the agents (AGENTS.md says so)
use it instead of the shipped one, and upgrading the lab never touches it. A spawned project gets the
shipped project template with your files on top.

## A kind of project

Add a folder `templates/project-types/<type>/` (or `lab/templates/project-types/<type>/`) with its `TYPE.md` (what an experiment is, its runner,
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
