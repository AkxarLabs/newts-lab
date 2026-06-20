---
name: compete
description: Spin off a target-driven project for a task with a fixed, straightforward target (a benchmark to beat, a metric to hit, a leaderboard to climb, an internal KPI) and iterate toward it — fanning out ideas in-project and running experiments, no paper/novelty pipeline. Argument; an optional slug or task name. The "I have a target, go chase it" on-ramp.
---

# Compete — pursue a fixed target

For a **task with a straightforward target** (beat a benchmark, hit a metric, climb a
leaderboard, reach a KPI), `/compete` spins off a project aimed at it and sets up the
**iterate-toward-target loop** — run experiments, fan out ideas in-project, log everything,
move the metric. It reuses the whole project engine (staged scale, frozen eval, budgets,
ledger, git, `/research-loop`) and **skips the paper layer** (no
`/ideate→/lit-review→/scope→/propose`, no novelty gate, no headline-hypothesis boundary).
Host-agnostic — Kaggle is one instance; the agent learns and records the task's specifics
itself in `TARGET.md`. Use when the success criterion is a number, not a claim.

## 1. Short interview — establish the target (this IS the Gate-1 authorization)

*Optional first:* if the target is fuzzy, run `/discuss target [task]` to grill the PI and
research the task before this interview — its session doc lists the answers below, so this step
transcribes rather than re-asks.

Spinning a project + spending compute is **Gate 1**; this interview *is* that PI conversation —
write its outcome into `IDEA.md` (no separate proposal). Establish:

- **The task & target** — name, URL (if any), the **done-condition** (e.g. "public ≥ 0.90",
  "RMSE < 0.42 on the grader", "top-10 by the deadline"), and the **deadline** (if any).
- **Metric + direction** (maximize | minimize).
- **Data/resources** — where they live, how to fetch/authenticate (command + env-var key names,
  never values); train vs. held-out/unlabeled input.
- **Scoring** — **internal** (computed locally, no data leaves the lab) or **external** (send an
  output to a scorer/leaderboard, read a score back). If external: how (CLI / HTTP call / grader
  script — fills `target.scoring.score_command`), and the scorer's rate limit (→ score envelope).
- **Output contract** (only if scored on an artifact you produce) — file/format, id + target
  column(s), exact expected row count.
- **Rules/constraints** — allowed external data, pretrained-model/runtime limits, account/team
  rules. These bind like `SYSTEM.md`.
- **Budgets** — per-stage caps + the **Gate-2 FULL-run envelope** (none = every FULL run waits
  for the PI), and (if external) the **score envelope** (per-day / total external reads).

## 2. Scaffold the project

