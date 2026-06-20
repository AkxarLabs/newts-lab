# Kartr Lab

A self-contained **research lab for an AI agent**. This repo holds the procedures, state, and templates that let an agent (Claude Code or similar) take a research direction from **ideation → literature review → proposal → experimentation → analysis & ablations → paper writing → internal review → finalization**, with the human acting as PI at a small number of explicit gates.

The repo is domain-agnostic by design: nothing here assumes a particular research area. Domain focus (e.g., small language models) lives in the ideas and projects you create with it.

## Documentation

Full docs live in [docs/](docs/) and serve as a styled site (search, nav, warm theme) with zero installation:

```bash
uv run --with properdocs --with mkdocs-material properdocs serve     # → http://127.0.0.1:8000
```

Start at [docs/index.md](docs/index.md) · [Getting started](docs/getting-started.md) · [Configuration](docs/configuration.md) · [Projects](docs/projects.md).

## Use as a template

Kartr Lab is a **template repository** — each lab is a living instance:

1. **Use this template** on GitHub (or `npx degit`/clone) → your own lab repo.
2. Check `lab/config.yaml` (`lab.projects_root` is the one key worth a look on day one).
3. `claude` → `/lab-status` → `/ideate <your direction>`. Lab state starts empty and compounds from there.

To pull template improvements into a running lab later: `git remote add template <url>` and cherry-pick — your lab state lives in files the template never touches.

## The model

**Hub and spoke.** This repo is the hub (the "lab"): it holds ideation, literature reviews, proposals, papers, lab-wide knowledge, and the executable procedures. Each approved proposal **spawns a self-contained project repo outside the hub** — at `lab.projects_root` (default `../kartr-lab-projects/<slug>`) — from a reproducible template; that's where all code and experiments live, so the hub never bloats with experiment state. Results flow back to the hub for analysis, writing, and knowledge accumulation.

