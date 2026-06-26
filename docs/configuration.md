# Configuration

Everything tunable lives in **three layers**, resolved highest-precedence first:

```
experiment yaml  >  project control.yaml  >  hub lab/config.yaml
(one experiment)    (one project, e2e)       (lab-wide defaults)
```

View the effective merged configuration — with the layer that set each key — at any time:

```bash
uv run --with pyyaml python tools/show_config.py                          # lab layer
uv run --with pyyaml python tools/show_config.py ../newts-lab-projects/my-proj
uv run --with pyyaml python tools/show_config.py ../newts-lab-projects/my-proj exp-004.yaml
```

…or just run `/configure` and let the agent present it. Edits go through `/configure [slug] set key=value` (or by hand — they're YAML files).

## Profiles & budget tiers

A **profile** is a named, *partial* bundle of `lab/config.yaml` overrides (built-ins in `lab/profiles/`). Applying one **stamps its values into `lab/config.yaml` in place — comments preserved** (no new resolution layer; the 3-layer model above is untouched). Two composable axes:

- **Budget tiers** — `low` · `medium` (the defaults) · `high` — scale *exploration*: how many agents/subagents, ideas, reviewer lenses, drafts, parallel subagents, and how strong the per-role models are. Rough token cost ≈ 0.3× / 1× / 3×.
- **Engine presets** — `claude-opus` · `claude-balanced` · `claude-fast` · `codex` · `opencode` · `mixed` — set *which* headless backend (`agents.programmatic.backend`) + its model. `mixed` puts the strong model on verification (overseer/reviewer) and a cheap one on running.

```bash
uv run --with pyyaml python tools/profiles.py list
uv run --with pyyaml python tools/profiles.py diff high      # what would change
uv run --with pyyaml python tools/profiles.py apply high      # stamp into lab/config.yaml (+ sync agent models)
uv run --with pyyaml python tools/profiles.py save my-preset  # snapshot current settings as a named profile
```
…or `/configure profile <list|show|diff|apply|save> <name>`.

| | `low` | `medium` (default) | `high` |
|---|---|---|---|
| `ideation.candidates` / `critics_per_idea` | 4 / 1 | 8 / 2 | 16 / 3 |
| `scoping.advocate_subagents` | false | true | true |
| `critique.ensemble_own_draft` | 3 | 5 | 7 |
| `experiment.num_drafts` / `max_parallel_subagents` | 2 / 1 | 3 / 3 | 5 / 6 |
| `agents.{reviewer,runner,overseer}_model` | sonnet / haiku / sonnet | inherit | opus |
| `agents.programmatic.max_concurrent` | 1 | 3 | 6 |
| **`experiment.multi_seed_n` (floor)** | **3** | **3** | **5** |
| **`oversight.level` (floor)** | **standard** | **standard** | **strict** |

**The one rule: budget scales exploration, never rigor.** A profile may **never** lower `experiment.multi_seed_n` below 3, set `oversight.level: off`, or touch `eval_frozen` / `gate2_envelope` — `tools/profiles.py apply` (and `validate`) **refuses** any that does. A `low` run is *cheaper, not sloppier* — it explores less but is held to the same gates, seeds, and verification. Make your own: apply the closest tier, tweak with `/configure set …`, then `tools/profiles.py save <name>`. See `lab/profiles/README.md`.

## Layer 1 — `lab/config.yaml` (lab-wide defaults)

| Key | Default | Owner | Effect |
|---|---|---|---|
| `lab.projects_root` | `../newts-lab-projects` | PI | where `/spawn-project` creates project repos (relative to hub) |
| `lab.stale_days` | 14 | PI | registry rows untouched longer than this get flagged by `check_lab.py` |
| `critique.ensemble_external` | 3 | PI | reviewer lenses for external-paper triage |
| `critique.ensemble_own_draft` | 5 | PI | reviewer lenses for our own drafts |
| `critique.score_anchor_human_mean` | 5.4 | PI | calibration anchor `/critique-paper` substitutes into every reviewer prompt |
| `critique.accept_bar` | 7 | PI | median Overall at/above this (+ zero unrefuted fatal flaws) = accept |
| `critique.max_review_cycles` | 3 | PI | revision cycles before escalating to the PI |
| `critique.claim_rel_tol` | 0.001 | agent-readable | relative tolerance `tools/audit_claims.py` uses to match a paper number to its run artifact (looser of this · printed precision) |
| `experiment.max_debug_depth` | 3 | agent-readable | consecutive debug attempts before record-and-move-on |
| `experiment.num_drafts` | 3 | agent-readable | distinct solution lines `/improve` maintains |
| `experiment.max_parallel_subagents` | 3 | agent-readable | concurrent worktree subagents (project may override) |
| `experiment.multi_seed_n` | 3 | agent-readable | seeds required before a number is paper-grade (project may override) |
| `loop.no_progress_backoff_cycles` | 3 | agent-readable | no-progress cycles before a loop stops (project may override) |
| `loop.monitor_poll_seconds` | 300 | agent-readable | zero-token polling cadence (project may override) |
| `loop.mode` | `execute` | PI (per-loop via LOOP_BRIEF) | default loop mode: `execute` (run plan, then stop) or `explore` (autonomous in-project re-planning — frontier expansion + reopening non-headline decisions). The `LOOP_BRIEF.md` `Mode:` overrides per-loop. See [autonomy](autonomy.md). |
| `loop.explore_max_expansion_rounds` | 0 | PI | explore-mode only: results-grounded `expand` rounds allowed after the plan is exhausted (0 = no frontier expansion; decision revisits still fire, as those are gated by `loop.mode`) |
| `loop.explore_max_new_lines_per_round` | 3 | PI | explore-mode only: max new PLAN.md lines per `expand` round (each needs a pre-written criterion) |
| `compute.max_concurrent_runs` | 1 | PI | training campaigns allowed at once **across all projects** (slot ledger: `tools/run_slots.py`) |
| `compute.stale_slot_minutes` | 360 | PI | slots older than this are presumed crashed and reclaimed |
| `dashboard.port` | 8787 | PI | default port for the optional [Vivarium dashboard](dashboard.md) (`dashboard/serve.py`) |
| `agents.reviewer_model` | inherit | PI | model for `fresh-context-reviewer` (applied via the `model:` frontmatter of `.claude/agents/fresh-context-reviewer.md`; `inherit` \| `sonnet` \| `opus` \| `haiku`) |
| `agents.runner_model` | inherit | PI | model for `experiment-runner` (→ its agent-file frontmatter) |
| `agents.critic_model` | inherit | PI | ideation critics / scoping advocates — **inline subagents with no agent file, so this value cannot be applied** (they run at the session model) |
| `agents.overseer_model` | inherit | PI | model for `overseer` (→ its agent-file frontmatter) |
| `oversight.level` | standard | PI | `off` · `standard` (author-response + analysis checks, autopilot Gate-1 self-approval, phantom-experiment sweep, accept-unlocking refutations) · `strict` (+ grading meta-review fatal flaws, loop progress claims) |
| `ideation.candidates` | 8 | agent-readable | initial candidates `/ideate` generates |
| `ideation.reflection_rounds` | 2 | agent-readable | reflect→evolve cycles per surviving idea |
| `ideation.critics_per_idea` | 2 | agent-readable | parallel critic subagents per idea per reflect pass |
| `ideation.enable_combination` | true | agent-readable | propose crossovers of complementary survivors |
| `ideation.in_project` | true | PI | enable `/ideate --in-project <slug>` (divergent in-project method-ideation, scoped to the frozen set); `false` = capability OFF (the headline-reopen route falls back to a successor hub `/ideate`) |
| `ideation.in_project_candidates` | 4 | agent-readable | approach candidates an in-project ideation round generates |
| `ideation.in_project_rounds` | 1 | agent-readable | max in-project ideation rounds before stopping |
| `ideation.in_project_approval` | `pi` | PI | **campaign-only** knob — only modulates approval *under a signed `/autopilot` campaign*; **manual `--in-project` runs are always PI-gated**. `pi` = surviving approaches queue at `/propose` for Gate 1; `campaign_auto` = under a campaign, auto-approve within delegation bounds + overseer `support` |
| `discuss.max_research_minutes` | 15 | agent-readable | cap on live web/arXiv/S2 research *during* a `/discuss` session (discussion fuel, not the lit review); `0` = Q&A only |
| `scoping.options_per_decision` | 3 | agent-readable | alternatives generated per design-decision branch in `/scope` |
| `scoping.advocate_subagents` | true | agent-readable | one parallel advocate per option argues its case |
| `scoping.max_open_questions` | 3 | agent-readable | decisions allowed to remain OPEN (pilot-settled) at `/propose` time |
| `writing.venue` | `neurips` | PI | paper format `/write-paper` builds from. `neurips` \| `icml` \| `iclr` \| `aclarr` \| `aaai` \| `generic`; picks `templates/paper/venues/<venue>/main.tex` + fetches that venue's style file (URLs/limits in that dir's `README.md`). Project `control.yaml` may override per-project |
| `writing.max_reflection_rounds` | 3 | agent-readable | verifier-gated revision rounds in `/write-paper` (gains plateau ~3) |
| `writing.citation_match_threshold` | 0.85 | agent-readable | title-similarity gate for `tools/s2.py verify` |
| `writing.cite_grounding_threshold` | 0.7 | agent-readable | title-word overlap for `tools/s2.py citecheck` to call a `\cite` "grounded" in lit-review.md |
| `writing.page_limit` | 9 | PI | target main-text pages; over-length trimmed gradually. Set to the venue limit (neurips/iclr 9 · icml/aclarr 8 · aaai 7) |

