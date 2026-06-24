# Project types

Not every project is ML training. Newts' Lab's lifecycle (ideate → … → paper) is
domain-agnostic; only the **project spoke** (what a "run" is) varies. That variation is captured
as a **project type**, chosen once at `/spawn-project`.

## Two orthogonal axes

| Axis | What it sets | Where it lives |
|---|---|---|
| **Methodology type** | what an "experiment" *is* and how the hard rules realize (staged scale, multi-seed *or its analogue*, frozen eval, the runner) — **structure** | `templates/project-types/<type>/TYPE.md` |
| **Domain profile** | venues, data sources, field conventions — **content** | `templates/domain-profiles/<domain>.md` |

They compose: *math-econ theory* = the `theory` type × the `econ` profile. You don't multiply
types per field — you attach a light profile. The agent can **draft a profile (or a new type) on
demand**; the shipped ones are starters.

## The five default types

| Type | An "experiment" is… | Runner | Multi-seed | Frozen eval / selection |
|---|---|---|---|---|
| **`ml`** *(default)* | a model train/eval run | `python-import` | seeds (`sweep.py`) | validation selects, held-out test reports |
| **`empirical`** | a regression / specification run | `shell-command` (R/Stata) or `python-import` | bootstrap / spec multiplicity | pre-register spec + outcome; hold-out/placebo |
| **`simulation`** | a seeded simulation draw | `python-import` or `shell-command` | independent draws | calibration moments; out-of-sample regime |
| **`theory`** | a derivation / proof step | proof-assistant (`shell-command`) or none | N/A (deterministic) | worked examples as the held-out check |
| **`target-driven`** | a run emitting a scored output | `python-import` | seeds | external scorer **is** the held-out test |

`target-driven` is the existing `/compete` mode (it applies the `templates/compete/` overlay).
Each type is **one page** (`TYPE.md`) copied into the project so an in-project session knows its
own rules — the agent designs the concrete `run.py` body / configs / smoke per project.

## The shared engine — one seam

Every project is stamped from the same `templates/project/` base and reuses the whole engine
(config layering, seeding, the watchdog-enforced budget, run artifacts, the append-only registry,
`/experiment`, `/improve`, `/research-loop`). A type plugs in at **one place** —
`scripts/run.py`'s `runner:`:

- **`python-import`** (default): `import <package>.experiment.run(cfg, ctx)` — the ML/Python path,
  unchanged.
- **`shell-command`**: runs `runner_command` (any language — `Rscript`, `stata -b`, `julia`, a Lean
  checker). It receives `$RUN_DIR`, `$CONFIG_PATH`, `$SEED` and writes a **flat JSON dict of final
  metrics to `$RUN_DIR/result.json`**. `run.py` records that through the same `RunContext`, so
  **hard rule 1 (every number traces to an artifact) holds identically across languages**, and the
  budget watchdog still reaps the external process tree on breach.

```yaml
# control.yaml (an empirical project in R)
project_type: empirical
runner: shell-command
runner_command: ["Rscript", "spec.R"]   # writes {"beta": ..., "se": ..., "n": ...} to $RUN_DIR/result.json
```

## How a type is chosen

At `/spawn-project` (**latest binding**): the agent reads the approved proposal + the type cards,
recommends a `{type, domain}`, and the **PI confirms it** (it shapes the whole project — a
Gate-1-adjacent decision; under a signed `/autopilot` campaign, within its delegation bounds). The
choice is recorded in `control.yaml` `project_type:` and the card is dropped into the project root.
`ml` is the default and behaves exactly as before, so existing projects are unaffected.

## Adding a type or domain

Write a new `templates/project-types/<type>/TYPE.md` (a PI-owned act) or
`templates/domain-profiles/<domain>.md` — no engine change. The card states the contract; the
agent fills in the specifics. See the registry READMEs in those directories.