```
        ┌────────────────────────  HUB (this repo)  ────────────────────────┐
        │  /ideate → /lit-review → /scope → /propose ──[PI gate]──┐         │
        │                                                         ▼         │
        │  lab/knowledge ◄── /finalize ◄── /review-paper ◄── /write-paper   │
        └───────▲────────────────────────────────────────────────▲──────────┘
                │                                                │
                │   ┌── SPOKE (../kartr-lab-projects/<slug>) ┴───┐
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
| `/setup-lab` | First-run interview → writes `lab/config.yaml`, verifies env, seeds directions |
| `/autopilot` | Unattended end-to-end campaign: ideas → reviewed paper drafts under a signed brief |
| `/advance` | Stage-gated mode: run exactly the next lifecycle stage, then stop for PI verification |
| `/adopt` | Enter the lifecycle anywhere — scaffold prerequisites for an existing idea, design, or code repo |
| `/compete` | Spin off a **target-driven** project for a fixed target (benchmark/leaderboard/KPI) — iterate toward the metric, no paper pipeline |
| `/lab-status` | Orient: registry + notebook + `tools/check_lab.py` lint; recommend next action |
| `/discuss` | Collaborative human↔agent session (grill-style Q&A + live research) that seeds the next stage — optional pre-step to `/ideate`, `/compete`, `/scope`, `/write-paper` |
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
| `/make-figures` | Figures/tables mechanically from run artifacts (shared figure library) + multimodal self-review |
| `/write-paper` | Evidence-first LaTeX drafting; placeholder-resolved verified citations; claims re-audited every revision round |
| `/review-paper` | Mechanical claims audit (`tools/audit_claims.py`) + fresh-context critique ensemble with minority veto |
| `/finalize` | Close out: archive, write-back to lab knowledge, update registry |
| `/grill-with-docs` | Sharpen an engineering plan/design via a relentless grilling loop → `CONTEXT.md` glossary + ADRs (vendored, MIT). Available in the hub and every project repo |

`/grill-with-docs` composes two smaller vendored skills that are also invocable on their own:
`/grilling` (the one-question-at-a-time loop) and `/domain-modeling` (glossary + ADRs). See
[docs/skills.md](docs/skills.md) for the full reference.

## Directory map

```
kartr-lab/
├── CLAUDE.md            # Lab protocol — the agent's operating manual (read every session)
├── docs/DESIGN.md       # Full design rationale & prior-art synthesis
├── .github/workflows/   # CI: docs build+deploy (Pages), lab lint, cross-platform template smoke
├── .claude/skills/      # The procedures above
├── .claude/agents/      # Scoped subagents: fresh-context-reviewer, experiment-runner, overseer
├── lab/
│   ├── REGISTRY.md      # Single source of truth for all studies/projects + states
│   ├── config.yaml      # Lab-wide tunables (ensemble sizes, debug depth, backoff, ...)
│   ├── knowledge/       # Lab world model: FINDINGS, FAILURES, OPEN-QUESTIONS
│   └── notebook/        # Dated lab-notebook entries (one per working session)
├── studies/<slug>/      # one research effort: IDEA.md, lit-review.md, proposal.md, critiques/
│   └── paper/           #   LaTeX paper + claims.yaml (appears at the writing stage)
├── templates/           # project/, project-types/ (ml/empirical/simulation/theory/…), domain-profiles/, paper/ (+ venues/), idea/, review/, loop/, compete/
├── tools/               # audit_claims.py, check_lab.py, show_config.py, run_slots.py, s2.py, lab_bus.py
├── dashboard/           # Vivarium — optional local Rain-World-style living-lab-world dashboard (rooms, critters, worker critters + Newt; delete it and nothing changes)
└── (projects live at ../kartr-lab-projects/<slug> — see lab/config.yaml lab.projects_root)
```

## Quickstart

```bash
cd kartr-lab
claude        # start the agent
> /setup-lab                  # first time: 5-minute configuration interview
> /ideate efficient small-LM post-training   # or any direction
```

The agent takes it from there, pausing at the PI gates (proposal approval, full-scale launch, finalization) for your sign-off.

**Pick your level of autonomy** — same procedures, same gates, different pace ([full guide](docs/autonomy.md)):

- **Manual** — invoke each procedure yourself (`/ideate` → `/lit-review` → …).
- **Stage-gated** — `/advance`: one lifecycle stage per command, verified by you between stages.
- **Project loop** — `/research-loop <slug>`: unattended experiments under a signed brief. Two modes (set in the brief's `Mode:`): `execute` (run the approved plan, then stop) or `explore` (autonomous in-project re-planning — expand the frontier and reopen non-headline design decisions within the envelope; see [autonomy](docs/autonomy.md)).
- **Full autopilot** — `/autopilot`: sign one campaign brief, wake up to reviewed drafts (wrap with the built-in scheduler: `/loop 30m /autopilot continue <campaign-file>`).

Already have an idea, a design, or a codebase? `/adopt` enters the lifecycle mid-stream.
Have a fixed target (a benchmark, a leaderboard, a KPI)? `/compete` spins off a
target-driven project that chases the metric directly — no paper pipeline.

## Contributing

Improving the lab machinery (a skill, tool, template, the dashboard, or docs)? See
[CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, the four checks CI runs, and the
conventions that keep the lab coherent. (Running research with the lab isn't a
contribution — that work lives in your own lab state, never in a PR.)

## Principles (short version — full version in CLAUDE.md)

1. **Every reported number traces to a run artifact.** No exceptions; the reviewer audits this.
2. **Staged scale:** smoke → pilot → full. Never launch full-scale first.
3. **Git is memory.** One commit per experiment in projects; append-only ledgers.
4. **Operators over orchestration:** good experiment hygiene beats clever search.
5. **Selection discipline:** validation selects, held-out test reports — never the reverse.
6. **Extensible by default:** new experiments are new configs/modules, never edits to the baseline.
7. **Knowledge compounds:** every session writes back to `lab/knowledge/` so later projects start smarter.
