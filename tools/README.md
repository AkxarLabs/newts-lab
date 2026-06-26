# Hub tools

Mechanical checks for lab state and paper claims. The hub deliberately has no Python
environment of its own — invoke with uv's ephemeral env:

```bash
uv run --with pyyaml python tools/guard.py spawn|full-run|frozen|state|evolve|... <slug>  # mechanical lifecycle guards
uv run --with pyyaml python tools/check_lab.py            # registry/idea consistency lint
uv run --with pyyaml python tools/audit_claims.py studies/<slug>/paper [--check-commits]
uv run --with pyyaml python tools/show_config.py [<project-path> [exp-NNN.yaml]]  # 3-layer config + provenance
uv run --with pyyaml python tools/run_slots.py acquire|touch|release|status       # cross-project compute slots
uv run --with pyyaml python tools/s2.py search|bibtex|verify ...                  # literature API + citation audit
uv run python tools/lab_bus.py emit|inbox|ack ...                                # event bus / PI directives (dashboard)
uv run --with pyyaml python tools/agent_runner.py launch|list|kill ...           # optional headless programmatic agents
```

- `guard.py` — the enforcement layer for the highest-risk transitions (Gate-1 recorded before
  spawn, a signed Gate-2 envelope before a FULL run, frozen-set intact, legal lifecycle moves,
  append-only ledgers, write-back/evolve done, decision/plan-trace integrity). Exit 0 = proceed ·
  1 = blocked · 2 = warn. A guard never *grants* a gate, only confirms one is recorded.
- `check_lab.py` — used by `/lab-status`: detects registry↔IDEA.md state drift, orphan
  idea/project/paper dirs, and stale rows. Exit 1 = real inconsistency, fix immediately.
- `audit_claims.py` — used by `/review-paper` Part A: verifies every number in a paper's
  `claims.yaml` against the referenced run artifacts, and scans `main.tex` for unannotated
  numerals. Exit 0 all verified · 2 MANUAL items need human verification · 1 any FAIL or
  uncovered numeral (which blocks review).
- `s2.py` — Semantic Scholar (+ OpenAlex fallback) for `/lit-review` searches, `/write-paper`
  BibTeX, and `/review-paper` citation verification (`verify`: any nonzero exit blocks;
  `search`: exit 3 = both backends down, empty ≠ absence).
- `lab_bus.py` — the append-only event bus the optional dashboard reads (`emit` events,
  `inbox` PI directives, `ack` them). Best-effort and never required; see `docs/dashboard.md`.
  The same file ships into every project as `scripts/lab_bus.py` (auto-detects hub vs project).
- `agent_runner.py` — optional, PI-owned, OFF by default: launches a headless top-level agent
  (`claude` / `codex` / `opencode`) into a project repo for concurrent multi-project work; see
  `docs/autonomy.md`.
- **Write-back & finalization helpers** (run by the lifecycle skills, rarely by hand):
  `process_writebacks.py` / `hub_writeback.py` (reconcile project→hub write-backs), `sync_figures.py`
  + `lock_artifacts.py` (`/finalize` figure sync + cited-artifact locking), `trace_hook.py` (the
  best-effort activity tracer wired in `.claude/settings.json`).

Project-level helpers (sweep/compare/status/check_project) live in each project's `scripts/`.
