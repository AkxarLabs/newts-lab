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

## The gates in detail

**Gate 1 — proposal approval.** The cheapest, highest-leverage human moment (Agent Laboratory measured +0.6 review points from checkpoints like this). You approve: hypothesis, the strongest-fair baseline, frozen eval protocol, the staged experiment table with promotion criteria written in advance, budgets, and kill criteria. Optionally you pre-authorize a **Gate 2 envelope** here.

**Gate 2 — full-scale launch.** SMOKE and PILOT runs are autonomous; FULL runs need approval — either per-run, or covered by a recorded envelope (`control.yaml → gate2_envelope`, `pi_signed: true`). Runs outside an envelope's scope always need fresh approval. The envelope is what lets overnight loops do full-scale work without you.

**Gate 3 — finalization.** Nothing leaves the lab without you reading it. By this point the paper has survived the mechanical claims audit and the fresh-context critique ensemble.

## Session protocol (interactive)

Every session: orient first (`/lab-status` → registry, latest notebook entry, consistency lint), work the highest-leverage item, and **write back before ending** — a dated notebook entry, registry sync, and any durable insight promoted to `lab/knowledge/` (FINDINGS / FAILURES / OPEN-QUESTIONS). An insight that lives only in a chat transcript is lost; this write-back is hard rule 11 and the mechanism by which the lab compounds.

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
