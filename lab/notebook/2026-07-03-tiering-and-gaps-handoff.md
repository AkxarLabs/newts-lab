# Handoff — model tiering + gap-closure implementation plan (2026-07-03)

**Status: IMPLEMENTED 2026-07-03** (all four phases). Executed via 6 file-disjoint
implementation workers → integration barrier → 4 adversarial reviewers, then a
fix-and-reverify pass. Result: **277 tests pass** (259 baseline + 18 new), `role_sync
check` clean (12 role files in sync), `check_lab` clean, docs `--strict` clean, all
consistency greps clean, profiles behavior-preserving, all defaults still resolve to
`inherit` (zero behavior change until the PI sets a ladder). Reviewer findings all
resolved: two `hub_writeback` guard regressions (same-state re-assert now legal; a
refused transition now exits non-zero), the Gate-3 marker wording corrected (a headless
agent still cannot finalize — `AUTOSCIENTIST_NO_GATE3`), P0.4 docs rows added, two stale
`critic_model` claims swept (`agent-roles/README.md`, `docs/tools.md`), P1.8 Codex-native
note and P3.1 `/analyze` kill emit added. Uncommitted (PI controls commits; no push).

The original spec follows unchanged for the record.

**Status: PLANNED, NOT IMPLEMENTED.** This is a complete, self-contained implementation
spec produced from a four-way audit (model plumbing · user-journey trace · config
comprehensiveness · cross-system integration). PI approved scope: **all four phases**.
An implementing session should be able to execute this file top-to-bottom without
re-deriving anything.

**Audit verdict (context):** no mode has a hard broken handoff — all 46 tool references,
12 templates, every lifecycle transition vs `guard.py`'s legal table, the writeback
field contract, Windows-compat, and all dashboard routes verified clean. What follows
closes the gaps that ARE real.

---

## Phase P0 — bugs + doc/config drift (no design decisions)

### P0.1 — ideate `--in-project` escalation uses a project-cwd path from hub context (BUG)
- **File:** `.claude/skills/ideate/SKILL.md` (~line 146, the **Approval** section).
- **Change:** `uv run python scripts/lab_bus.py escalate --detail "in-project approach needs PI"`
  → `uv run python tools/lab_bus.py escalate --detail "in-project approach needs PI"`.
- **Why:** `/ideate --in-project` runs in a HUB session (worksheet in `lab/ideation/`,
  reads the project across the boundary); the hub has no `scripts/`. Line ~153 of the
  same file already uses `tools/lab_bus.py` correctly. (`improve`/`research-loop` use
  `scripts/` legitimately — they run at project cwd. Do NOT change those.)

### P0.2 — `/discuss scope` session doc is written but never read (orphaned seed)
- **File:** `.claude/skills/scope/SKILL.md` §1 first paragraph.
- **Change:** "Read `IDEA.md` (with the reflection summary) and `lit-review.md`
  (especially positioning)." → append: "…and, if present, the `/discuss scope` session
  doc(s) in `studies/<slug>/sessions/` — the PI-settled starter decision list; seed the
  branch enumeration from it rather than re-deriving decisions the PI already framed."
- All four other discuss purposes are already consumed downstream; this closes the last one.

### P0.3 — Gate-3 marker has no authoring step (guard checks a marker no skill writes)
- **Files:** `.claude/skills/review-paper/SKILL.md` Part C route step (the
  "Meta-review **accept** AND zero unrefuted fatal flaws → **PI Gate 3**" bullet).
- **Change:** append to that bullet: "On the PI's approval, record it durably: append a
  line `Gate 3: approved — <date>` (with any PI note) to
  `studies/<slug>/paper/reviews/review-N.md` **or** write
  `studies/<slug>/paper/gate3-approval.md` — this is the recorded marker
  `guard.py finalization` accepts, so a later/headless session can finalize without the
  interactive `--pi-approved` fallback."
- Guard side needs no change (`guard.py:562-578` `_gate3_marker` already accepts both paths).

### P0.4 — `target.final_run_id` undocumented and missing from the template
- **File 1:** `templates/compete/control.target.yaml` — add at the end of the `target:` block:
  ```yaml
  final_run_id: null            # Gate 3 (PI only): the run whose output the PI selects as the
                                # final deliverable for the hidden/final split. Set by the PI at
                                # finalization; checked by tools/guard.py finalization.
  ```
