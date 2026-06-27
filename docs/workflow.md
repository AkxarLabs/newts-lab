# The workflow

## Lifecycle state machine

Every idea moves through states tracked in `lab/REGISTRY.md` (the single source of truth) and mirrored in its `IDEA.md` frontmatter — `tools/check_lab.py` lints them against each other.

```
seed → triaged → lit-review → scoping → proposal ──[GATE 1]──→ active → analysis
                                                                    ↑       │
                                                                    └───────┤ (more ablations)
                                                                            ▼
                  final ←──[GATE 3]── internal-review ←── writing ←─────────┘
```

`parked` and `killed` are reachable from any state. **Killing early is a feature** — kill criteria are written into every proposal *before* experiments start, and `/research-loop` checks them every cycle.

How fast an idea moves through the machine is up to you: invoke each procedure yourself, run one stage at a time with `/advance` (it stops for your verification after every stage), or delegate the whole walk to `/autopilot` — see [Autonomy & modes](autonomy.md).

| State | Meaning | Exit via |
|---|---|---|
| `seed` | raw idea captured | `/ideate` triage |
| `triaged` | scored + tournament-ranked, worth a lit review | `/lit-review` |
| `lit-review` | literature grounding in progress | novelty verdict |
| `scoping` | design decisions deliberated branch-by-branch (`decisions.md`) | value re-verification |
| `proposal` | full proposal drafted from settled decisions | **PI Gate 1** |
| `active` | project spawned, experiments running | plan complete / kill |
| `analysis` | results interrogated, ablations decided | `/analyze` routing |
| `writing` | paper drafted from artifacts | `/write-paper` done |
| `internal-review` | claims audit + critique ensemble | accept + **PI Gate 3** |
| `final` | closed out, knowledge harvested | — |

## Start anywhere

You don't have to enter at `seed`. `/adopt` interviews you briefly (optionally after a `/discuss direction` session, whose `lab/ideation/` doc it reads so settled framing isn't re-asked), scaffolds exactly the prerequisite files for your starting point, registers the idea, and routes onward:

| You arrive with | Enter at | `/adopt` scaffolds | Next command |
|---|---|---|---|
| an idea / hypothesis | `triaged` | `IDEA.md` (your text verbatim) + registry row | `/lit-review` |
| …and you know the literature | `scoping` | + `lit-review.md` stub, items marked **PI-waived** | `/scope` |
| a settled design | proposal prep | + `decisions.md` from your answers (ADR per decision) | `/propose` |
| an existing code/results repo | `active` / `analysis` | registry row pointing at *your* repo + the project contract retrofitted (`control.yaml`, `CLAUDE.md`/`AGENTS.md`, `PLAN.md`, run tracking) — additions only, your code untouched | `/experiment` / `/analyze` |
| a draft paper | `internal-review` | `studies/<slug>/paper/` + a real `claims.yaml` | `/review-paper` |

Two things adoption never waives: the PI gates, and hard rule 1 — pre-existing numbers without run artifacts can't enter papers (they become planned reproduction experiments, or they're dropped). Skipped stages are recorded as PI-waived in `IDEA.md`, so reviewers know what was never machine-verified.

## The gates in detail

**Gate 1 — proposal approval.** The cheapest, highest-leverage human moment (Agent Laboratory measured +0.6 review points from checkpoints like this). You approve: hypothesis, the strongest-fair baseline, frozen eval protocol, the staged experiment table with promotion criteria written in advance, budgets, and kill criteria. Optionally you pre-authorize a **Gate 2 envelope** here.

**Gate 2 — full-scale launch.** SMOKE and PILOT runs are autonomous; FULL runs need approval — either per-run, or covered by a recorded envelope (`control.yaml → gate2_envelope`, `pi_signed: true`). Runs outside an envelope's scope always need fresh approval. The envelope is what lets overnight loops do full-scale work without you.

**Gate 3 — finalization.** Nothing leaves the lab without you reading it. By this point the paper has survived the mechanical claims audit and the fresh-context critique ensemble.

