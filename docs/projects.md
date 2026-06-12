# Projects

A **project** is where a single research idea's code and experiments live. Projects are spawned from `templates/project/` by `/spawn-project` and are designed for two audiences at once: an agent iterating automatically, and a human researcher extending the work later.

## Where projects live

**Outside the hub**, at `lab.projects_root` — default `../AutoScientist-Projects/<slug>`, a sibling folder next to your lab:

```
Documents/
├── AutoScientist/                  ← hub (ideas, papers, knowledge, procedures)
└── AutoScientist-Projects/
    ├── slm-distill-router/         ← project: own git repo
    ├── slm-distill-router-wt-exp-007/   ← transient worktree (parallel /improve variant)
    └── tiny-rlhf-probe/            ← another project
```

Each project is **its own git repository**: independently cloneable, publishable, and archivable. The hub tracks only the pointer (registry row) — it never accumulates experiment state. Worktree dirs (`-wt-`) are transient and ignored by the lab lint.

## Anatomy

```
<slug>/
├── control.yaml             # end-to-end run controls — created at spawn, editable (see Configuration)
├── PLAN.md                  # approved experiment plan: frozen eval protocol, staged table, kill criteria
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
│   └── figures/             # every paper figure/table is generated here from artifacts
├── runs/                    # per-run artifact dirs (gitignored) + committed registry.jsonl
└── tests/                   # smoke + watchdog tests — keep green forever
```

## The reproducibility contract

A stranger (human or agent) cloning a finished project can:

```bash
uv sync                                   # exact environment from the committed uv.lock
uv run pytest                             # pipeline verified in seconds
uv run python scripts/run.py --config configs/experiments/<any-past-exp>.yaml --seed <s>
```

…and re-run **any past experiment from its config file**. That works because of the run contract: every run dumps its fully resolved config + git SHA + seed + metrics into `runs/<run_id>/`, appends one line to the committed `runs/registry.jsonl`, and is budget-capped by a watchdog that cannot be talked out of it.

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
- The hub's `ideas/<slug>/` (lit review, proposal) and `papers/<slug>/` give the full intellectual context; the registry row links everything.

## Domain-specific templates

`templates/project/` is deliberately domain-agnostic (the toy experiment exists only to prove the pipeline). When a domain's patterns stabilize — e.g. SLM finetuning with HF transformers + peft + a fixed eval harness — fork the template into `templates/project-slm/` and point `/spawn-project` at it. The contract (control.yaml, run tracking, ledgers, watchdog, tests) stays identical; only the domain layer changes.
