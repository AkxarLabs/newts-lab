# Newts' Lab — Design rationale

Why the repo is shaped the way it is: the goals, the prior art it draws on, and the design decisions that follow.

## 1. Goal

Automate the full research workflow — ideation → literature review → proposal → experimentation → analysis/ablations → paper writing → review → finalization — so that an AI agent (Claude Code) can drive it end-to-end, with the human as PI at a few explicit gates. The framework is domain-agnostic, and every project it spawns is reproducible and extensible by others.

## 2. Prior art, and what we took from each

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
| **Paper-writing systems** (PaperOrchestra, Jr. AI Scientist, freephdlabor, aiXiv) (2025–26) | Evidence-first drafting order; result tables emitted from artifacts; citation placeholders resolved against Semantic Scholar with a title-match gate; bounded review-and-revise cycles. | `/write-paper`'s evidence-first ordering, numbers-from-artifacts-only, placeholder→resolution→audit citation flow, and ≤3 verifier-gated reflection rounds (see §3.7). | Multi-agent, model-locked orchestrators bolted onto a no-orchestrator lab — we take the mechanisms, not the harness. |

### The synthesis in one paragraph

The field's consensus failure modes are: hallucinated results, metric gaming, unablated stacked changes, validation overfitting, weak autonomous ideation, and findings lost to context overflow. The consensus fixes are: artifact-traceable claims, fixed budgets, mandatory ablations, held-out test discipline, human gates at high-leverage points, and a persistent structured knowledge store. Newts' Lab is those fixes, encoded as **procedures (skills) + templates + a file-based state machine**, with git as the memory substrate — rather than as an orchestration program. The agent driving this *is already* an agentic loop (Claude Code); wrapping it in another Python orchestrator adds failure surface without adding capability. Karpathy's result — a bare repo + a Markdown protocol outperforming heavyweight harnesses — is the existence proof. When a project really is "optimize one number in one file," a spawned project degenerates gracefully into exactly that shape (one config axis, one metric, `/research-loop`): autoresearch is a special case of the lab, not a competitor.

## 3. Architecture

### 3.1 Hub and spoke

- **Hub (this repo):** ideation, lit reviews, proposals, papers, lab knowledge, procedures, templates, registry. One git repo.
- **Spokes (`<projects_root>/<slug>/`, default `../newts-lab-projects/`):** one per approved proposal, instantiated from `templates/project/`, each **its own git repo, outside the hub entirely**. Three reasons: (a) a project must be independently cloneable and reproducible by others; (b) experiment-per-commit history and run artifacts would bloat the hub; (c) projects can be archived or published independently. The location is a config key (`lab.projects_root`).
- The hub's `lab/REGISTRY.md` is the single index linking ideas ↔ projects ↔ papers ↔ states.

### 3.2 Procedures as skills, not orchestration code

Each pipeline stage is a Claude Code skill (`.claude/skills/<name>/SKILL.md`) — an executable, human-editable procedure. This generalizes the `program.md` idea: the human improves the *procedures*; the agent executes them with judgment. Benefits over a Python pipeline: procedures degrade gracefully (the agent adapts when reality deviates), they're diffable and reviewable, and improving the lab means editing Markdown.

### 3.3 State machine + registry

States: `seed → triaged → lit-review → scoping → proposal → active → analysis → writing → internal-review → final`, plus `parked`/`killed` from anywhere. State lives in two places, deliberately redundant: each idea's `IDEA.md` frontmatter (local truth) and `lab/REGISTRY.md` (global index). Every procedure ends by syncing both.

### 3.4 Three PI gates

