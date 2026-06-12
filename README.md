# AutoScientist

A self-contained **research lab for an AI agent**. This repo holds the procedures, state, and templates that let an agent (Claude Code or similar) take a research direction from **ideation → literature review → proposal → experimentation → analysis & ablations → paper writing → internal review → finalization**, with the human acting as PI at a small number of explicit gates.

The repo is domain-agnostic by design: nothing here assumes a particular research area. Domain focus (e.g., small language models) lives in the ideas and projects you create with it.

## Documentation

Full docs live in [docs/](docs/) and serve as a styled site (search, nav, warm theme) with zero installation:

```bash
uv run --with mkdocs-material mkdocs serve     # → http://127.0.0.1:8000
```

Start at [docs/index.md](docs/index.md) · [Getting started](docs/getting-started.md) · [Configuration](docs/configuration.md) · [Projects](docs/projects.md).

## Use as a template

AutoScientist is a **template repository** — each lab is a living instance:

1. **Use this template** on GitHub (or `npx degit`/clone) → your own lab repo.
2. Check `lab/config.yaml` (`lab.projects_root` is the one key worth a look on day one).
3. `claude` → `/lab-status` → `/ideate <your direction>`. Lab state starts empty and compounds from there.

To pull template improvements into a running lab later: `git remote add template <url>` and cherry-pick — your lab state lives in files the template never touches.

## The model

**Hub and spoke.** This repo is the hub (the "lab"): it holds ideation, literature reviews, proposals, papers, lab-wide knowledge, and the executable procedures. Each approved proposal **spawns a self-contained project repo outside the hub** — at `lab.projects_root` (default `../AutoScientist-Projects/<slug>`) — from a reproducible template; that's where all code and experiments live, so the hub never bloats with experiment state. Results flow back to the hub for analysis, writing, and knowledge accumulation.

```
        ┌────────────────────────  HUB (this repo)  ────────────────────────┐
        │  /ideate → /lit-review → /propose ──[PI gate]──┐                  │
        │                                                ▼                  │
        │  lab/knowledge ◄── /finalize ◄── /review-paper ◄── /write-paper   │
        └───────▲────────────────────────────────────────────────▲──────────┘
                │                                                │
                │   ┌── SPOKE (../AutoScientist-Projects/<slug>) ┴───┐
                └── │  /spawn-project → /experiment → /improve →     │
          findings  │  /analyze   (own git repo, own env, own        │
                    │  control.yaml — independently reproducible)    │
                    └────────────────────────────────────────────────┘
```

## Lifecycle states

Every idea moves through a state machine, tracked in [lab/REGISTRY.md](lab/REGISTRY.md):

`seed → triaged → lit-review → scoping → proposal → [PI gate] → active → analysis → writing → internal-review → [PI gate] → final`

…with `parked` and `killed` available from any state. Killing ideas early and often is a feature: kill criteria are written into every proposal before experiments start.

## Procedures (slash commands)

The workflow is encoded as Claude Code skills in `.claude/skills/`:

| Command | What it does |
|---|---|
| `/lab-status` | Orient: registry + notebook + `tools/check_lab.py` lint; recommend next action |
| `/ideate` | Phased pipeline: research → generate → multi-agent reflection → evolve → combine → tournament |
| `/lit-review` | Ground an idea in literature; novelty verdict; positioning |
| `/scope` | Deliberate every design decision branch (advocate subagents) → ADR-style `decisions.md` + value re-check |
| `/critique-paper` | Adversarial fresh-context reviewer ensemble on ANY paper — external (lit triage) or our own drafts |
| `/propose` | Write a full proposal with staged experiment plan, budgets, kill criteria (+ optional Gate 2 envelope) |
| `/spawn-project` | Instantiate `templates/project/` at `<projects_root>/<slug>` (own git repo + control.yaml) |
| `/configure` | View the effective 3-layer config with provenance; edit lab or project values |
| `/experiment` | Run the experiment loop: smoke → pilot → full, ledger + git as memory |
| `/improve` | Operator-driven iteration (draft/debug/improve/crossover) with parallel worktree subagents |
| `/research-loop` | Unattended autonomous loop under a PI-signed `LOOP_BRIEF.md` — never-stop-within-budget, zero-token monitoring |
| `/analyze` | Analyze results, decide ablations/follow-ups, write findings |
| `/write-paper` | Draft the LaTeX paper in `papers/<slug>/`; every number traced via `claims.yaml` |
| `/review-paper` | Mechanical claims audit (`tools/audit_claims.py`) + fresh-context critique ensemble with minority veto |
| `/finalize` | Close out: archive, write-back to lab knowledge, update registry |

## Directory map

```
AutoScientist/
├── CLAUDE.md            # Lab protocol — the agent's operating manual (read every session)
├── docs/DESIGN.md       # Full design rationale & prior-art synthesis
├── .claude/skills/      # The procedures above
├── .claude/agents/      # Scoped subagents: fresh-context-reviewer, experiment-runner
├── lab/
│   ├── REGISTRY.md      # Single source of truth for all ideas/projects + states
│   ├── config.yaml      # Lab-wide tunables (ensemble sizes, debug depth, backoff, ...)
│   ├── knowledge/       # Lab world model: FINDINGS, FAILURES, OPEN-QUESTIONS
│   └── notebook/        # Dated lab-notebook entries (one per working session)
├── ideas/<slug>/        # IDEA.md, lit-review.md, proposal.md, critiques/ per idea
├── papers/<slug>/       # LaTeX papers + claims.yaml (claim → artifact mapping)
├── templates/           # project/, paper/, idea/, review/, loop/ templates
├── tools/               # audit_claims.py, check_lab.py, show_config.py
└── (projects live at ../AutoScientist-Projects/<slug> — see lab/config.yaml lab.projects_root)
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
