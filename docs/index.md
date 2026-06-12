# AutoScientist

**A research lab for an AI agent.** AutoScientist takes a research direction from ideation through literature review, proposal, experimentation, analysis and ablations, to a finished LaTeX paper — driven by an agent (Claude Code), with you as the PI at three explicit gates.

It is a *template*, not a framework: procedures are Markdown skills the agent executes with judgment, state is plain files and git, and nothing here assumes a research domain. The design distills what worked across the autonomous-research literature — Sakana's AI Scientist, Karpathy's autoresearch, Google's co-scientist, Kosmos, Meta's AIRA — and hard-codes defenses against their documented failure modes. The full reasoning lives in [Design rationale](DESIGN.md).

## The shape of the lab

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

The **hub** (this repo) holds ideas, literature reviews, proposals, papers, accumulated knowledge, and the executable procedures. Every approved proposal **spawns a project repo outside the hub** — independently cloneable, reproducible, and extensible by humans. Findings flow back and compound in `lab/knowledge/`, so each project starts smarter than the last.

## The three PI gates

Everything between gates runs autonomously. Everything at a gate stops for you.

| Gate | When | What you approve |
|---|---|---|
| **1 — Proposal** | before any compute is spent | hypothesis, baselines, staged plan, budgets, kill criteria — optionally a Gate 2 envelope |
| **2 — Full scale** | before any FULL-stage run | the expensive runs (or pre-authorize an envelope for unattended loops) |
| **3 — Finalization** | before anything leaves the lab | the paper, after it survives the internal review ensemble |

## Load-bearing principles

1. **Every reported number traces to a run artifact** — enforced mechanically by `tools/audit_claims.py`, not by promise.
2. **Staged scale** — smoke → pilot → full; most ideas die cheaply at pilot.
3. **Git is memory** — one commit per experiment attempt; append-only ledgers; nothing lives only in a chat transcript.
4. **Frozen things stay frozen** — eval protocol, test sets, seeds, budgets. The watchdog enforces budgets in code.
5. **Fresh eyes review** — papers are critiqued by reviewer subagents that never saw them written, calibrated against the human scoring mean.
6. **Knowledge compounds** — findings, failures, and open questions persist in the hub and seed the next ideation round.

## Where to go next

- [Getting started](getting-started.md) — instantiate the template, `/setup-lab`, first session
- [Autonomous operation](autonomy.md) — `/overnight`: one command before bed, reviewed drafts in the morning
- [The workflow](workflow.md) — lifecycle states, gates, and protocols in detail
- [Skills reference](skills.md) — all 14 procedures
- [Configuration](configuration.md) — the 3-layer config system and every key
- [Projects](projects.md) — anatomy of a spawned project and guidelines for extending one
- [Tools](tools.md) — the mechanical helpers