- **File 2:** `docs/configuration.md` `target.*` table — add rows:
  - `target.final_run_id` | **PI only** | the PI-selected winning run id (Gate 3 for target-driven projects; `guard.py finalization` requires it)
  - `target.spec` | PI | path of the PI-owned brief (default `TARGET.md`) — read, never edited, by the agent
- Guard already reads it (`guard.py:605-607`); no code change.

### P0.5 — `/configure` skill's PI-owned list out of sync with `tools/configure.py`
- **File:** `.claude/skills/configure/SKILL.md` step 2.
- **Change:** the enumeration currently reads "…`lab.*`, `compute.*`, `agents.*`,
  `oversight.level`, `critique.*`, `writing.page_limit`, `budgets.*` (after Gate 1),
  `gate2_envelope.*`, `eval_frozen`, and `loop.mode` / `loop.explore_*`…". Add the four
  keys from `configure.py:41-42` `PI_OWNED_EXACT`: **`ideation.in_project`,
  `ideation.in_project_approval`, `writing.venue`, `autopilot.max_concurrent_projects`**.
- No change to `configure.py` (the enforcement is correct; the prose lagged).

### P0.6 — ownership drift: doc vs enforcement (align docs to `configure.py`)
- **File:** `docs/configuration.md` Layer-1 table.
  - `critique.claim_rel_tol` — Owner "agent-readable" → **PI** (the `critique.` prefix is
    mechanically blocked by `configure.py:38`, and the YAML section header says PI-owned;
    it *is* a rigor knob).
  - `dashboard.port` and `dashboard.editor` — Owner "PI" → **agent-readable** (cosmetic
    local-only knobs; `configure.py` has no `dashboard.` prefix and shouldn't — don't add one).

### P0.7 — PI-owned comment tags missing in `lab/config.yaml` (the surface a hand-editing PI reads)
- **File:** `lab/config.yaml`. Add "PI-owned" to the inline comments of:
  - the `oversight:` section header (line ~140): `# ── confabulation circuit-breakers (overseer agent) · PI-owned ──`
  - `ideation.in_project` (line ~153): append `PI-owned kill-switch.` to its comment
  - `writing.venue` (line ~187) and `writing.page_limit` (line ~198): append `PI-owned.`
  - `loop.mode` (line ~226): append `PI-owned (with loop.explore_*).`
- (`critique:` header already tagged; leave `templates/project/control.yaml` alone — its
  PI-owned keys are already bold in docs and marked in the file.)

### P0.8 — `/setup-lab` interview misses venue + dashboard + the programmatic master switch
- **File:** `.claude/skills/setup-lab/SKILL.md`, the interview section.
- **Add a "Paper venue" bullet** (after "Autonomy appetite", before "Models & keys"):
  target venue for papers — `writing.venue` (`neurips` default · `icml` · `iclr` ·
  `aclarr` · `aaai` · `generic`) + matching `writing.page_limit` (neurips/iclr 9 ·
  icml/aclarr 8 · aaai 7). Both PI-owned; a wrong default silently shapes every paper.
- **Add a "Dashboard (optional)" bullet:** mention `uv run python dashboard/serve.py`
  (localhost, port `dashboard.port` 8787), the `dashboard.editor` deep-link scheme, and
  that Gate 1/2 can be signed from it (Gate 3 never).
- **In the existing "Headless launch backend" bullet**, add one leading sentence: "The
  master switch `agents.programmatic.enabled` ships **false** and stays false unless the
  PI explicitly opts in here — everything below only matters once it's on."

### P0.9 — `agent_runner.py` fallback default contradicts config
- **File:** `tools/agent_runner.py` line ~637 (`_campaign_cap`).
- **Change:** `("max_concurrent_projects", 2), 2, 1)` → `("max_concurrent_projects", 1), 1, 1)`
  (config default and docs both say 1; the code-side fallback only bites if the key is
  deleted, but it should fail safe → sequential).
