# Writing the paper: the method

How this lab drafts a paper by default. The PI can add to it or replace it (dashboard → Compose). The
contract (SKILL.md) fixes the evidence and citation rules, the audits after every round, the
bibliography verification and the hand-off; this file is the craft.

Why this ordering: a whole-paper single pass degrades the Method section, numbers passing through prose
get transcribed wrong, and Related Work written early gets invented.

## The drafting order

1. **Method first**, because it degrades when written late. Build it from `decisions.md` and the
   project's actual code.
2. **Outline the whole paper**: for each section, the points to make and the figure, table or claim that
   supports each. The contributions are numbered claims, each with its evidence.
3. **Experimental Setup → Results → Ablations.** These sections narrate the tables and figures that
   already exist.
4. **Related Work last.** It is the most hallucination-prone section. Position the paper against the
   closest works by what they *actually showed*.
5. **Introduction** (contributions first, each pointing at its claim), **Limitations**, then the
   **Abstract**.
   - Include the analysis's interpretation risks in the Limitations: honest limitations score better
     than their absence.

## Interpretation discipline

Interpretive statements ("this suggests X because Y") are markedly more error-prone than data statements
in audited AI-written papers. Keep them few, and make each one earn its place.

## Reflection rounds

- **Stop early** when a round changes nothing substantive. Quality regresses after about 3 rounds.
- **Trim over-length gradually**: one pass of tightening per round, never a single slash-cut.
- **Read the PDF** (you can see it):
  - figures render and are legible;
  - tables are aligned;
  - there are no orphaned floats;
  - the sections flow.

## Optional: shape the narrative with the PI first

An author interview (`/discuss paper <slug>`) settles:
- the single headline claim;
- the 2–3 load-bearing results;
- the positioning against the closest work;
- the weakest result, and why.

Its session doc seeds the outline and the contributions. Skip this in autonomous runs.
