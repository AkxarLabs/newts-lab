---
name: adopt
description: Enter the lifecycle anywhere — scaffold the prerequisite files for an idea, design, or existing code/results repo the PI already has, register it, and route to the right next procedure. The "I don't need the whole pipeline" entry point.
---

# Adopt Existing Work

Not every idea starts at `/ideate`. The PI may arrive with an idea, a known
literature, a settled design, or a half-finished codebase. This skill scaffolds
exactly the prerequisites the entry state needs, records what was skipped, and
routes onward — so any *part* of the workflow is usable alone.

## 1. Short interview — establish the entry point

Ask what exists (don't make the PI pick a state name; infer it):
- Just an idea / hypothesis? → enter at **`triaged`** (skip ideation).
- Also knows the related literature? → enter at **`scoping`** (PI-waived lit review).
- Design already decided (datasets, baselines, metric)? → enter at proposal prep.
- Existing code repo, possibly with results? → **register it as the project** (below).
- A draft paper needing the review machinery only? → enter at `internal-review`
  (papers/<slug>/ + claims.yaml required first — see integrity rules).

## 2. Scaffold the prerequisites

For every entry point: create `ideas/<slug>/IDEA.md` from `templates/idea/` carrying
the PI's text verbatim (their words are the hypothesis source), add the registry row,
and log the entry in the notebook. Then per entry point:

| Entering at | Also create | Then route to |
|---|---|---|
| `triaged` | — | `/lit-review <slug>` |
| `scoping` | `lit-review.md` stub: what the PI asserts about the literature, each item marked **PI-waived** (not machine-verified); novelty verdict = "PI-asserted" | `/scope <slug>` |
| proposal prep | `decisions.md` from the interview — one ADR row per already-made decision, rationale from the PI; genuinely open ones stay OPEN | `/propose <slug>` |
| existing repo | see "Adopting a repo" | `/experiment` or `/analyze` |
| `internal-review` | `papers/<slug>/` with the draft + a real `claims.yaml` (every number → artifact) | `/review-paper <slug>` |

**Adopting a repo** (registering external code as the project):
1. Registry row's Project column = its path (it may live anywhere; `lab.projects_root`
   is only the default for *spawned* projects).
2. Retrofit the project contract — copy from `templates/project/` whatever is missing:
   `control.yaml` (fill budgets with the PI), `CLAUDE.md` + `AGENTS.md` (substitute
   placeholders), `PLAN.md` (write it WITH the PI: frozen eval, kill criteria, what's
   already done vs planned), `runs/registry.jsonl` + `scripts/` if absent. Don't
   restructure their code — the contract wraps it; runs just need to land in
   `runs/<run_id>/` with a registry line (adapt `scripts/run.py` to call their
   entry point).
3. State: `active` if experiments remain, `analysis` if they claim results are in.
4. `uv run --with pyyaml python scripts/check_project.py` must exit 0 before routing on.

## 3. Integrity rules (what adoption may NOT skip)

- **Skipped stages are recorded, not hidden.** Each one gets a line in IDEA.md's state
  log: `<stage>: PI-waived <date>` — so reviewers and future sessions know what was
  never machine-verified. A PI-waived lit review also means `/write-paper`'s Related
  Work will need real `/lit-review`-style verified notes before citing — budget for it.
- **Hard rule 1 is not waivable.** Pre-existing numbers without run artifacts cannot
  enter analyses or papers. Offer the PI the honest menu: re-run them under the
  contract (they become planned reproduction rows in PLAN.md), or drop them.
- Gates are not waivable either: an adopted idea entering past Gate 1 needs the PI's
  approval recorded in IDEA.md at adoption time (the interview *is* that conversation
  — write it down); Gate 2/3 apply unchanged.
- Adoption never overwrites existing files in an adopted repo; additions only, each
  listed in the report.

## 4. Report

State entered, files created, what was PI-waived, what reproduction work (if any) was
queued, and the exact next command.
