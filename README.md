# AutoScientist

A self-contained **research lab for an AI agent**. This repo holds the procedures, state, and templates that let an agent (Claude Code or similar) take a research direction from **ideation → literature review → proposal → experimentation → analysis & ablations → paper writing → internal review → finalization**, with the human acting as PI at a small number of explicit gates.

The repo is domain-agnostic by design: nothing here assumes a particular research area. Domain focus (e.g., small language models) lives in the ideas and projects you create with it.

## The model

**Hub and spoke.** This repo is the hub (the "lab"): it holds ideation, literature reviews, proposals, papers, lab-wide knowledge, and the executable procedures. Each approved proposal **spawns a self-contained project repo** under `projects/` from a reproducible template — that's where all code and experiments live. Results flow back to the hub for analysis, writing, and knowledge accumulation.

```
        ┌────────────────────────  HUB (this repo)  ────────────────────────┐
        │  /ideate → /lit-review → /propose ──[PI gate]──┐                  │
        │                                                ▼                  │
        │  lab/knowledge ◄── /finalize ◄── /review-paper ◄── /write-paper   │
        └───────▲────────────────────────────────────────────────▲──────────┘
                │                                                │
                │            ┌──────── SPOKE (projects/<slug>) ──┴───┐
                └── findings │  /spawn-project → /experiment → /analyze │
                             │  (own git repo, own env, reproducible)  │
                             └─────────────────────────────────────────┘
```

## Lifecycle states

Every idea moves through a state machine, tracked in [lab/REGISTRY.md](lab/REGISTRY.md):

`seed → triaged → lit-review → proposal → [PI gate] → active → analysis → writing → internal-review → [PI gate] → final`

…with `parked` and `killed` available from any state. Killing ideas early and often is a feature: kill criteria are written into every proposal before experiments start.

## Procedures (slash commands)

The workflow is encoded as Claude Code skills in `.claude/skills/`:

| Command | What it does |
|---|---|
| `/lab-status` | Orient: read registry + notebook, report lab state, recommend next action |
| `/ideate` | Generate, score, and tournament-rank candidate ideas into `ideas/` |
| `/lit-review` | Ground an idea in literature; novelty verdict; positioning |
| `/propose` | Write a full proposal with staged experiment plan, budgets, kill criteria |
| `/spawn-project` | Instantiate `templates/project/` into `projects/<slug>/` (own git repo) |
| `/experiment` | Run the experiment loop: smoke → pilot → full, ledger + git as memory |
| `/analyze` | Analyze results, decide ablations/follow-ups, write findings |
| `/write-paper` | Draft the LaTeX paper in `papers/<slug>/`; every number traced via `claims.yaml` |
| `/review-paper` | Internal NeurIPS-style review + claim/artifact audit |
| `/finalize` | Close out: archive, write-back to lab knowledge, update registry |

## Directory map

```
AutoScientist/
├── CLAUDE.md            # Lab protocol — the agent's operating manual (read every session)
├── docs/DESIGN.md       # Full design rationale & prior-art synthesis
├── .claude/skills/      # The procedures above
├── lab/
│   ├── REGISTRY.md      # Single source of truth for all ideas/projects + states
│   ├── knowledge/       # Lab world model: FINDINGS, FAILURES, OPEN-QUESTIONS
│   └── notebook/        # Dated lab-notebook entries (one per working session)
├── ideas/<slug>/        # IDEA.md, lit-review.md, proposal.md per idea
├── projects/<slug>/     # Spawned experiment repos (each its own git repo; not tracked by hub)
├── papers/<slug>/       # LaTeX papers + claims.yaml (claim → artifact mapping)
└── templates/           # project/, paper/, idea/, review/ templates
```

## Quickstart

```bash
cd AutoScientist
claude        # start the agent
> /lab-status                 # orient
> /ideate efficient small-LM post-training   # or any direction
```

The agent takes it from there, pausing at the PI gates (proposal approval, full-scale launch, finalization) for your sign-off.

## Principles (short version — full version in CLAUDE.md)

1. **Every reported number traces to a run artifact.** No exceptions; the reviewer audits this.
2. **Staged scale:** smoke → pilot → full. Never launch full-scale first.
3. **Git is memory.** One commit per experiment in projects; append-only ledgers.
4. **Operators over orchestration:** good experiment hygiene beats clever search.
5. **Selection discipline:** validation selects, held-out test reports — never the reverse.
6. **Extensible by default:** new experiments are new configs/modules, never edits to the baseline.
7. **Knowledge compounds:** every session writes back to `lab/knowledge/` so later projects start smarter.
