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

**Compute reality**
- What hardware runs experiments (GPU? how many concurrent training runs can it take)?
  → `compute.max_concurrent_runs`.
- Typical tolerable wall-clock for a FULL run? → noted for proposal/control defaults.

**Autonomy appetite**
- Default Gate 2 stance: per-FULL-run approval, or routinely grant envelopes at Gate 1?
  → note in config comments; affects what `/propose` offers.
- Oversight level (`oversight.level`): `standard` (recommended) or `strict` (more
  overseer checks, more tokens)?

**Models & keys**
- Different models for subagent roles (`agents.*`), or `inherit` everywhere (default)?
  → if non-default, also set the `model:` frontmatter of the mapped `.claude/agents/<role>.md`
  (reviewer_model→fresh-context-reviewer, runner_model→experiment-runner,
  overseer_model→overseer); `critic_model` maps to no file (inline subagents — can't apply).
- **Headless launch backend** (matters once you run programmatic / multi-project autonomy —
  `agents.programmatic`): which backend (`claude` default, or `codex`), and the per-backend
  **default model + reasoning effort**? Ship-defaults are claude `claude-opus-4-8` at `--effort
  high` and codex `gpt-5.5` at `medium` reasoning — confirm or change per the PI's account/quota
  (codex model availability is auth-dependent; verify the slug on the host). Also the **permission
  posture** — claude `permission_mode: auto` + the project allowlist, codex `sandbox:
  workspace-write` + `approval: never` — keep the human-in-loop defaults unless the PI wants
  stricter (`dontAsk`) or needs network for codex (`network_access: true`). → write
  `agents.programmatic.backend` and `agents.programmatic.backends.{claude,codex}.{model,effort/
  reasoning_effort,…}`.
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
