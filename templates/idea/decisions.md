# Design Decisions — {{title}}

*Idea: `{{slug}}` · Date: {{date}} · Produced by `/scope`; consumed by `/propose`.
Append-only after Gate 1: reopening a decision is a NEW entry referencing the old one.
A loop in `explore` mode may reopen a **non-headline** decision autonomously when its
`Revisit if:` trigger fires (within the Gate-2 envelope); reopening a `Headline: yes`
decision is the escalation boundary (PI note / campaign-delegation check).*

## Decision index

| ID | Decision | Status | Headline | Choice |
|----|----------|--------|----------|--------|
| D-001 | | settled / OPEN | yes / no | |

---

## D-001: <decision area, e.g. "Dataset & benchmark">

**Question:** <!-- the precise choice being made and why it matters downstream -->

**Options considered:**

| Option | Strongest case (advocate) | Most likely failure modes |
|--------|---------------------------|---------------------------|
| A — | | |
| B — | | |
| C — | | |

**Decision:** <!-- the choice -->

**Rationale:** <!-- why this beats the alternatives, grounded in lit-review.md / IDEA.md -->

**Rejected because:**
- B — <!-- one line per rejected option -->
- C —

**Headline:** <!-- yes = this choice is load-bearing for the central hypothesis the
proposal's novelty rests on (reopening it is the PI-escalation boundary); no = a supporting
decision an explore-mode loop may reopen autonomously when the trigger below fires. -->

**Revisit if:** <!-- the concrete, checkable evidence that would reopen this decision —
write it as something a later session can verify against run artifacts (e.g. "pilot shows
dataset-A val_acc within seed noise of the baseline at exp-003"). This is what an explore
loop's `revisit` operator tests each cycle. -->

---

<!-- OPEN decisions: same format, Status OPEN, plus: -->
<!-- **Settled by:** exp-NNN (the pilot that resolves this) — at most
     scoping.max_open_questions of these may exist at /propose time. -->
