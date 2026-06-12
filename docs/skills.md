# Skills reference

The procedures of the lab, invoked as slash commands in Claude Code. Source of truth: `.claude/skills/<name>/SKILL.md` — these summaries link the pieces together.

## Orientation

### `/lab-status`
Reads the registry, latest notebook entries, and open questions; runs `tools/check_lab.py` and fixes drift; reports every non-final item with what unblocks it (gate-blocked items first) and recommends one next action. **Run at the start of any session.**

### `/configure [slug] [set key=value]`
Views the effective 3-layer config with provenance (`tools/show_config.py`) or edits the right layer. PI-owned keys (budgets, envelope, `eval_frozen`, critique settings) require explicit PI confirmation. See [Configuration](configuration.md).

## Ideation → proposal

### `/ideate [direction]`
Phased pipeline (depth from `ideation.*` config): **research** (knowledge mining + focused web scan) → **generate** (`ideation.candidates` mechanism-diverse candidates) → **reflect** (parallel fresh-context critic subagents per idea — novelty/feasibility/value skeptics) → **evolve** (revise or kill against critiques, `reflection_rounds` cycles) → **combine** (crossovers of complementary survivors) → **tournament** (pairwise ranking) → **triage** (top 1–3 persisted with their strongest surviving critique). Mirrors the co-scientist Generate/Reflect/Evolve/Rank loop.

### `/lit-review <slug>`
Iterative search (logged query-by-query, loop-until-dry), per-paper notes recording what each paper *actually shows* — these notes become the only permitted citation source later. Ends with an adversarial **novelty verdict** that gates progression. For load-bearing papers, calls `/critique-paper` in external mode.

### `/critique-paper <arXiv|URL|PDF|slug>`
Adversarial multi-lens critique of **any** paper. Spawns `fresh-context-reviewer` subagents — one per lens (novelty is always one, and must web-search the claimed contributions), each receiving *only* the paper's file path, never a summary. Scores anchored to the human mean (5.4); median aggregation; **minority veto** — any documented fatal flaw blocks accept unless refuted in writing. Ensemble size: `critique.ensemble_external` (3) for triage, `critique.ensemble_own_draft` (5) for our drafts.

### `/scope <slug>`
Deep design deliberation between lit review and proposal (state `scoping`). Enumerates every design-decision branch (framing, dataset, scale, baselines, metric/eval, recipe, ablation axes, compute), generates `scoping.options_per_decision` options per branch, deliberates each — optionally with one parallel **advocate subagent per option** — and records an ADR-style `decisions.md` (decision, rationale, rejected-because, revisit-if). Ends with an adversarial **value re-verification** (still novel/valuable/feasible?) — the cheapest kill checkpoint in the lifecycle. At most `scoping.max_open_questions` decisions may stay OPEN, each tied to the pilot that settles it.

### `/propose <slug>`
Assembles the proposal **from `decisions.md`**: frozen eval protocol (validation selects, held-out test reports), strongest fair baseline, staged experiment table with promotion criteria written in advance (OPEN decisions become pilot rows), ablation plan, budgets, kill criteria. Presents at **Gate 1** and stops; offers the optional Gate 2 envelope.

## Experimentation

### `/spawn-project <slug>`
Instantiates `templates/project/` at `<projects_root>/<slug>` (outside the hub), fills **`control.yaml`** (the project's end-to-end run config — created at setup) from the approved proposal, `git init` + `uv sync` + smoke + tests, then registers the path in the registry.

### `/experiment <slug> [exp-id]`
The core loop: read memory (ledger, registry, git log) → new immutable config per attempt → staged scale → record (ledger entry + one commit) → update PLAN. Hard constraints: debug cap, frozen eval/budgets (watchdog-enforced), kill-criteria checks after every pilot, multi-seed before any finding.

### `/improve <slug> [focus]`
Operator-driven iteration *after* the initial implementation: **draft** (mechanism-distinct lines), **debug** (ancestral-chain context only), **improve** (sibling-table context for diversity), **crossover** (combinations enter the ablation plan immediately). Complexity-adaptive prompting; parallel variants via `experiment-runner` subagents in git worktrees; merge-back through the journal (only the parent writes shared ledgers). Exits on plateau → `/analyze`.

### `/research-loop <slug>`
Unattended operation under a PI-signed `LOOP_BRIEF.md`. Fixed action priority (planned experiments → ablations → multi-seed confirmation → improve operators), zero-token monitoring, never-stop-within-budget, anti-burn backoff, PI morning report on exit. See [The workflow](workflow.md#unattended-protocol-research-loop).

## Analysis → publication

### `/analyze <slug>`
Reconstructs results **from artifacts only** (numbers carry run ids), checks each pre-written criterion, interrogates the interpretation (confounds, missing ablations, the cheapest experiment that could break the favored story), routes (more experiments / writing / kill), and distills to `lab/knowledge/`.

### `/make-figures <slug>`
All figures and tables, mechanically from `runs/` artifacts via the project's figure library: one tiny script per figure (the aggregator pattern), seed-band rules, booktabs tables emitted as `.tex` files the paper inputs — then a **multimodal self-review** of each rendered figure (trend supports the claim, legible at print size, complete, informative, consistent).

### `/write-paper <slug>`
Evidence-first drafting with ordering ablated in prior systems: figures/tables and a seeded bibliography first; **Method written first** (it degrades when written late); outline; Setup → Results → Ablations narrating the artifacts; **Related Work last** (the most hallucination-prone section); contributions-first intro; abstract last. Citations are `[cite: description]` placeholders resolved mechanically via `tools/s2.py`. Then ≤ `writing.max_reflection_rounds` verifier-gated reflection rounds — each one re-runs compile + chktex + the **claims audit** (revision is when fabrication happens) — and a blocking bibliography verification (`s2.py verify`: title match, year, retractions).

### `/review-paper <slug>`
Part A: mechanical claims audit (`tools/audit_claims.py`) + bib verification (`s2.py verify`) + phantom-experiment sweep — **blocking**. Part B: `/critique-paper` own-draft ensemble. Part C: **author-response triage** — every action item gets an evidenced ACCEPT / REBUT / NEEDS-EXPERIMENT verdict (feedback is validated, never obeyed); NEEDS-EXPERIMENT items become PLAN.md rows and route the idea back to `active` through the normal experiment machinery. Accept + zero unrefuted vetoes → **Gate 3**. Cycle cap: `critique.max_review_cycles`. See [the refinement loop](workflow.md#the-paper-refinement-loop-and-its-safeguards).

### `/finalize <slug>`
Reproducibility pass on the project repo (fresh `uv sync` → tests green → figures regenerate → tag `paper-v1`), knowledge write-back (including future-work threads → OPEN-QUESTIONS), a procedure retrospective (proposed edits to the skills themselves), registry → `final`.

## Subagents used by skills

| Agent (`.claude/agents/`) | Used by | Isolation contract |
|---|---|---|
| `fresh-context-reviewer` | /critique-paper, /review-paper | gets file path + lens only; writes its own review file; no Bash |
| `experiment-runner` | /improve, /research-loop | confined to its git worktree; returns a result packet; never touches shared ledgers |
