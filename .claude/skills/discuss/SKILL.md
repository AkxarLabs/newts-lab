---
name: discuss
description: Collaborative human↔agent session — a one-question-at-a-time grilling loop where the agent researches your questions live (logged) and records a session doc that seeds the next stage. Usage; /discuss <purpose> [target], purpose ∈ {direction, scope, in-project, target, paper}. Optional pre-step to /ideate, /scope, /compete, /ideate --in-project, /write-paper.
---

# Discuss — collaborative direction-setting & ideation

A structured human↔agent working session. It **reuses the vendored `/grilling` loop**
(`.claude/skills/grilling/SKILL.md` — one focused question at a time, each with your recommended
answer, walking the design tree) and adds the two things research needs: **live, logged research**
of the questions raised, and a **session doc** that seeds the next skill — `grill-with-docs` for
research framing instead of engineering ADRs.

**Optional everywhere.** Every stage it feeds runs fully autonomously without it; a `/discuss`
session only produces a better-informed entry point. Never run it inside an unattended
`/autopilot` campaign (no human to grill) — skip silently there.

## Purposes

| `<purpose>` | Run before | Reads first | Session doc | Seeds (handoff) |
|---|---|---|---|---|
| `direction` *(pre-slug)* | `/ideate` | `lab/knowledge/{OPEN-QUESTIONS,FINDINGS,FAILURES}.md`, `lab/REGISTRY.md` | `lab/ideation/<date>-<HHMMSS>-<topic>.md` | `OPEN-QUESTIONS.md` `Q-NNN` (`source: discuss`) + a direction doc `/ideate` Phase 0 reads |
| `scope` *(per-slug)* | `/scope <slug>` | `studies/<slug>/{IDEA.md,lit-review.md}` | `studies/<slug>/sessions/<date>-scope.md` | a starter decision list for `/scope` |
| `target` *(pre- or per-slug)* | `/compete` | `IDEA.md`/`TARGET.md` if any | per-slug → `studies/<slug>/sessions/<date>-target.md`; else `lab/ideation/<date>-<HHMMSS>-<topic>.md` | the answers `/compete`'s interview transcribes into `TARGET.md` + `control.yaml` `target:` |
| `in-project` *(per-slug)* | `/ideate --in-project <slug>` | project `PLAN.md`, `decisions.md`, `EXPERIMENT_LOG.md` tail, `control.yaml` (across the boundary) | `studies/<slug>/sessions/<date>-in-project.md` | candidate-approach framing, **held to the frozen set** (problem/eval/test/seeds/budgets never moved) |
| `paper` *(per-slug)* | `/write-paper <slug>` | `studies/<slug>/{IDEA.md,lit-review.md}`, project `decisions.md` + `runs/` digest | `studies/<slug>/sessions/<date>-paper.md` | the headline claim, load-bearing results, positioning, and an outline for `/write-paper` §2 |

## 1. Set up the session

1. Parse `<purpose> [target]`. Resolve **pre-slug vs per-slug**: per-slug iff `[target]` names an
   existing `studies/<slug>/` dir. Pre-slug `direction`/`target` → write to `lab/ideation/`;
   everything per-slug → `studies/<slug>/sessions/` (create `sessions/` if absent).
2. Session-doc path: pre-slug → `lab/ideation/<date>-<HHMMSS>-<topic>.md`; per-slug →
   `studies/<slug>/sessions/<date>-<purpose>.md`. Instantiate from `templates/idea/session.md`,
   filling the Frame (purpose, target, goal).
3. Read the purpose's input artifacts (table above) **before asking anything**, so your questions
   are grounded and your recommended answers real.

## 2. The grilling loop + live research

Run the `/grilling` contract (read `.claude/skills/grilling/SKILL.md`), with one research-specific
addition:

- **One focused question at a time**, each carrying *your recommended answer*; wait for the PI
  before the next. Walk the tree, resolving dependencies one by one. Append every question +
  recommendation + the PI's answer to the **Q&A log** table.
- **If a question can be answered by reading the artifacts/codebase, do that instead of asking.**
- **Research on demand (the addition).** When an answer hinges on a literature or empirical fact
  ("is X saturated?", "the SOTA baseline?", "did anyone try Y?"), research it *before* posing the
  next question — `uv run --with pyyaml python tools/s2.py search "..."` (replayable Semantic
  Scholar), web, or arXiv — bounded by `discuss.max_research_minutes` (`lab/config.yaml`). **Log
  every query** to the **Research log** table and surface what it *actually shows* in the next
  question's preamble. Never assert a literature claim you didn't log (the `/lit-review`
  discipline). Fuel for the discussion, not the lit review itself.
- **How to ask:** `AskUserQuestion` when the question has a small set of discrete options (your
  recommended answer becomes the first option); otherwise conversationally. Either way, **one
  question at a time**.
- **Stop** when two consecutive questions add nothing new, or the PI ends the session.

## 3. Record outcomes & seed the next stage

Write the **Outcomes** (decided / open threads) and **Routed to** sections, then seed the handoff
artifact for the purpose:

- `direction` → append the open threads to `lab/knowledge/OPEN-QUESTIONS.md` as `Q-NNN` entries
  (mark `source: discuss`), and leave the direction doc at its `lab/ideation/` path for
  `/ideate`'s Phase 0 to read as its research-scan seed.
- `target` → list the task / done-condition / metric+direction / data / scoring / rules / budgets
  the PI settled, in the shape `/compete`'s interview expects (so it transcribes them into
  `TARGET.md` + `control.yaml` rather than re-asking).
- `scope` → a starter list of the key design decisions surfaced, for `/scope` to deliberate.
- `in-project` → candidate-approach sketches **inside the frozen set**, for `/ideate --in-project`
  to generate from. A direction needing the frozen set moved is out of scope — note it and route
  to a hub `/ideate` or `/propose` re-entry (never seed it as in-bounds).
- `paper` → the headline claim, 2–3 load-bearing results (with run ids), positioning vs the
  closest work, and a section outline, for `/write-paper` §2.

A `/discuss` session **never crosses a PI gate** — it produces framing, not approvals. Surviving
directions still enter the normal pipeline (and its gates) via the skill it hands off to.

## 4. Hand off & write-back

1. Append a dated `lab/notebook/<date>-discuss.md` entry (Hard rule 11 — Context/Did/Decided/Next).
2. Best-effort bus event: `uv run python tools/lab_bus.py emit cycle --detail "discuss: <purpose> → <next-skill>"`.
3. Report to the PI: what was decided, the session-doc path, what was seeded, and the **exact next
   command** (e.g. "run `/ideate <topic>` — it will read `lab/ideation/<file>`").
