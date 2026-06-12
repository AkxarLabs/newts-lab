---
name: write-paper
description: Draft the LaTeX paper in papers/<slug>/ from project artifacts, with every number traced via claims.yaml. Argument; the idea slug.
---

# Write Paper

Input: idea in state `writing` with a completed analysis. Output: `papers/<slug>/` with compiling LaTeX and a complete claims.yaml.

## Procedure

1. Create `papers/<slug>/` from `templates/paper/` (main.tex, references.bib, claims.yaml, `figures/`, `reviews/`).
2. **Figures/tables first.** Write/extend scripts in `projects/<slug>/scripts/figures/` that generate every figure and table from `runs/` artifacts; commit them in the project; copy outputs to `papers/<slug>/figures/`. No hand-made figures, no hand-typed result numbers — if a table is text, it's generated text pasted whole.
3. **Claims ledger as you write, not after.** Every quantitative claim gets a `claims.yaml` entry (claim, numbers, paper location, run ids, artifact paths, derivation) at the moment it enters the text. Annotate the LaTeX with `% C00N` comments at each number.
4. **Write** in this order: Experimental Setup (must match the frozen proposal — any deviation is disclosed), Results, Ablations, Method, Related Work, Introduction, Limitations, Abstract. Setup-and-results-first keeps the narrative honest to what was actually run.
5. **Citations**: only papers with notes in `ideas/<slug>/lit-review.md`; verify each bib entry against the source. A paper you haven't noted, you don't cite — add it to the lit review first if needed.
6. **Limitations section is real**: include the analysis's interpretation risks and scope limits. Honest limitations are a review criterion, not decoration.
7. Compile (`latexmk -pdf main.tex`), fix until clean, visually inspect every figure and table in the PDF (readable axes, sane layout).
8. Update registry (state → `internal-review`, next action "/review-paper") + notebook. Report: PDF path, claim count, anything you were unable to support with artifacts (which must therefore not be in the text).