If the PI already has a code repo, branch to §5 *now* (wrap it, don't copy a fresh tree over it).
Otherwise spawn fresh below. `/compete` does **not** call `tools/guard.py spawn` (that guard
requires a `studies/<slug>/proposal.md` Gate-1 marker; a target chase has no proposal — Gate 1 is
recorded in `IDEA.md` per step 1).

1. `studies/<slug>/IDEA.md` from `templates/idea/`, carrying the PI's target verbatim. Set
   frontmatter `state: active` (leaving it `seed` makes `tools/check_lab.py` flag a mismatch). In
   `## State log`, append one bullet per skipped stage in the template's `- <date>: <event>` form:
   `- <date>: lit-review — N/A (target-driven)` (same for `scoping`, `proposal`), plus
   `- <date>: Gate 1 — PI-authorized (compete interview)`.
2. Apply the templates into the project dir, in order:
   - `templates/project/` — the base contract. **Substitute** `{{slug}}` / `{{title}}` /
     `{{date}}` / `{{hub_path}}` in `control.yaml`, `PLAN.md`, `CLAUDE.md`, `AGENTS.md`,
     `README.md`, `EXPERIMENT_LOG.md`, `pyproject.toml` (exactly as `/spawn-project` step 3 — an
     unsubstituted `{{…}}` fails `check_project.py`, and `pyproject.toml name = "{{slug}}"`
     breaks `uv sync`).
   - then the **`templates/compete/`** overlay (additions, **except** it replaces the base
     `src/project_pkg/experiment.py` and `configs/experiments/exp-001-smoke.yaml` with target
     versions that emit + validate an output): `TARGET.md`, `scripts/check_output.py`,
     `scripts/report_score.py`, `src/project_pkg/{output_io,experiment}.py`,
     `configs/experiments/exp-001-smoke.yaml`.
   - append `templates/compete/control.target.yaml` to the project's `control.yaml`.
3. Fill **`TARGET.md`** (PI-owned brief) and the `control.yaml` `target:` block from the
   interview: `metric`, `direction`, `done`, `deadline`, the `output` contract (or `null` for a
   local-metric target), `scoring` (`read_back`, `external`, and `score_command` if `command`).
   Set `budgets` and `gate2_envelope`, and — if external — the `score_envelope`, exactly as
   `/spawn-project` does. **Never set any `pi_signed: true` on your own authority** — only
   transcribe what the PI signed in the interview (leave `signed_via: null` for a direct PI sign).
   Keep `eval_frozen: true` (the metric + local split is the frozen eval).
4. Fill **`PLAN.md`** (the engine drives off its rows — `/experiment`, `/advance`,
   `/research-loop`). Frozen evaluation = the metric + the local validation split that mirrors the
   scorer + the held-out test (the external scorer, if any); **Headline hypothesis = the target
   itself** ("reach `<done>`"); kill criteria; and a staged experiment table seeded with at least
   the SMOKE row and the first real baseline line(s). Budgets reference `control.yaml`.
5. Initialize and verify: `git init`, `uv sync`, run the smoke
   (`uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml`), then
   `uv run --with pyyaml python scripts/check_output.py runs/<run_id>/<file>` (if there's an
   output contract — the toy emits a valid one), then `uv run pytest tests/` and
   `uv run --with pyyaml python scripts/check_project.py` (exit 0).
   - **All green** → only now set the registry row to state **`active`** (Project column = project
     path; next action = `/experiment exp-002`), commit ("scaffold: /compete target-driven
     project, smoke green"), and commit `uv.lock`.
   - **Still red** after up to `experiment.max_debug_depth` fix attempts → leave the directory
     **uncommitted**, do **not** set the registry to `active`, record the failure, and report to
     the PI.
6. Append a lab notebook entry; emit `uv run python tools/lab_bus.py emit state_change --idea <slug> --detail "compete: spawned, active"`.

## 3. Iterate toward the target (the loop — this is the point)

The method space is **open** (no headline-hypothesis boundary), so fan out freely toward the
metric, with the engine's normal discipline:

- `/experiment <slug>` — the next planned line, SMOKE→PILOT→FULL; one `EXPERIMENT_LOG.md` entry +
  `runs/registry.jsonl` row + one git commit per attempt (rules 7, 8, 11).
- `/improve <slug> explore` — fan out variants and **expand the frontier**.
- `/ideate --in-project <slug>` — generate **divergent approaches** inside the project (scoped to
  the frozen set: task/metric/output/rules/deadline). Fully in-bounds here (no headline gate to
  trip), so it is the main idea-generator for the climb (requires `ideation.in_project: true`; if
  `false`, use a successor hub `/ideate`).
- `/research-loop <slug>` (`Mode: explore`) — unattended climbing under a PI-signed
  `LOOP_BRIEF.md`, with **`target.done` and the deadline as stop conditions**.
- **Selection discipline (hard rule 5, sharpened):** tune/select on the **local** validation
  split; when scoring is external, the scorer **is** the held-out test — read it sparingly via
  `scripts/report_score.py`, never select on external rank alone.

## 4. Gates & the outward action

- **Gate 1** — recorded at the §1 interview (authorizes the spawn + compute).
- **Gate 2** — FULL runs follow the `gate2_envelope` (signed or fresh PI approval), exactly as
  any project; `tools/guard.py full-run <slug>` enforces it.
- **External scoring = an outward action** (Gate-2 analogue, distinct from the compute envelope).
  Sending an output to a scorer/leaderboard runs under the PI-signed `target.score_envelope`
  (per-day / total caps + deadline), enforced by `scripts/report_score.py` (a cap of 0 authorizes
  nothing). No envelope ⇒ every external read waits for the PI. The deadline **hard-blocks** an
  external read in `report_score.py` and stops the `/research-loop`; `check_output.py` only
  **warns** on it (it validates a file, it doesn't gate submission).
- **Gate 3 — never delegated, never dashboard-signed.** *Selecting the final output* for the
  hidden/final split, declaring the target met, and sending anything outside the lab are done by
  the PI in a session. Close out with `/finalize <slug>` (reproducibility pass on the winning
  run; cited artifacts/output secured in the project).

## 5. Adopting an existing repo as a target project

If the PI already has code (a starter kernel, a baseline repo), don't restructure it — **wrap
it** (see `/adopt` "Adopting a repo"): register its path as the Project; copy in the missing
contract files plus the `templates/compete/` overlay (don't `git init` an already-init repo,
don't overwrite the PI's code); set `package:` in `control.yaml` to its package name (the runner
autodetects a single `src/` package; `package:` pins it when there are several); adapt
`experiment.py` to call its entry point and `write_output(...)` the scorer's artifact.
`uv run --with pyyaml python scripts/check_project.py --adopt` must exit 0. Everything else (the
PLAN.md fill, IDEA.md `state: active`, the no-self-sign rule) is the same as §2.

## 6. Report

Target + done-condition, where the project lives, smoke/output-check/test status, the
`control.yaml` `target:` summary (incl. envelopes), and the exact next command (usually
`/experiment <slug>` or authorizing a `LOOP_BRIEF.md` for `/research-loop`).