### Headless launch backends — `agents.programmatic.*` (optional, PI-owned, OFF by default)

The "one headless session per project" launcher (`tools/agent_runner.py`; see [Autonomy](autonomy.md)). Stays off until the PI enables it. The per-backend comments in `lab/config.yaml` are the full reference — this is the map.

| Key | Default | Owner | Effect |
|---|---|---|---|
| `agents.programmatic.enabled` | false | PI | master switch — `true` lets the orchestrator launch headless top-level agents into projects (also required for `autopilot.max_concurrent_projects > 1`) |
| `agents.programmatic.backend` | claude | PI | which CLI: `claude` (`claude -p`) · `codex` (`codex exec`) · `opencode` (`opencode run`). codex/opencode are **optional installs**, needed only when selected |
| `agents.programmatic.model` | inherit | PI | global model override across backends; `inherit` = each backend uses its own `backends.<x>.model` default |
| `agents.programmatic.permission_mode` | auto | PI | claude `--permission-mode` (`auto` = broad in-repo approval that still blocks dangerous ops, paired with the project `.claude/settings.json` allowlist; `dontAsk` stricter, `bypassPermissions` wider). A blocked op is denied → the agent escalates via the bus |
| `agents.programmatic.max_minutes` · `max_concurrent` · `max_depth` · `max_transcript_mb` | 240 · 3 · 1 · 200 | PI | per-agent wall-clock cap (watchdog) · per-project concurrency · launch-recursion cap (1 = no nesting) · stored-transcript cap (MB) |
| `agents.programmatic.backends.<backend>.*` | — | PI | per-backend model/effort + safety knobs: claude `{model, effort, permission_mode}` · codex `{model, reasoning_effort, sandbox, approval, network_access}` · opencode `{model, variant, permission, agent, skip_permissions}` · all `{extra_args}`. The safety flags are *refused* in `extra_args` and must go through these dedicated keys |
| `autopilot.max_concurrent_projects` | 1 | PI | how many projects an `/autopilot` campaign drives at once. `1` = one project end-to-end (sequential). `>1` turns autopilot into a coordinator that launches one headless session per project — and **requires** `agents.programmatic.enabled: true` |

