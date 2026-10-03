# Tools

Mechanical helpers — small, stdlib+pyyaml-only scripts. Hub tools run via uv's ephemeral env (nothing to install); project helpers ship inside every spawned project.

## Hub tools (`tools/`)

### `audit_claims.py` — verify a paper's numbers against artifacts

```bash
uv run --with pyyaml python tools/audit_claims.py studies/<slug>/paper [--rel-tol 1e-3] [--check-commits]
```

For every claim in the paper's `claims.yaml`, each number must be found in the referenced run artifacts (resolved via `lab.projects_root`):

| Status | Meaning | Exit |
|---|---|---|
| `PASS` | number found directly in an artifact (tolerance = half-ULP of printed precision) | 0 if all pass |
| `PASS-derived` | matches the mean/std of a metric across the claim's artifact list (the "mean over N seeds" case) | 0 |
| `MANUAL` | no match but a derivation is stated — a human must verify; never silently passed | 2 |
| `FAIL` | artifact missing or no match (closest value reported) | 1 |

`/review-paper` Part A runs this and **blocks** the qualitative review on any FAIL or unresolved MANUAL. This is the mechanical teeth behind "every number traces to an artifact." `--scan-integers` additionally flags bare integers sitting near result words (samples/tasks/runs/seeds/…), excluding years (1900–2099) and structural refs — off by default (integers otherwise swamp the scan with counts and section numbers).