- **Test:** in `tests/test_agent_runner.py`, add/adjust a case: config without an
  `autopilot:` section → `_campaign_cap` returns 1 (not 2).

### P0.10 — AGENTS.md structured-command list omits `stop_loop`
- **File:** `AGENTS.md`, the "Structured commands" bullet: add `stop_loop` to the
  parenthesized action list (the dashboard backend whitelists it in `dashboard/serve.py:51`,
  and the bus/inbox renders it — only the manual's enumeration lags).

---

## Phase P1 — model tiering (the centerpiece)

**Design (PI's framing):** three tiers — expensive (fable/opus) · medium (sonnet) ·
cheap (haiku) — assignable per task purely through config. Semantic tier names (they
describe capability, not price): **`strong` / `standard` / `fast`**.

**Ground truth to respect:**
- Role frontmatter model flows: `lab/config.yaml agents.<key>` → `role_sync.py:_model_for`
  → `.claude/agents/<role>.md` `model:` (`role_sync.py:60-64,75-81`). Values pass through
  UNVALIDATED, so full pinned ids already work — they're just undocumented.
- The current Claude Code Task/Agent spawn accepts a per-call `model` parameter
  (aliases incl. `fable`) — which makes the "critic_model cannot be applied" claim
  **stale on Claude Code**. Inline critics/advocates CAN be tiered; skills must pass it.
- Backward compat: every default below resolves to `inherit` → zero behavior change
  until the PI opts in.

### P1.1 — `agents.tiers` in `lab/config.yaml`
Insert at the top of the `agents:` section (before `reviewer_model`):
```yaml
  tiers:                        # ── the PI's model ladder · PI-owned ──
                                # Each tier names a model: an alias (sonnet | opus | haiku |
                                # fable) or a FULL pinned id (e.g. claude-haiku-4-5-20251001 —
                                # pin when alias drift matters, same rule as the headless
                                # backends). `inherit` = the session model. The per-role keys
                                # below may name a TIER (strong/standard/fast) or a model
                                # directly — both resolve through tools/role_sync.py.
    strong: inherit             # judgment-heavy, low-volume: paper reviewers, meta-review
    standard: inherit           # well-specified execution: runner, critics, advocates, overseer
    fast: inherit               # high-volume / retrieval-shaped work
```
And change the role-key defaults + comments:
```yaml
  reviewer_model: strong        # → .claude/agents/fresh-context-reviewer.md (tier name or model)
  runner_model: standard        # → .claude/agents/experiment-runner.md
  overseer_model: standard      # → .claude/agents/overseer.md
  critic_model: standard        # ideation critics / scoping advocates — inline subagents; on
                                # Claude Code the spawning skill passes this (tier-resolved) as
                                # the per-spawn Task model. Backends without a per-spawn model
                                # override run them at the session model.
```
(Ownership: the `agents.` prefix in `configure.py` already makes `agents.tiers.*` PI-owned — no change needed.)

### P1.2 — tier resolution in `tools/role_sync.py`
Add a resolver and use it in `_model_for`:
```python
def resolve_model(val: str, agents_cfg: dict) -> str:
    """Resolve a tier name (agents.tiers) to its model; pass anything else through.
    Cycle-safe; empty/None -> inherit."""
    tiers = agents_cfg.get("tiers") or {}
    seen = set()
    val = (str(val).strip() if val is not None else "") or "inherit"
    while val in tiers and val not in seen:
        seen.add(val)
        val = (str(tiers[val]).strip() if tiers[val] is not None else "") or "inherit"
    return val

def _model_for(meta: dict) -> str:
    key = meta.get("model_key")
    cfg = _cfg_agents()
    return resolve_model(cfg.get(key) if key else None, cfg)
```
Also update the module docstring's rendered-targets list (P1.5 adds a target).

### P1.3 — retire the divergent sync path in `tools/profiles.py`
`cmd_apply` currently patches `.claude/agents/*.md` with a private regex
(`_sync_agent_model`, `profiles.py:165-174,262-263`) — it never touches the Codex tomls
and can't resolve tiers. **Replace:** after stamping `lab/config.yaml`, if any stamped
key starts with `agents.`, call the canonical renderer:
```python
import role_sync  # tools/ sibling; profiles.py already sys.path-inserts tools/
...
if any(d[0] == "agents" for d in flat):
    role_sync.render()
```
Delete `_sync_agent_model` and its `AGENT_FILE` usage in `cmd_apply` (keep `AGENT_FILE`
if other code references it — grep first). Update the "Agent model frontmatter synced"
print to report `role_sync` output instead. `configure.py cmd_set` already re-renders
via `role_sync` (`configure.py:140-144`) — unchanged, now both paths converge.

### P1.4 — per-role reasoning effort
- **Verify first (blocking pre-step):** confirm the exact frontmatter key Claude Code
  accepts for subagent reasoning effort in `.claude/agents/*.md` (consult the
  claude-code docs / a `claude-code-guide` agent). If none exists, scope this item to
  the Codex render only and note it in docs.
- **Config:** add to `lab/config.yaml agents:` (after the role keys):
  ```yaml
  reviewer_effort: ""           # per-role reasoning effort (low|medium|high|xhigh|max).
  runner_effort: ""             # "" = the model's default. Rendered into the role files by
  overseer_effort: ""           # role_sync (Claude frontmatter if supported; Codex
                                # model_reasoning_effort — overrides the role-yaml default).
  ```
- **`role_sync.py`:** derive `effort_key = model_key.replace("_model", "_effort")`;
  `_render_claude` emits an effort line only when the resolved value is non-empty;
  `_render_codex` uses the config value when set, else the existing
  `codex.model_reasoning_effort` from the role yaml (which stays as the fallback — do
  NOT delete it from `agent-roles/*.yaml`).

### P1.5 — spawned projects get real Claude role files
- **`role_sync.py:_targets`:** add
  `(HUB / "templates" / "project" / ".claude" / "agents" / f"{name}.md", "claude")`.
- Run `role_sync.py render` → creates `templates/project/.claude/agents/{experiment-runner,fresh-context-reviewer,overseer}.md`.
  `spawn_project.py` copies the template tree wholesale, so no spawner change; verify
  `templates/project/.gitignore` doesn't exclude `.claude/agents/` (it doesn't exclude
  `.claude/skills/`, so expect fine — check anyway).
- **Semantics to document** (in `docs/configuration.md` + `templates/project/CLAUDE.md`):
  a project's role files are a **spawn-time snapshot** of the hub's tier resolution; the
  project-layer override is editing the project's own `.claude/agents/<role>.md`
  frontmatter directly (deliberately NOT a `control.yaml agents:` block — see Non-goals).
- This makes `templates/project/CLAUDE.md:8`'s promise ("run experiment-runner … as real
  Task subagents") true. Also fixes `autopilot/SKILL.md:51`'s "fully operable" claim.

### P1.6 — make `critic_model` real (Claude Code), honestly scoped
- **`.claude/skills/ideate/SKILL.md`:** line ~11 "critic model: `agents.critic_model`" →
  "critic model: `agents.critic_model` (a tier name resolves via `agents.tiers`; on
  Claude Code pass the resolved model as each critic Task spawn's `model` parameter
  unless `inherit`; backends without per-spawn model overrides run critics at the
  session model)". Phase 2 spawn step + `--in-project` step 2: add "(model:
  `agents.critic_model`, tier-resolved)" to the spawn instruction.
