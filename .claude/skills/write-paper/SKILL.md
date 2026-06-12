---
name: write-paper
description: Draft the LaTeX paper in papers/<slug>/ from project artifacts — evidence-first ordering, mechanical citation resolution, verifier-gated reflection rounds with claims re-audit. Argument; the idea slug.
---

# Write Paper

Input: idea in state `writing` with a completed analysis. Output: `papers/<slug>/`
with compiling LaTeX, complete `claims.yaml`, verified bibliography. Knobs:
`writing.*` in `lab/config.yaml`.

The ordering below is evidence-first (ablated in prior systems: whole-paper single
passes degrade the Method section; numbers passing through prose generation get
transcribed wrong; Related Work written early gets invented).

## 1. Evidence before words

1. Create `papers/<slug>/` from `templates/paper/`.
2. **Figures and tables first**: run `/make-figures <slug>`. Result tables are `.tex`
   files the paper `\input`s — no result numeral is ever typed into prose. Any number
   that must appear in a sentence gets its `claims.yaml` entry (claim, numbers,
   location, run ids, artifacts, derivation) at the moment it's written, annotated
   `% C00N` in the LaTeX.
3. **Seed the bibliography**: pull the load-bearing entries from
   `ideas/<slug>/lit-review.md` via `tools/s2.py bibtex <id>` (mechanical BibTeX — no
   hand-typed entries). Sparse, stale bibliographies are a known tell of AI-written
   papers; the lit review should yield 20+ candidates.

## 2. Draft — in this order

1. **Method** (first — it degrades when written late): from `decisions.md` and the
   project's actual code. Precise enough to reimplement.
2. **Outline** the full paper: per section, the points to make and which figure/table/
   claim id supports each. Contributions = numbered claims, each with its evidence.
3. **Experimental Setup** (must match the frozen proposal; deviations disclosed) →
   **Results** → **Ablations** — these sections narrate the already-made tables and
   figures; they assert nothing the artifacts don't show.
4. **Citations as placeholders while drafting**: where a source is needed, write
   `[cite: short description]` inline; afterwards resolve each mechanically —
   lit-review note → `s2.py bibtex` → replace with `\cite{key}`. Need a source not in
   the lit review? Add it to the lit review (with a note) first, or cut the sentence.
5. **Related Work last** (it's the most hallucination-prone section): from lit-review
   notes only, positioning against the closest works by what they *actually showed*.
6. **Introduction** (contributions-first, each pointing at its claim id), **Limitations**
   (include the analysis's interpretation risks — honest limitations score better than
   their absence), **Abstract**.
7. **Interpretation discipline**: interpretive statements ("this suggests X because Y")
   are ~3× more error-prone than data statements in audited AI-written papers. Every
   discussion claim either points at evidence or is explicitly hedged as conjecture.

## 3. Verifier-gated reflection (max `writing.max_reflection_rounds`)

Each round, in order — and stop early when a round changes nothing substantive
(quality regresses past ~3 rounds):

1. **Mechanical checks**: every `\cite` key exists in references.bib; every
   `\includegraphics` file exists; no placeholder text; compile
   (`latexmk -pdf main.tex`) + `chktex -q -n2 -n24 -n13 -n1`; page count vs
   `writing.page_limit` — over-length is trimmed **gradually** (one pass of tightening
   per round, never a single slash-cut).
2. **Claims re-audit**: `tools/audit_claims.py papers/<slug>` — after EVERY round, not
   just at the end. Revision is when fabrication happens: systems that revised against
   reviewer feedback invented supporting ablations, and phantom experiments hide in
   ablation/analysis subsections. Any number the audit can't trace gets deleted, not
   defended.
3. **Read the PDF** (you can see it): figures render and are legible, tables aligned,
   no orphaned floats, section flow reads.

## 4. Bibliography verification (blocking)

`tools/s2.py verify papers/<slug>/references.bib` — every entry checked against the
real record (title match ≥ `writing.citation_match_threshold`, year, retraction via
OpenAlex). NOT-FOUND or RETRACTED entries are fixed or removed before review;
free-generated citations are fabricated at ~18% base rate, which is why this is
mechanical and blocking.

## 5. Revision entry (cycles after the first review)

When entering from a review cycle, the worklist is `reviews/response-N.md` — **ACCEPT
items only**. REBUT items change nothing. NEEDS-EXPERIMENT items may only be written up
once their experiments have actually run (artifacts exist; claims.yaml entries first).
Then the full reflection gate (§3) runs again — the claims re-audit each round exists
precisely because revision is when fabrication happens.

## 6. Hand off

Update registry (state → `internal-review`, next action "/review-paper") + notebook.
Report: PDF path, page count, claim count, citation-verification summary, and anything
you could not support with artifacts (which is therefore not in the text).
