# Kartr Lab — Design Document

*Why this repo is shaped the way it is. Written 2026-06-12, after a survey of the autonomous-research landscape.*

## 1. Goal

Automate the full research workflow — ideation → literature review → proposal → experimentation → analysis/ablations → paper writing → review → finalization — such that an AI agent (Claude Code) can drive it end-to-end, with the human as PI at a few explicit gates. The framework must be domain-agnostic, and every project it spawns must be reproducible and extensible by others.

## 2. Prior art surveyed, and what we took from each

| System | Core mechanism | What we adopted | What we rejected |
|---|---|---|---|
| **Sakana AI Scientist v1** (2024) | Linear pipeline: idea gen → Semantic Scholar novelty check → Aider experiment loop (5 runs, 4 retries) → LaTeX writeup → NeurIPS-form LLM reviewer. Human-built "templates" per domain. | The lifecycle decomposition; the NeurIPS-form structured reviewer with ensemble + meta-review; novelty check against literature before investing. | Rigid domain templates; review that doesn't gate anything; single-shot linearity. Independent audits found 42% experiment failures and 57% of papers with hallucinated numbers — hence our traceability hard rule. |
| **Sakana AI Scientist v2** (2025) | Template-free best-first tree search (BFTS) over experiment nodes (draft/debug/improve), 4 stages (preliminary → tuning → research agenda → ablations), stage-completion checks, multi-seed confirmation of best nodes, VLM figure feedback. First AI paper to pass (workshop) peer review. | The staged experiment progression; debug-depth limits (max 3) and debug-vs-explore balance; multi-seed confirmation before promoting results; figures reviewed, not just generated. | Running the full tree search blind — we keep the agent's judgment in the loop instead of a fixed search policy (see AIRA below for why). |
| **Karpathy's autoresearch** (2026) | Radical minimalism: agent edits one file (`train.py`), human edits one file (`program.md`), fixed 5-min budget per run, one metric (`val_bpb`), **git commit/reset as keep-discard and memory**, "NEVER STOP" directive. *(Provenance note: the `results.tsv` ledger and the "8-agent org" experiment are community-sourced reconstructions, not official-README claims.)* | Git-as-memory; append-only results ledger; fixed budgets for comparability; "human programs the org, agent programs the experiment"; single human-edited control file (our `CLAUDE.md` plays the `program.md` role). The well-documented risks of seed/metric gaming and unablated stacking became hard rules 4, 6 and the mandatory-ablations stage. | One-file scope — too restrictive for multi-stage research projects; no lit review or writing. |
| **Agent Laboratory** (2025) | Role-played phases (PhD/Postdoc/Engineer/Professor), mle-solver + paper-solver, pickled checkpoints per subphase, **copilot mode** with human checkpoints (raised review scores 3.8 → 4.38/10). | Human checkpoints demonstrably improve quality → our three PI gates. Per-phase task notes from the human. | Persona theater (roles add overhead without mechanism); pickle state (we use plain files + git — inspectable, diffable). |
| **AI2 CodeScientist** (2025) | Ideation by recombining papers × vetted codeblocks; **MINI_PILOT → PILOT → FULL_EXPERIMENT staged gating**; containerized execution with cost caps; meta-analysis across runs. | Staged scale (our smoke → pilot → full) — the single best cost-control idea in the literature; vetted-code grounding (our project template = the vetted starting point); hard cost/time limits. | The web-GUI orchestration layer; Modal-only execution. |
| **Google AI co-scientist** (2025) | Multi-agent hypothesis engine: Generate → Reflect → **Elo tournament via pairwise debate** → Evolve → Meta-review, with persistent context memory. (The Elo is auto-evaluated, not a ground-truth correctness measure.) | Tournament-style pairwise comparison in `/ideate` (cheap, surprisingly strong relative signal vs. absolute scoring); meta-review feedback loop (our `lab/knowledge` write-back updates future ideation). | Six standing agents — overkill for a solo lab; we get the same effect with one agent following procedures. |
| **FutureHouse Robin / Edison Kosmos** (2025) | Kosmos: a **structured world model** (entities, claims, results, open questions) updated after every rollout — the thing that keeps 200-rollout, 12-hour runs coherent. Traceability as hard constraint (every statement cites a notebook cell or paper). | `lab/knowledge/` as a lightweight world model (FINDINGS / FAILURES / OPEN-QUESTIONS with artifact pointers); claim-level citation discipline (`claims.yaml`). Their audit found *interpretive reasoning* was the weak spot (57.9% accuracy) → our review rubric audits interpretation separately from data. | A database — plain Markdown files are queryable enough for one lab and survive any tooling change. |
| **Meta AIRA / RE-bench / MLE-bench** (2025) | Agent = search policy + **operators**; finding: operators dominate, fancy search adds nothing with weak operators. **Validation→test generalization gap grows with search time** (+9–13 pts of self-deception). Scoped memory: siblings for diversity, ancestor chain for debugging. RE-bench: agents win on many cheap shots, lose on returns-to-time. | Invest in operator quality (the `/experiment` procedure's hygiene rules) over orchestration; strict val/test separation written into every proposal; ledger-before-acting (read what was tried); prefer several small experiments over one long run. | MCTS/evolutionary search machinery — unjustified at this scale. |

### The synthesis in one paragraph

The field's consensus failure modes are: hallucinated results, metric gaming, unablated stacked changes, validation overfitting, weak autonomous ideation, and findings lost to context overflow. The consensus fixes are: artifact-traceable claims, fixed budgets, mandatory ablations, held-out test discipline, human gates at high-leverage points, and a persistent structured knowledge store. Kartr Lab is those fixes, encoded as **procedures (skills) + templates + a file-based state machine**, with git as the memory substrate — rather than as an orchestration program. The agent driving this *is already* an agentic loop (Claude Code); wrapping it in another Python orchestrator (Sakana-style) adds failure surface without adding capability. Karpathy's result — a bare repo + a Markdown protocol outperforming heavyweight harnesses — is the existence proof.

## 3. Architecture

### 3.1 Hub and spoke

- **Hub (this repo):** ideation, lit reviews, proposals, papers, lab knowledge, procedures, templates, registry. One git repo.
- **Spokes (`<projects_root>/<slug>/`, default `../kartr-lab-projects/`):** one per approved proposal, instantiated from `templates/project/`, each **its own git repo, outside the hub entirely** (v3 change — previously a gitignored `projects/` subdir). Rationale: (a) a project must be independently cloneable/reproducible by others — that's a stated goal; (b) experiment-per-commit history and run artifacts would bloat the hub; (c) projects can be archived/published independently. The location is a config key (`lab.projects_root`).
- The hub's `lab/REGISTRY.md` is the single index linking ideas ↔ projects ↔ papers ↔ states.

### 3.2 Procedures as skills, not orchestration code

Each pipeline stage is a Claude Code skill (`.claude/skills/<name>/SKILL.md`) — an executable, versioned, human-editable procedure. This is the `program.md` idea generalized: the human improves the *procedures*; the agent executes them with judgment. Benefits over a Python pipeline: procedures degrade gracefully (the agent adapts when reality deviates), they're diffable/reviewable, and improving the lab = editing Markdown.

### 3.3 State machine + registry

States: `seed → triaged → lit-review → scoping → proposal → active → analysis → writing → internal-review → final`, plus `parked`/`killed` from anywhere. State lives in two places, deliberately redundant: each idea's `IDEA.md` frontmatter (local truth) and `lab/REGISTRY.md` (global index). Every procedure ends by syncing both.

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

- Paper lives in `studies/<slug>/paper/` (hub), built from artifacts in the project repo. Figures/tables are *generated by committed scripts* from `runs/` artifacts — never hand-made (kills the hallucinated-numbers class of failure at the source).
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
- **No multi-agent personas.** One agent, many procedures. The ephemeral, scoped subagents added in v2 (fresh-context reviewers, worktree experiment runners) are not standing roles — they are single-task tools spawned and merged by the parent session; the no-orchestrator stance is unchanged.
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
- ~~Parallel experimentation via worktree subagents~~ — **built** (`/improve`, 2026-06).
- ~~Automated nightly loops~~ — **built** (`/research-loop` + `LOOP_BRIEF.md`, 2026-06).
- An `arXiv watch` procedure that feeds `OPEN-QUESTIONS.md` from new papers in tracked areas.
- Elo-persistent idea ranking across ideation sessions (currently per-session tournament).

## 7. Critique, loops, and iteration (added 2026-06)

The v2 upgrade added three capability clusters plus mechanical tooling, each grounded in a second research pass (claims independently re-verified, 18/18 confirmed):

**Paper critique (`/critique-paper`, `/review-paper` Part B).** LLM reviewers have measurable pathologies: leniency (uncalibrated models average 6.9–8.1/10 where humans average ~5.4 — OpenReviewer's headline fix), a novelty blind spot (they over-focus on technical validity and under-assess originality — "Mind the Blind Spots"), and same-session anchoring (fresh-context review beats same-session, F1 28.6 vs 24.6 — Cross-Context Review). Our design: one fresh-context subagent per rubric lens (a dedicated, web-search-obligated novelty lens), adversarial "build the case for rejection" charge, an explicit calibration anchor table, **median (not mean) aggregation**, and a **minority veto** — any reviewer-documented fatal flaw blocks accept unless refuted in writing (minority-veto ensembles measurably beat majority voting against agreeableness bias). The claims audit became mechanical (`tools/audit_claims.py`), in the spirit of Kosmos's notebook-cell citation auditing.

**Unattended loops (`/research-loop` + `LOOP_BRIEF.md`).** Karpathy's never-stop-within-budget discipline, made safe: the PI-signed brief is the loop's Gate 2 (a loop never authorizes itself); in-flight runs are monitored at zero tokens (`scripts/status.py` liveness checks — the Deep Researcher Agent pattern: judgment at completion, not during); the runner watchdog makes `budget.max_minutes` a hard guarantee rather than advice; and an anti-burn backoff (K no-progress cycles → stop with diagnosis) prevents the micro-tweak death spiral observed in long autoresearch runs.

**Operator iteration (`/improve`).** AIRA's central finding — operators dominate search policy — encoded directly: draft/debug/improve/crossover operators with **scoped memory** (draft/improve see a sibling table for diversity pressure; debug sees only its ancestral chain, preventing oscillation), complexity-adaptive prompting (ambition scales with how explored a node is), worktree-isolated parallel variants, and merge-back **through the journal** (subagents return result packets; only the parent writes shared ledgers — append-only purity preserved, zero merge-conflict surface). `EXPERIMENT_LOG.md` gained optional `Parent:`/operator lineage fields, turning the existing ledger into the experiment tree.

All tunables (ensemble sizes, debug depth, seed counts, backoff, staleness) centralize in `lab/config.yaml`.

## 8. Gap analysis vs the field (2026-06, v4)

Where Kartr Lab now stands against the systems surveyed in §2, and what remains deliberately or temporarily missing.

**Covered, with the field's best mechanism:** lifecycle decomposition + gated autonomy (Agent Laboratory's copilot data); template-free but contract-ful experimentation with journals, debug caps, multi-seed (Sakana v2, AIDE); operator-quality focus with scoped memory (AIRA); git-as-memory + budgets-as-facts (autoresearch); fresh-context ensemble review with calibration + minority veto (OpenReviewer/CCR/Sakana reviewer lineage); claim→artifact mechanical audit (Kosmos's traceability, mechanized); compounding knowledge store (Kosmos world model, minimized); multi-agent ideation with reflection/evolution/combination + tournament ranking (co-scientist's Generate/Reflect/Evolve/Rank, v4); ADR-style design deliberation before commitment (`/scope`, v4 — no surveyed system does this explicitly; closest is CodeScientist's human plan-editing); cross-project compute slots (v4); cross-agent operability via AGENTS.md (autoresearch's any-agent stance, v4).

**Known gaps, by choice or for later** *(updated v5, 2026-06-13)*:

1. **Persistent idea Elo** — tournament results are per-session; co-scientist maintains a standing ranked population. Add when idea volume justifies it (registry column + tournament history file).
2. **Multi-lab sharing (AgentRxiv)** — collaborating lab instances exchanging reports gave a +13.7% *relative* gain on MATH-500. A future `lab/exchange/` + a fetch procedure could replicate it; single-lab for now.
3. ~~Literature API tooling~~ — **closed (v5)**: `tools/s2.py` (S2 search/bulk with OpenAlex fallback, mechanical BibTeX, zero-assumption citation verification incl. retraction checks). PaperQA2-class claim-level contradiction detection remains future work.
4. **Benchmark harness (AstaBench/MLE-bench-class)** — no standardized self-evaluation of the lab itself; the procedure retrospective in `/finalize` is the lightweight substitute.
5. ~~VLM figure review~~ — **closed by PI decision (v5)**: no dedicated lens; current models are natively multimodal, so figure inspection is folded into `/make-figures` self-review and the reviewers reading the compiled PDF.
6. **Domain template** (`templates/project-slm/`) — still pending the first real SLM project stabilizing its patterns (deliberate: extract, don't speculate).
7. **Cost telemetry** — token/$ accounting per stage (CodeScientist's hard cost caps); currently only compute budgets are enforced, not API spend.

### v5 addendum — the writing layer (research pass 2026-06-13)

A dedicated survey of paper-writing systems (PaperOrchestra/Google 2026, Jr. AI Scientist, freephdlabor, aiXiv, CycleResearcher, APRES, PaperRecon; plus the citation-auditing literature) reshaped `/write-paper` and added `/make-figures`:

- **Evidence-first ordering** (Jr. AI Scientist's ablated finding): bib seeding → Method first → outline → results sections → Related Work last. Whole-paper single passes measurably degrade the Method section; early Related Work invites invention.
- **Numbers never pass through prose**: result tables are emitted as `.tex` from artifacts (`figures.emit_table`) and `\input` — the mechanism that eliminated numerical transcription errors in Jr. AI Scientist.
- **Citations: placeholder → mechanical resolution** (freephdlabor's pattern): `[cite: description]` inline, resolved via S2 with a title-match gate (PaperOrchestra used 0.7 Levenshtein; we verify the final bib at 0.85), then a blocking zero-assumption audit — free-generated citations are a well-documented fabrication source (Walters & Wilder 2023 measured ~18% fabricated references from GPT-4), so the bib is verified against the resolver, never trusted from the model.
- **Verifier-gated reflection, ≤3 rounds, claims re-audit every round**: refinement gains plateau by round 3 and regress after; worse, **revision is when fabrication happens** — Jr. AI Scientist documented the writer inventing ablations in response to reviewer feedback (and the review score going *up*), with phantom experiments hiding in ablation/analysis subsections. Hence: `audit_claims.py` after every revision round, and a phantom-experiment sweep in `/review-paper`.
- **Interpretation hedging**: Kosmos's audit found interpretive statements markedly more error-prone than data statements (57.9% vs 85.5% accuracy) — discussion claims must point at evidence or be marked conjecture.
- **Reviewer-in-the-loop revision is worth it when audited**: aiXiv measured 10%→70% acceptance through revise-and-respond cycles; LLM-REVal +0.3–0.4 score from review-guided revision — the existing `/review-paper` cycle matches this evidence, now with the fabrication guard.

## 9. External code policy & the autoresearch comparison (v6)

### Using other systems' code directly — verdicts (licenses checked 2026-06)

Policy: Kartr Lab stays a content-and-protocol template with stdlib+pyyaml tools; external systems are sources of *mechanisms* first, dependencies only when a piece is clean, light, and load-bearing.

| System | Public / license | Verdict |
|---|---|---|
| **PaperOrchestra** (Google, `google-research/paper-orchestra`) | yes / Apache-2.0 | Mechanisms adopted (outline-as-work-order, S2 citation gate, ≤3 review-driven cycles). Running it directly would bolt a 5-agent Gemini-locked orchestrator onto a no-orchestrator lab — consult its code/prompts, don't depend on it. |
| **PaperVizAgent / PaperBanana** | yes / Apache-2.0 | Diagram generation needs paid image-gen APIs; optional future helper for conceptual figures. |
| **Sakana AI-Scientist-v2** | yes / **RAIL-style license** (use restrictions + disclosure duties) | **Prompts and mechanisms only** — which is exactly what we did (staged tree search ideas, reviewer form, chktex loop, plot aggregation). Vendoring code would import the license restrictions. |
| **freephdlabor** | yes / MIT top-level, but embeds AI-Scientist-v2-derived parts | Mechanisms only (citation placeholders, PDF acceptance gate — both adopted). |
| **SemanticCite** (claim↔citation support classification) | yes / MIT, small Qwen3 weights public | **Best direct-adoption candidate** when claim-level citation checking matters (runs locally via Ollama, ~4 GB). Deferred until bib-metadata verification proves insufficient. |
| **OpenReviewer** (Llama-OpenReviewer-8B) | yes / Llama 3.1 license | Liftable as a local second-opinion reviewer; for now its *calibration findings* are in our anchor table, which captures most of the value at zero weight-hosting cost. |
| **scienceplots** | yes / MIT | Compatible with our rcParams approach (`no-latex` variant required); optional per-project add — our `figures.py` themes cover the default need without the LaTeX-install dependency. |
| **chktex** | GPL, bundled with TeX Live | Used by `/write-paper`'s reflection gate; requires a TeX distribution on the machine (not present here yet — install TeX Live when the first paper compiles). |

### How Kartr Lab compares to Karpathy's autoresearch

They solve different problems and agree on the physics. **autoresearch** is one experiment loop perfected: one editable file, one metric, a fixed per-run budget, git as keep/discard memory, an overnight never-stop loop — and *no* lit review, no hypothesis management, no paper, no gates, single-project by construction. **Kartr Lab** is the surrounding research organization: ideation through publication with the human at three gates — and its inner experiment loop (`/research-loop` + `/improve` + watchdog + ledgers) is essentially autoresearch's invariants generalized: git-as-memory → per-attempt commits + append-only ledgers; one metric → a frozen eval protocol per project; 5-minute budget → watchdog-enforced per-stage budgets; `program.md` → `CLAUDE.md`/`AGENTS.md` + `control.yaml`; never-stop → never-stop-within-envelope with anti-burn backoff (his loops' observed micro-tweak spiral is why the backoff exists). What autoresearch has that we deliberately preserve as an ideal: radical smallness — when a project really is "optimize one number in one file," a spawned Kartr Lab project *degenerates gracefully into exactly that shape* (one config axis, one metric, `/research-loop`), which is the correct relationship: autoresearch is our special case, not our competitor.

## 10. Operation modes & project-side autonomy (v8)

Two questions drove this wave: *"how does `/autopilot` relate to Claude Code's built-in `/loop`?"* and *"can the spawned project run itself?"*

**Skills vs `/loop` — complementary layers.** The built-in `/loop` is a session-scoped scheduler (`/loop [interval] <prompt-or-skill>`; fires while the session is open and idle; 7-day expiry; restored on `--resume`). It carries no domain semantics: no gates, no signed budgets, no resumable state. Our skills are the opposite layer — procedure + authorization (campaign brief, gate delegation, append-only ledgers, morning report) with no scheduler. The design composes them rather than rebuilding either: `/autopilot` signs the brief interactively, then `/loop 30m /autopilot continue <campaign-file>` provides crash-resilient re-entry, each firing resuming from the Campaign Log. Telling users to "just use `/loop`" would hand them the scheduler without the authorization layer — exactly the unattended failure mode the briefs exist to prevent.

**Modes are entry points, not state.** Manual (per-skill), stage-gated (`/advance`: one lifecycle stage, then a hard stop with a verification summary — never crossing a PI gate), project loops (`/research-loop`, `/improve`), full `/autopilot`. Plus `/adopt` for entering mid-lifecycle with existing work: scaffold the prerequisites, record skipped stages as PI-waived, never waive gates or traceability (pre-existing numbers without artifacts become reproduction rows, not citations). No `autonomy.mode` config key exists on purpose — a mode is which command you type, so switching modes mid-project is free and the protocol stays single.

**The project is self-operating.** Each spawned repo ships `CLAUDE.md` (project protocol: orientation order, autonomy bounds from control.yaml, subagent policy, hub write-back) and `AGENTS.md` (cold-start checklist + non-Claude notes), so `cd project && claude` needs no hub context; `scripts/check_project.py` is the mechanical readiness lint. The optional `SYSTEM.md` (lab-level, copied at spawn) is the PI's prose description of the machine — binding like control.yaml, PI-owned, presence-detected rather than configured. The subagent decision (parallel worktree variants vs sequential) belongs to the implementation agent, bounded by `parallelism.max_parallel_subagents` and compute slots.

### Docs engine (v8.1)

The docs site runs on **ProperDocs** (properdocs.org) — the maintained, MkDocs-compatible successor SSG — with the Material theme on top (verified working: ProperDocs 1.6.7 + mkdocs-material 9.7.6, `--strict` supported). Config lives in `properdocs.yml`; serve with `uv run --with properdocs --with mkdocs-material properdocs serve`. The switch was prompted by upstream MkDocs 2.0's announced plugin/theming breakage; ProperDocs keeps the 1.x contract. The visual identity is a custom `autoscientist` scheme in `docs/stylesheets/extra.css`: warm paper palette (off-white `#FAF6EF` / brown `#6E4F38` / ink `#221C16` / clay `#A8714A`), Fraunces display headings over Source Serif 4 body, booktabs-style tables (matching the lab's paper tables), a paper-light header with a clay masthead rule, and a hero + card-grid landing page.

## 11. The bus & the dashboard (v9)

Two waves. **v9a** was a verified correctness pass: a 10-lens adversarial audit of every skill, agent, template, tool, and doc, each finding independently re-verified against the files before becoming a fix. The verdict that mattered for the lab's shape — *the 3 agents are sufficient, no skill needs merging or splitting* — held; the fixes were seam repairs (the parallel-merge artifact-loss bug, the campaign↔loop authorization deadlock, slot heartbeats, stall-kill calibration, claims-coverage in the audit, a `\pm` compile bug) and Windows-hardening, concentrated exactly where unattended/parallel operation stresses the handoffs between layers.

**v9b** added human-in-the-loop visibility without compromising the file-based, append-only philosophy. The design choice with the most leverage: **the dashboard is not the source of truth, the files are.** A signal layer — *the bus* (`lab/.bus/` and `<project>/.bus/`, gitignored JSONL) — carries events out of every step. Mechanical emitters (`run.py`, `sweep.py`, `run_slots.py`) fire from code, so the dashboard is truthful even when an agent forgets to narrate; agent emitters (`lab_bus.py emit`) add the judgment events. The dashboard (`dashboard/serve.py`, stdlib + a no-build vanilla frontend) tails those files and rebuilds its whole world model on every request — no database of its own.

**Marginalia** (the dashboard) and **Pica** (an inchworm buddy) were chosen by a 3-concept, 2-judge design panel (unanimous). The lab's substrate already *is* a notebook, so rendering it as a living daybook costs almost no usability for an experimental form; the geometer-moth larva ("earth-measurer") is a measuring animal for a traceability lab, and its position/posture is an honest one-glance status. Two honesty constraints are load-bearing: **directives** (the buddy as controller) are delivered as files agents poll at their next checkpoint — never a real-time interrupt — and the UI shows pending→seen→done states truthfully, with a directive *subordinate to gates and hard rules* (it can steer, never sign a gate or change a frozen setting); and **the dashboard's only write is appending a directive** — it signs nothing, the Gates view shows the exact command the PI runs instead. The whole thing is an optional dependency: delete `dashboard/` and the lab is unchanged.

## 12. In-project autonomy — the `explore` loop mode (v10)

The lab was a strong *executor of an approved plan* but could not do what AutoResearch / Sakana's AI-Scientist do **inside one project**: invent new directions from results, discard a design assumption fixed at scoping time, and re-plan — autonomously. Three things blocked it: the loop's action menu ended at `/improve`'s operators (the only generative one, `draft`, capped at `num_drafts`) and then *stopped* when the plan was exhausted with budget left; `decisions.md` carried a per-decision **`Revisit if:`** trigger that **no skill ever read**; and there was no defined autonomy boundary for an in-project pivot, so a literal agent either under-explored or drifted silently — the one failure mode the rest of the design works hardest to prevent.

The fix is **integration, not new infrastructure**, and it is gated behind a brief-authorized **mode** so the conservative loop is unchanged and the PI's signature scopes the wider authority. `LOOP_BRIEF.md` gains `Mode: execute | explore` (default `execute`). In `explore`, the loop's menu gains two operators (defined in `/improve`, so manual exploratory iteration works too): **`expand`** — when the plan is exhausted with budget left, a results-grounded ideation pass proposes new mechanism-distinct lines (each with a pre-written criterion) instead of stopping; and **`revisit`** — when artifacts satisfy a settled decision's trigger, reopen it (new `D-NNN`, dependents → `retired-by-revision`, seed replacements). Why a mode and not a new skill: the v9 audit's verdict was *no skill should be split*, ~90% of the loop machinery is shared, and the brief is already the authorization object — the natural place for the signature to carry the broader action space.

The design keeps every guarantee that makes autonomous research trustworthy, and makes the autonomy boundary **mechanical** rather than a per-cycle judgment: each decision is flagged `Headline: yes/no` at scope time (headline = load-bearing for the central hypothesis the novelty rests on). Reopening a *non-headline* decision and expanding the frontier are autonomous within the frozen set + the Gate-2 envelope; reopening a *headline* decision, touching the frozen set, or exceeding the envelope escalates — a PI note, or under a signed `/autopilot` campaign the same delegation-bounds + overseer `support` check as a Gate-1 self-approval. Selection discipline (the field's clearest lesson — AIRA's generalization gap, Karpathy's seed-hacking) binds *harder* here, not softer: every expanded line still tunes on validation, reports on the frozen test, and needs multi-seed before a paper claim, and expansion rounds are capped precisely because a longer search overfits validation. And it stays default-off (`loop.mode: execute`, zero expansion rounds), so no existing lab changes behavior on upgrade — `explore` is something the PI opts into by signing a brief that says so.

## 13. Vivarium — the dashboard becomes the control surface (v11)

The v9 dashboard (Marginalia, a journal spread with an inchworm) was honest and read-only, but the PI's verdict was blunt: it looked generic and "leave a note" wasn't real control. v11 reskins and re-scopes it. **Look:** the lab is now a warm glass **terrarium** (`Vivarium`) — ideas are plants at their growth stage, projects are jars on a wooden shelf, slots are fireflies, a lantern lights for gates, and the buddy is **Newt**, an axolotl whose *regeneration* is the perfect metaphor for explore-mode's discard-and-regrow (and a Newton wink). The journal metaphor was dropped because the substrate didn't *need* to look like its own files to be legible, and the diorama is far more distinctive.

**Control (the harder change).** The dashboard is a local Python server; it cannot run an agent skill (that's the Claude session), so "all-inclusive control" is layered honestly: (1) **structured commands** (`start_loop`, `set_mode`, `run_smoke`, `park`, `kill`, …) appended to the bus as `kind:"command"` directives the running agent executes in-protocol at its next checkpoint — buttons, not free-text; (2) **read-only tools** (`check_lab`, `status`, `compare`, `show_config`, `inbox`) run directly as side-effect-free subprocesses; (3) **PI gate approval** for Gate 1 & 2 recorded directly (Gate 1 signs the proposal + leaves a `gate1_approved` command; Gate 2 flips `pi_signed: true` with `signed_via: dashboard:<ts>`), each confirm-gated and logged to `lab/.bus/pi-actions.jsonl`. The one hard line held: **Gate 3 is never signable from the dashboard** — sending anything outside the lab is always a session act. The v9 "the dashboard signs nothing" stance was loosened deliberately and only by explicit PI decision, and only for the gates the PI may sign directly anyway; the localhost bind and explicit confirm keep it the PI's action, not the agent's.

## 14. The lab as a living world — Rain World re-skin + the traceability backbone (v12)

The v11 terrarium worked but read as "a generic dashboard," and a never-shipped attempt to re-skin it in the design language of the game *flOw* (a luminous WebGL deep, Three.js vendored for additive bloom) was reversed before it landed. v12 is what shipped instead: the lab re-imagined as **one continuous, hand-drawn living world** in the design language of the game *Rain World* — muted, painterly, lo-fi, cozy-melancholic — and, underneath it, a **traceability backbone** that gives every working agent its own visible, inspectable trace. The name **Vivarium** stays, and the buddy **Newt** stays (now a unique little creature of its own, not an axolotl and not a slugcat); the data contract, the three control tiers, and the Gate-3 hard line all carry over verbatim.

**Why Rain World.** The PI wanted a scene that reads as a *place* rather than a chart, with a distinctive, characterful art direction that the "generic dashboard" critique couldn't stick to. Rain World's idiom — a quiet, lived-in 2.5D world of rooms full of small creatures going about their business — maps cleanly onto a research lab: the lifecycle is a sequence of rooms, the ideas and the agents are the creatures, and watching the lab *is* watching that world tick along. It is also legible at a glance and warm without being cute-by-numbers, which suits a tool the PI leaves open all day.

**Renderer choice — the real reversal: Canvas-2D, no dependencies.** The shipped renderer is a single **Canvas-2D** surface in vanilla JavaScript — no WebGL, no build, no runtime network, nothing vendored. **Three.js and the entire `static/vendor/` tree were deleted.** The flOw direction had justified vendoring Three for "free" bloom; the Rain World direction's painterly, lo-fi look needs no bloom at all, so the dependency lost its only rationale. Deleting it **better honours the dashboard's zero-build / offline / delete-it-and-nothing-changes ethos**: there is now genuinely nothing to fetch, lazy-load, or fall back from. The single Canvas-2D renderer also *is* the fallback — it draws one still frame of the same scene for `prefers-reduced-motion` and `?static`, so there is no second code path to keep honest.

**The world of rooms + a cinematic camera.** The lab is one world read along the lifecycle, each stage a **room** whose art signals the stage: `the seedbed` (seed), `sorting` (triaged), `the stacks` (lit-review), `drafting` (scoping), `the proposal gate` (proposal/Gate 1), `the wet lab` (active, the busiest room, Gate 2), `analysis`, `the writing room` (writing), `the review panel` (internal-review, Gate 3), `the archive` (final), plus `the quiet shelf` (parked) and `the compost` (killed). Every idea/project is a cute **critter** living in the room of its current state (killed critters sink and desaturate; parked are dim). The default World view is an overview centred on current activity (drag to pan); clicking a room **cinematically zooms in** (with a *back* breadcrumb), and double-clicking a project critter zooms into its **bench** — that project's workers up close, its isolated lab. A top-centre **"now happening" pulse strip** summarises loops / gates / in-flight runs / working agents for at-a-glance tracking.

**The creature + its animation.** Newt is a **unique procedural creature** with a simple, cute look of its own (deliberately neither an axolotl nor a Rain-World slugcat), driven by the same nine poses as before (gate / failure / success / regen / running / writing / letter / idle / sleep) via the unchanged `newtPoseFor()` brain. The **regeneration lore is preserved and made literal**: on a re-plan / explore event a frond **dissolves into motes and regrows** — explore-mode's discard-and-regrow shown rather than told — keeping the wink at Newton.

**Workers as creatures — roles, legend, inspector, clustering, despawn.** The bigger visual change is that **every working agent or subagent is now its own critter**, colour-coded by role across six roles: orchestrator (gold; special — larger, a soft halo, the only one that roams between rooms), experiment-runner (teal), fresh-context-reviewer (violet), overseer (slate-blue), ideation-critic (rose), scoping-advocate (amber). Same-role workers are differentiated **deterministically** (hue/marking/walk-phase derived from the worker id, so a worker always looks like itself). A worker that finishes plays a **despawn animation** (dissolving into motes); a crowded room collapses its extra workers into a **"+N more"** cluster. An always-visible **legend** (bottom-left, "Who's working") maps role → colour with live head-counts and click-to-highlight, and **clicking a worker critter** opens an **inspector** showing that one worker's own clean action history.

**The traceability backbone (the lab feature underneath).** The worker critters are surfaced by a new lab capability that is **independent of the dashboard** — delete `dashboard/` and these logs are still written. Claude Code **hooks** (`.claude/settings.json` → `tools/trace_hook.py`, shipped identically in the project template) log every agent's and subagent's tool actions to **per-worker logs**: `lab/.bus/workers/<worker_id>.jsonl` (hub) and `<project>/.bus/workers/<id>.jsonl` (each project) — one file per worker, so each trace is clean and separated. `dashboard/sources.py` aggregates these into the new `snapshot().workers[]`. Two properties keep it sound: it is **best-effort and never blocks a tool call** (logs are local, disposable, gitignored), and **the harness writes the logs, not the subagents** — so subagent rule 3 (shared ledgers are parent-only) is untouched: the trace is the harness *observing* the agents, not the agents reporting into a shared ledger. It complements hard rule 11 (knowledge write-back): the notebook/knowledge distillation is unchanged and remains the durable record; the per-worker trace is the ephemeral, mechanical *who-did-what* underneath it, for visibility and debugging rather than memory.

**In-project ideation (the related capability).** A short investigation found a real gap: the lab could iterate *within* an approved plan but had no first-class way to do divergent **method-approach** ideation inside an active project. Option A would have overloaded `/improve`'s operators; **Option B was chosen** — surface "Ideate approaches" on the project command sheet, backed by `/ideate --in-project`, producing candidate approaches (not experiments) scoped to the frozen set. A new bus event kind **`approach_ideate`** joins `frontier_expand` / `decision_revisit` / `replan`; such events appear in the Ledger and Newt narrates them. Whether the lab may run this autonomously is **config-settable** (the same approval discipline as the rest of in-project autonomy), so it stays off by default and the PI's signature scopes the wider authority.

**Preserved invariants.** Nothing about the protocol moved: the **three PI gates** stand, **Gate 3 is never signable from the dashboard** (the one hard line — finalization/sending outside the lab is always a session act), the **frozen set** (eval/test/seeds/budgets) is untouched, in-project re-planning is still **`active → active`** with no new lifecycle state, the dashboard's **data contract** is unchanged, and **`dashboard/serve.py` is byte-identical** — the only Python change is `sources.py` gaining `workers[]`. The endpoints, the five tabs (World/Projects/Gates/Ledger/In flight), and the three control tiers all carry over from v11.

## 15. The hardened hub↔project boundary (v13)

The hub holds the paper; the project holds its evidence — and a paper must not silently depend on a live, mutable project repo. Four seams were tightened, all mechanical tools invoked by the existing procedures (no new lifecycle state, no relaxed gate):

- **Figures synced with a manifest.** `/make-figures` ends by running `tools/sync_figures.py <slug>`, which copies the project's `figures/*.{pdf,tex,png}` into `studies/<slug>/paper/figures/` and records a `.manifest.json` (source path + sha256 + project commit). `/write-paper` and `/review-paper` run `sync_figures.py <slug> --check` before the claims audit — a stale or diverged hub figure blocks exactly like a failed audit.
- **Cited artifacts archived at finalize.** `/finalize`'s reproducibility pass runs `tools/lock_artifacts.py <slug>` (each `claims.yaml`-cited `runs/<id>/metrics.json` copied into committed `studies/<slug>/paper/artifacts/`, with a locked `artifact_sha256` per claim) and then `audit_claims.py … --verify-hashes`, which resolves the hub archive first. After finalization the paper is **auditable from the hub alone**, even if the project repo later moves or is archived.
- **Write-back via one atomic tool.** A project session calls `tools/hub_writeback.py --slug <slug> …` to append the hub notebook/knowledge entry and set the registry row atomically; if the hub is unreachable it leaves a `HUB-WRITEBACK-PENDING:` block in `EXPERIMENT_LOG.md`, reconciled at the next hub-session orientation by `tools/process_writebacks.py --apply` (append-only — it writes a `HUB-WRITEBACK-DONE` marker, never edits the pending line). Subagent rule 3 is untouched: only the parent merges.
- **Bidirectional escalation.** A project loop blocked mid-run — a `Headline: yes` reopen, a block on a frozen/PI-owned setting, or FULL work outside the envelope — emits `lab_bus.py escalate` alongside its local PI note, so the request reaches the hub (`/lab-status`, the dashboard) without waiting for loop exit. Escalation requests PI attention; it is **never** gate approval, and Gate 3 stays a session-only act.

The back-half of the lifecycle (`analysis` → `writing` → `internal-review`) runs in a hub session reading the project's artifacts across the boundary; a NEEDS-EXPERIMENT item or new ablation routes back as one coordinated cross-repo step (append PLAN.md rows in the project **and** set the hub registry `state → active` in the same checkpoint, then commit + emit `replan`). The project may be re-entered multiple times during the paper phase — still `active → active`, no new lifecycle state.
