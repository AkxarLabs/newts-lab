# Configuration

Everything tunable lives in **three layers**, resolved highest-precedence first:

```
experiment yaml  >  project control.yaml  >  hub lab/config.yaml
(one experiment)    (one project, e2e)       (lab-wide defaults)
```

View the effective merged configuration — with the layer that set each key — at any time:

```bash
uv run --with pyyaml python tools/show_config.py                          # lab layer
uv run --with pyyaml python tools/show_config.py ../AutoScientist-Projects/my-proj
uv run --with pyyaml python tools/show_config.py ../AutoScientist-Projects/my-proj exp-004.yaml
```

…or just run `/configure` and let the agent present it. Edits go through `/configure [slug] set key=value` (or by hand — they're YAML files).

## Layer 1 — `lab/config.yaml` (lab-wide defaults)

| Key | Default | Owner | Effect |
|---|---|---|---|
| `lab.projects_root` | `../AutoScientist-Projects` | PI | where `/spawn-project` creates project repos (relative to hub) |
| `lab.stale_days` | 14 | PI | registry rows untouched longer than this get flagged by `check_lab.py` |
| `critique.ensemble_external` | 3 | PI | reviewer lenses for external-paper triage |
| `critique.ensemble_own_draft` | 5 | PI | reviewer lenses for our own drafts |
| `critique.score_anchor_human_mean` | 5.4 | PI | calibration anchor `/critique-paper` substitutes into every reviewer prompt |
| `critique.accept_bar` | 7 | PI | median Overall at/above this (+ zero unrefuted fatal flaws) = accept |
| `critique.max_review_cycles` | 3 | PI | revision cycles before escalating to the PI |
| `experiment.max_debug_depth` | 3 | agent-readable | consecutive debug attempts before record-and-move-on |
| `experiment.num_drafts` | 3 | agent-readable | distinct solution lines `/improve` maintains |
| `experiment.max_parallel_subagents` | 3 | agent-readable | concurrent worktree subagents (project may override) |
| `experiment.multi_seed_n` | 3 | agent-readable | seeds required before a number is paper-grade (project may override) |
| `loop.no_progress_backoff_cycles` | 3 | agent-readable | no-progress cycles before a loop stops (project may override) |
| `loop.monitor_poll_seconds` | 300 | agent-readable | zero-token polling cadence (project may override) |
| `compute.max_concurrent_runs` | 1 | PI | training campaigns allowed at once **across all projects** (slot ledger: `tools/run_slots.py`) |
| `compute.stale_slot_minutes` | 360 | PI | slots older than this are presumed crashed and reclaimed |
| `agents.reviewer_model` | inherit | PI | model for `fresh-context-reviewer` (applied via the `model:` frontmatter of `.claude/agents/fresh-context-reviewer.md`; `inherit` \| `sonnet` \| `opus` \| `haiku`) |
| `agents.runner_model` | inherit | PI | model for `experiment-runner` (→ its agent-file frontmatter) |
| `agents.critic_model` | inherit | PI | ideation critics / scoping advocates — **inline subagents with no agent file, so this value cannot be applied** (they run at the session model) |
| `agents.overseer_model` | inherit | PI | model for `overseer` (→ its agent-file frontmatter) |
| `oversight.level` | standard | PI | `off` · `standard` (author-response + analysis checks, autopilot Gate-1 self-approval, phantom-experiment sweep, accept-unlocking refutations) · `strict` (+ grading meta-review fatal flaws, loop progress claims) |
| `ideation.candidates` | 8 | agent-readable | initial candidates `/ideate` generates |
| `ideation.reflection_rounds` | 2 | agent-readable | reflect→evolve cycles per surviving idea |
| `ideation.critics_per_idea` | 2 | agent-readable | parallel critic subagents per idea per reflect pass |
| `ideation.enable_combination` | true | agent-readable | propose crossovers of complementary survivors |
| `scoping.options_per_decision` | 3 | agent-readable | alternatives generated per design-decision branch in `/scope` |
| `scoping.advocate_subagents` | true | agent-readable | one parallel advocate per option argues its case |
| `scoping.max_open_questions` | 3 | agent-readable | decisions allowed to remain OPEN (pilot-settled) at `/propose` time |
| `writing.max_reflection_rounds` | 3 | agent-readable | verifier-gated revision rounds in `/write-paper` (gains plateau ~3) |
| `writing.citation_match_threshold` | 0.85 | agent-readable | title-similarity gate for `tools/s2.py verify` |
| `writing.page_limit` | 9 | PI | target main-text pages; over-length trimmed gradually |

## Layer 2 — `<project>/control.yaml` (per-project, end-to-end)

**Created automatically at spawn** — the first set-up step generates this config from the approved proposal — and editable for the project's whole life. This is where you control a project's runs end to end:

| Key | Owner | Effect |
|---|---|---|
| `budgets.smoke_max_minutes` / `pilot_…` / `full_…` | **PI after Gate 1** | per-stage wall-clock caps, **enforced by the run watchdog** (a run that exceeds its stage budget is killed and recorded as `timeout`) |
| `budgets.total_note` | PI | free-text total compute cap from the proposal |
| `seeds.list` | agent | default seeds for `scripts/sweep.py` |
| `seeds.multi_seed_n` | agent | project override of the paper-grade seed count |
| `parallelism.max_parallel_subagents` | agent | project override for `/improve` |
| `parallelism.sweep_parallel` | agent | default `--parallel` for sweeps |
| `loop.no_progress_backoff_cycles` / `monitor_poll_seconds` | agent | project overrides for `/research-loop` |
| `monitoring.log_interval_seconds` | agent | expected seconds between `ctx.log()` calls — passed to `status.py --log-interval` so a sparse-logging run isn't flagged stalled |
| `figures.theme` | agent | figure vibe: `clean` (Okabe-Ito default) · `warm` (brown/clay editorial) · `bold` (Tol bright, talks) · `mono` (grayscale + linestyle cycling, B/W-safe) |
| `gate2_envelope.full_runs` / `per_run_max_minutes` / `total_max_minutes` / `expires` | **PI only** | the pre-authorized FULL-run envelope — the canonical machine-readable record Gate 2 checks (`expires` checked before each FULL launch) |
| `gate2_envelope.pi_signed` | **PI authority** | set directly by the PI, **or** transitively under a PI-signed `/autopilot` campaign brief whose bounds cover it |
| `gate2_envelope.signed_via` | provenance | `null` = signed directly by the PI; else the path of the campaign brief carrying the signature |
| `eval_frozen` | **PI only** | the eval protocol is frozen; the agent may *never* set this false |

!!! warning "PI-owned keys"
    `/configure` refuses to change PI-owned keys unless the request comes explicitly from you in-session. `gate2_envelope.pi_signed: true` and `eval_frozen: false` carry PI authority by hard rule, not convention — set directly when you ask in-session, or (for `pi_signed`) transitively under a PI-signed `/autopilot` campaign brief, which records its path in `signed_via`. The agent never sets them on its own initiative.

!!! note "Not config, but binding: `SYSTEM.md`"
    Alongside `control.yaml`, a project may carry a PI-written `SYSTEM.md` — a prose description of the machine it runs on (hardware reality, data locations, scheduling rules, forbidden actions). It's not merged into any config layer, but agents treat its constraints as binding like control.yaml and never edit it. Lab default at `lab/SYSTEM.md` (template: `templates/SYSTEM.md`, offered by `/setup-lab`), copied into each project at spawn. See [Autonomy & modes](autonomy.md#autonomy-inside-the-project-directory).

## Layer 3 — `configs/experiments/*.yaml` (one per experiment)

The unit of experimentation. **Immutable once run** — a variant is a *new* file, which is what keeps every past experiment re-runnable forever. Anything set here (including `budget.max_minutes`) beats the layers below. `configs/base.yaml` holds the project's shared *domain* defaults (model, data, eval definition) between control.yaml and the experiment files.

### Stage-budget mapping

If neither the experiment yaml nor `base.yaml` sets `budget.max_minutes`, the loader maps it from `control.yaml → budgets.<stage>_max_minutes` for the run's stage — so per-stage caps apply automatically without repeating them in every experiment file. The fully resolved config is dumped into every run's artifact dir as `config.resolved.yaml`; per-key provenance (which layer set each key) is available via `tools/show_config.py`.

## How configs flow through a project's life

1. **Gate 1**: PI approves budgets (+ optional envelope) in the proposal.
2. **Spawn**: `control.yaml` is generated from the template and filled from the proposal; envelope recorded with `pi_signed: true` if granted (`signed_via` = the campaign brief, when an `/autopilot` campaign authorizes it).
3. **Any time**: `/configure` (or hand-edit) adjusts agent-owned values; PI-owned values need you.
4. **Every run**: experiment yaml → base → control resolve into one artifact-dumped config; the watchdog enforces the resulting budget.
5. **Loops**: `/research-loop` reads `gate2_envelope` + `loop.*` from control.yaml; the LOOP_BRIEF carries your signature and points here for numbers.
