# Projects

A **project** is where a single research idea's code and experiments live. Projects are spawned from `templates/project/` by `/spawn-project` and are designed for two audiences at once: an agent iterating automatically, and a human researcher extending the work later.

Every project has a **type** (`ml` by default, or `empirical` / `simulation` / `theory` / `target-driven`) chosen at spawn, which defines what an "experiment" is and lets non-ML domains (e.g. economics) reuse the same engine — see [Project types](project-types.md).

## Where projects live

**Outside the hub**, at `lab.projects_root` — default `../kartr-lab-projects/<slug>`, a sibling folder next to your lab:

```
Documents/
├── kartr-lab/                  ← hub (ideas, papers, knowledge, procedures)
└── kartr-lab-projects/
    ├── slm-distill-router/         ← project: own git repo
    ├── slm-distill-router-wt-exp-007/   ← transient worktree (parallel /improve variant)
    └── tiny-rlhf-probe/            ← another project
```

Each project is **its own git repository**: independently cloneable, publishable, and archivable. The hub tracks only the pointer (registry row) — it never accumulates experiment state. Worktree dirs (`-wt-`) are transient and ignored by the lab lint.

## Anatomy

```
<slug>/
├── CLAUDE.md                # project protocol — a session started HERE is fully operational
├── AGENTS.md                # the same for any other agent + cold-start checklist
├── SYSTEM.md                # optional, PI-owned: the machine's ground truth (copied from lab/SYSTEM.md)
├── control.yaml             # end-to-end run controls — created at spawn, editable (see Configuration)
├── PLAN.md                  # approved experiment plan: frozen eval protocol, staged table, kill criteria
├── NOTES.md                 # distilled memory: gotchas+fixes / tried-and-abandoned / what's settled — read in full at orientation
├── EXPERIMENT_LOG.md        # append-only narrative ledger with lineage fields — read this first
├── configs/
│   ├── base.yaml            # shared domain defaults
│   └── experiments/         # ONE immutable file per experiment
├── src/project_pkg/         # config loader, seeding, run tracking, experiment logic
├── scripts/
│   ├── run.py               # single entry point (budget watchdog built in)
│   ├── sweep.py             # multi-seed / grid launcher
│   ├── compare.py           # registry queries (best, seeds, experiments)
│   ├── status.py            # zero-token run monitor
│   ├── check_project.py     # readiness lint + suggested next procedure
│   └── figures/             # every paper figure/table is generated here from artifacts
├── runs/                    # per-run artifact dirs (gitignored) + committed registry.jsonl
└── tests/                   # smoke + watchdog tests — keep green forever
```

A project is **autonomously operable from inside**: `cd <slug> && claude` reads the project's `CLAUDE.md` and gives the agent everything — orientation order, autonomy bounds (`control.yaml`), machine constraints (`SYSTEM.md`, if you wrote one), when to parallelize with subagents, and pointers to the hub procedures it follows. `scripts/check_project.py` is the cold-start lint: it verifies the repo is runnable and suggests the next procedure. See [Autonomy & modes](autonomy.md#autonomy-inside-the-project-directory).

## The reproducibility contract

A stranger (human or agent) cloning a finished project can:

```bash
uv sync                                   # exact environment from the committed uv.lock
uv run pytest                             # pipeline verified in seconds
uv run python scripts/run.py --config configs/experiments/<any-past-exp>.yaml --seed <s>
```

…and re-run **any past experiment from its config file**. That works because of the run contract: every run dumps its fully resolved config + git SHA (+ a `code.patch` if the tree was dirty) + seed + **environment provenance** (`meta.json → env`: python version, platform, and torch/CUDA + GPU when present) + metrics into `runs/<run_id>/`, appends one line to the committed `runs/registry.jsonl`, and is budget-capped by a watchdog that cannot be talked out of it. The config loader is **layered** (`control.yaml` → `configs/base.yaml` → experiment yaml → CLI `-o` overrides), resolves once, and **validates at load** — a typo'd `stage`, a non-int `seed`, or a non-numeric budget fails immediately rather than KeyError-ing deep in the run (the `_validate` hook in `config.py` is where a project adds its own required-key/range checks). This is deliberately a small, single-dependency design rather than a heavyweight config framework: config *groups* are the `base`/experiment split, *multirun* is `scripts/sweep.py` (grid × seeds), and *overrides* are `-o key=value` — so the simple default stays simple, and a genuinely composition-heavy project can opt into a heavier tool as a project type rather than the lab adopting one by default. See [Configuration](configuration.md).

## Project memory — chronological + distilled

A project carries **two** memory layers so a later session (or a human) never re-learns what an earlier one already paid for:

- **Chronological** — `EXPERIMENT_LOG.md` (one append-only entry per attempt, including failures, with `Parent:`/operator lineage), `runs/registry.jsonl` (machine-readable per-run summaries, queryable via `scripts/compare.py`), and `git log` (one commit per attempt). The full record of *what happened*.
- **Distilled** — `NOTES.md`: a short, append-only index over the log with three sections — **gotchas & fixes** (environment/data/infra traps + their workaround), **tried & abandoned** (approach → exp-ids → why it failed → "don't retry unless…"), and **what worked / settled here**. Every line carries an evidence pointer (`exp-NNN`/`run_id`). It is read **in full** at orientation (it stays small by construction), so a project's hard-won lessons survive even after early `EXPERIMENT_LOG.md` entries scroll out of the tail. `/experiment` and `/improve` append to it when an attempt yields a durable lesson; durable *cross-project* lessons are also promoted up to `lab/knowledge/` (hard rule 11) — `NOTES.md` is the local "don't repeat this *here*" cache, not a replacement.

