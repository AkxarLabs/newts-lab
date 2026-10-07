# Newts' Lab

<div class="as-hero" markdown>
<p class="as-kicker">A research lab for an AI agent</p>
<p class="as-lede">Newts' Lab takes a research direction from <strong>ideation</strong> through literature review, proposal, experimentation, analysis and ablations, to a <strong>finished LaTeX paper</strong> — driven by an agent, with you as the PI at three explicit gates.</p>

[Getting started](getting-started.md){ .md-button }
[Autonomy & modes](autonomy.md){ .md-button .md-button--secondary }
</div>

It is a *template*, not a framework: procedures are Markdown skills the agent executes with judgment, state is plain files and git, and nothing here assumes a research domain. The design distills what worked across the autonomous-research literature — Sakana's AI Scientist, Karpathy's autoresearch, Google's co-scientist, Kosmos, Meta's AIRA — and hard-codes defenses against their documented failure modes. The full reasoning lives in [Design rationale](DESIGN.md).

<figure markdown>
![The dashboard: the lab as a 3D tabletop, with the Today panel](assets/dashboard-home-dark.png){ .as-shot }
<figcaption>Local-only and offline: <a href="dashboard/">the dashboard</a> is the whole product. Start it with one double-click, set the lab up, start work, answer the agents and approve the gates. The lab is drawn behind it as a 3D tabletop, a room per stage.</figcaption>
</figure>

## The shape of the lab

```
        ┌────────────────────────  HUB (this repo)  ────────────────────────┐
        │  /ideate → /lit-review → /scope → /propose ──[PI gate]──┐         │
        │                                                         ▼         │
        │  lab/knowledge ◄── /finalize ◄── /review-paper ◄── /write-paper   │
        └───────▲────────────────────────────────────────────────▲──────────┘
                │                                                │
                │   ┌── SPOKE (../newts-lab-projects/<slug>) ┴───┐
                └── │  /spawn-project → /experiment → /improve →     │
          findings  │  /analyze   (own git repo, own env, own        │
                    │  control.yaml — independently reproducible)    │
                    └────────────────────────────────────────────────┘
```

The **hub** (this repo) holds ideas, literature reviews, proposals, papers, accumulated knowledge, and the executable procedures. Every approved proposal **spawns a project repo outside the hub** — independently cloneable, reproducible, and extensible by humans. Findings flow back and compound in `lab/knowledge/`, so each project starts smarter than the last — both results (FINDINGS / FAILURES) and literature (a shared `REFERENCES.md` reading index) accumulate, seeding faster discovery next time.

## The three PI gates

Everything between gates runs autonomously. Everything at a gate stops for you.

| Gate | When | What you approve |
|---|---|---|
| **1 — Proposal** | before any compute is spent | hypothesis, baselines, frozen evaluation and analysis plan, staged plan, budgets, kill criteria, optionally the Gate 2 limits |
| **2 — Full scale** | before any full-scale run | the expensive runs, or approve their limits ahead for unattended loops |
| **3 — Finalization** | before anything leaves the lab | the paper, after it survives the internal review ensemble |

## Load-bearing principles

1. **Every reported number traces to a run artifact** — enforced mechanically by `checks/audit_claims.py`, not by promise.
2. **Staged scale** — smoke test, trial runs, then full runs; most ideas die cheaply at the trial runs.
3. **Git is memory** — one commit per experiment attempt; append-only ledgers; nothing lives only in a chat transcript.
4. **Frozen things stay frozen** — eval protocol, test sets, seeds, budgets. The watchdog enforces budgets in code.
5. **Fresh eyes review** — papers are critiqued by reviewer subagents that never saw them written, calibrated against the human scoring mean.
6. **Knowledge compounds** — findings, failures, and open questions persist in the hub and seed the next ideation round.

## Where to go next

<div class="grid cards" markdown>

-   **Getting started**

    ---

    Instantiate the template, run the `/setup-lab` interview, pick your on-ramp.

    [Getting started →](getting-started.md)

-   **Autonomy & modes**

    ---

    Manual, stage-gated (`/advance`), project loops, or full `/autopilot` — and how they compose with the built-in `/loop`.

    [Autonomy & modes →](autonomy.md)

-   **The workflow**

    ---

    Lifecycle states, the three gates, the paper-refinement loop and its safeguards — plus how to start anywhere with `/adopt`.

    [The workflow →](workflow.md)

-   **Skills reference**

    ---

    Every procedure: what each does, what it reads, where it stops.

    [Skills reference →](skills.md)

-   **Configuration**

    ---

    The 3-layer config system and every key, with per-key ownership (PI vs agent).

    [Configuration →](configuration.md)

-   **Projects & tools**

    ---

    Anatomy of a spawned project, the reproducibility contract, and the mechanical helpers.

    [Projects →](projects.md) · [Tools →](tools.md)

</div>