`--scan-novelty` extends the same idea from numbers to **novelty**: it flags priority/superiority claims in `main.tex` prose — *state-of-the-art*, *"first to"*, *outperforms all*, *unprecedented*, *best-known* — that carry no `\cite` (positioning them against the prior work they claim to beat) or `% Cnnn/Nnnn` backing (a traced number, or a `% Nnnn` lit-review novelty pointer). Each is a **WARN (exit 2)** — the discovery-vs-rediscovery gate: `/write-paper` surfaces it while drafting, `/review-paper` + `/finalize` block on an unresolved one, so a "we're first / SOTA" claim must trace to the `/lit-review` novelty verdict exactly as a number traces to an artifact (a mechanical answer to the field's most public failure: rediscovery shipped as discovery). Zero LLM cost — a regex lint, conservative by design (`novel` alone is too common to flag).

### `audit_multiseed.py` · `audit_ablation_coverage.py` · `audit_eval_discipline.py` — paper integrity

```bash
uv run --with pyyaml python tools/audit_multiseed.py         studies/<slug>/paper
uv run --with pyyaml python tools/audit_ablation_coverage.py studies/<slug>/paper
uv run --with pyyaml python tools/audit_eval_discipline.py   studies/<slug>/paper
```

Three focused audits that mechanize the hard rules `audit_claims.py` doesn't cover — each exits **0 clean · 2 needs-human-review · 1 violation**:

- **multi-seed** (hard rule 6): a claim marked `headline: true` in `claims.yaml` must be backed by ≥ `seeds.multi_seed_n` (project) / `experiment.multi_seed_n` (lab, default 3) distinct seeds — resolved by mapping each artifact's `runs/<run_id>/…` to its seed in `runs/registry.jsonl`. A `multi_seed_waiver:` (rationale) routes to MANUAL.
- **ablation coverage**: every bullet under the proposal's `### Planned ablations` must leave a trace in the project's `PLAN.md`/`EXPERIMENT_LOG.md`, be marked waived/N-A/dropped, or route back — none silently dropped (heuristic; the reviewer reads the table).
- **eval discipline** (hard rule 5): the frozen `§4` protocol must define both a validation and a held-out test set, and no `headline` claim may declare `split: validation` (reporting a selection-time metric). Theory/simulation types relax to MANUAL (the TYPE card defines the analogue).

New optional `claims.yaml` fields these read: `headline: true` (marks a load-bearing claim), `split: test|validation` (which set it's reported on), `multi_seed_waiver: <rationale>`. Wired **WARN** in `/write-paper` (surface gaps while drafting) and **blocking** in `/review-paper` Part A + `/finalize`.

### `check_lab.py` — lab state lint

```bash
uv run --with pyyaml python tools/check_lab.py [--stale-days N] [--strict]
```

Checks registry↔IDEA.md state agreement, orphan study/project dirs (`studies/<slug>/` in the hub and projects scanned at `lab.projects_root`; transient `-wt-` worktrees ignored), and stale rows. Exit 1 on real inconsistencies. `/lab-status` runs it every session.

### `run_slots.py` — cross-project compute coordination

```bash
uv run --with pyyaml python tools/run_slots.py acquire <project> <label>   # exit 1 = denied
uv run --with pyyaml python tools/run_slots.py release <slot-id>
uv run --with pyyaml python tools/run_slots.py status
```

Within a project, the experiment loop controls its own runs; the hub-level risk is two projects (or a loop plus an interactive session) launching training on the same GPU. One slot = one training campaign (a run **or** a sweep — the sweep manages its own internal parallelism); the cap is `compute.max_concurrent_runs`. Slots are files under `lab/.slots/` (atomic create, stale-reclaimed after `compute.stale_slot_minutes`). Hard rule 13: acquire before any PILOT/FULL campaign, release when the ledger entry is written; SMOKE is exempt; subagents never manage slots — the parent does. **`scripts/run.py`/`sweep.py` now acquire/release a slot automatically** for direct PILOT/FULL runs (a sweep holds one campaign slot its children inherit via `AUTOSCIENTIST_SLOT_HELD`), so the ledger can't be bypassed by calling the runner directly; the manual commands remain for status checks and hand-run campaigns.

### `s2.py` — literature search, BibTeX, citation verification, cite-from-lit-review lint

```bash
uv run --with pyyaml python tools/s2.py search "small LM distillation" [--limit 10] [--year 2023:] [--bulk]
uv run --with pyyaml python tools/s2.py bibtex arXiv:2504.08066 [--append studies/<slug>/paper/references.bib]
uv run --with pyyaml python tools/s2.py bibtex DOI:10.48550/arXiv.2504.08066   # the agentic websearch→DOI fallback
uv run --with pyyaml python tools/s2.py verify studies/<slug>/paper/references.bib [--threshold 0.85]
uv run --with pyyaml python tools/s2.py citecheck studies/<slug>/paper
```

Semantic Scholar Graph API with OpenAlex fallback. `search` gives `/lit-review` replayable, logged queries (title/year/venue/citations/TLDR per hit); it exits **3** when *both* backends are unreachable, so an empty result is never mistaken for "no prior work".

`bibtex` returns the canonical entry for a paper id — no hand-typed bibliography — through a **keyless fallback chain**: Semantic Scholar `citationStyles` → **doi.org content-negotiation** → **Crossref** transform → **OpenAlex** (reconstructed from fields), so it works with no API key even when S2 is down or throttling a keyless caller. arXiv ids resolve via their DataCite DOI (`10.48550/arXiv.<id>`). `--append <references.bib>` writes the entry straight into the bib (dedup'd by key/DOI) and prints the `cite-key` to add to the paper. When a paper has no usable id/DOI, the resolver prints the **agentic fallback**: web-search the title for its DOI, then `bibtex DOI:<doi> --append …` — you supply the DOI, the script fills the entry.

`verify` is the zero-assumption citation audit `/review-paper` runs: every bib entry title-matched against the real record (pass `--threshold <writing.citation_match_threshold>`), year-checked, and retraction-checked via OpenAlex `is_retracted`. **Any nonzero exit blocks** — NOT-FOUND/RETRACTED *and* MISMATCH (near-miss/wrong-year). Free-generated LLM citations are fabricated at ~18% base rate — this check is blocking, not advisory.

`citecheck` is the **cite-from-lit-review** lint: every `\cite` in the paper's `.tex` must resolve to a `references.bib` entry (**DANGLING** → exit 1) and to a `studies/<slug>/lit-review.md` note (matched by DOI/arXiv id, else ≥70% title-word overlap; **UNGROUNDED** → exit 2, the by-hand confirm list). Catches a citation that's real but was never in the lit review.

Env keys: `S2_API_KEY` (keyless S2 shares a saturated global pool; backoff built in), `OPENALEX_API_KEY` (required for OpenAlex calls since 2026-02 — **without it the OpenAlex fallback and the retraction check silently degrade; the keyless doi.org + Crossref bibtex paths still work**).

### `show_config.py` — 3-layer config with provenance

```bash
uv run --with pyyaml python tools/show_config.py [<project-path> [exp-NNN.yaml]]
```

Prints the lab layer, the project's control.yaml, the effective skill values (control-first, lab fallback), and — given an experiment — the fully resolved run config with the layer that set each key. Backs `/configure`. See [Configuration](configuration.md).

### `profiles.py` — budget tiers & engine config profiles

```bash
uv run --with pyyaml python tools/profiles.py list|show <name>|diff <name>|validate <name>|apply <name>|save <name>
```

Named, *partial* bundles of `lab/config.yaml` overrides (built-ins in `lab/profiles/`): budget tiers (`low`/`medium`/`high`, scaling agent/subagent counts, parallelism, per-role model strength) and engine presets (`claude-*`/`codex`/`opencode`/`mixed`, setting the headless backend). `apply` **stamps each value into `lab/config.yaml` in place — comments preserved** (no YAML round-trip that would strip the documented reference file), **syncs the `.claude/agents/*.md` `model:` frontmatter** for per-role model changes, and **refuses any profile that lowers an integrity floor** (`multi_seed_n` < 3, `oversight: off`, touching `eval_frozen`/`gate2_envelope`) — budget scales exploration, never rigor. `save` snapshots the current settings as a new named profile. Backs `/configure profile …`. See [Configuration → Profiles](configuration.md).

### `guard.py` — mechanical lifecycle guards

```bash
uv run --with pyyaml python tools/guard.py <spawn|full-run|release-full-run|frozen|state|append-only|writeback|evolve|decisions|plan-trace|finalization> <slug> [args]
```

The lock on the door behind the prose: the highest-risk rules turned into checks called at the risky transitions — `spawn` (Gate 1 recorded before `/spawn-project`), `full-run` (a signed, unexpired Gate-2 envelope before any FULL run; with `--config/--planned-runs/--planned-minutes` it also **accounts** the request against prior FULL rows + active reservations vs the envelope's per-run/total/count caps, and `--reserve` books capacity so a concurrent sweep can't double-spend it), `release-full-run <slug> <id>` (releases such a reservation once its runs have landed), `frozen` (`eval_frozen` + PI-owned blocks intact), `state from→to` (a legal lifecycle transition), `append-only` (ledgers only appended), `writeback` (rule 11 done), `evolve` (rule 11's three triggered write-back operators fired where the state demands — BLOCK on a `killed` row with no CORRECTION in FAILURES.md/NOTES, WARN on a results-stage row with no RECIPE in FINDINGS.md/NOTES), `decisions` (settled non-headline decisions carry a machine-checkable Revisit predicate; `--strict` blocks on a missing one), `plan-trace` (every non-baseline PLAN.md row traces to a `D-NNN`/`(expand Rn)` origin; a `Headline-change: yes` row bypassing `/propose` is blocked), `finalization` (**Gate 3** — never an agent's; a campaign's delegated record counts only while `tools/gate3.py` says that campaign still delegates it — blocks unless the state is right (`internal-review`, or `active`+`target.active` for target-driven), a Gate-3 marker is recorded (a `gate 3 approved` line in the meta-review / a target's `final_run_id`) or `--pi-approved` is passed, **and** `AUTOSCIENTIST_NO_GATE3` is unset — the executor sets that env on every launched agent, so a headless agent can never finalize). Exit **0 = proceed · 1 = blocked · 2 = warn**. A guard never *grants* a gate — it only confirms one is already recorded, or refuses an unsafe move. **The project runners enforce this too:** `scripts/run.py`/`sweep.py` call `full-run` (Gate 2) and `run_slots.py acquire` (hard rule 13) before any FULL / PILOT+FULL run, so neither can be bypassed by invoking the runner directly (SMOKE is exempt).

### `configure.py` — owner-aware config view/set/profile

```bash
uv run --with pyyaml python tools/configure.py view [--project <slug|path>] [--experiment <yaml>]
uv run --with pyyaml python tools/configure.py set <key=value> [--project <slug|path>] [--pi-approved] [--signed-via <path>]
uv run --with pyyaml python tools/configure.py profile <list|show|diff|apply|save> [<name>]
```

The mechanical half of `/configure`. `view` wraps `show_config.py` (effective 3-layer config + provenance). `set` stamps ONE value into the right layer — `lab/config.yaml` or a project's `control.yaml` (`--project`) — **preserving comments** (reuses `profiles.stamp`), and **refuses a PI-owned key without `--pi-approved`** (the ownership map mirrors the Owner column in [Configuration](configuration.md): `lab.*`/`compute.*`/`agents.*`/`critique.*`/`budgets.*`/`gate2_envelope.*`/`oversight.level`/`writing.page_limit`/`writing.venue`/`eval_frozen`/`loop.mode`/`loop.explore_*`/`ideation.in_project*`/`autopilot.max_concurrent_projects` — but *not* the agent-readable `loop.no_progress_backoff_cycles` etc.). Warns loudly on `eval_frozen=false`, records `--signed-via` for a `gate2_envelope.pi_signed=true`, and re-renders the role files after an `agents.*` change. `profile` delegates to `profiles.py` (rigor-floor enforced). The judgment — is this the PI, and should the key change — stays in the skill; the tool makes the owner gate unskippable.

### `spawn_project.py` — mechanical project scaffolder

```bash
uv run --with pyyaml python tools/spawn_project.py --slug <slug> --title "<title>" \
  --project-type ml [--domain econ] [--overlay compete] [--run-smoke] [--skip-guard]
```

The deterministic half of `/spawn-project`: copies `templates/project/` → `<projects_root>/<slug>` with the four placeholders substituted as **UTF-8, no BOM** (`hub_path` forward-slashed so `control.yaml` stays valid YAML on Windows — a real failure mode a hand-copy hits), drops the hub-side runtime cruft (`.pytest_cache`/`.bus`/`__pycache__`/stale `runs/` dirs), applies the project-TYPE card + `control.yaml` `project_type` + optional domain profile (`--domain` → `DOMAIN.md`) + optional target-driven overlay (`--overlay compete`), and copies `lab/SYSTEM.md` if present. Runs `guard.py spawn` first (Gate 1), and **refuses** to overwrite a slug with commits or a non-empty `runs/`. With `--run-smoke` it also `uv sync`s, runs the smoke + tests (project-local basetemp) + `check_project.py`, and commits **only if all green** (never a red scaffold). The judgment steps — fill `PLAN.md` from the proposal, set budgets/the Gate-2 envelope, update the registry — stay in the skill.

### `role_sync.py` — render backend-native subagent role files

```bash
uv run --with pyyaml python tools/role_sync.py render   # write/update generated role files
uv run --with pyyaml python tools/role_sync.py check    # CI drift guard — exit 1 if any is stale
```

One canonical source per subagent role in `agent-roles/` (`<name>.yaml` metadata + `<name>.md` verbatim body) renders to backend-native files: `.claude/agents/<name>.md` (Claude Task subagents, `model:` resolved from `lab/config.yaml` `agents.*` — the same source `/configure` and `profiles.py` sync) and `.codex/agents/<name>.toml` (Codex GA subagents, hub + the copy in `templates/project/`). The three roles — `fresh-context-reviewer`, `experiment-runner`, `overseer` — render here; ideation critics / scoping advocates have no role file, so `/ideate` and `/scope` apply `agents.critic_model` (tier-resolved) as their per-spawn Task model on Claude Code and run them at the session model on other backends (subagent rule 7). opencode gets `.opencode/agents/<name>.md` too (`mode: subagent`; the role's Claude tool list mapped onto opencode permissions, `task: deny`; no model line — its subagents inherit the session model). Gemini CLI / Cursor are compatibility-only until a CLI smoke proves their role-file schema — use the sequential approximation or the executor (one headless process per unit of work) meanwhile. `check` is a drift guard for CI; edit the source in `agent-roles/`, never the generated files.

### `executor_cli.py` — headless procedure runs (the dashboard's engine)

```bash
uv run --with pyyaml python tools/executor_cli.py enqueue --skill <name> [--target <slug>] [--args "..."] \
    [--backend claude|codex|opencode] [--chain off|next|loop] [--repeat-minutes N] [--wait]
uv run --with pyyaml python tools/executor_cli.py serve | tick | list | show <run> | attention | health | skills
uv run --with pyyaml python tools/executor_cli.py answer <run> --pick "<question>=<label>" | --text "..."
uv run --with pyyaml python tools/executor_cli.py reply <run> --text "..." | resume | stop | cancel <run>
```

Runs a **whitelisted** lab procedure (`skills` lists them; `/finalize` is never one) as a headless
agent session in a detached supervisor (`tools/executor/`): queued → started by the scheduler under
the caps → live transcript + manifest + `lab/.bus/runs.jsonl` ledger → paused on a PI question and
resumed on the answer (same session) → completed with a `run_report` footer (`next`, `needs_pi`,
`summary`). PI-owned, off by default (`agents.programmatic.enabled`); every gate still binds; Gate 3 is
never delegated. The dashboard's *Run a procedure* is this same engine. See [Autonomy](autonomy.md#headless-runs-the-executor).

### `signature_guard.py` — only the PI signs (a hook, not a command)

A PreToolUse hook the executor installs in every headless run: claude's per-run settings, codex
`-c hooks` flags, and an opencode plugin via `OPENCODE_CONFIG_DIR`. It reads one hook payload on
stdin and exits **2** (the reason on stderr) when a tool call would create or change a PI signature:

- a Gate-1 marker;
- an envelope's `pi_signed` / `signed_via`, or a signed envelope's values;
- `gate3-approval.md`;
- a LOOP_BRIEF or campaign authorization;
- a registry row moved to `final` without a signed Gate 3;
- PI-owned config;
- `pi-actions.jsonl`;
- the shell escape hatches.

It compares before vs after, and honours delegation by a PI-signed campaign brief. Denials are
logged to the run's `permissions.jsonl`. See [Autonomy → Headless runs](autonomy.md#headless-runs-the-executor).

### `new_lab.py` — create a new lab from this template

```bash
uv run --with pyyaml python tools/new_lab.py <dest> [--name "My lab"] [--projects-root ../my-lab-projects]
```

What the dashboard's *Create a new lab* runs:

- copies the template's committed files (`git archive HEAD`);
- empties the registry, the knowledge base, the notebook and `studies/`;
- sets `lab.name` and `lab.projects_root`;
- runs `git init` and makes the first commit.

### `terminal.py` — a terminal window for a CLI's own sign-in or install

```bash
uv run --with pyyaml python tools/terminal.py login claude     # opens a window running `claude auth login`
uv run --with pyyaml python tools/terminal.py install codex
```

It opens a visible console (Windows Command Prompt, macOS Terminal, or a Linux terminal emulator)
running a **fixed** command per backend. The dashboard asks for a purpose, never a command line.
Credentials are typed into the CLI's own login and never pass through the lab.

### `newts.py` (repo root) — start the dashboard

```bash
uv run --with pyyaml python newts.py [--hub <lab>] [--port N] [--no-browser]
```

It starts `dashboard/serve.py` for the lab and opens the browser. On a machine you reached over SSH
(or with no display) it prints the `ssh -N -L …` line to use from your own computer instead.
`--background` detaches it, so it outlives your SSH session; `--status` and `--stop` manage it, and
`--json` makes the output machine-readable. If the dashboard is already running
for that lab it just opens the browser, and if 8787 is busy it picks the next free port. The
double-click launchers (`Start Newts Lab.cmd`, `start-newts.command`, `start-newts.sh`) run it.

### `system_probe.py` — what this machine offers

```bash
uv run --with pyyaml python tools/system_probe.py [--hub <lab>]
```

It prints JSON: CPUs, memory, GPUs, disk, schedulers (SLURM with its partitions and accounts, PBS, LSF),
environment modules and tools, plus a suggested `compute.scheduler`. The dashboard's Settings → System &
compute runs it on the lab's machine. See [Machines & compute](compute.md).

### `run.py` — the single entry point, with a real watchdog

```bash
uv run python scripts/run.py --config configs/experiments/exp-004.yaml [--seed N] [-o key=value ...]
```

Loads the layered config, seeds everything, creates `runs/<run_id>/` (resolved config + git SHA + seed + metrics), appends to `registry.jsonl`. **`budget.max_minutes` is enforced**: a daemon watchdog records the breach (`meta.budget.breached`, `status: timeout`, `error.txt`) and hard-exits 2. Budgets are facts, not suggestions.

### `sweep.py` — multi-seed / grid launcher

```bash
uv run python scripts/sweep.py --config <exp.yaml> --seeds 0,1,2 [--grid k=v1,v2 ...] [--parallel N]
```

One `run.py` subprocess per (combo × seed) with an outer kill-timeout as defense in depth behind the watchdog; ends with a mean ± std markdown table per combo, pasteable into the ledger. This is how the multi-seed rule (`experiment.multi_seed_n`) gets satisfied in one command.

### `compare.py` — query the run record

```bash
uv run python scripts/compare.py best --metric val_loss --minimize
uv run python scripts/compare.py seeds --metric val_loss
uv run python scripts/compare.py experiments exp-003 exp-004 --metric val_loss
uv run python scripts/compare.py list --last 20
```

Reads only `runs/registry.jsonl`; markdown output with seed-aggregated mean ± std and deltas.

### `figures.py` — the paper-grade figure & table library (`src/project_pkg/`)

Not a CLI — the module every `scripts/figures/` script imports, so figure code in projects stays a few lines and all figures are consistent by construction:

- `new_fig(width="single"|"double")` — axes at **final printed width** (3.3 in / 6.9 in), warm-free venue-neutral style: vector PDF, TrueType fonts (`fonttype 42` — Type 3 fails camera-ready checks), 7–8 pt labels, Okabe-Ito colorblind-safe cycle, constrained layout.
- `save_fig(fig, name, consumed_runs=[...])` — PDF + review PNG, printing the run ids consumed (provenance for `claims.yaml`).
- `load_registry()` / `metric_curve(run_id, metric)` / `seed_stats(rows, metric)` — artifact access; headline comparisons must go through `seed_stats`.
- `format_measurement(mean, std, n)` — sig-fig discipline (std to 2 sig figs, mean to match: `71.28 ± 0.39`).
- `emit_table(headers, rows, path)` — booktabs `.tex` files the paper `\input`s, so **result numbers never pass through prose generation** (the single most effective anti-transcription-error mechanism in the surveyed systems).

`/make-figures` orchestrates these per paper; matplotlib is imported lazily (add it to the project's pyproject when plotting starts).

### `status.py` — zero-token run monitor

```bash
uv run python scripts/status.py [<run_id>] [--log-interval 60]
```

One line: `alive | stalled | done | failed | timeout · elapsed/budget · last metric`. The **only** check `/research-loop` makes while a run is in flight — liveness from `meta.json` + `metrics.jsonl` mtime, no log dumps, no judgment about partial curves. Exit 3 on `stalled` (two in a row → treat the run as failed).

### `check_project.py` — readiness lint + orientation

```bash
uv run --with pyyaml python scripts/check_project.py
```

The project-side analogue of `check_lab.py`: required files present, no unfilled template placeholders, `control.yaml` parses (budgets + envelope blocks), `registry.jsonl` readable — then an orientation block regardless: runs recorded, last run + status, envelope signed or not, SYSTEM.md present or not, and a **suggested next procedure**. Exit 0 ready, 1 not. Run it on any fresh clone, after `/spawn-project`, or whenever an agent cold-starts in the project directory.

## Design note

There is deliberately **no orchestrator binary and no pip package**. The tools are boring on purpose: each one reads files a human can read, prints markdown a human can paste, and exits with a code a script can branch on. The agent's judgment plus these deterministic checks is the architecture.

## `upgrade_project.py` — bring spawned projects up to date

A project is a snapshot of `templates/project/` at spawn, so later improvements to agent tracing never reach it on
their own. This copies only the template-owned plumbing — `scripts/trace_hook.py`, `scripts/lab_bus.py`, the
`hooks` block of `.claude/settings.json` (permissions untouched), `.codex/hooks.json`, the opencode tracer plugin
and the role files — never research content. Idempotent; it does not commit.

```bash
uv run --with pyyaml python tools/upgrade_project.py --all --check   # report stale files (exit 1 if any)
uv run --with pyyaml python tools/upgrade_project.py --all           # or: <slug> [<slug>…]
```
