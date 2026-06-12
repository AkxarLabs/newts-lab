# Tools

Mechanical helpers — small, stdlib+pyyaml-only scripts. Hub tools run via uv's ephemeral env (nothing to install); project helpers ship inside every spawned project.

## Hub tools (`tools/`)

### `audit_claims.py` — verify a paper's numbers against artifacts

```bash
uv run --with pyyaml python tools/audit_claims.py papers/<slug> [--rel-tol 1e-3] [--check-commits]
```

For every claim in the paper's `claims.yaml`, each number must be found in the referenced run artifacts (resolved via `lab.projects_root`):

| Status | Meaning | Exit |
|---|---|---|
| `PASS` | number found directly in an artifact (tolerance = half-ULP of printed precision) | 0 if all pass |
| `PASS-derived` | matches the mean/std of a metric across the claim's artifact list (the "mean over N seeds" case) | 0 |
| `MANUAL` | no match but a derivation is stated — a human must verify; never silently passed | 2 |
| `FAIL` | artifact missing or no match (closest value reported) | 1 |

`/review-paper` Part A runs this and **blocks** the qualitative review on any FAIL or unresolved MANUAL. This is the mechanical teeth behind "every number traces to an artifact."

### `check_lab.py` — lab state lint

```bash
uv run --with pyyaml python tools/check_lab.py [--stale-days N] [--strict]
```

Checks registry↔IDEA.md state agreement, orphan idea/project/paper dirs (projects scanned at `lab.projects_root`; transient `-wt-` worktrees ignored), and stale rows. Exit 1 on real inconsistencies. `/lab-status` runs it every session.

### `show_config.py` — 3-layer config with provenance

```bash
uv run --with pyyaml python tools/show_config.py [<project-path> [exp-NNN.yaml]]
```

Prints the lab layer, the project's control.yaml, the effective skill values (control-first, lab fallback), and — given an experiment — the fully resolved run config with the layer that set each key. Backs `/configure`. See [Configuration](configuration.md).

## Project helpers (`scripts/` in every project)

### `run.py` — the single entry point, with a real watchdog

```bash
uv run python scripts/run.py --config configs/experiments/exp-004.yaml [--seed N] [-o key=value ...]
```

Loads the layered config, seeds everything, creates `runs/<run_id>/` (resolved config + git SHA + seed + metrics), appends to `registry.jsonl`. **`budget.max_minutes` is enforced**: a daemon watchdog records the breach (`meta.budget.breached`, `status: timeout`, `error.txt`) and hard-exits 2. Budgets are facts, not suggestions.

### `sweep.py` — multi-seed / grid launcher

```bash
uv run python scripts/sweep.py --config <exp.yaml> --seeds 0,1,2 [--grid k=v1,v2 ...] [--parallel N]
```

One `run.py` subprocess per (combo × seed) with an outer kill-timeout as defense in depth behind the watchdog; ends with a mean ± std markdown table per combo, pasteable into the ledger. This is how the multi-seed rule (`experiment.multi_seed_n`) gets satisfied in one command.

### `compare.py` — query the run record

```bash
uv run python scripts/compare.py best --metric val_loss --minimize
uv run python scripts/compare.py seeds --metric val_loss
uv run python scripts/compare.py experiments exp-003 exp-004 --metric val_loss
uv run python scripts/compare.py list --last 20
```

Reads only `runs/registry.jsonl`; markdown output with seed-aggregated mean ± std and deltas.

### `status.py` — zero-token run monitor

```bash
uv run python scripts/status.py [<run_id>] [--log-interval 60]
```

One line: `alive | stalled | done | failed | timeout · elapsed/budget · last metric`. The **only** check `/research-loop` makes while a run is in flight — liveness from `meta.json` + `metrics.jsonl` mtime, no log dumps, no judgment about partial curves. Exit 3 on `stalled` (two in a row → treat the run as failed).

## Design note

There is deliberately **no orchestrator binary and no pip package**. The tools are boring on purpose: each one reads files a human can read, prints markdown a human can paste, and exits with a code a script can branch on. The agent's judgment plus these deterministic checks is the architecture.
