# Contributing to Kartr Lab

Thanks for improving the lab. This guide is about contributing to the **lab machinery**
— the skills, tools, templates, dashboard, and docs in this repo. It is *not* about
running research: doing `/ideate → … → /finalize` is **using** the lab, and that work
lands in your own lab state (`lab/`, `studies/`) and your project repos, never
in a PR here.

Two kinds of change live in this repo:

| You're changing… | Then… |
|---|---|
| **Lab machinery** — a `.claude/skill`, a `tool`, a `template`, the `dashboard`, `docs` | open a PR (this guide) |
| **Your research** — ideas, proposals, experiments, papers | stays in your lab/project state; nothing to PR |

## Dev environment

No install step — everything runs through [`uv`](https://docs.astral.sh/uv/), which
resolves dependencies per-command:

```bash
git clone <your-fork> && cd kartr-lab
uv run --with pyyaml --with pytest python -m pytest tests/ -q     # tools regression suite
```

Python is pinned via `uv`; you don't manage a venv by hand.

## Run the checks CI runs (before you push)

CI (`.github/workflows/ci.yml`) gates every PR on these — run them locally first:

```bash
# 1. Registry / idea consistency lint
uv run --with pyyaml python tools/check_lab.py

# 2. Hub trust-tools regression suite (hermetic — no network, no real lab touched)
uv run --with pyyaml --with pytest python -m pytest tests/ -q

# 3. Dashboard still reads a lab without crashing
uv run --with pyyaml python -c "import sys; sys.path.insert(0,'dashboard'); import sources; print(sources.snapshot()['cold'])"

# 4. Docs build clean (ALL internal links must resolve)
uv run --with properdocs --with mkdocs-material properdocs build --strict
```

A change to `templates/project/` also gets a **spawn smoke** in CI (it instantiates the
template and runs its `check_project.py` + pytest); if you touch the project template,
spawn it once and run a SMOKE experiment to confirm it still boots.

## Conventions (these keep the lab coherent)

These mirror the hard rules in [CLAUDE.md](CLAUDE.md) — the same discipline the agent
follows applies to changes you make by hand:

1. **Config values live in config files, never in skill prose.** Tunables go in
   `lab/config.yaml` (with a documented default + an entry in
   [docs/configuration.md](docs/configuration.md)) and are *read* by the skill — a skill
   file never hardcodes a number a PI might want to change. See
   [docs/configuration.md](docs/configuration.md) for the 3-layer model.
2. **Skills are instructions written *to the agent*** — second person, numbered steps,
   one procedure per `SKILL.md`. Keep them imperative and declarative; don't bury a knob
   in a paragraph.
3. **Tools resolve paths from a module-global `HUB`** (`HUB = Path(__file__).resolve().parents[1]`)
   read *at call time*. The test harness (`tests/conftest.py`) loads each tool as an
   isolated module and monkeypatches *that module's* `HUB` to a throwaway fake hub — so
   do **not** introduce a shared cross-tool module that holds its own `HUB`/state, or you
   break test hermeticity. Duplicating a small resolver (e.g. `projects_root()`) across
   tools is intentional, not a DRY violation to "fix".
4. **Append-only ledgers.** `lab/REGISTRY.md`, `lab/notebook/`, and the knowledge files
   are append/edit-forward; never rewrite history. Project ledgers
   (`EXPERIMENT_LOG.md`, `runs/registry.jsonl`) are append-only by hard rule.
5. **Docs must build `--strict`** — every internal link resolves, every page is in the
   nav (`properdocs.yml`). Add a doc page → add it to the nav.
6. **Extensibility over edits.** New behavior is a new config/module/skill behind an
   interface, not an in-place rewrite of a path everyone depends on. Anything runnable
   before your change stays runnable after it.
7. **PI gates are sacrosanct.** Don't add a path that lets the agent self-approve Gate 1
   (compute), launch a FULL run outside a signed `gate2_envelope` (Gate 2), or finalize /
   send anything outside the lab (Gate 3). Gate 3 is **never** delegated or
   dashboard-signed.

## Where things live

```
.claude/skills/<name>/SKILL.md   one procedure each (the slash commands)
.claude/agents/<role>.md         scoped subagents (model via `model:` frontmatter)
tools/*.py                       hub trust tools (hermetically tested in tests/)
templates/project/               the spawned-project repo template (own git, own env)
templates/paper/                 paper scaffold + venues/<venue>/ (vendored style files)
templates/{idea,review,loop,compete}/   other scaffolds
dashboard/                       optional offline Vivarium dashboard (delete-safe)
docs/                            the docs site (properdocs/mkdocs-material)
tests/                           hermetic pytest suite for the tools
```

Common tasks:
- **New skill** → add `.claude/skills/<name>/SKILL.md`, list it in
  [README.md](README.md) + [docs/skills.md](docs/skills.md).
- **New tool** → put it in `tools/`, read paths from a module-global `HUB`, and add a
  hermetic test in `tests/` (see `tests/conftest.py`'s `load()` + `hub` fixture).
- **New config knob** → add it to `lab/config.yaml` with a default + comment, document it
  in [docs/configuration.md](docs/configuration.md), and read it from the skill/tool.
- **New paper venue** → add `templates/paper/venues/<venue>/` (preamble + vendored
  `.sty`/`.bst`), extend the `writing.venue` enum, and update that dir's `README.md`.

## Git workflow

- Branch from `main`; keep a PR to one logical change.
- Commit messages: a short imperative subject line summarizing the change (match the
  existing log style, e.g. *"Harden the hub↔project boundary"*). If the change was
  AI-assisted, keep the `Co-Authored-By:` trailer.
- Make sure the four checks above pass locally; CI runs them on the PR.
- Don't commit machine-local files (`.claude/settings.local.json`), build output
  (`site/`), or runtime state (`lab/.bus/`, `lab/.slots/`) — they're already gitignored.

## Reporting issues

Open a GitHub issue with: what you ran (the exact command / skill), what you expected,
what happened (paste the relevant ledger/notebook lines or tool output), and your OS +
`uv` version. For a dashboard issue, note the browser and whether `?demo` reproduces it.
