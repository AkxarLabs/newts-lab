# AutoScientist — Design Document

*Why this repo is shaped the way it is. Written 2026-06-12, after a survey of the autonomous-research landscape.*

## 1. Goal

Automate the full research workflow — ideation → literature review → proposal → experimentation → analysis/ablations → paper writing → review → finalization — such that an AI agent (Claude Code) can drive it end-to-end, with the human as PI at a few explicit gates. The framework must be domain-agnostic, and every project it spawns must be reproducible and extensible by others.

## 2. Prior art surveyed, and what we took from each

| System | Core mechanism | What we adopted | What we rejected |
|---|---|---|---|
| **Sakana AI Scientist v1** (2024) | Linear pipeline: idea gen → Semantic Scholar novelty check → Aider experiment loop (5 runs, 4 retries) → LaTeX writeup → NeurIPS-form LLM reviewer. Human-built "templates" per domain. | The lifecycle decomposition; the NeurIPS-form structured reviewer with ensemble + meta-review; novelty check against literature before investing. | Rigid domain templates; review that doesn't gate anything; single-shot linearity. Independent audits found 42% experiment failures and 57% of papers with hallucinated numbers — hence our traceability hard rule. |
| **Sakana AI Scientist v2** (2025) | Template-free best-first tree search (BFTS) over experiment nodes (draft/debug/improve), 4 stages (preliminary → tuning → research agenda → ablations), stage-completion checks, multi-seed confirmation of best nodes, VLM figure feedback. First AI paper to pass (workshop) peer review. | The staged experiment progression; debug-depth limits (max 3) and debug-vs-explore balance; multi-seed confirmation before promoting results; figures reviewed, not just generated. | Running the full tree search blind — we keep the agent's judgment in the loop instead of a fixed search policy (see AIRA below for why). |
| **Karpathy's autoresearch** (2026) | Radical minimalism: agent edits one file (`train.py`), human edits one file (`program.md`), fixed 5-min budget per run, one metric, `results.tsv` ledger, **git commit/reset as keep-discard and memory**. | Git-as-memory; append-only results ledger; fixed budgets for comparability; "human programs the org, agent programs the experiment"; single human-edited control file (our `CLAUDE.md` plays the `program.md` role). His observed failure modes (seed-hacking for fake gains, stacked changes never ablated) became hard rules 4, 6 and the mandatory-ablations stage. | One-file scope — too restrictive for multi-stage research projects; no lit review or writing. |
| **Agent Laboratory** (2025) | Role-played phases (PhD/Postdoc/Engineer/Professor), mle-solver + paper-solver, pickled checkpoints per subphase, **copilot mode** with human checkpoints (raised review scores 3.8 → 4.38/10). | Human checkpoints demonstrably improve quality → our three PI gates. Per-phase task notes from the human. | Persona theater (roles add overhead without mechanism); pickle state (we use plain files + git — inspectable, diffable). |
| **AI2 CodeScientist** (2025) | Ideation by recombining papers × vetted codeblocks; **MINI_PILOT → PILOT → FULL_EXPERIMENT staged gating**; containerized execution with cost caps; meta-analysis across runs. | Staged scale (our smoke → pilot → full) — the single best cost-control idea in the literature; vetted-code grounding (our project template = the vetted starting point); hard cost/time limits. | The web-GUI orchestration layer; Modal-only execution. |
| **Google AI co-scientist** (2025) | Multi-agent hypothesis engine: Generate → Reflect → **Elo tournament via pairwise debate** → Evolve → Meta-review, with persistent context memory. Elo correlated with correctness. | Tournament-style pairwise comparison in `/ideate` (cheap, surprisingly strong relative signal vs. absolute scoring); meta-review feedback loop (our `lab/knowledge` write-back updates future ideation). | Six standing agents — overkill for a solo lab; we get the same effect with one agent following procedures. |
| **FutureHouse Robin / Edison Kosmos** (2025) | Kosmos: a **structured world model** (entities, claims, results, open questions) updated after every rollout — the thing that keeps 200-rollout, 12-hour runs coherent. Traceability as hard constraint (every statement cites a notebook cell or paper). | `lab/knowledge/` as a lightweight world model (FINDINGS / FAILURES / OPEN-QUESTIONS with artifact pointers); claim-level citation discipline (`claims.yaml`). Their audit found *interpretive reasoning* was the weak spot (57.9% accuracy) → our review rubric audits interpretation separately from data. | A database — plain Markdown files are queryable enough for one lab and survive any tooling change. |
| **Meta AIRA / RE-bench / MLE-bench** (2025) | Agent = search policy + **operators**; finding: operators dominate, fancy search adds nothing with weak operators. **Validation→test generalization gap grows with search time** (+9–13 pts of self-deception). Scoped memory: siblings for diversity, ancestor chain for debugging. RE-bench: agents win on many cheap shots, lose on returns-to-time. | Invest in operator quality (the `/experiment` procedure's hygiene rules) over orchestration; strict val/test separation written into every proposal; ledger-before-acting (read what was tried); prefer several small experiments over one long run. | MCTS/evolutionary search machinery — unjustified at this scale. |

### The synthesis in one paragraph

The field's consensus failure modes are: hallucinated results, metric gaming, unablated stacked changes, validation overfitting, weak autonomous ideation, and findings lost to context overflow. The consensus fixes are: artifact-traceable claims, fixed budgets, mandatory ablations, held-out test discipline, human gates at high-leverage points, and a persistent structured knowledge store. AutoScientist is those fixes, encoded as **procedures (skills) + templates + a file-based state machine**, with git as the memory substrate — rather than as an orchestration program. The agent driving this *is already* an agentic loop (Claude Code); wrapping it in another Python orchestrator (Sakana-style) adds failure surface without adding capability. Karpathy's result — a bare repo + a Markdown protocol outperforming heavyweight harnesses — is the existence proof.

## 3. Architecture

### 3.1 Hub and spoke

- **Hub (this repo):** ideation, lit reviews, proposals, papers, lab knowledge, procedures, templates, registry. One git repo.
- **Spokes (`projects/<slug>/`):** one per approved proposal, instantiated from `templates/project/`, each **its own git repo** (the hub gitignores them). Rationale: (a) a project must be independently cloneable/reproducible by others — that's a stated goal; (b) experiment-per-commit history would drown the hub's history; (c) projects can be archived/published independently.
- The hub's `lab/REGISTRY.md` is the single index linking ideas ↔ projects ↔ papers ↔ states.

### 3.2 Procedures as skills, not orchestration code

Each pipeline stage is a Claude Code skill (`.claude/skills/<name>/SKILL.md`) — an executable, versioned, human-editable procedure. This is the `program.md` idea generalized: the human improves the *procedures*; the agent executes them with judgment. Benefits over a Python pipeline: procedures degrade gracefully (the agent adapts when reality deviates), they're diffable/reviewable, and improving the lab = editing Markdown.

### 3.3 State machine + registry

States: `seed → triaged → lit-review → proposal → active → analysis → writing → internal-review → final`, plus `parked`/`killed` from anywhere. State lives in two places, deliberately redundant: each idea's `IDEA.md` frontmatter (local truth) and `lab/REGISTRY.md` (global index). Every procedure ends by syncing both.

### 3.4 Three PI gates

1. **Proposal approval** — before compute is spent (Agent Laboratory's copilot data: human checkpoints buy +0.6 review points; this is the cheapest one).
2. **Full-scale launch** — smoke/pilot are cheap and autonomous; FULL runs burn real compute and need sign-off (CodeScientist's gating).
3. **Finalization** — nothing leaves the lab without the PI reading it (Zochi/Sakana norm: human accountability for AI-generated work).

Everything between gates is autonomous.

### 3.5 The knowledge layer (anti-amnesia)

`lab/knowledge/` is the Kosmos world-model, minimized:
- `FINDINGS.md` — confirmed results, each with an artifact pointer.
- `FAILURES.md` — what didn't work and the diagnosed reason (this is what makes the *next* project smarter; most systems lose this entirely).
- `OPEN-QUESTIONS.md` — threads worth pursuing, feeding the next `/ideate`.
- `lab/notebook/YYYY-MM-DD-*.md` — session journal (raw, chronological).

The flow is: notebook (raw) → knowledge (distilled) → next ideation (compounding). This closes the meta-review loop from co-scientist without standing agents.

### 3.6 Experiment loop design (the operators)

Per AIRA, operator quality is the bottleneck, so the `/experiment` procedure encodes the operators precisely:

- **Staged scale:** SMOKE (≤ minutes; verifies pipeline + artifact writing) → PILOT (small but statistically informative; this is where most ideas die) → FULL (PI-gated). Promotion criteria written in the proposal *before* running.
- **Keep/discard via git:** one commit per experiment attempt; revert if the ledger doesn't justify keeping it. `git log` + `EXPERIMENT_LOG.md` + `runs/registry.jsonl` are read *before* proposing the next experiment (scoped memory: ledger = sibling history; the failing experiment's own thread = ancestor chain).
- **Debug policy:** max 3 consecutive fix attempts, then record-and-move-on (Sakana v2's `max_debug_depth`).
- **Anti-gaming rules:** budgets, seeds, eval code, and test sets are frozen per-proposal; changing them requires a PI flag, not an edit (Karpathy's seed-hacking incident, AIRA's generalization gap).
- **Multi-seed confirmation** (≥3 seeds) for any number destined for a paper (Sakana v2).
- **Ablations are a stage, not an afterthought** — every kept change appears in the ablation plan (Karpathy's stacked-changes failure).

### 3.7 Writing & review

- Paper lives in `papers/<slug>/` (hub), built from artifacts in the project repo. Figures/tables are *generated by committed scripts* from `runs/` artifacts — never hand-made (kills the hallucinated-numbers class of failure at the source).
- `claims.yaml` maps every quantitative claim → run id + artifact path. The `/review-paper` procedure audits it mechanically (grep the number in the artifact) before doing the NeurIPS-form qualitative review (Sakana's rubric: Originality/Quality/Clarity/Significance 1–4, Soundness/Presentation/Contribution 1–4, Overall 1–10, Decision).
- Citations only from the lit-review notes (which record how each paper was found and what it actually says) — never from memory (Sakana v2's "LSTMs by Goodfellow" incident).

### 3.8 Reproducibility & extensibility standards (project template)

- `uv` + `pyproject.toml` + lockfile; pinned Python.
- Every run = one YAML config; runner dumps resolved config + git SHA + seed into `runs/<run_id>/`; appends one line to `runs/registry.jsonl` (committed). The artifact dir — not any tracker — is the source of truth.
- New experiments = new configs / new modules behind interfaces; baseline code paths stay runnable forever ("any past experiment re-runnable from its config after any later change").
- Smoke test in `tests/` so a stranger (or future agent) can verify the pipeline in minutes.
- Local-first tracking (JSONL + generated plots); wandb optional, never load-bearing.

## 4. What we deliberately did NOT build

- **No orchestrator program / no daemon.** The agent session is the orchestrator. Adding one would re-create Sakana v1's brittleness.
- **No multi-agent personas.** One agent, many procedures. Parallelism, when needed, is "spawn subagents for independent experiments," not standing roles.
- **No database.** Markdown + JSONL + git. Inspectable, diffable, survives tooling churn.
- **No domain assumptions.** SLM-specific scaffolding (HF/peft/trl recipes, eval harnesses) belongs in a future `templates/project-slm/` variant or in the first spawned project — not in the framework.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Agent games metrics (seed/timeout/eval edits) | Hard rules 4–6 in CLAUDE.md; frozen eval protocol per proposal; review audits the diff history |
| Validation overfitting over long projects | Held-out test never read by the loop; selection discipline rule; multi-seed confirmation |
| Knowledge loss across sessions/context | Registry + notebook + knowledge write-back as mandatory session-end step |
| Weak autonomous ideation (the field's weakest link) | Tournament ranking + lit grounding + OPEN-QUESTIONS feedback; PI gate before any spend |
| Hallucinated paper content | claims.yaml audit + script-generated figures + citation-from-notes-only |
| Runaway cost | Staged scale with PI gate before FULL; budgets in proposal; debug-depth cap |

## 6. Possible future extensions

- `templates/project-slm/`: an SLM-specialized project template (HF transformers + peft + trl + fixed eval harness) once the first SLM project stabilizes its patterns.
- Parallel experimentation: `/experiment` spawning isolated subagents per independent config (worktree isolation), merging via the ledger.
- Automated nightly loops (`/loop` or scheduled agents) for long experiment queues between PI gates.
- An `arXiv watch` procedure that feeds `OPEN-QUESTIONS.md` from new papers in tracked areas.
- Elo-persistent idea ranking across ideation sessions (currently per-session tournament).
