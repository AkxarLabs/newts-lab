---
name: make-figures
description: Generate the paper's figures and tables from run artifacts — aggregator scripts using the project's figures library, then a multimodal self-review pass. Argument; the idea slug. Called standalone or from /write-paper.
---

# Make Figures

All visual/tabular evidence for `studies/<slug>/paper/`, generated mechanically from
`runs/` artifacts in the project repo. The figure library
(`src/project_pkg/figures.py`) carries the style, so scripts stay tiny and figures
are consistent. Add `matplotlib` to the project's pyproject if absent. (For a non-`ml`
project the artifacts may be regression tables / sim summaries — the *artifact-not-hand-made*
rule still binds; `theory` figures are illustrative, where the project's `TYPE.md` relaxes it.)

This file is the procedure's **contract**: the evidence rules, provenance, registration and syncing
always bind. *Which* figures to make, how to design them and how to review them is the stage's
**method**, which step 0 loads (the default `METHOD.md` beside this file, or the PI's replacement, plus
the PI's own instructions for this stage).

## 0. Load this stage's brief

`uv run --with pyyaml python tools/workflow.py brief make-figures --study <slug>`. Skip this if a
`NEWTS STAGE BRIEF /make-figures` block is already in your context. Follow its method and instructions
within this contract.

## 1. Inventory

From the analysis file and (if started) `claims.yaml`, list the figures and tables the paper needs as the
method describes. Each entry = the claim it supports + the run ids that evidence it.

## 2. One script per figure/table (the aggregator pattern)

In the project repo's `scripts/figures/` (`<projects_root>/<slug>/scripts/figures/`, path in the
registry row), one script per artifact (`fig_main_result.py`, `tab_ablations.py`):

- **Inputs only from artifacts**: `figures.load_registry()` / `figures.metric_curve()`
  / `runs/<id>/metrics.json`. Hard-coding a number in a figure script is fabrication.
- **Multi-seed rules**: any headline comparison plots/tabulates `figures.seed_stats()`
  mean with a band/± — and the caption MUST state the band's semantics
  ("mean ± std over n=3 seeds"). Single-seed curves are labeled as such.
- **Tables**: cells formatted by `figures.format_measurement()` (sig-fig discipline),
  laid out by `figures.emit_table()` (booktabs, no vertical rules), written as `.tex`
  files that the paper `\input`s — **numbers never pass through prose generation**.
- Design per the method.
- `figures.save_fig(..., consumed_runs=[...])` so every artifact prints its provenance
  for `claims.yaml`.

**Register every emitted artifact in `claims.yaml` now** (create `studies/<slug>/paper/` from
`templates/paper/` first if it doesn't exist — running standalone before `/write-paper` is
fine): one entry per table/figure with its claim, the numbers it shows, its location (table
label / figure file), the run ids from `consumed_runs`, and the derivation. This makes
*tabular* results auditable — a table cell never echoed in prose would otherwise escape
`tools/audit_claims.py` entirely.

Run every script; commit the scripts in the project repo; then sync the outputs into the hub:
`uv run --with pyyaml python tools/sync_figures.py <slug>` — it copies `figures/*.{pdf,tex,png}`
into `studies/<slug>/paper/figures/` and records a manifest (sha256 + project commit) so a later
`tools/sync_figures.py <slug> --check` catches a stale (project regenerated) or hand-edited hub
figure. Never hand-copy figures.

## 3. Self-review

Review every generated figure as the method describes; a fix never changes the data. Record the review
(one line per figure, issues fixed) — `/write-paper` and the critique ensemble will re-check against the
final PDF.
