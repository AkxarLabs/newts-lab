# Project type: `theory`

Mathematical / theoretical work: proofs, derivations, models on paper (e.g. math-econ theory,
mechanism design, algorithms with guarantees). **The paper lifecycle applies fully; the
experiment *engine* is redefined or N/A — read this card before assuming the ML loop.**

- **An "experiment" is:** a **derivation or proof attempt** — establishing a lemma, checking a
  worked example / numerical sanity case, or finding a counterexample. There is no training run.
- **Runner & traceability (the load-bearing choice — pick one, record it in PLAN.md):**
  - **Machine-checked (preferred):** a proof assistant (Lean / Coq / Isabelle) or a symbolic check
    (SymPy/Mathematica). `runner: shell-command` runs the checker; it writes
    `{"checked": true, ...}` to `$RUN_DIR/result.json` — so **hard rule 1 traceability is preserved
    mechanically** (every claimed result points to a checked artifact).
  - **Human-checked (fallback):** the proof is a document, verified by a human. Hard rule 1 then
    binds at the *statement* level (each theorem → its proof in the repo, version-pinned), and the
    **mechanical audit (`audit_claims.py`) does not apply** — flag this explicitly in PLAN.md and at
    review so the loss of automatic verification is visible, not silent.
- **Staged scale:** special-case / low-dimension → general statement (analogous to SMOKE→FULL).
- **Multi-seed:** **N/A** (deterministic) — set `seeds.multi_seed_n: 1` and report "deterministic".
- **Selection discipline:** worked examples / numerical checks are the analogue of a held-out
  test — don't tune the theorem to the examples you also use to validate it.
- **Output:** a paper (theory venues via the domain profile); figures are illustrative, not
  data-derived, so `/make-figures`'s artifact rule is relaxed (note it).
- **Skills:** `/ideate`, `/lit-review`, `/scope`, `/propose`, `/write-paper`, `/review-paper`,
  `/finalize` apply. `/experiment` and `/improve` apply **only** in the machine-checked mode (as
  proof-attempt / lemma-decomposition); otherwise they are N/A — the work is done in `/write-paper`.
