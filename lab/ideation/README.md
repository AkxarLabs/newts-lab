# Ideation

Pre-slug exploration and collaborative-session docs — work that isn't yet (or may never be)
tied to a committed `studies/<slug>/`.

What lives here:

- **`/discuss` session docs** for pre-slug purposes (`direction`, and pre-slug `target`):
  `<date>-<HHMMSS>-<topic>.md`. (Per-slug `/discuss` sessions live in `studies/<slug>/sessions/`.)
- **`/ideate` worksheets** — the full exploration record of an ideate run (scan queries, candidate
  sketches, every critique, parentage, tournament records): `<date>-<HHMMSS>-ideation.md`, and
  `<date>-<HHMMSS>-<slug>-inproject-ideation.md` for `/ideate --in-project`. Only finalists graduate
  to `studies/<slug>/`; everything else stays here, so a crashed/compacted session is resumable and
  nothing lives only in chat.

**Naming:** `<date>-<HHMMSS>-…` — the `HHMMSS` time component makes same-day reruns collision-free
and keeps files chronologically sortable (no directory scan needed to pick a name).

This is durable lab state (**not** gitignored), distinct from:
- `lab/notebook/` — the dated session journal (Hard rule 11, one entry per working session), and
- `lab/knowledge/` — the promoted, compounding world model (FINDINGS / FAILURES / OPEN-QUESTIONS).

A promising thread that outlives the session is promoted to `OPEN-QUESTIONS.md` (a one-line `Q-NNN`
entry); the full debate stays in the worksheet/session doc here for anyone who wants to reopen it.