1. **Proposal approval** — before compute is spent (human checkpoints are the cheapest quality lever; Agent Laboratory measured +0.6 review points from them).
2. **Full-scale launch** — smoke/pilot are cheap and autonomous; FULL runs burn real compute and need sign-off (CodeScientist's gating).
3. **Finalization** — nothing leaves the lab without the PI reading it (human accountability for AI-generated work).

Everything between gates is autonomous.

### 3.5 The knowledge layer (anti-amnesia)

`lab/knowledge/` is a minimized world model:

- `FINDINGS.md` — confirmed results, each with an artifact pointer.
- `FAILURES.md` — what didn't work and the diagnosed reason (this is what makes the *next* project smarter; most systems lose it entirely).
- `OPEN-QUESTIONS.md` — threads worth pursuing, feeding the next `/ideate`.
- `REFERENCES.md` — a shared, append-only **reading index**: one row per paper worth remembering, logged during `/ideate` scans and `/lit-review`, so reading compounds across ideas instead of being re-fetched. Unlike the three above it is not a *triggered* write-back operator — it has no kill/result gate and is maintained continuously.
- `lab/notebook/YYYY-MM-DD-*.md` — session journal (raw, chronological).

The flow is notebook (raw) → knowledge (distilled) → next ideation (compounding), which closes the meta-review loop without standing agents.

### 3.6 Experiment loop (the operators)

Operator quality is the bottleneck (AIRA), so the `/experiment` procedure encodes the operators precisely:

- **Staged scale:** SMOKE (≤ minutes; verifies pipeline + artifact writing) → PILOT (small but statistically informative; where most ideas die) → FULL (PI-gated). Promotion criteria written in the proposal *before* running.
- **Keep/discard via git:** one commit per experiment attempt; revert if the ledger doesn't justify keeping it. `git log` + `EXPERIMENT_LOG.md` + `runs/registry.jsonl` are read *before* proposing the next experiment (scoped memory: ledger = sibling history; the failing experiment's own thread = ancestor chain).
- **Debug policy:** max 3 consecutive fix attempts, then record-and-move-on.
- **Anti-gaming rules:** budgets, seeds, eval code, and test sets are frozen per proposal; changing them requires a PI flag, not an edit.
- **Multi-seed confirmation** (≥3 seeds) for any number destined for a paper.
- **Ablations are a stage, not an afterthought** — every kept change appears in the ablation plan.

### 3.7 Writing & review

- The paper lives in `studies/<slug>/paper/` (hub), built from artifacts in the project repo. Figures and tables are *generated by committed scripts* from `runs/` artifacts — never hand-made — which removes the hallucinated-numbers class of failure at the source.
- **Evidence-first ordering:** bib seeding → Method first → outline → results sections → Related Work last. Whole-paper single passes degrade the Method section; early Related Work invites invention.
- **Numbers never pass through prose:** result tables are emitted as `.tex` from artifacts (`figures.emit_table`) and `\input`, eliminating transcription error.
- **Citations: placeholder → mechanical resolution.** `[cite: description]` inline, resolved via Semantic Scholar with a title-match gate, then a blocking zero-assumption audit. Free-generated citations are a documented fabrication source (~18% fabricated references measured for GPT-4), so the bib is verified against the resolver, never trusted from the model. Citations come only from the lit-review notes, which record how each paper was found and what it says.
- **Verifier-gated reflection, ≤3 rounds, claims re-audit every round.** Refinement gains plateau by round 3 and regress after; revision is also when fabrication happens (a writer can invent ablations in response to reviewer feedback). So `tools/audit_claims.py` runs after every revision round, plus a phantom-experiment sweep over ablation/analysis subsections in `/review-paper`.
- **Interpretation hedging:** interpretive statements are markedly more error-prone than data statements (Kosmos: 57.9% vs 85.5% accuracy), so discussion claims must point at evidence or be marked conjecture.
- **The review itself:** `claims.yaml` maps every quantitative claim → run id + artifact path, audited mechanically before the NeurIPS-form qualitative review. Reviewers are fresh-context subagents (one per rubric lens, a web-search-obligated novelty lens among them), with an adversarial "build the case for rejection" charge, an explicit calibration anchor table, **median aggregation**, and a **minority veto** — any reviewer-documented fatal flaw blocks accept unless refuted in writing. This counters the measured LLM-reviewer pathologies: leniency, the novelty blind spot, and same-session anchoring.