- **`.claude/skills/scope/SKILL.md`:** line ~11 same treatment; §2 step 2 advocate-spawn
  instruction gets "(model: `agents.critic_model`, tier-resolved)".
- **Stale-claim sweep** — update from "cannot be applied" to the honest per-backend rule
  ("applied as a per-spawn model override by `/ideate` and `/scope` on Claude Code;
  otherwise session model") in ALL of:
  - `lab/config.yaml` `critic_model` comment (done in P1.1)
  - `docs/configuration.md` `agents.critic_model` row
  - `AGENTS.md` subagent rule 7 (the "cannot be applied to them" sentence)
  - `.claude/skills/configure/SKILL.md` step 4 last sentence
  - `.claude/skills/setup-lab/SKILL.md` "Models & keys" bullet ("critic_model maps to no
    file … can't apply" parenthetical)
  - journey-audit note: the same stale text appears at `setup-lab:41` / `configure:36` —
    the grep `cannot .*appl|can't apply|maps to no file` must come back empty afterwards.

### P1.7 — name the role in `/experiment`'s parallelism section
- **File:** `.claude/skills/experiment/SKILL.md`, "## Parallelism (optional)".
- **Change:** "…parallel background processes or isolated subagents…" → "…parallel
  background processes or isolated **`experiment-runner`** subagents (model:
  `agents.runner_model`, tier-resolved; same contract as `/improve`'s parallel path —
  worktree confinement, result packets, parent-only ledgers)…" — so the runner tier
  governs this spawn site too.

### P1.8 — Codex render: optional per-role model line
- **`role_sync.py:_render_codex`:** after the description line, emit
  `model = "<value>"` when the role yaml carries `codex.model` (optional; absent today
  in all three `agent-roles/*.yaml` → no rendered change until someone sets it).
- **Docs honesty note** (configuration.md, agents section): tier keys are
  **Claude-native**; Codex subagent models default to the Codex CLI/config.toml and can
  be pinned per-role via `agent-roles/<role>.yaml` `codex.model`. Do NOT build a
  parallel Codex tier map (Non-goals).

### P1.9 — profiles rewritten in tier terms
- **`lab/profiles/low.yaml`:** replace the per-role model lines with
  `tiers: {strong: sonnet, standard: haiku, fast: haiku}` and keep role keys at tier
  names (or omit them — they already default to tier names after P1.1). Keep the
  existing comments' spirit ("verification stays mid-tier; cheapest for running").
- **`lab/profiles/high.yaml`:** `tiers: {strong: opus, standard: opus, fast: sonnet}`.
- **`lab/profiles/mixed.yaml`:** `tiers: {strong: opus, standard: sonnet, fast: haiku}`
  (its philosophy — strong on verification, cheap on running — becomes the tier map;
  keep the `programmatic:` block as is).
- **Check the other presets** (`medium/claude-opus/claude-balanced/claude-fast/codex/opencode`)
  for `agents.<role>_model` lines and convert any found the same way (read them first —
  only `low/high/mixed` are confirmed to set per-role models).
- **`profiles.stamp` caveat:** `stamp()` only rewrites keys **present** in
  `lab/config.yaml` — the `tiers:` block added in P1.1 must exist before profiles can
  stamp `agents.tiers.strong` etc. (it will, by ordering). Add `agents.tiers.*` to
  `PROFILE_KEYS` in `profiles.py` so `save` snapshots tiers.
- **`lab/profiles/README.md` + `docs/configuration.md` tier table row:** update the
  "per-role models" row to tier form (e.g. low = `haiku` standard / `sonnet` strong;
  high = `opus`), and fix the README's simplification the audit flagged (it omitted the
  overseer).

### P1.10 — the guidance table (which tier for which task)
Add a subsection to `docs/configuration.md` (after the agents rows), ~this content:

> **Which tier for which task** — the rule of thumb is volume × judgment: high-volume,
> retrieval-shaped work goes `fast`; well-specified execution goes `standard`;
> low-volume, judgment-heavy verification goes `strong`.
>
> | LLM work | Knob | Suggested tier |
> |---|---|---|
> | paper reviewers + meta-review (`/critique-paper`, `/review-paper`) | `agents.reviewer_model` | `strong` |
> | experiment variants (`/improve`, `/experiment`, `/research-loop`) | `agents.runner_model` | `standard` |
> | overseer verification checks | `agents.overseer_model` | `standard` (`strong` under `oversight.level: strict`) |
> | ideation critics / scoping advocates (`/ideate`, `/scope`) | `agents.critic_model` | `standard` |
> | headless project agents (`tools/agent_runner.py`) | `agents.programmatic.backends.*` | task-dependent; pin full ids |
> | the orchestrating session itself (generation, analysis, drafting, `/discuss`) | — none; it runs at YOUR session model | your seat IS the expensive tier |
>
> Example (Anthropic ladder): `tiers: {strong: opus, standard: sonnet, fast: haiku}`
> with the session on fable/opus. Aliases drift to newer models over time; pin a full
> id (e.g. `claude-haiku-4-5-20251001`) when reproducibility across months matters —
> same rule as `agents.programmatic.backends.claude.model`.

Also fix the Layer-1 table rows for `reviewer/runner/overseer_model`: allowed values →
"tier name (`strong`/`standard`/`fast`) | alias (`sonnet`/`opus`/`haiku`/`fable`) |
full pinned id | `inherit`", and add a row for `agents.tiers.{strong,standard,fast}`
and the three `*_effort` keys.

### P1.11 — `/setup-lab` + `/configure` skill text
- **setup-lab "Models & keys" bullet:** rewrite the first sub-bullet around tiers: ask
  the PI for their ladder ("strongest / workhorse / cheap — e.g. opus / sonnet / haiku;
  `inherit` everywhere is the safe default"), write `agents.tiers`, and note the role
  keys default to sensible tier names. Fold in the P1.6 critic honesty text.
- **configure SKILL step 4:** mention tier resolution ("a tier name is resolved through
  `agents.tiers` at render time; changing a tier re-renders every role that names it").

### P1.12 — tests (`tests/`)
- `test_role_sync.py` (extend or create): tier name resolves through `agents.tiers`;
  direct model passes through; unknown string passes through verbatim; `inherit`-valued
  tier → `inherit`; cycle in tiers terminates; project-template targets rendered
  (P1.5); effort line rendered only when set (P1.4); codex `model =` line only when
  role yaml sets it (P1.8).
- `test_profiles.py`: `apply` with an `agents.*` key updates BOTH `.claude/agents/*.md`
  and `.codex/agents/*.toml` (the convergence P1.3 buys); tier-form preset applies
  cleanly; `save` round-trips `agents.tiers.*`.
- Keep everything hermetic per the existing `conftest.load()` pattern (monkeypatch HUB).

---

## Phase P2 — wire the dead guards

Four guards are built, unit-tested, and advertised in AGENTS.md but invoked by nothing:
`state`, `evolve`, `frozen`, `writeback`. Wiring principle: **one mechanical choke point
where one exists, plus a blanket protocol line, plus the driver skills** — not a
copy-pasted line in all 25 skills.

### P2.1 — `guard.py state` (illegal registry transitions)
- **Mechanical choke point — `tools/hub_writeback.py:_set_state`:** before rewriting
  `cells[2]`, validate the transition. Import guard's table rather than shelling out:
  refactor `tools/guard.py` to expose `def legal_transition(frm: str, to: str) -> bool`
  (extract from `c_state`; `c_state` calls it), then in `_set_state`:
  ```python
  import guard  # tools/ sibling — sys.path.insert like configure.py does
  if not guard.legal_transition(cells[2], state):
      return f"illegal transition {cells[2]} -> {state} (guard.py state)"
  ```
  (`parked`/`killed` are reachable from any state per the lifecycle — the existing table
  already encodes that; no special-casing.)
- **Same check in `tools/process_writebacks.py`** where it applies a `state:` field from
  a HUB-WRITEBACK-PENDING block (read the file first; reuse `guard.legal_transition`).
- **Blanket protocol line — `AGENTS.md`:** the existing sentence "After **every** state
  change, update `lab/REGISTRY.md` in the same working session." → append: "Before
  writing a transition, check it: `uv run --with pyyaml python tools/guard.py state
  <slug> <from> <to>` (exit 1 = illegal — stop and re-read the lifecycle; the guard
  confirms, never grants)."
- **Driver skills:** add the one-line preflight to `.claude/skills/advance/SKILL.md`
  (before executing the selected stage) and `.claude/skills/autopilot/SKILL.md` (in the
  per-idea pipeline step where it advances state).
- **Tests:** `test_newer_tools.py` (or wherever hub_writeback is tested): illegal
  transition via `--state` returns the failure string and leaves the registry unchanged;
  legal transition still works; `killed` from anywhere works.

### P2.2 — `guard.py evolve` (rule-11 CORRECTION/RECIPE enforcement)
- **`AGENTS.md`** lifecycle parenthetical ("whichever procedure finds the evidence
  records the kill…") → append: "…then run `uv run --with pyyaml python tools/guard.py
  evolve <slug>` — a BLOCK means the kill left no CORRECTION; write the FAILURES.md /
  NOTES.md entry before moving on."
- **`.claude/skills/analyze/SKILL.md`** kill/park route (~line 29): add the same
  one-liner after recording a kill.
- **`.claude/skills/finalize/SKILL.md`** step 3 (hub close-out): add "Run
  `uv run --with pyyaml python tools/guard.py evolve <slug>` — a WARN here means the
  RECIPE wasn't distilled; fix before step 4."
- **`.claude/skills/autopilot/SKILL.md`** per-idea completion/kill step: same one-liner.
- No guard code change (`c_evolve` semantics are already right: BLOCK on kill-no-
  correction only when a project exists; WARN on results-stage-no-recipe).

### P2.3 — `guard.py frozen` (frozen-set integrity)
- **`.claude/skills/experiment/SKILL.md`** step 2 FULL bullet: alongside the existing
  `guard.py full-run` preflight, add "and `uv run --with pyyaml python
  <hub>/tools/guard.py frozen <slug>` — confirms `eval_frozen` + the PI-owned blocks are
  intact before any FULL run."
- **`.claude/skills/research-loop/SKILL.md`** loop start (step 1's "once at loop start"
  reads): add the same call once per loop start.
- Optional (cheap, higher-leverage): also call it from
  `templates/project/scripts/_runner_guards.py` next to where the FULL-run guard is
  invoked at the runner boundary — read that file first; if the full-run guard is
  invoked via subprocess there, add `frozen` in the same style. If it complicates the
  runner path, skip — the two skill wirings above are the accepted scope.
- **Docs:** `docs/workflow.md` — wherever it names the frozen guard, confirm the claimed
  call sites now exist.

### P2.4 — `guard.py writeback` (advisory)
- **`.claude/skills/research-loop/SKILL.md`** exit step (after the write-back bullet)
  and **`.claude/skills/finalize/SKILL.md`** step 3: add
  `uv run --with pyyaml python tools/guard.py writeback <slug>` — WARN-only; it confirms
  the rule-11 write-back landed.

### P2.5 — Gate-1 guard analogue for `/compete` (closes the gate-enforcement asymmetry)
- **`tools/guard.py c_spawn`:** currently requires the Gate-1 marker in
  `studies/<slug>/proposal.md`. Add a target-driven fallback: if no `proposal.md`
  exists but `studies/<slug>/IDEA.md` contains both a line matching
  `N/A (target-driven)` **and** a line matching `(?i)gate\s*1.*(approved|authorized)`,
  → PASS with a "target-driven Gate-1 (compute authorization) marker found" message.
  Everything else keeps the current behavior.
- **`.claude/skills/compete/SKILL.md`:** at the end of the §1 interview (the Gate-1
  compute authorization), add: "Record the authorization in `IDEA.md`: a line
  `Gate 1 (compute authorization): approved — <date>, per /compete interview`. Then run
  `uv run --with pyyaml python tools/guard.py spawn <slug>` before creating the project
  — same mechanical stop as the paper path."
- **Tests (`tests/test_guard.py`):** target-driven IDEA.md with both markers → 0;
  missing the gate line → 1; paper path unchanged.

---

## Phase P3 — polish

### P3.1 — emit the two genuinely missing dashboard event kinds
(Audit correction: `frontier_expand`/`decision_revisit` ARE emitted — `/improve` steps 5
and 6 instruct both. Only these two lack emitters:)
- **`paper_compiled`:** `.claude/skills/write-paper/SKILL.md` §6 hand-off: add
  "Emit `uv run python tools/lab_bus.py emit paper_compiled --idea <slug> --detail
  '<pages>pp, <claims> claims'`." (drives the dashboard's writing-phase rendering).
- **`kill`:** in the same `AGENTS.md` kill parenthetical touched by P2.2, add "…and emit
  `uv run python tools/lab_bus.py emit kill --idea <slug> --detail '<reason>'`"; mirror
  in `analyze`'s kill route (P2.2 already touches that line — do both in one edit).
- Leave `session_start`/`session_end`/`writeback` as demo-only kinds (harmless; not
  specially rendered).

### P3.2 — gate the revisit machinery for target-driven projects
- **`.claude/skills/research-loop/SKILL.md`** step 1 explore-mode read: append
  "(target-driven projects have no `decisions.md` — skip the revisit scan entirely;
  frontier expansion is the explore mechanism there)".
- **`.claude/skills/improve/SKILL.md`** operator 6 (`revisit`) intro: same parenthetical.
- **`tools/guard.py c_decisions`:** if the registry row's project has
  `control.yaml target.active: true`, return 0 with "target-driven — no decisions.md
  expected" instead of the WARN "run /scope first". Test in `test_guard.py`.

### P3.3 — `show_config.py` effective table: venue/page_limit provenance
- **File:** `tools/show_config.py` `SKILL_KEYS` — add:
  `("writing.venue", "writing.venue", "writing.venue")` and
  `("writing.page_limit", "writing.page_limit", "writing.page_limit")` (control-first,
  lab fallback — the two keys docs explicitly allow per-project overrides for).

### P3.4 — lit-review depth knob
- **`lab/config.yaml`:** new tiny section:
  ```yaml
  litreview:                    # ── /lit-review depth ──
    max_minutes: 45             # cap on the live search phase (0 = unbounded). The depth knob
                                # /discuss.max_research_minutes is the analogue for /discuss.
  ```
- **`.claude/skills/lit-review/SKILL.md`:** reference it where the search loop is
  defined ("stop the sweep at `litreview.max_minutes`; log what was NOT covered").
- **`docs/configuration.md`:** Layer-1 row (agent-readable).
- Skip `min_papers` (the write-paper skill already demands 20+ bib candidates — enough).

---

## Cross-cutting verification (run after each phase; all must be green before commit)

1. `uv run --with pyyaml --with pytest python -m pytest tests/ -q` — full hermetic suite
   (baseline today: 259 passed).
2. `uv run --with pyyaml python tools/role_sync.py check` — exit 0 after render (P1).
3. `uv run --with pyyaml python tools/check_lab.py` — exit 0.
4. `uv run --with properdocs --with mkdocs-material properdocs build --strict` — clean.
5. Spawn-smoke (CI runs it on `templates/project/` changes; run locally too):
   instantiate the template with dummy placeholders, `scripts/check_project.py`,
   `uv run pytest`, one SMOKE — confirms the new `.claude/agents/` files ride along and
   nothing has unsubstituted `{{`.
6. Greps that must come back clean:
   - `grep -rn "cannot be applied\|can't apply\|maps to no file" .claude/skills docs lab AGENTS.md` — no stale critic_model claims (P1.6).
   - `grep -rn "scripts/lab_bus" .claude/skills/ideate` — empty (P0.1).
   - `grep -rn "fable" lab/config.yaml docs/configuration.md` — present (P1).
7. Manual: `tools/profiles.py diff low && apply low && diff low` (second diff empty;
   `.codex/agents/*.toml` and `.claude/agents/*.md` both updated), then re-apply the
   PI's real settings.

## Non-goals (deliberately excluded as bloat — do NOT implement)
- **Token/$ cost ceilings** — the harness can't meter tokens mechanically from inside;
  wall-clock (`max_minutes`, watchdogs) stays the enforceable proxy.
- **A `control.yaml agents:` block** (project-layer per-role model plumbing) — the
  project-layer knob is the rendered role-file frontmatter itself (P1.5); a second
  config path would add a resolution layer for a rare need.
- **A parallel Codex tier map** — tier keys are Claude-native; Codex gets the optional
  per-role `codex.model` passthrough (P1.8) and the honest doc note.
- **Webhook/notification config, dashboard auth token, S2 retry/timeout knobs, per-stage
  (SMOKE-cheap/FULL-strong) model switching** — surveyed, judged not worth the surface.

## Suggested commit sequence (PI controls commits; never push to origin without explicit confirmation — shared AkxarLabs upstream)
1. `P0: fix ideate bus path + close doc/config drift (journey+config audit)`
2. `P1: model tiers — agents.tiers, critic_model applied, per-role effort, project role files`
3. `P2: wire the dormant guards (state/evolve/frozen/writeback) + compete Gate-1 marker`
4. `P3: polish — kill/paper_compiled events, target-driven revisit gating, venue provenance, litreview cap`
Each ends with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