## The hardened hub↔project boundary

The paper lives in the hub but its evidence lives in the project — so the boundary between them is wired so a finalized paper never depends on a live project repo:

- **Figures are synced, not copied by hand.** `tools/sync_figures.py <slug>` copies the project's `figures/*.{pdf,tex,png}` into `studies/<slug>/paper/figures/` and records a `.manifest.json` (source path + sha256 + project commit); `--check` (run by `/write-paper` and `/review-paper`) fails if any hub copy is stale or diverged.
- **Cited artifacts are archived at finalize.** `tools/lock_artifacts.py <slug>` copies every `runs/<id>/metrics.json` cited in `claims.yaml` into committed `studies/<slug>/paper/artifacts/`, with a locked `artifact_sha256` per claim; `audit_claims.py … --verify-hashes` then resolves the hub archive first and re-checks the hashes — so a **finalized paper is auditable from the hub alone**.
- **Write-back is a single atomic tool.** A project session calls `tools/hub_writeback.py --slug <slug> …` to append the hub notebook/knowledge entry and set the registry row in one step; if the hub is unreachable it leaves a `HUB-WRITEBACK-PENDING:` block in `EXPERIMENT_LOG.md` that the next hub session reconciles via `tools/process_writebacks.py --apply`.
- **Escalation is bidirectional.** A project loop blocked mid-run (a headline reopen, a frozen-setting block, FULL work outside the envelope) emits `lab_bus.py escalate` so the hub/PI sees it without waiting for loop exit — it requests attention, never grants a gate.

## Extensibility rules (how the code stays extendable)

These are the project-level hard rules, written for auto-research but exactly what makes human extension pleasant:

1. **A new experiment is a new config file.** Experiment yamls are immutable once run; variants are new files. History never breaks.
2. **New method variants live beside the baseline, never replace it.** New module/function behind a config switch; the baseline path stays runnable forever.
3. **The eval protocol is frozen** (`control.yaml → eval_frozen`). Changing metrics/splits mid-project invalidates every comparison — it requires PI sign-off and an explicit new config key, never an in-place edit.
4. **Append-only ledgers.** `EXPERIMENT_LOG.md` (with `Parent:`/operator lineage fields) and `registry.jsonl` record everything tried — including failures. Read them before experimenting; they are the project's memory.
5. **One commit per attempt** with the experiment id in the message — `git log` is a third, independent ledger.
6. **Figures are scripts.** Anything that appears in a paper is regenerable from `runs/` artifacts by a committed script in `scripts/figures/`.

## For human researchers extending a project

- Start with `EXPERIMENT_LOG.md` + `python scripts/compare.py list` — what was tried, what won, what failed and why.
- `PLAN.md` tells you what the original hypothesis and frozen eval were; `control.yaml` tells you the operating budgets.
- To try your own idea: add `configs/experiments/exp-1xx-yourname.yaml` (+ code behind a switch if needed), run it, log it. You're following the same contract the agent does — and the agent can later build on *your* entries.
- The hub's `studies/<slug>/` (lit review, proposal) and `studies/<slug>/paper/` give the full intellectual context; the registry row links everything.

## Adopting an external repo as a project

You don't have to start from the template. An existing repo — your own baseline, a cloned starter kernel, someone else's codebase — can be **wrapped** (not restructured) and connected to the lab via `/adopt` (or `/compete` for a target-driven one):

1. **Register its path.** The registry row's Project column may point anywhere (absolute or hub-relative); `lab.projects_root` is only the default for *spawned* projects.
2. **Drop the contract on top** (additions only): copy from `templates/project/` whatever `scripts/check_project.py` requires that's missing — `control.yaml`, `PLAN.md`, `EXPERIMENT_LOG.md`, `configs/base.yaml` + a smoke yaml, `scripts/`, an empty `runs/registry.jsonl`.
3. **Keep their package name.** `scripts/run.py` and `sweep.py` autodetect the package under `src/`, and `control.yaml → package:` pins it — so their code drives the runner **without a rename**. Set `package: their_pkg_name` and adapt the thin `experiment.py` (`run(cfg, ctx) -> dict`) to call their entry point; runs just need to land in `runs/<run_id>/` with a registry line.
4. **Provenance is non-negotiable.** `scripts/check_project.py --adopt` must exit 0 — pre-existing numbers must trace to `runs/` artifacts (hard rule 1), or be re-run under the contract.

See the [`/adopt`](skills.md#adopt) skill for the full procedure, and [Target-driven projects](compete.md) for wrapping a competition/benchmark repo.

## Domain-specific templates

`templates/project/` is deliberately domain-agnostic (the toy experiment exists only to prove the pipeline). When a domain's patterns stabilize — e.g. SLM finetuning with HF transformers + peft + a fixed eval harness — fork the template into `templates/project-slm/` and point `/spawn-project` at it. The contract (control.yaml, run tracking, ledgers, watchdog, tests) stays identical; only the domain layer changes. The target-driven overlay `templates/compete/` (used by `/compete`) works the same way — it adds the output/score contract on top of the base template.
