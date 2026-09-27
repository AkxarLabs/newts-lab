---
name: write-paper
description: Draft the LaTeX paper in studies/<slug>/paper/ from project artifacts — evidence-first ordering, mechanical citation resolution, verifier-gated reflection rounds with claims re-audit. Argument; the idea slug.
---

# Write Paper

Input: idea in state `writing` with a completed analysis. Output: `studies/<slug>/paper/`
with compiling LaTeX, complete `claims.yaml`, verified bibliography. Knobs:
`writing.*` in `lab/config.yaml`.

This file is the procedure's **contract**: the evidence and citation rules, the audits, the bibliography
verification and the hand-off always bind. *How* to draft (the section order, the narrative, the craft of
the reflection rounds) is the stage's **method**, which step 0 loads (the default `METHOD.md` beside this
file, or the PI's replacement, plus the PI's own instructions for this stage).

## 0. Load this stage's brief

`uv run --with pyyaml python tools/workflow.py brief write-paper --study <slug>`. Skip this if a
`NEWTS STAGE BRIEF /write-paper` block is already in your context. Follow its method and instructions
within this contract.

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
   `studies/<slug>/lit-review.md` via `tools/s2.py bibtex <id> --append references.bib` —
   mechanical BibTeX appended straight into the bib (dedup'd) with the `cite-key` printed
   back; the resolver falls back **keylessly** S2 → doi.org → Crossref → OpenAlex, so it
   works without any API key. **Never hand-type a BibTeX entry.** Sparse bibliographies tell
   of AI-written papers; the lit review should yield 20+ candidates.

## 2. Draft

Draft in the order and style the method describes. Whatever the method, these rules hold:

- **Method** is precise enough to reimplement, and matches the project's actual code.
- **Experimental Setup** matches the frozen proposal; deviations are disclosed.
- **Results / Ablations** assert nothing the artifacts don't show.
- **Citations as placeholders while drafting**: where a source is needed, write
  `[cite: short description]` inline; afterwards resolve each mechanically —
  lit-review note → `s2.py bibtex <id> --append references.bib` → `\cite{<returned cite-key>}`.
  If the note has no usable id, or the resolver can't find the paper, the fallback is
  **agentic**: web-search the title for its **DOI**, then
  `s2.py bibtex DOI:<doi> --append references.bib` (still mechanical — you supply the DOI,
  the script fills the entry and returns the key). Need a source not in the lit review? Add
  it to the lit review (with a note) first, or cut the sentence.
- **Related Work** comes from lit-review notes only.
- **Interpretation**: every discussion claim either points at evidence or is explicitly hedged as
  conjecture.
- An optional `/discuss paper <slug>` author interview (framing only) adds no result and crosses no gate.

## 3. Verifier-gated reflection (max `writing.max_reflection_rounds`)

Run reflection rounds as the method describes. Each round, in order:

1. **Mechanical checks**: every `\cite` key exists in references.bib; every
   `\includegraphics` file exists; no placeholder text; compile
   (`latexmk -pdf main.tex`) + `chktex -q -n2 -n24 -n13 -n1`; page count vs
   `writing.page_limit`. **No LaTeX toolchain on this machine?** Record
   it, run every non-compile check, and flag the paper as *not-compiled* — Gate 3 cannot
   be presented without a PDF, so this becomes a queued PI note, not a silent skip.
2. **Figures + claims re-audit**: `tools/sync_figures.py <slug> --check` (hub figures still
   match their project sources — a regenerated-but-unsynced or hand-edited figure fails), then
   `tools/audit_claims.py studies/<slug>/paper --scan-novelty --rel-tol <critique.claim_rel_tol>` (completeness scan —
   every numeral in Results/Ablations/Abstract carries a `% CNNN` annotation — plus the per-claim artifact check,
   plus a **novelty WARN**: any priority/superiority claim — SOTA / "first to" / "outperforms all" / unprecedented —
   with no `\cite` or `% Cnnn/Nnnn` backing gets cited against the closest prior work, a `% Nnnn` lit-review
   pointer, or softened *now* — it hard-blocks at `/review-paper` + `/finalize`)
   — after EVERY round, not just at the end. Revision is when fabrication happens: phantom
   experiments hide in ablation/analysis subsections. Any number the audit can't trace gets
   deleted, not defended. Also run the three paper-integrity audits as a **WARN** here (they
   hard-block later at `/review-paper` + `/finalize`, so surface the gaps while drafting):
   `tools/audit_multiseed.py`, `tools/audit_ablation_coverage.py`, `tools/audit_eval_discipline.py`
   (each on `studies/<slug>/paper`) — a headline result thin on seeds, a dropped ablation, or a
   validation-selected number gets fixed now, not at the gate. Mark load-bearing claims
   `headline: true` and add `split: test`/`multi_seed_waiver:` to `claims.yaml` as needed.
3. **Read the PDF** per the method.

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
Emit `uv run python tools/lab_bus.py emit paper_compiled --idea <slug> --detail "<pages>pp, <claims> claims"`
(drives the dashboard's writing-phase rendering).
Report: PDF path, page count, claim count, citation-verification summary, and anything
you could not support with artifacts (which is therefore not in the text).
