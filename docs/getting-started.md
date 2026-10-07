# Getting started

## The fastest way: the dashboard

1. Install [uv](https://docs.astral.sh/uv/) and git, and get the template (see
   [Instantiate your lab](#instantiate-your-lab) below).
2. Double-click **`Start Newts Lab.cmd`** (Windows) or **`start-newts.command`** (macOS), or run
   `uv run --with pyyaml python newts.py`. Your browser opens the dashboard.
3. Follow the setup wizard:
   - connect an agent (install it and sign in through its own login window);
   - choose how much the lab does on its own;
   - answer the `/setup-lab` interview right in the page;
   - pick an on-ramp.

After that you work from the dashboard: **Start something** (or just type a question), watch the runs as
conversations, answer the agents when they ask, and approve the gates when they wait for you. The rest
of this page is the same lab from a terminal. See [The dashboard](dashboard.md) for the full tour.

!!! tip "On a server, a GPU box or a cluster"
    Run `uv run --with pyyaml python newts.py --background` there. It keeps running after you log out
    and prints the one `ssh -L` line to use from your own computer. Or add the machine in your local
    dashboard (Labs & machines → Add a machine) and it connects for you. On a cluster, set how training
    runs (SLURM or another scheduler) in Settings → This machine & compute. See [Machines & compute](compute.md).

## Prerequisites

- [Claude Code](https://claude.com/claude-code) — the first-class agent driver
- [uv](https://docs.astral.sh/uv/) — Python env/deps for projects and the lab tools
- git

!!! tip "Other agents (Codex, Cursor, …)"
    The lab is drivable by any agent that reads `AGENTS.md` — the root one carries the
    protocol and how to follow the `.claude/skills/` procedures manually (including how
    to approximate the multi-agent steps); every spawned project ships its own
    `AGENTS.md` so any agent can run experiments in it directly.

## Instantiate your lab

Newts' Lab is a **template repository** — each lab is a living instance of it:

1. On GitHub: **Use this template** → create your lab repo (or `npx degit <repo> my-lab`, or plain clone).
2. Open `lab/config.yaml` and check the two keys that matter on day one:
   - `lab.projects_root` — where project repos are created (default: `../newts-lab-projects`, a sibling folder next to the hub)
   - the `critique` / `experiment` / `loop` defaults (sane as shipped)
3. That's it. Lab state (`lab/REGISTRY.md`, knowledge, notebook) starts empty and fills as you work.

!!! note "Upgrading an instance later"
    Add the template as a second remote (`git remote add template <url>`) and cherry-pick improvements to skills/templates/tools. Your lab state never conflicts — it lives in files the template doesn't touch.

## The git model — what's yours, what's shared, what's ignored

Your lab is a single git repo that mixes three kinds of files. The rule of thumb: **commit your config and your research to your own lab — that's how a lab persists and compounds ("git is memory"). Only lab-*machinery* improvements ever flow back to the template. Runtime scratch is already ignored.**

| Kind | Examples | Commit to your lab? | Send upstream to the template? |
|---|---|---|---|
| **Machinery** | `.claude/skills/`, `tools/`, `templates/`, `dashboard/`, `docs/`, `AGENTS.md`, `AGENT-GUIDE.md`, `CLAUDE.md` | rarely — you mostly don't edit these | **yes** — as PRs (that's contributing) |
| **Config & identity** | `lab/config.yaml`, `.claude/agents/*.md` (rendered), `SYSTEM.md` | **yes** — your settings, versioned | no — personal (your budgets, models, machine) |
| **Research memory** | `lab/REGISTRY.md`, `lab/notebook/`, `lab/knowledge/`, `studies/`, `lab/ideation/` | **yes** — this *is* the lab's memory | no |
| **Runtime scratch** | `lab/.bus/`, `lab/.slots/`, project `runs/`, `site/`, `research/` | already **`.gitignore`d** — stays local | — |

So committing config edits and generated ideas to *your own* lab repo is the intended model, not clutter. What must never happen is your lab state going **upstream** to the shared template you cloned from — which is exactly why the lab ships as a *template*, not something you fork.

Two things that surprise people at first:

- **Editing config re-renders subagent files.** `/setup-lab` and `/configure` regenerate `.claude/agents/*.md` from your `agents.*` settings (via `tools/role_sync.py`), so one config change shows up as a two-file diff. They're committed pre-rendered **on purpose** — a fresh clone (or a teammate) has working subagents immediately, with no build step.
- **Ideas and the notebook are committed, not ignored.** They are durable memory, not logs. The ephemeral *signal* — the event bus and compute-slot ledger under `lab/.bus/` and `lab/.slots/` — is what's gitignored; the *output* of ideation (`studies/`, `lab/ideation/`, the notebook) is versioned so it can compound across sessions.

## Your first session

```text
cd your-lab
claude
> /setup-lab                               # 5-minute interview: compute, autonomy, models, directions
```

`/setup-lab` configures everything interactively (it writes `lab/config.yaml` for you).
Then pick your on-ramp — there is one for every starting point and autonomy appetite:

| You have / you want | Start with |
|---|---|
| Nothing yet — explore a direction | `/ideate <direction>` — walk the lifecycle with gates |
| An idea, a known literature, or an existing codebase | `/adopt` — scaffold the right files and enter mid-lifecycle (optionally `/discuss direction` first to sharpen it; `/adopt` reads its session doc) |
| One stage at a time, verifying between stages | `/advance <slug>` — runs exactly the next stage, then stops for you |
| Hands-off: approve once, read drafts in the morning | `/autopilot` — approve a campaign and go to sleep |

See [Autonomy & modes](autonomy.md) for how the modes differ and how the unattended
ones compose with Claude Code's built-in `/loop` scheduler.

The agent generates and tournament-ranks candidate ideas, then walks the lifecycle:
`/lit-review` → `/scope` → `/propose` → **Gate 1 (you)** → `/spawn-project` →
`/experiment` → `/analyze` → `/make-figures` → `/write-paper` → `/review-paper` →
**Gate 3 (you)** → `/finalize`.

You'll be stopped at the gates and otherwise left to read the notebook.

## Watching it work

The [dashboard](dashboard.md) is the lab's product surface; you don't need the terminal at all:

- **Home**: the 3D lab with what needs you, what is running and what is next.
- **Studies**: a pipeline board, and a page per study.
- **Runs**: every agent as a conversation.
- **Results**: what agents made for you.
- **Library**: every document.
- **Workflow** and **Settings**: change how the lab works, and its limits.

It runs the same agent CLIs as you, with your login, and every run carries a guard, so
agents can never approve a gate for you.

```bash
uv run --with pyyaml python newts.py        # http://127.0.0.1:8787 (opens your browser)
```

A session in a terminal and the dashboard work side by side: a command or note you leave in the
dashboard reaches a terminal session at its next checkpoint, and a terminal session's work shows up
live in the dashboard.

## Serving these docs

No installation needed — uv runs [ProperDocs](https://properdocs.org/) (the maintained MkDocs successor; the Material theme runs on top of it) ephemerally:

```bash
uv run --with properdocs --with mkdocs-material properdocs serve    # http://127.0.0.1:8000
uv run --with properdocs --with mkdocs-material properdocs build    # static site into site/
```

!!! note "Auto-published on push"
    The `docs` GitHub Actions workflow (`.github/workflows/docs.yml`) builds the site with
    `--strict` on every push and pull request (so a broken link fails the check) and deploys
    it to GitHub Pages on a push to the default branch. One-time setup in your lab repo:
    **Settings → Pages → Source = "GitHub Actions"**. The companion `ci` workflow lints the
    registry, imports the dashboard, and spawns the project template to run its smoke test on
    Linux and Windows.

## A typical week with the lab

| When | What happens |
|---|---|
| Monday | `/ideate` from `lab/knowledge/OPEN-QUESTIONS.md` (skim `REFERENCES.md` for prior reading); pick one; `/lit-review` overnight |
| Tuesday | Read the proposal, approve Gate 1 with a small Gate 2 limit |
| Tue–Thu | `/spawn-project`, pilots via `/experiment`, then `/research-loop` overnight within those limits |
| Friday | Read the PI morning report, `/analyze`, decide: ablate further or start `/write-paper` |
| Next week | `/review-paper` cycles until the ensemble accepts; Gate 3; `/finalize` writes the knowledge back |
