---
name: write-paper
description: Draft the LaTeX paper in studies/<slug>/paper/ from project artifacts — evidence-first ordering, mechanical citation resolution, verifier-gated reflection rounds with claims re-audit. Argument; the idea slug.
---

# Write Paper

Input: idea in state `writing` with a completed analysis. Output: `studies/<slug>/paper/`
with compiling LaTeX, complete `claims.yaml`, verified bibliography. Knobs:
`writing.*` in `lab/config.yaml`.

The ordering below is evidence-first: whole-paper single passes degrade the Method section,
numbers passing through prose get transcribed wrong, and Related Work written early gets invented.

## 1. Evidence before words

1. Create `studies/<slug>/paper/` from `templates/paper/`. **Select the venue** from the resolved
   `writing.venue` (project `control.yaml` overrides `lab/config.yaml`): for a non-`generic`
   venue, copy the **entire** `templates/paper/venues/<venue>/` directory into `studies/<slug>/paper/`
   — the official `.sty`/`.bst` are vendored there, so it compiles offline with no fetch. For
   `generic`, use the venue-agnostic `templates/paper/main.tex` (`\documentclass{article}`).
   Only if the deadline targets a **newer cycle** than the vendored version, refresh the style
   file per `templates/paper/venues/README.md` (and if offline, keep the vendored one and queue
   a finalize note — **never leave a non-compiling preamble**). Set `page_limit` from
   `writing.page_limit` (the venue's typical limit is in that README).
2. **Figures and tables first**: run `/make-figures <slug>`. Result tables are `.tex`
   files the paper `\input`s — no result numeral is ever typed into prose.
   **Every quantitative claim gets a `claims.yaml` entry — table cell or sentence**
   (claim, numbers, location, run ids, artifacts, derivation). `/make-figures` registers
   the table/figure numbers as it emits them; you add the prose-only ones (abstract,
   contributions) as you write them, each annotated `% C00N` in the LaTeX. A number with
   no entry is invisible to the blocking audit — so it must not exist.
3. **Seed the bibliography**: pull the load-bearing entries from
   `studies/<slug>/lit-review.md` via `tools/s2.py bibtex <id>` (mechanical BibTeX — no
   hand-typed entries). Sparse bibliographies tell of AI-written papers; the lit review
   should yield 20+ candidates.

## 2. Draft — in this order

*Optional author-interrogation first:* `/discuss paper <slug>` shapes the narrative with the PI —
the single headline claim, 2–3 load-bearing results, positioning vs the closest work, the weakest
result and why. Its session doc in `studies/<slug>/sessions/` seeds the outline (step 2) and the
contributions. Framing only; adds no result, crosses no gate. Skip in autonomous runs.

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
   are markedly more error-prone than data statements in audited AI-written papers. Every
   discussion claim either points at evidence or is explicitly hedged as conjecture.

## 3. Verifier-gated reflection (max `writing.max_reflection_rounds`)

Each round, in order — and stop early when a round changes nothing substantive
(quality regresses past ~3 rounds):

1. **Mechanical checks**: every `\cite` key exists in references.bib; every
   `\includegraphics` file exists; no placeholder text; compile
   (`latexmk -pdf main.tex`) + `chktex -q -n2 -n24 -n13 -n1`; page count vs
   `writing.page_limit` — over-length is trimmed **gradually** (one pass of tightening
   per round, never a single slash-cut). **No LaTeX toolchain on this machine?** Record
   it, run every non-compile check, and flag the paper as *not-compiled* — Gate 3 cannot
   be presented without a PDF, so this becomes a queued PI note, not a silent skip.
2. **Figures + claims re-audit**: `tools/sync_figures.py <slug> --check` (hub figures still
   match their project sources — a regenerated-but-unsynced or hand-edited figure fails), then
   `tools/audit_claims.py studies/<slug>/paper` (completeness scan — every numeral in
   Results/Ablations/Abstract carries a `% CNNN` annotation — plus the per-claim artifact check)
   — after EVERY round, not just at the end. Revision is when fabrication happens: phantom
   experiments hide in ablation/analysis subsections. Any number the audit can't trace gets
   deleted, not defended.
3. **Read the PDF** (you can see it): figures render and are legible, tables aligned,
   no orphaned floats, section flow reads.

## 4. Bibliography verification (blocking)

`tools/s2.py verify studies/<slug>/paper/references.bib --threshold <writing.citation_match_threshold>`
— every entry checked against the real record (title match ≥ threshold, year, retraction
via OpenAlex). **Any nonzero exit blocks** — NOT-FOUND, RETRACTED, *and* MISMATCH
(below-threshold title or wrong year — the near-miss-fabrication case) are re-resolved via
`s2.py bibtex` against the lit-review note, or removed, before review. Free-generated citations
are fabricated at ~18% base rate, which is why this is mechanical and blocking.

## 5. Revision entry (cycles after the first review)

When entering from a review cycle, the worklist is `reviews/response-N.md` — **ACCEPT
items only**. REBUT items change nothing. NEEDS-EXPERIMENT items are written up only once
their experiments have actually run (artifacts exist; claims.yaml entries first). Then the
full reflection gate (§3) runs again — the claims re-audit each round exists precisely
because revision is when fabrication happens.

## 6. Hand off

Update registry (state → `internal-review`, next action "/review-paper") + notebook.
Report: PDF path, page count, claim count, citation-verification summary, and anything
you could not support with artifacts (which is therefore not in the text).
