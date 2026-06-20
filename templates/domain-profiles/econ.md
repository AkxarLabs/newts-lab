# Domain profile: `econ` (economics)

Attach on top of a methodology type — usually `empirical` (applied micro/econometrics),
`simulation` (DSGE / structural / ABM), or `theory` (micro theory, mechanism design, math-econ).

- **Venues / citation targets:** *Econometrica*, *American Economic Review (AER)*, *Quarterly
  Journal of Economics (QJE)*, *Journal of Political Economy (JPE)*, *Review of Economic Studies*,
  the *AEJ* series; field journals (*J. Econometrics*, *J. Monetary Economics*, etc.). NBER/SSRN
  working papers for recent work. Note: the lab's vendored LaTeX venues are ML-conference styles —
  for an econ submission, set `writing.venue: generic` and use the target journal's class, or add
  the journal style under `templates/paper/venues/` first.
- **Data sources** (cite the access command + env-var key *names*, never values): FRED
  (macro/financial series), IPUMS (census/CPS microdata), BLS, BEA, World Bank / IMF, OECD,
  Compustat/CRSP (licensed — check access), Penn World Table. Semantic Scholar / OpenAlex (via
  `tools/s2.py`) cover econ literature for `/lit-review`.
- **Conventions (what rigor looks like here):**
  - **Identification first** — name the source of variation and the threats (selection, reverse
    causality, confounds); the design (RCT/DiD/IV/RDD/event-study) is the contribution as much as
    the estimate.
  - **Pre-register the primary specification + outcome** (PLAN.md), then report the held-out
    out-of-sample / placebo / hold-out-period check — this is the `empirical` type's frozen-eval
    rule, and it directly answers the field's specification-search (p-hacking) concern.
  - **Robustness checks = ablations** (alternative specs, subsamples, clustering choices) — each a
    planned PLAN.md row, not an afterthought.
  - **Standard errors:** report and justify the clustering/HAC choice; the multi-seed analogue is
    bootstrap/randomization inference, not random seeds.
- **Typical types:** `empirical` (default for applied work), `simulation` (macro/structural),
  `theory` (proofs/mechanism design — machine-checked if formalized, else human-checked).
