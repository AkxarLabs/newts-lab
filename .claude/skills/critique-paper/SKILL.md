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
  `papers/<slug>/reviews/critique-<date>/`.
- **External mode** (arXiv id / URL / PDF path): fetch the paper and save it to
  `ideas/<slug>/critiques/sources/<bibkey>.md` (or note the local PDF path). Critique
  output goes to `ideas/<slug>/critiques/<bibkey>.md`. If no idea context, use
  `lab/reviews/<bibkey>/`.

## 2. Spawn the reviewer ensemble (fresh-context invariant)

- Ensemble size: `critique.ensemble_external` lenses (novelty, soundness,
  claims-evidence) for external papers; `critique.ensemble_own_draft` (all five) for
  own drafts.
- Spawn one `fresh-context-reviewer` subagent per lens, **in parallel**. Each prompt
  contains ONLY: the paper file path, the lens name + its definition and the calibration
  block (paste both verbatim from `critique-lenses.md`), and the output file path.
- **HARD RULE: never include your own summary, opinion, or context about the paper in a
  reviewer prompt.** The reviewers' value is that they read cold. (This is the
  fresh-context invariant — same-session review measurably underperforms.)

## 3. Meta-review

Fill `templates/review/meta-review.md` yourself from the reviewers' files:
- Scores aggregate as **median (min–max)** per dimension — never mean.
- Grade every weakness against the **taste rubric** (`critique-lenses.md`): GENERIC and
  MISDIRECTED points are noted but carry no action items; only LOAD-BEARING points
  drive decisions. (`oversight.level: strict`: spawn an `overseer` `critique-taste`
  check per fatal flaw and `support` check per refutation.)
- Collect every `FATAL FLAW:` line into the veto table. **Any unrefuted fatal flaw
  blocks accept**; an override requires a written refutation with specific evidence.
- Synthesize agreements/conflicts; produce numbered action items (own-draft mode).
- Write the meta-review file beside the reviewer files.

## 4. Route by mode

- **Own draft**: report median Overall, decision, fatal flaws, and action items. The
  caller (`/review-paper`) handles routing.
- **External**: distill into the idea's `lit-review.md` paper notes (the critique file
  is the deep record; the note gets the verdict + what it means for our positioning —
  e.g., "claimed SOTA is unsupported at our scale; weaker baseline than it appears").
  Report the verdict and the one most decision-relevant finding to the user.
