# AutoScientist — Design Document

*Why this repo is shaped the way it is. Written 2026-06-12, after a survey of the autonomous-research landscape.*

## 1. Goal

Automate the full research workflow — ideation → literature review → proposal → experimentation → analysis/ablations → paper writing → review → finalization — such that an AI agent (Claude Code) can drive it end-to-end, with the human as PI at a few explicit gates. The framework must be domain-agnostic, and every project it spawns must be reproducible and extensible by others.

## 2. Prior art surveyed, and what we took from each

| System | Core mechanism | What we adopted | What we rejected |
|---|---|---|---|
| **Sakana AI Scientist v1** (2024) | Linear pipeline: idea gen → Semantic Scholar novelty check → Aider experiment loop (5 runs, 4 retries) → LaTeX writeup → NeurIPS-form LLM reviewer. Human-built "templates" per domain. | The lifecycle decomposition; the NeurIPS-form structured reviewer with ensemble + meta-review; novelty check against literature before investing. | Rigid domain templates; review that doesn't gate anything; single-shot linearity. Independent audits found 42% experiment failures and 57% of papers with hallucinated numbers — hence our traceability hard rule. |
| **Sakana AI Scientist v2** (2025) | Template-free best-first tree search (BFTS) over experiment nodes (draft/debug/improve), 4 stages (preliminary → tuning → research agenda → ablations), stage-completion checks, multi-seed confirmation of best nodes, VLM figure feedback. First AI paper to pass (workshop) peer review. | The staged experiment progression; debug-depth limits (max 3) and debug-vs-explore balance; multi-seed confirmation before promoting results; figures reviewed, not just generated. | Running the full tree search blind — we keep the agent's judgment in the loop instead of a fixed search policy (see AIRA below for why). |
| **Karpathy's autoresearch** (2026) | Radical minimalism: agent edits one file (`train.py`), human edits one file (`program.md`), fixed 5-min budget per run, one metric (`val_bpb`), **git commit/reset as keep-discard and memory**, "NEVER STOP" directive. *(Provenance note: the `results.tsv` ledger and the "8-agent org" experiment are community-sourced reconstructions, not official-README claims; the seed-hacking incident IS official — repo discussion #43, agent changed seed 42→137 for a fake gain.)* | Git-as-memory; append-only results ledger; fixed budgets for comparability; "human programs the org, agent programs the experiment"; single human-edited control file (our `CLAUDE.md` plays the `program.md` role). The confirmed seed-hacking incident and the unablated-stacking risk became hard rules 4, 6 and the mandatory-ablations stage. | One-file scope — too restrictive for multi-stage research projects; no lit review or writing. |
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
- **Spokes (`<projects_root>/<slug>/`, default `../AutoScientist-Projects/`):** one per approved proposal, instantiated from `templates/project/`, each **its own git repo, outside the hub entirely** (v3 change — previously a gitignored `projects/` subdir). Rationale: (a) a project must be independently cloneable/reproducible by others — that's a stated goal; (b) experiment-per-commit history and run artifacts would bloat the hub; (c) projects can be archived/published independently. The location is a config key (`lab.projects_root`).
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

Where AutoScientist now stands against the systems surveyed in §2, and what remains deliberately or temporarily missing.

**Covered, with the field's best mechanism:** lifecycle decomposition + gated autonomy (Agent Laboratory's copilot data); template-free but contract-ful experimentation with journals, debug caps, multi-seed (Sakana v2, AIDE); operator-quality focus with scoped memory (AIRA); git-as-memory + budgets-as-facts (autoresearch); fresh-context ensemble review with calibration + minority veto (OpenReviewer/CCR/Sakana reviewer lineage); claim→artifact mechanical audit (Kosmos's traceability, mechanized); compounding knowledge store (Kosmos world model, minimized); multi-agent ideation with reflection/evolution/combination + tournament ranking (co-scientist's Generate/Reflect/Evolve/Rank, v4); ADR-style design deliberation before commitment (`/scope`, v4 — no surveyed system does this explicitly; closest is CodeScientist's human plan-editing); cross-project compute slots (v4); cross-agent operability via AGENTS.md (autoresearch's any-agent stance, v4).

**Known gaps, by choice or for later** *(updated v5, 2026-06-13)*:

