---
name: make-figures
description: Generate the paper's figures and tables from run artifacts — aggregator scripts using the project's figures library, then a multimodal self-review pass. Argument; the idea slug. Called standalone or from /write-paper.
---

# Make Figures

All visual/tabular evidence for `papers/<slug>/`, generated mechanically from
`runs/` artifacts in the project repo. The figure library
(`src/project_pkg/figures.py`) carries the style, so scripts stay tiny and figures
are consistent by construction. Add `matplotlib` to the project's pyproject if absent.

## 1. Inventory

From the analysis file and (if started) `claims.yaml`: list every figure and table the
paper needs — each entry = the claim it supports + the run ids that evidence it.
A figure with no claim is decoration; cut it now. Typical set: one overview/main-result
figure, one training-curve or scaling figure, the ablation table, the comparison table.

## 2. One script per figure/table (the aggregator pattern)

In `projects/.../scripts/figures/`, one script per artifact (`fig_main_result.py`,
`tab_ablations.py`):

- **Inputs only from artifacts**: `figures.load_registry()` / `figures.metric_curve()`
  / `runs/<id>/metrics.json`. Hard-coding a number in a figure script is fabrication.
- **Multi-seed rules**: any headline comparison plots/tabulates `figures.seed_stats()`
  mean with a band/± — and the caption MUST state the band's semantics
  ("mean ± std over n=3 seeds"). Single-seed curves are labeled as such.
- **Tables**: cells formatted by `figures.format_measurement()` (sig-fig discipline),
  laid out by `figures.emit_table()` (booktabs, no vertical rules), written as `.tex`
  files that the paper `\input`s — **numbers never pass through prose generation**
  (this single rule eliminated numerical transcription errors in prior systems).
- ≤3 panels per figure; ≤7 series per panel (Okabe-Ito palette limit); vary
  linestyle/marker as well as color.
- `figures.save_fig(..., consumed_runs=[...])` so every artifact prints its provenance
  for `claims.yaml`.

Run every script; commit scripts in the project repo; copy outputs (`.pdf`, `.tex`) to
`papers/<slug>/figures/`.

## 3. Self-review (multimodal — you can see)

Read each generated `.png` and check, per figure:

1. **Trend supports the claim** it's attached to — if the picture doesn't show what the
   text will say, fix the text's expectation or the figure choice, never the data.
2. **Legible at print size**: the PNG renders the figure at final width — if you have
   to squint at tick labels, the reader can't read them at all.
3. **Complete**: legend present, axes labeled with units, error-band semantics in the
   caption draft.
4. **Informative**: a panel where all series overlap into one line, or all bars are
   equal, earns its space only if "no difference" IS the finding — say so in the
   caption or cut it.
5. **Consistent** with the other figures (same fonts/palette — automatic if every
   script used the library; investigate any visible drift).

Record the review (one line per figure, issues fixed) — `/write-paper` and the
critique ensemble will re-check against the final PDF.
