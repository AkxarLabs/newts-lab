# Collaborative sessions — `/discuss` & grilling

Two related capabilities let a human and the agent **think together**, structured as a
one-question-at-a-time interview:

- **`/discuss`** — the lab's research-collaboration session: set a direction, sharpen a target,
  scope approaches, or frame a paper *with* the PI, with the agent researching the questions live.
- **`grill-with-docs`** (+ `grilling`, `domain-modeling`) — vendored general **engineering**
  grilling skills (MIT, from [mattpocock/skills](https://github.com/mattpocock/skills)) for
  sharpening a *design/refactor* and recording a glossary + ADRs as you go.

Both reuse the same engine — the **`grilling`** loop: *ask one focused question at a time, each
with your recommended answer, wait for the human, walk the design tree.* The difference is what
they produce.

## `/discuss <purpose> [target]`

An **optional** pre-step that produces a *session doc* and seeds the next skill — the autonomous
pipeline still runs without it; a session just makes the entry point better-informed. It crosses
**no PI gate** (framing only). Skip it in unattended `/autopilot` runs (no human to grill).

What makes it more than a plain interview: **the agent researches your questions live.** When an
answer hinges on a literature or empirical fact ("is this already saturated?", "what's the SOTA
baseline?"), it runs a logged web / arXiv / Semantic-Scholar search (`tools/s2.py search`, capped
by `discuss.max_research_minutes`) and surfaces what it *actually shows* in the next question —
never asserting an unlogged claim (the same discipline as `/lit-review`).

| `<purpose>` | Run before | Pre/per-slug | Session doc → seeds |
|---|---|---|---|
| `direction` | `/ideate` | pre-slug | `lab/ideation/…` → `OPEN-QUESTIONS.md` + a direction doc Phase 0 reads |
| `target` | `/compete` | either | the task / metric / scoring / rules `/compete` transcribes into `TARGET.md` |
| `scope` | `/scope` | per-slug | `studies/<slug>/sessions/…` → a starter decision list |
| `in-project` | `/ideate --in-project` | per-slug | candidate approaches **held to the frozen set** |
| `paper` | `/write-paper` | per-slug | the headline claim, load-bearing results, positioning, outline |

Pre-slug docs live in `lab/ideation/` (alongside the `/ideate` worksheets); per-slug docs live in
`studies/<slug>/sessions/`. The session-doc shape (Frame · Q&A log · Research log ·
Outcomes · Routed-to) is scaffolded from `templates/idea/session.md`.

Conduct: one focused question at a time (conversational, or `AskUserQuestion` when the answer has
discrete options), researching between turns, until the tree is walked or you call it.

## `grill-with-docs` (engineering design)

Available in the hub **and copied into every spawned project** (so it works standalone, for Claude
or Codex). Use it to stress-test a *plan or design* before building — a refactor, a new module, the
lab's own tooling. It composes `grilling` with `domain-modeling`, which records:

- a **glossary** at `CONTEXT.md` (repo root) — the project's ubiquitous language, and
- **ADRs** in `adr/` — short architectural-decision records, created lazily.

> **Adaptation:** upstream writes ADRs to `docs/adr/`. In this repo `docs/` is the rendered
> documentation site (built `--strict`), so ADRs go to a top-level `adr/` instead — the only change
> from upstream (recorded in the skill's `NOTICE`). These *engineering* ADRs are deliberately
> separate from the lab's *research* design records (`studies/<slug>/decisions.md`) and its
> knowledge base (`lab/knowledge/`).

## Why a structured interview

A one-question-at-a-time loop with a recommended answer beats a wall of questions: it walks
dependencies in order, lets the human correct course early, and (for `/discuss`) lets the agent go
research a point before moving on. It is the human-in-the-loop counterpart to the lab's autonomous
machinery — the same procedures, the same gates, just a better-informed start.
