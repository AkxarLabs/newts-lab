---
name: setup-lab
description: First-run interview — ask the PI the key questions, write lab/config.yaml accordingly, verify the environment, and seed the first directions. Run once after instantiating the template (and any time to reconfigure).
---

# Setup Lab

Goal: an interview that leaves the lab configured, verified, and pointed at the PI's
research interests. Ask the questions below (grouped, not one at a time); write the
answers into `lab/config.yaml` (preserving comments); report what was set.

## 1. Interview

**Research focus**
- What area(s) do you research, and the 1–3 directions you most want explored first?
  → seed each as an entry in `lab/knowledge/OPEN-QUESTIONS.md` (Q-001…), which
  `/ideate` reads first.

**Budget tier (a fast starting point)**
- How much should the lab spend by default — `low` (few subagents, single-ish idea search, cheaper
  models), `medium` (the balanced default), or `high` (max parallelism, more ideas, strongest
  models)? → `tools/profiles.py apply <tier>` stamps the whole set of depth/parallelism/model knobs
  at once; the questions below then fine-tune it. (Tiers never lower the integrity floors — seeds,
  oversight, frozen eval, gates stay safe at every tier.) See `docs/configuration.md` → Profiles.

**Compute reality**
- What hardware runs experiments (GPU? how many concurrent training runs can it take)?
  → `compute.max_concurrent_runs`.
- Typical tolerable wall-clock for a FULL run? → noted for proposal/control defaults.

**Autonomy appetite**
- Default Gate 2 stance: per-FULL-run approval, or routinely grant envelopes at Gate 1?
  → note in config comments; affects what `/propose` offers.
- Oversight level (`oversight.level`): `standard` (recommended) or `strict` (more
  overseer checks, more tokens)?

**Paper venue**
- Target venue for papers — `writing.venue` (`neurips` default · `icml` · `iclr` · `aclarr` ·
  `aaai` · `generic`) + the matching `writing.page_limit` (neurips/iclr 9 · icml/aclarr 8 · aaai
  7). Both PI-owned; a wrong default silently shapes every paper.

**Models & keys**
- The **model ladder** — three tiers the roles draw from: `strong` (strongest, judgment-heavy),
  `standard` (workhorse), `fast` (cheap, high-volume). Ask the PI for each (e.g. `opus` / `sonnet`
  / `haiku`, or a full pinned id; `inherit` everywhere is the safe default and ships unchanged) →
  write `agents.tiers.{strong,standard,fast}`. The per-role keys (`reviewer_model`, `runner_model`,
  `overseer_model`, `critic_model`) default to sensible tier names and `tools/role_sync.py` renders
  them into the `.claude/agents/*.md` + `.codex/agents/*.toml` role files (a role key may also name
  a model directly). `critic_model` (ideation critics / scoping advocates) is applied on Claude Code
  via `/ideate` & `/scope`'s per-spawn Task `model`; other backends run them at the session model.
- **Headless launch settings** (`agents.programmatic.*`: whether the dashboard may start agents, the
  backend, its model, the permission posture, limits) are the PI's dashboard settings — the setup
  wizard's Agents and Autonomy steps, or Settings → Autonomy & limits. Don't write them from here (the
  signature guard refuses it in a headless run); if the PI asks, point them there.
- Semantic Scholar API key? (Free with an institutional email — strongly recommended;
  keyless access is saturated.) → tell them to set `S2_API_KEY`; same for
  `OPENALEX_API_KEY`.

**Projects location**
- Keep `lab.projects_root` at `../newts-lab-projects` or elsewhere?

**The machine itself (optional)**
- Anything the implementation agent should know about the machine(s) experiments run
  on — data/cache locations, scheduling etiquette, forbidden actions, known quirks?
  → if yes, create `lab/SYSTEM.md` from `templates/SYSTEM.md` with their answers
  (PI-owned; copied into every spawned project, where it binds the agent like
  control.yaml). If no, skip — absence means "no constraints beyond the protocol".

**Dashboard (optional)**
- The lab's dashboard (`Start Newts Lab`, or `uv run --with pyyaml python newts.py`) is where the PI
  starts work, watches runs and signs gates — Gate 1, Gate 2 and Gate 3 (with a typed confirmation) —
  and signs campaigns, which can delegate Gate 1/2 and, if the PI ticks it, Gate 3. `dashboard.*` keys
  are the PI's dashboard settings; mention the dashboard and move on.

## 2. Apply & verify

1. Write the answers into `lab/config.yaml`.
2. Environment check: `git --version`, `uv --version`, `uv run --with pyyaml python
   tools/check_lab.py` (should pass on an empty lab), `uv run --with properdocs
   --with mkdocs-material properdocs build --strict` (docs build), and `latexmk --version`
   + `chktex --version` (required by `/write-paper`'s blocking compile gate — a paper can't
   reach Gate 3 without a PDF). Report anything missing with the install command (TeX:
   TeX Live / MiKTeX).
3. Smoke the project template once in a temp copy so the first real spawn is never the
   first test: **substitute the `{{slug}}`/`{{title}}`/`{{date}}`/`{{hub_path}}` placeholders
   with dummy values first** (same list as `/spawn-project` step 3 — `pyproject.toml`'s
   `name = "{{slug}}"` is an invalid package name, so a verbatim copy can't `uv sync`),
   then `uv sync`, run the smoke config, and `uv run pytest`.

## 3. Hand off

Report the configuration summary, then offer the two on-ramps:
- Interactive: `/ideate <first direction>` — walk the lifecycle with gates.
- Unattended: `/autopilot` — authorize a campaign and let the lab run while you sleep.
- Somewhere between: `/advance <slug>` — one lifecycle stage at a time, you verify
  between stages. Have an existing idea or codebase? `/adopt` enters mid-lifecycle.
- A task with a fixed target (benchmark / leaderboard / KPI, no paper)? `/compete` spins off a
  target-driven project that iterates toward the metric.