## The paper-refinement loop (and its safeguards)

Review cycles are where autonomous pipelines corrupt themselves: an LLM reviewer makes a wrong point, the LLM author "fixes" it, and a documented failure mode follows — writers *inventing supporting ablations* in response to feedback, with review scores going up. The loop is therefore built around validation, not obedience:

```
/write-paper → /review-paper ──→ accept + no vetoes ──→ [GATE 3] → /finalize
                    │
                    ├─ author response (every action item, WITH EVIDENCE):
                    │    ACCEPT  → /write-paper works only these
                    │    REBUT   → nothing changes (evidence recorded)
                    │    NEEDS-EXPERIMENT → new PLAN.md rows → state `active`
                    │                       /experiment → /analyze → /write-paper
                    └─ cycle cap (critique.max_review_cycles) → PI escalation
```

Safeguards, layered:

1. **Author-response triage** — feedback is checked against artifacts and lit notes before it changes anything; a rebuttal requires evidence, and so does an acceptance.
2. **New claims require new runs** — a NEEDS-EXPERIMENT point routes the idea back to `active` and through the normal experiment machinery (gates, budgets, ledger). Prose never substitutes for an experiment.
3. **Claims re-audit every revision round** — `audit_claims.py` runs after each reflection pass, not once at the end, plus a phantom-experiment sweep over ablation/analysis subsections in the next review.
4. **Frozen stays frozen** — a reviewer demanding eval/test/budget changes escalates to the PI; it is never an edit.
5. **Stalemate escalation** — an item rebutted twice but re-raised goes to the PI; the loop never relitigates indefinitely.

## Session protocol (interactive)

Every session: orient first (`/lab-status` → registry, latest notebook entry, consistency lint), work the highest-leverage item, and **write back before ending** — a dated notebook entry, registry sync, and any durable insight promoted to `lab/knowledge/` via three triggered operators: a **correction** (a kill / budget-exhaust → FAILURES, so the next project never retries it), a **recipe** (a settled success → FINDINGS), and a **direction** (a result that opens a new thread → OPEN-QUESTIONS). An insight that lives only in a chat transcript is lost; this write-back is hard rule 11 (a kill's correction is enforced by `guard.py evolve`) and the mechanism by which the lab compounds. Orthogonally — *not* a fourth triggered operator — papers worth remembering are logged continuously to `lab/knowledge/REFERENCES.md` during `/ideate` and `/lit-review` research scans: a shared reading index with no kill/result gate, so literature compounds across ideas the way findings do.

## Unattended protocol (/research-loop)

For overnight work. Three rules make it safe:

1. **The brief is the gate.** A loop requires `LOOP_BRIEF.md` with a PI signature; its numeric scope lives in `control.yaml`. A loop never authorizes itself.
2. **Zero-token monitoring.** While a run is in flight the agent may only poll `scripts/status.py` — no log reading, no judging half-finished curves. The runner's watchdog enforces budgets in code, so babysitting adds nothing.
3. **Never stop, but back off.** Within budget the loop must always pick a next action (FULL work outside the envelope queues as a PI note); but after `loop.no_progress_backoff_cycles` cycles without progress it stops with a written diagnosis — the cure for the micro-tweak death spiral.

Every cycle appends a Loop Log row; exit produces a **PI morning report** at the top of the notebook entry: best result, queued decisions, recommended next command.

## Experiment discipline (applies everywhere)

- **Staged scale:** SMOKE (minutes, proves the pipeline) → PILOT (smallest decisive run — most ideas die here) → FULL (gated). Promotion criteria are written before running.
- **One commit per attempt**, message `exp-NNN: <outcome>`; revert code freely, never the ledger.
- **Debug cap:** `experiment.max_debug_depth` consecutive fixes, then record-and-move-on.
- **Multi-seed:** nothing is a finding until confirmed at `experiment.multi_seed_n` seeds (`scripts/sweep.py`).
- **Frozen:** eval protocol, test set, seeds policy, budgets. Selection happens on validation; test is read once, for the paper.