1. **Persistent idea Elo** — tournament results are per-session; co-scientist maintains a standing ranked population. Add when idea volume justifies it (registry column + tournament history file).
2. **Multi-lab sharing (AgentRxiv)** — collaborating lab instances exchanging reports gave +13.7% on MATH-500. A future `lab/exchange/` + a fetch procedure could replicate it; single-lab for now.
3. ~~Literature API tooling~~ — **closed (v5)**: `tools/s2.py` (S2 search/bulk with OpenAlex fallback, mechanical BibTeX, zero-assumption citation verification incl. retraction checks). PaperQA2-class claim-level contradiction detection remains future work.
4. **Benchmark harness (AstaBench/MLE-bench-class)** — no standardized self-evaluation of the lab itself; the procedure retrospective in `/finalize` is the lightweight substitute.
5. ~~VLM figure review~~ — **closed by PI decision (v5)**: no dedicated lens; current models are natively multimodal, so figure inspection is folded into `/make-figures` self-review and the reviewers reading the compiled PDF.
6. **Domain template** (`templates/project-slm/`) — still pending the first real SLM project stabilizing its patterns (deliberate: extract, don't speculate).
7. **Cost telemetry** — token/$ accounting per stage (CodeScientist's hard cost caps); currently only compute budgets are enforced, not API spend.

### v5 addendum — the writing layer (research pass 2026-06-13)

A dedicated survey of paper-writing systems (PaperOrchestra/Google 2026, Jr. AI Scientist, freephdlabor, aiXiv, CycleResearcher, APRES, PaperRecon; plus the citation-auditing literature) reshaped `/write-paper` and added `/make-figures`:

- **Evidence-first ordering** (Jr. AI Scientist's ablated finding): bib seeding → Method first → outline → results sections → Related Work last. Whole-paper single passes measurably degrade the Method section; early Related Work invites invention.
- **Numbers never pass through prose**: result tables are emitted as `.tex` from artifacts (`figures.emit_table`) and `\input` — the mechanism that eliminated numerical transcription errors in Jr. AI Scientist.
- **Citations: placeholder → mechanical resolution** (freephdlabor's pattern): `[cite: description]` inline, resolved via S2 with a title-match gate (PaperOrchestra used 0.7 Levenshtein; we verify the final bib at 0.85), then a blocking zero-assumption audit (the citation-auditing protocol hit 91.7% verification on real papers; LLM free-generation fabricates ~18%).
- **Verifier-gated reflection, ≤3 rounds, claims re-audit every round**: refinement gains plateau by round 3 and regress after; worse, **revision is when fabrication happens** — Jr. AI Scientist documented the writer inventing ablations in response to reviewer feedback (and the review score going *up*), with phantom experiments hiding in ablation/analysis subsections. Hence: `audit_claims.py` after every revision round, and a phantom-experiment sweep in `/review-paper`.
- **Interpretation hedging**: Kosmos's audit found interpretive statements ~3× more error-prone than data statements (57.9% vs 85.5% accuracy) — discussion claims must point at evidence or be marked conjecture.
- **Reviewer-in-the-loop revision is worth it when audited**: aiXiv measured 10%→70% acceptance through revise-and-respond cycles; LLM-REVal +0.3–0.4 score from review-guided revision — the existing `/review-paper` cycle matches this evidence, now with the fabrication guard.

## 9. External code policy & the autoresearch comparison (v6)

### Using other systems' code directly — verdicts (licenses checked 2026-06)

Policy: AutoScientist stays a content-and-protocol template with stdlib+pyyaml tools; external systems are sources of *mechanisms* first, dependencies only when a piece is clean, light, and load-bearing.

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

### How AutoScientist compares to Karpathy's autoresearch

They solve different problems and agree on the physics. **autoresearch** is one experiment loop perfected: one editable file, one metric, a fixed per-run budget, git as keep/discard memory, an overnight never-stop loop — and *no* lit review, no hypothesis management, no paper, no gates, single-project by construction. **AutoScientist** is the surrounding research organization: ideation through publication with the human at three gates — and its inner experiment loop (`/research-loop` + `/improve` + watchdog + ledgers) is essentially autoresearch's invariants generalized: git-as-memory → per-attempt commits + append-only ledgers; one metric → a frozen eval protocol per project; 5-minute budget → watchdog-enforced per-stage budgets; `program.md` → `CLAUDE.md`/`AGENTS.md` + `control.yaml`; never-stop → never-stop-within-envelope with anti-burn backoff (his loops' observed micro-tweak spiral is why the backoff exists). What autoresearch has that we deliberately preserve as an ideal: radical smallness — when a project really is "optimize one number in one file," a spawned AutoScientist project *degenerates gracefully into exactly that shape* (one config axis, one metric, `/research-loop`), which is the correct relationship: autoresearch is our special case, not our competitor.

## 10. Operation modes & project-side autonomy (v8)

Two questions drove this wave: *"how does `/autopilot` relate to Claude Code's built-in `/loop`?"* and *"can the spawned project run itself?"*

**Skills vs `/loop` — complementary layers.** The built-in `/loop` is a session-scoped scheduler (`/loop [interval] <prompt-or-skill>`; fires while the session is open and idle; 7-day expiry; restored on `--resume`). It carries no domain semantics: no gates, no signed budgets, no resumable state. Our skills are the opposite layer — procedure + authorization (campaign brief, gate delegation, append-only ledgers, morning report) with no scheduler. The design composes them rather than rebuilding either: `/autopilot` signs the brief interactively, then `/loop 30m /autopilot continue <campaign-file>` provides crash-resilient re-entry, each firing resuming from the Campaign Log. Telling users to "just use `/loop`" would hand them the scheduler without the authorization layer — exactly the unattended failure mode the briefs exist to prevent.

**Modes are entry points, not state.** Manual (per-skill), stage-gated (`/advance`: one lifecycle stage, then a hard stop with a verification summary — never crossing a PI gate), project loops (`/research-loop`, `/improve`), full `/autopilot`. Plus `/adopt` for entering mid-lifecycle with existing work: scaffold the prerequisites, record skipped stages as PI-waived, never waive gates or traceability (pre-existing numbers without artifacts become reproduction rows, not citations). No `autonomy.mode` config key exists on purpose — a mode is which command you type, so switching modes mid-project is free and the protocol stays single.

**The project is self-operating.** Each spawned repo ships `CLAUDE.md` (project protocol: orientation order, autonomy bounds from control.yaml, subagent policy, hub write-back) and `AGENTS.md` (cold-start checklist + non-Claude notes), so `cd project && claude` needs no hub context; `scripts/check_project.py` is the mechanical readiness lint. The optional `SYSTEM.md` (lab-level, copied at spawn) is the PI's prose description of the machine — binding like control.yaml, PI-owned, presence-detected rather than configured. The subagent decision (parallel worktree variants vs sequential) belongs to the implementation agent, bounded by `parallelism.max_parallel_subagents` and compute slots.
