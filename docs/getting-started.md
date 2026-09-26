# Getting started

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
| **Machinery** | `.claude/skills/`, `tools/`, `templates/`, `dashboard/`, `docs/`, `AGENTS.md`, `CLAUDE.md` | rarely — you mostly don't edit these | **yes** — as PRs (that's contributing) |
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
| Hands-off: sign once, read drafts in the morning | `/autopilot` — authorize a campaign and go to sleep |

See [Autonomy & modes](autonomy.md) for how the modes differ and how the unattended
ones compose with Claude Code's built-in `/loop` scheduler.

The agent generates and tournament-ranks candidate ideas, then walks the lifecycle:
`/lit-review` → `/scope` → `/propose` → **Gate 1 (you)** → `/spawn-project` →
`/experiment` → `/analyze` → `/make-figures` → `/write-paper` → `/review-paper` →
**Gate 3 (you)** → `/finalize`.

You'll be stopped at the gates and otherwise left to read the notebook.

## Watching it work (optional)

To keep an eye on the lab while agents iterate — every lifecycle stage and every running
project, live — launch the optional [Vivarium dashboard](dashboard.md): the lab rendered as a
**living lab world** — each lifecycle stage is a room, each idea
or project is a critter living in its room, and every working agent is its own **sub-newt** you
can **click to inspect** (a legend bottom-left maps role → colour with live head-counts). A buddy
named Newt moves through it, and you click to **command** the agents (start/stop loops, request
runs, approve Gate 1 & 2), all from the scene.

One thing to know before you click: the dashboard **observes and signs — the agent executes**.
Commands and gate approvals are recorded to the lab's file bus, and a Claude session acts on
them at its **next checkpoint** (session start / loop cycle). With no session running, nothing
happens until you start one (`claude` → `/lab-status`). Against a brand-new lab (empty registry)
the world is empty and there are no gates to approve yet — they appear once a session produces
a proposal.

```bash
uv run --with pyyaml python dashboard/serve.py        # http://127.0.0.1:8787
```

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
| Tuesday | Read the proposal, approve Gate 1 with a small Gate 2 envelope |
| Tue–Thu | `/spawn-project`, pilots via `/experiment`, then `/research-loop` overnight under the envelope |
| Friday | Read the PI morning report, `/analyze`, decide: ablate further or start `/write-paper` |
| Next week | `/review-paper` cycles until the ensemble accepts; Gate 3; `/finalize` writes the knowledge back |
