---
name: critique-paper
description: Adversarial multi-lens critique of any paper — an external paper (arXiv id/URL/PDF path) for lit triage, or one of our own drafts (idea slug). Fresh-context reviewer ensemble + meta-review with minority veto.
---

# Critique Paper

Ensemble sizes, anchors, and cycle caps come from `lab/config.yaml` (`critique.*`).
Lens definitions + the calibration block live in `templates/review/critique-lenses.md`.

## 1. Detect mode & materialize the paper to a file

- **Own-draft mode** (argument is an idea slug with `papers/<slug>/`): the paper file is
  the compiled PDF (preferred) or `papers/<slug>/main.tex`. Reviews go to
  `papers/<slug>/reviews/critique-<date>/`. For a lifecycle paper the canonical entry is
  `/review-paper` (its blocking Part A claims audit runs first); a standalone own-draft
  critique is advisory and never advances state.
- **External mode** (arXiv id / URL / PDF path): download the actual artifact — for an
  arXiv id, the PDF (`https://arxiv.org/pdf/<id>`) to
  `ideas/<slug>/critiques/sources/<bibkey>.pdf`; fall back to saved extracted text
  (`<bibkey>.md`) only when no PDF is obtainable, and note in the critique header that the
  source was extracted text (reviewers must read the paper, not a lossy summary). Reviewer
  files + meta-review go to `ideas/<slug>/critiques/<bibkey>/` (one file per lens); the
  distilled verdict goes to the lit-review note. If no idea context, use
  `lab/reviews/<bibkey>/`.

## 2. Spawn the reviewer ensemble (fresh-context invariant)

- Ensemble size: `critique.ensemble_external` lenses (novelty, soundness,
  claims-evidence) for external papers; `critique.ensemble_own_draft` (all five) for
  own drafts.
- Spawn one `fresh-context-reviewer` subagent per lens, **in parallel**. Each prompt
  contains ONLY: the paper file path, the lens name + its definition and the calibration
  block (paste both from `critique-lenses.md`, **substituting the anchor value with
  `critique.score_anchor_human_mean`** so a re-tuned anchor actually takes effect), and the
  output file path.
- **HARD RULE: never include your own summary, opinion, or context about the paper in a
  reviewer prompt.** The reviewers' value is that they read cold. (This is the
  fresh-context invariant — same-session review measurably underperforms.)

## 3. Meta-review

Fill `templates/review/meta-review.md` yourself from the reviewers' files:
- Scores aggregate as **median (min–max)** per dimension — never mean.
- Grade every weakness against the **taste rubric** (`critique-lenses.md`): GENERIC and
  MISDIRECTED points are noted but carry no action items; only LOAD-BEARING points
  drive decisions.
- Collect every `FATAL FLAW:` line into the veto table. **Any unrefuted fatal flaw
  blocks accept**; an override requires a written refutation with specific evidence.
- **Oversight** (own-draft mode): a fatal-flaw refutation is written by the same session
  that wrote the paper, yet it unlocks accept — so at `oversight.level` ≠ off, spawn an
  `overseer` `support` check on **every refutation that would flip a fatal flaw to
  refuted** (statement = the refutation; evidence = the cited artifact paths). At `strict`,
  additionally grade each fatal flaw itself with an `overseer` `critique-taste` check. An
  overseer-rejected refutation does not override the veto.
- Synthesize agreements/conflicts; produce numbered action items (own-draft mode).
- Write the meta-review file beside the reviewer files.

## 4. Route by mode

- **Own draft**: report median Overall, decision, fatal flaws, and action items. The
  caller (`/review-paper`) handles routing.
- **External**: distill into the idea's `lit-review.md` paper notes (the critique file
  is the deep record; the note gets the verdict + what it means for our positioning —
  e.g., "claimed SOTA is unsupported at our scale; weaker baseline than it appears").
  Report the verdict and the one most decision-relevant finding to the user.
