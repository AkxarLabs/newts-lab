# Figures: the method

How this lab designs and reviews figures by default. The PI can add to it or replace it (dashboard →
Workflow). The contract (SKILL.md) fixes the evidence rules: artifact inputs only, multi-seed bands, the
table pipeline, provenance, registration and syncing. This file is design and taste.

## Choosing the figures

- List every figure and table the paper needs. Each entry is the claim it supports plus the run ids that
  back it.
- A figure with no claim is decoration; cut it now.
- A typical set:
  - one overview or main-result figure;
  - one training-curve or scaling figure;
  - the ablation table;
  - the comparison table.

## Design

- At most 3 panels per figure and at most 7 series per panel (the Okabe-Ito palette limit).
- Vary linestyle and marker as well as colour.
- Keep each script tiny. The project's figure library carries the style, so figures stay consistent.

## Self-review (you can see: read each generated PNG)

1. **The trend supports the claim** it's attached to. If the picture doesn't show what the text will
   say, fix the text's expectation or the figure choice, never the data.
2. **Legible at print size.** The PNG renders at final width. If you have to squint at the tick labels,
   the reader can't read them.
3. **Complete**: a legend, axes labelled with units, and the error-band semantics in the caption draft.
4. **Informative.** A panel where all series overlap into one line, or all bars are equal, earns its
   space only if "no difference" is the finding. Say so in the caption, or cut it.
5. **Consistent** with the other figures: the same fonts and palette. This is automatic if every script
   used the library; investigate any visible drift.