### 3.8 Reproducibility & extensibility (project template)

- `uv` + `pyproject.toml` + lockfile; pinned Python.
- Every run = one YAML config; the runner dumps the resolved config + git SHA + seed into `runs/<run_id>/` and appends one line to `runs/registry.jsonl` (committed). The artifact dir — not any tracker — is the source of truth.
- New experiments = new configs / new modules behind interfaces; baseline code paths stay runnable forever (any past experiment re-runnable from its config after any later change).
- A smoke test in `tests/` lets a stranger (or a future agent) verify the pipeline in minutes.
- Local-first tracking (JSONL + generated plots); wandb optional, never load-bearing.
- Environment provenance: every run records the Python version, platform, and (when importable) torch/CUDA + GPU name, alongside the git SHA, dirty-tree `code.patch`, and seed.

### 3.9 In-project autonomy (the `explore` loop mode)

Beyond executing an approved plan, the loop can — when authorized — invent new directions from results and re-plan inside one project. `LOOP_BRIEF.md` carries `Mode: execute | explore` (default `execute`). In `explore`, when the plan is exhausted with budget left, the loop's operator menu gains two operators (also available to manual `/improve`):

- **`expand`** — a results-grounded ideation pass proposes new mechanism-distinct lines (each with a pre-written criterion) instead of stopping.
- **`revisit`** — when artifacts satisfy a settled decision's `decisions.md` `Revisit if:` trigger, the decision is reopened (new `D-NNN`, dependents retired, seed replacements).

The autonomy boundary is mechanical, not a per-cycle judgment: each decision is flagged `Headline: yes/no` at scope time (headline = load-bearing for the central hypothesis the novelty rests on). Reopening a *non-headline* decision and expanding the frontier are autonomous within the frozen set and the Gate-2 envelope; reopening a *headline* decision, touching the frozen set, or exceeding the envelope escalates (a PI note, or under a signed campaign the delegation-bounds + overseer check that guards a Gate-1 self-approval). Selection discipline binds *harder* here — every expanded line still tunes on validation, reports on the frozen test, and needs multi-seed before a paper claim; expansion rounds are capped because longer search overfits validation. `explore` is default-off, so a lab opts into it only by signing a brief that says so.

### 3.10 The hub↔project boundary

The hub holds the paper; the project holds its evidence — and a paper must not silently depend on a live, mutable project repo. Four mechanical seams, invoked by the existing procedures (no new lifecycle state, no relaxed gate):

- **Figures synced with a manifest.** `/make-figures` runs `tools/sync_figures.py <slug>`, copying the project's `figures/*.{pdf,tex,png}` into `studies/<slug>/paper/figures/` and recording a `.manifest.json` (source path + sha256 + project commit). `/write-paper` and `/review-paper` run `sync_figures.py <slug> --check` before the claims audit — a stale or diverged hub figure blocks like a failed audit.
- **Cited artifacts archived at finalize.** `/finalize` runs `tools/lock_artifacts.py <slug>` (each `claims.yaml`-cited `runs/<id>/metrics.json` copied into committed `studies/<slug>/paper/artifacts/`, with a locked `artifact_sha256` per claim), then `audit_claims.py … --verify-hashes`. After finalization the paper is auditable from the hub alone, even if the project repo later moves.
- **Write-back via one atomic tool.** A project session calls `tools/hub_writeback.py --slug <slug> …` to append the hub notebook/knowledge entry and set the registry row atomically; if the hub is unreachable it leaves a `HUB-WRITEBACK-PENDING:` block in `EXPERIMENT_LOG.md`, reconciled at the next hub-session orientation by `tools/process_writebacks.py --apply` (append-only). Only the parent merges, so subagent rule 3 is untouched.
- **Bidirectional escalation.** A project loop blocked mid-run (a `Headline: yes` reopen, a block on a frozen/PI-owned setting, or FULL work outside the envelope) emits `lab_bus.py escalate` alongside its local PI note, so the request reaches the hub without waiting for loop exit. Escalation requests attention; it is never gate approval.

