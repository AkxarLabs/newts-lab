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

### `run_slots.py` — cross-project compute coordination

```bash
uv run --with pyyaml python tools/run_slots.py acquire <project> <label>   # exit 1 = denied
uv run --with pyyaml python tools/run_slots.py release <slot-id>
uv run --with pyyaml python tools/run_slots.py status
```

Within a project, the experiment loop controls its own runs; the hub-level risk is two projects (or a loop plus an interactive session) launching training on the same GPU. One slot = one training campaign (a run **or** a sweep — the sweep manages its own internal parallelism); the cap is `compute.max_concurrent_runs`. Slots are files under `lab/.slots/` (atomic create, stale-reclaimed after `compute.stale_slot_minutes`). Hard rule 13: acquire before any PILOT/FULL campaign, release when the ledger entry is written; SMOKE is exempt; subagents never manage slots — the parent does.

### `s2.py` — literature search, BibTeX, citation verification

```bash
uv run --with pyyaml python tools/s2.py search "small LM distillation" [--limit 10] [--year 2023:] [--bulk]
uv run --with pyyaml python tools/s2.py bibtex arXiv:2504.08066
uv run --with pyyaml python tools/s2.py verify papers/<slug>/references.bib [--threshold 0.85]
```

Semantic Scholar Graph API with OpenAlex fallback. `search` gives `/lit-review` replayable, logged queries (title/year/venue/citations/TLDR per hit). `bibtex` returns the canonical entry for a paper id — no hand-typed bibliography. `verify` is the zero-assumption citation audit `/review-paper` runs: every bib entry title-matched against the real record (threshold from `writing.citation_match_threshold`), year-checked, and retraction-checked via OpenAlex `is_retracted`. Free-generated LLM citations are fabricated at ~18% base rate — this check is blocking, not advisory. Optional env keys: `S2_API_KEY` (keyless S2 shares a saturated global pool; backoff built in), `OPENALEX_API_KEY`.

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

### `figures.py` — the paper-grade figure & table library (`src/project_pkg/`)

Not a CLI — the module every `scripts/figures/` script imports, so figure code in projects stays a few lines and all figures are consistent by construction:

- `new_fig(width="single"|"double")` — axes at **final printed width** (3.3 in / 6.9 in), warm-free venue-neutral style: vector PDF, TrueType fonts (`fonttype 42` — Type 3 fails camera-ready checks), 7–8 pt labels, Okabe-Ito colorblind-safe cycle, constrained layout.
- `save_fig(fig, name, consumed_runs=[...])` — PDF + review PNG, printing the run ids consumed (provenance for `claims.yaml`).
- `load_registry()` / `metric_curve(run_id, metric)` / `seed_stats(rows, metric)` — artifact access; headline comparisons must go through `seed_stats`.
- `format_measurement(mean, std, n)` — sig-fig discipline (std to 2 sig figs, mean to match: `71.28 ± 0.39`).
- `emit_table(headers, rows, path)` — booktabs `.tex` files the paper `\input`s, so **result numbers never pass through prose generation** (the single most effective anti-transcription-error mechanism in the surveyed systems).

`/make-figures` orchestrates these per paper; matplotlib is imported lazily (add it to the project's pyproject when plotting starts).

### `status.py` — zero-token run monitor

```bash
uv run python scripts/status.py [<run_id>] [--log-interval 60]
```

One line: `alive | stalled | done | failed | timeout · elapsed/budget · last metric`. The **only** check `/research-loop` makes while a run is in flight — liveness from `meta.json` + `metrics.jsonl` mtime, no log dumps, no judgment about partial curves. Exit 3 on `stalled` (two in a row → treat the run as failed).

## Design note

There is deliberately **no orchestrator binary and no pip package**. The tools are boring on purpose: each one reads files a human can read, prints markdown a human can paste, and exits with a code a script can branch on. The agent's judgment plus these deterministic checks is the architecture.
