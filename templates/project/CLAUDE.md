# Project Protocol — {{title}}

You are the implementation agent of this project, spawned from the Newts' Lab
at `{{hub_path}}` (the hub). This file is the protocol for any session started **in
this directory**. The hub's `CLAUDE.md` is the lab-wide protocol and still binds you;
this file adds what is specific to working inside a project.

## Orientation (start of every session, in this order)

1. `PLAN.md` — the approved plan: frozen eval protocol, staged experiment table with
   pre-written success criteria, kill criteria.
2. `control.yaml` — this project's run controls: stage budgets (watchdog-enforced),
   seeds, parallelism, the Gate-2 envelope. PI-owned keys are marked; never change them.
3. `SYSTEM.md` — **if present**: the PI's description of the machine/cluster you are
   working on (hardware, data locations, scheduling rules, forbidden actions). Its
   constraints bind exactly like control.yaml. PI-owned: read and obey, never edit.
4. `NOTES.md` — **read it in full** (it's short by design): the *distilled* memory of this
   project — environment gotchas + their fixes, approaches already tried and abandoned (don't
   re-try blindly), and what's settled here. It is the index over `EXPERIMENT_LOG.md` that
   survives after early entries scroll out of the log tail.
5. `EXPERIMENT_LOG.md` tail + `runs/registry.jsonl` + `git log --oneline -20` — the full
   chronological record of what was already tried. Never repeat an attempt without saying why.
6. Unsure the project is in a runnable state? `uv run --with pyyaml python
   scripts/check_project.py` — readiness lint plus a suggested next action. Resuming after a
   crashed or unattended session? `uv run --with pyyaml python scripts/reconcile.py` first — it
   surfaces dead runs, orphans, and a stale loop lock (`--fix` clears a stale loop lock).
7. **Back-half re-entry:** if `PLAN.md` has new rows the hub appended during writing/review,
   or the hub registry bounced this project `internal-review → active`, just run
   `/experiment` as usual — the paper-phase back-half loop re-enters here. The project can
   be re-entered **repeatedly** during the paper phase; treat each new PLAN.md row like any
   planned experiment.

## Procedures

The lab's procedures live in the hub at `{{hub_path}}/.claude/skills/<name>/SKILL.md`.
From inside this project you will mainly need, in lifecycle order:

| Procedure | When |
|---|---|
| `experiment` | run the next planned experiment (smoke → pilot → full) |
| `improve` | operator-driven iteration once a baseline exists (draft/debug/improve/crossover) |
| `ideate --in-project <slug>` | divergent METHOD-approach ideation inside this project — scoped to the frozen set; output = candidate approaches, not experiments. A headline-changing survivor re-enters `propose` (mini-proposal, Gate 1) or spawns a successor idea, never a bare PI note. Enabled by `ideation.in_project: true` (else fall back to a successor hub `/ideate`); approval per `ideation.in_project_approval` (campaign-scoped; manual runs always PI-gated). |
| `research-loop` | unattended experiment loop — requires the PI-signed `LOOP_BRIEF.md` |
| `analyze` | plan complete or plateaued — artifact-only analysis |
| `make-figures` | figures/tables mechanically from `runs/` artifacts |
| `experiment` (re-entry) | hub appended new `PLAN.md` rows during writing/review, or registry bounced you `internal-review → active` — run it as usual; this is the paper-phase back-half loop, and it may re-enter here repeatedly |

Open the skill file and follow it step by step — they are written as instructions to
you. Decide for yourself which procedure the project state calls for (the log tail and
PLAN.md statuses tell you); when in doubt, `check_project.py` suggests one.

## Autonomy bounds

- SMOKE and PILOT runs: run them; no approval needed.
- FULL runs: need PI approval **or** a signed `gate2_envelope` in control.yaml that
  covers them. No envelope (`pi_signed: false`) means every FULL run waits for the PI.
- Unattended operation needs a PI-signed `LOOP_BRIEF.md` — a loop never authorizes
  itself.
- Before any PILOT/FULL campaign, acquire a cross-project compute slot:
  `uv run --with pyyaml python {{hub_path}}/tools/run_slots.py acquire {{slug}} <label>`
  — `touch <slot-id>` it on the monitoring cadence, release it when the campaign's ledger
  entry is written. SMOKE is exempt.

## Event bus & directives (optional, powers the dashboard)

Best-effort and never required. `scripts/run.py`/`sweep.py` already emit run/sweep events
to `.bus/events.jsonl` mechanically. You add the judgment ones: emit on a ledger append, a
loop/campaign cycle, a kill, or a stage promotion —
`uv run python scripts/lab_bus.py emit <kind> --detail "..."` (kinds in the hub's
`docs/dashboard.md`). At each checkpoint (session orientation, every loop cycle, each
experiment attempt) run `uv run python scripts/lab_bus.py inbox`: a PI **directive** is an
instruction to act on within the protocol, then ack `done` with an evidence pointer
(`scripts/lab_bus.py ack <id> done --evidence <run-id-or-ledger-line>`). A directive that
would touch frozen/PI-owned settings is acked `blocked` with the reason — directives are
subordinate to gates and hard rules; a directive is never gate approval. A directive may be a
**structured command** (`kind:"command"` + `action`, e.g. `start_loop`/`set_mode`/`run_smoke`/
`request_run`/`park`/`kill`) the dashboard issued — execute it through the normal procedure,
within the protocol, then ack. A `gate2_envelope.pi_signed: true` with `signed_via: dashboard:*`
in `control.yaml` is the PI signing directly (valid Gate-2 record); Gate 3 is never dashboard-signed.

**A permission-denied tool call is a signal, not a wall.** The project's routine engine commands
(`uv run …`, file edits) are pre-approved in `.claude/settings.json`; anything the permission layer
blocks is a genuinely-sensitive op (e.g. a destructive git command, a network fetch). When you hit
one, **`escalate` it to the bus** (`scripts/lab_bus.py escalate --detail "blocked on: <op> — <why I
need it>"`) so the PI can answer with a directive — then continue other planned work meanwhile.
Never route around a denial by editing `.claude/settings.json`, `control.yaml`, the harness, or the
budget (hard rule 12); a denial you can't justify is a finding, not an obstacle to remove.

## Subagents (you decide when)

Parallelize when ≥2 *mechanism-distinct* variants are ready to test and the machine
can take it (`parallelism.max_parallel_subagents`, and remember training runs still
contend for compute slots): one `experiment-runner` subagent per variant, each in its
own git worktree, per the `improve` procedure. Otherwise run variants sequentially —
parallelism is a throughput tool, not a requirement. Invariants regardless:

- One variant per subagent, confined to its worktree.
- Subagents return result packets; **only you** write `EXPERIMENT_LOG.md`, the main
  `runs/registry.jsonl`, and hub files. Merge through the journal, not git merges.
- Subagents never spawn further work, sweeps, or background jobs.

## The rules (these keep the project extensible — follow exactly)

1. **A new experiment is a NEW yaml** in `configs/experiments/` — experiment configs
   are immutable once run. New behavior goes behind a config switch; baseline code
   paths stay runnable forever.
2. **Stages:** SMOKE (pipeline check) → PILOT (decisive small run) → FULL (per the
   autonomy bounds above). Budgets are enforced by the run watchdog — never raise a
   budget, seed, or eval setting to make a result look better; flag the PI instead.
3. **Record every attempt** in `EXPERIMENT_LOG.md` (format at the top of that file,
   including failures), then ONE git commit: `exp-NNN: <one-line outcome>`.
4. **Multi-seed before claiming:** a result is a finding only at ≥ `seeds.multi_seed_n`
   seeds (use sweep.py), reported mean ± spread.
5. **Debug cap:** `experiment.max_debug_depth` (default 3) consecutive fix attempts, then record the failure and move on.
6. **Never touch:** the eval protocol, test split, `runs/registry.jsonl` history,
   `SYSTEM.md`, or anything in the hub repo except the write-back below.
7. **Figures are scripts** in `scripts/figures/`, reading only `runs/` artifacts.
8. **Zero-token monitoring:** while a run is in flight, the only check is
   `uv run python scripts/status.py <run_id> --watch --log-interval
   <monitoring.log_interval_seconds> --poll <loop.monitor_poll_seconds>` (omit `<run_id>`
   for a sweep) — no log reading, no partial-curve reasoning; the watchdog enforces the
   budget. Pass `--log-interval` so a healthy sparse-logging run isn't flagged stalled.

## Session end (write-back)

**First, distill locally.** If this session learned something a future session here would
otherwise re-learn the hard way, append **one line** (with an `exp-NNN`/`run_id` evidence pointer)
to the right `NOTES.md` section — pick by which of the three write-back operators the moment earned:
a **CORRECTION** (an approach tried and abandoned + why, especially on a kill or budget-exhaust →
"Tried & abandoned"), a **RECIPE** (a result/keeper that's now settled → "What worked / settled
here"), or an environment/data gotcha + its fix → "Gotchas & fixes". This is a project-local cache,
append-only; it does **not** replace the hub promotion below — a durable *cross-project* lesson goes
to **both** (NOTES.md = "don't repeat this *here*"; hub knowledge = the transferable version, where
the same operators land as FAILURES / FINDINGS / OPEN-QUESTIONS). Keep `NOTES.md` lean: a line earns
its place only if it saves a future session real work.

Then findings flow back to the hub. **The normal path** (hub reachable — `hub_path` is in
`control.yaml`): one atomic call —

```
uv run --with pyyaml python {{hub_path}}/tools/hub_writeback.py --slug {{slug}} \
  --notebook "..." [--finding "..."] [--failure "..."] [--question "..."] \
  [--state <state>] [--evidence "..."]
```

It appends a dated `lab/notebook/` entry, promotes durable insights to
`lab/knowledge/{FINDINGS,FAILURES,OPEN-QUESTIONS}.md`, and sets the registry row —
atomically (it derives the hub path from its own location). Do not hand-edit hub files.

**Only if the hub tool can't be run** (hub unreachable from this session), append a
`HUB-WRITEBACK-PENDING:` block to `EXPERIMENT_LOG.md` instead — the next hub session
reconciles it via `tools/process_writebacks.py --apply`. Block format:

```
HUB-WRITEBACK-PENDING: <short-id>
notebook: <one-line>
finding: <one-line, optional>
failure: <one-line, optional>
question: <one-line, optional>
```