The back-half of the lifecycle (`analysis → writing → internal-review`) runs in a hub session reading the project's artifacts across the boundary; a NEEDS-EXPERIMENT item or new ablation routes back as one coordinated cross-repo step (append PLAN.md rows in the project **and** set the hub registry `state → active` in the same checkpoint, then commit + emit `replan`). The project may be re-entered multiple times during the paper phase — still `active → active`, no new lifecycle state.

### 3.11 The event bus & the dashboard

An optional, file-based signal layer makes the lab observable without becoming a second source of truth. The governing principle: **the files are the source of truth; the dashboard only reads them.**

- **The bus** is append-only JSONL under gitignored `lab/.bus/` (hub) and `<project>/.bus/` (each project). **Mechanical emitters** (`scripts/run.py`, `sweep.py`, `tools/run_slots.py`) fire from code, so the signal is truthful even when an agent forgets to narrate; **agent emitters** (`lab_bus.py emit`) add the judgment events (registry changes, gate stops, kills, write-backs, pivots).
- **The dashboard** (`dashboard/serve.py`, stdlib + a no-build Canvas-2D frontend) tails those files and rebuilds its whole world model on every request — no database of its own. Delete `dashboard/` and the lab is unchanged.
- **Control is layered honestly.** The dashboard is a local server and cannot run an agent skill, so it works in three tiers: (1) **structured commands** appended to the bus as `kind:"command"` directives the running agent executes in-protocol at its next checkpoint; (2) **read-only tools** (`check_lab`, `status`, `compare`, `show_config`, `inbox`) run as side-effect-free subprocesses; (3) **PI gate approval** for Gate 1 and Gate 2 recorded directly (the server binds localhost and is driven by the PI). **Gate 3 is never signable from the dashboard** — sending anything outside the lab is always a session act. A directive is subordinate to gates and hard rules; it can steer, never sign a gate or change a frozen setting.
- **Per-worker traceability** is a separate, dashboard-independent capability: Claude Code hooks (`tools/trace_hook.py`, shipped identically in the project template) log each agent's and subagent's tool actions to one file per worker (`.bus/workers/<id>.jsonl`). The harness writes these, not the subagents, so subagent rule 3 holds; they are best-effort, never block a tool call, and are local/disposable. The dashboard aggregates them into `snapshot().workers[]`.

## 4. What we deliberately did NOT build

- **No orchestrator program / no daemon.** The agent session is the orchestrator. Adding one would re-create Sakana v1's brittleness. The ephemeral, scoped subagents (fresh-context reviewers, worktree experiment runners) are single-task tools spawned and merged by the parent session, not standing roles.
- **No multi-agent personas.** One agent, many procedures.
- **No database.** Markdown + JSONL + git. Inspectable, diffable, survives tooling churn.
- **No domain assumptions.** Domain-specific scaffolding (model recipes, eval harnesses) belongs in a project type or in the first spawned project — not in the framework.
- **No vendored heavyweight dependencies.** External systems are sources of *mechanisms*; the lab's tools stay stdlib + pyyaml, and code is vendored only when a piece is clean, light, and load-bearing (and its license permits).

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Agent games metrics (seed/timeout/eval edits) | Hard rules 4–6 in CLAUDE.md; frozen eval protocol per proposal; review audits the diff history |
| Validation overfitting over long projects | Held-out test never read by the loop; selection discipline rule; multi-seed confirmation; capped expansion rounds in `explore` |
| Knowledge loss across sessions/context | Registry + notebook + knowledge write-back as a mandatory session-end step |
| Weak autonomous ideation | Tournament ranking + lit grounding + OPEN-QUESTIONS feedback; PI gate before any spend |
| Hallucinated paper content | `claims.yaml` audit + script-generated figures + citation-from-notes-only + per-revision re-audit |
| Runaway cost | Staged scale with PI gate before FULL; budgets in proposal; debug-depth cap; anti-burn backoff in loops |