## Layer 2 — `<project>/control.yaml` (per-project, end-to-end)

**Created automatically at spawn** — the first set-up step generates this config from the approved proposal — and editable for the project's whole life. This is where you control a project's runs end to end:

| Key | Owner | Effect |
|---|---|---|
| `package` | agent | the importable package under `src/` that `scripts/run.py` + `sweep.py` drive (config/experiment/seeding/tracking). Spawned projects keep `project_pkg`; an **adopted** repo sets this to its own package name instead of renaming it (autodetected when `src/` has exactly one package; this pins it) |
| `hub_path` | set at spawn | absolute path back to the hub repo (lets the project resolve the hub's lifecycle skills + write-back targets). Substituted from `{{hub_path}}` when the template is instantiated |
| `project_type` | PI-confirmed at spawn | the methodology axis: `ml` (default) · `empirical` · `simulation` · `theory` · `target-driven`. Selects the type card (`templates/project-types/<type>/TYPE.md`) that defines what an "experiment" is — see [Project types](project-types.md) |
| `runner` / `runner_command` | agent | how `scripts/run.py` executes a run: `runner: python-import` (default, drives `package`) **or** `runner: shell-command` + `runner_command:` for a non-Python engine (R/Stata/Julia/proof-checker) that writes `result.json` to `$RUN_DIR`. Keeps hard-rule-1 traceability for any language |
| `budgets.smoke_max_minutes` / `pilot_…` / `full_…` | **PI after Gate 1** | per-stage wall-clock caps, **enforced by the run watchdog** (a run that exceeds its stage budget is killed and recorded as `timeout`) |
| `budgets.total_note` | PI | free-text total compute cap from the proposal |
| `seeds.list` | agent | default seeds for `scripts/sweep.py` |
| `seeds.multi_seed_n` | agent | project override of the paper-grade seed count |
| `parallelism.max_parallel_subagents` | agent | project override for `/improve` |
| `parallelism.sweep_parallel` | agent | default `--parallel` for sweeps |
| `loop.no_progress_backoff_cycles` / `monitor_poll_seconds` | agent | project overrides for `/research-loop` |
| `loop.mode` / `loop.explore_*` | PI | loop mode (`execute`/`explore`) + explore caps; the LOOP_BRIEF `Mode:` overrides per-loop. `explore_*` widen the agent's authority, so PI-owned. |
| `monitoring.log_interval_seconds` | agent | expected seconds between `ctx.log()` calls — passed to `status.py --log-interval` so a sparse-logging run isn't flagged stalled |
| `figures.theme` | agent | figure vibe: `clean` (Okabe-Ito default) · `warm` (brown/clay editorial) · `bold` (Tol bright, talks) · `mono` (grayscale + linestyle cycling, B/W-safe) |
| `gate2_envelope.full_runs` / `per_run_max_minutes` / `total_max_minutes` / `expires` | **PI only** | the pre-authorized FULL-run envelope — the canonical machine-readable record Gate 2 checks (`expires` checked before each FULL launch) |
| `gate2_envelope.pi_signed` | **PI authority** | set directly by the PI, **or** transitively under a PI-signed `/autopilot` campaign brief whose bounds cover it |
| `gate2_envelope.signed_via` | provenance | `null` = signed directly by the PI; else the path of the campaign brief carrying the signature |
| `eval_frozen` | **PI only** | the eval protocol is frozen; the agent may *never* set this false |

**`target.*` — present only for `/compete` (target-driven) projects** (appended from `templates/compete/control.target.yaml`; absent for paper projects). See [Target-driven projects](compete.md).

| Key | Owner | Effect |
|---|---|---|
| `target.active` | agent | marks this a target-driven project (set by `/compete`) |
| `target.name` / `url` | agent | the task/target label + page (free-text, **not** tool-specific) |
| `target.metric` / `direction` | **PI (frozen)** | the scored metric + `maximize`/`minimize` — part of the frozen eval |
| `target.done` | PI | the done-condition (e.g. `public >= 0.90`) — a loop stop-condition |
| `target.deadline` | PI | hard deadline (YYYY-MM-DD), if any — a loop stop-condition + checked by the scripts |
| `target.output.*` | **PI (frozen)** | the output-artifact contract (`path`, `format`, `id_column`, `target_columns`, `expected_rows`) validated by `scripts/check_output.py`; omit for a local-metric-only target |
| `target.scoring.read_back` | PI | `manual` (record an observed score) \| `command` (run `score_command`) |
| `target.scoring.external` | **PI** | `true` if obtaining a score **sends data outside the lab** (then `score_envelope` authorizes it) |
| `target.scoring.score_command` | agent | the task's own score command for `read_back: command` — **any tool** (CLI/HTTP/grader); placeholders `{file}{run_id}{note}{name}`. No host assumed |
| `target.score_envelope.*` | **PI only** | the outward-action envelope for external reads (`per_day_max`, `total_max`, `pi_signed`, `signed_via`) — a Gate-2 analogue enforced by `scripts/report_score.py` |

!!! warning "PI-owned keys"
    `/configure` refuses to change PI-owned keys unless the request comes explicitly from you in-session. `gate2_envelope.pi_signed: true` and `eval_frozen: false` carry PI authority by hard rule, not convention — set directly when you ask in-session, or (for `pi_signed`) transitively under a PI-signed `/autopilot` campaign brief, which records its path in `signed_via`. The agent never sets them on its own initiative.

!!! note "Not config, but binding: `SYSTEM.md`"
    Alongside `control.yaml`, a project may carry a PI-written `SYSTEM.md` — a prose description of the machine it runs on (hardware reality, data locations, scheduling rules, forbidden actions). It's not merged into any config layer, but agents treat its constraints as binding like control.yaml and never edit it. Lab default at `lab/SYSTEM.md` (template: `templates/SYSTEM.md`, offered by `/setup-lab`), copied into each project at spawn. See [Autonomy & modes](autonomy.md#autonomy-inside-the-project-directory).

## Layer 3 — `configs/experiments/*.yaml` (one per experiment)

The unit of experimentation. **Immutable once run** — a variant is a *new* file, which is what keeps every past experiment re-runnable forever. Anything set here (including `budget.max_minutes`) beats the layers below. `configs/base.yaml` holds the project's shared *domain* defaults (model, data, eval definition) between control.yaml and the experiment files.

### Stage-budget mapping

If neither the experiment yaml nor `base.yaml` sets `budget.max_minutes`, the loader maps it from `control.yaml → budgets.<stage>_max_minutes` for the run's stage — so per-stage caps apply automatically without repeating them in every experiment file. The fully resolved config is dumped into every run's artifact dir as `config.resolved.yaml`; per-key provenance (which layer set each key) is available via `tools/show_config.py`.

### Load-time validation & environment capture

Two lightweight reproducibility guards, deliberately in place of a heavyweight config framework (Hydra/OmegaConf — which would also fight `run.py`'s in-process budget watchdog and `RunContext`'s own run-dir ownership):

- **Validation at load** (`config.py → _validate`): after merge, the loader fails fast on the universal mistakes — a `stage` that isn't `SMOKE|PILOT|FULL`, a non-int `seed`, a non-numeric `budget.max_minutes` — instead of KeyError-ing deep inside `experiment.run`. `_validate` is the documented place to add **this project's** required-key/range checks (it's a few readable lines, not a schema DSL).
- **Environment provenance** (`tracking.py → meta.json.env`): every run records the python version, platform, and (when importable) torch/CUDA + GPU name, alongside the git SHA, dirty-tree `code.patch`, and seed. `uv.lock` pins the dependency closure; this pins the *runtime* facts that matter for replaying GPU-heavy work.

## How configs flow through a project's life

1. **Gate 1**: PI approves budgets (+ optional envelope) in the proposal.
2. **Spawn**: `control.yaml` is generated from the template and filled from the proposal; envelope recorded with `pi_signed: true` if granted (`signed_via` = the campaign brief, when an `/autopilot` campaign authorizes it).
3. **Any time**: `/configure` (or hand-edit) adjusts agent-owned values; PI-owned values need you.
4. **Every run**: experiment yaml → base → control resolve into one artifact-dumped config; the watchdog enforces the resulting budget.
5. **Loops**: `/research-loop` reads `gate2_envelope` + `loop.*` from control.yaml; the LOOP_BRIEF carries your signature and points here for numbers.
