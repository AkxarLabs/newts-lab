# The dashboard

*Local-only. Nothing leaves your machine. Delete the `dashboard/` folder and the lab still works from a terminal.*

The dashboard is the lab's product surface. Start it, pick or create a lab, and do everything from
there: set up the lab, connect an agent, start work, watch it, answer its questions and approve the
three gates. The lab is drawn behind it as a 3D tabletop.

<figure markdown>
![Home: the lab as a 3D tabletop, with the Today panel](assets/dashboard-home-dark.png){ .as-shot }
<figcaption><strong>Home</strong>: each stage of the research is a room on the table. The <strong>Today</strong> panel lists what needs you, what is running and what is next. The bar underneath takes a question or an instruction.</figcaption>
</figure>

## Start it

Double-click **`Start Newts Lab.cmd`** (Windows) or **`start-newts.command`** (macOS), or run:

```bash
uv run --with pyyaml python newts.py
```

It starts the server for the lab in that folder, in the background, and opens your browser at
`http://127.0.0.1:8787`. Closing the window stops nothing: queued runs, retries and campaigns keep going.
Stop the server from **Settings → About**, or with `newts.py --stop`. `--foreground` keeps it in the
window. If the port is taken it picks the next free one. Other options: `--hub <another lab>`,
`--port`, `--no-browser`. The server only listens on `127.0.0.1`. The one prerequisite is
[uv](https://docs.astral.sh/uv/).

**On a remote machine.** Run `newts.py --background` there. It keeps running after you log out, and on a
box with no desktop it prints the `ssh -L` line to use from your computer. Or add the machine to your
local dashboard (below). See [Machines & compute](compute.md).

### The top bar

| | |
|---|---|
| **Lab name** (top left) | Opens **Labs & machines**: switch labs, add a machine. |
| **Home · Studies · Runs · Results · Library · Workflow** | The pages. On a phone, **More ▾** opens the rest. |
| **⏸ Pause lab** | Stops every agent now. They resume when you press **Resume lab**. It shows while anything runs. |
| **Sun / moon** | Theme: System, then Light, then Dark. |
| **Search** (`/` or `Ctrl+K`) | Jump to any study, run, page or action. |
| **Bell** | Everything that needs you, with a count. |
| **Settings** | All customisation, in one place. |

### Labs & machines

**Labs & machines** shows every lab on this computer and every remote lab you have opened, with what
needs you in each. Click an item to go straight to it. From there you can:

- open a recent lab, or any folder that contains `lab/config.yaml`;
- create a new lab: a name and a place (`tools/new_lab.py` copies the template and makes the first commit);
- switch labs live. Agents that are running keep running;
- add a machine you reach over SSH. The dashboard starts that lab's own server there and tunnels to
  it, and the top bar says *on &lt;machine&gt;*. Remote labs stay connected in the background.

## First run: the setup wizard

A lab that has not been set up opens the wizard (`#/setup`). You can skip it and come back from
Settings → About.

1. **Welcome.** What the lab is: the lab folder, a project repo per approved study, and three gates only you approve.
2. **Agents.** One card per agent CLI (Claude Code, Codex, opencode) showing whether it is installed and
   signed in. **Install…** and **Sign in…** open a terminal window running the CLI's own installer or
   login. Your credentials go to the CLI, never to the page.
3. **Autonomy.** Whether the dashboard may start agents, the default agent, the budget tier, how many
   runs at once, and how strict the oversight is. Everything is written to `lab/config.yaml`.
4. **Your research.** `/setup-lab` runs as a conversation: research areas, compute, venue, models.
5. **First step.** Explore a new direction, bring in what you have, talk it through, compete on a
   target, start a campaign, or take the one-minute tour of the Workflow page.

<figure markdown>
![The setup wizard: connect an agent](assets/dashboard-setup.png){ .as-shot }
<figcaption>Step 2 of the wizard: one card per agent CLI. The card turns green by itself once you have signed in.</figcaption>
</figure>

## Home

The workflow's rooms stand on a table round your desk. Each study is a card on its room's shelf, and
each run is a newt at its station, its subagents smaller newts beside it.

| Room | Stage |
|---|---|
| **The Incubator** | ideas (`seed`, `triaged`) |
| **The Study** | literature review, scoping, proposal. **Gate 1** is at its door |
| **The Lab** | experiments. **Gate 2** is at its door. One lab per live project |
| **The Bench** | analysis |
| **The Writing Room** | writing and internal review. **Gate 3** is at its door |
| **The Archive** | finished studies |
| **The Margins** | parked and killed studies |

In the world:

- Click a card to open its study, a gate arch for the study waiting on it, a room to zoom in.
- Click a newt to open its run: what it is doing, its subagents, what it handed back.
- Click the desk for the inbox, or the big Newt to start something.
- Drag to turn, scroll to zoom. The chips top left (**Work, Cost, Waiting on you, Risk**) re-tint the rooms.
- **Key** (bottom left) lists the roles with live counts.

The **Today** panel on the right (collapsible) has **Start something**, your campaigns, **Needs you**
(gates, questions, permission requests, crashed or silent runs), **Running**, **Up next**, **New
results to look at**, **Just finished** and **Since you were last here**. Most rows can be acted on in place.

<figure markdown>
![Home by day](assets/dashboard-home-light.png){ .as-shot }
<figcaption>The same Home by day. Night adds glowing room trim, street lamps and fireflies.</figcaption>
</figure>

Your other labs stand as small tables past the back edge. Without WebGL the dashboard works the same,
minus the world.

## Starting work

**Start something** opens one sheet. At the top you can type a question or an instruction. Below it are
the procedures, in plain words:

| Intent | Runs | Stops |
|---|---|---|
| Explore a new direction | `/ideate` | when the best 1 to 3 ideas are filed as studies |
| Bring in what I have | `/adopt` | once it is in the lifecycle |
| Talk it through | `/discuss` | crosses no gate |
| Work on a study | the procedures that fit its stage | at the procedure's own stop point, or at a gate |
| Advance a study one step | `/advance` | after one stage |
| Plan a campaign | `/autopilot` under a brief you approve | at anything outside the brief's limits |
| Compete on a target | `/compete` | at its own Gate 1 |
| Check on the lab | `/lab-status` | with a recommendation |

**Options** apply to that run only: the agent and model, the effort level, the time limit, what happens
when it finishes (stop, run its next step, or keep going until a gate), and **repeat every N minutes**.

The first time you start something, the dashboard asks once to let it start agents. Runs queue first and
start when a slot is free, within the limits in Settings → Limits & permissions.

<figure markdown>
![Start something](assets/dashboard-start.png){ .as-shot }
<figcaption><strong>Start something</strong>: an instruction box on top, then every procedure in plain words.</figcaption>
</figure>

### Ask or instruct

Type in the bar under the world, or at the top of Start something.

**Questions the dashboard can answer from the lab's live state get an instant answer, with no agent.**
For example "what needs me?", "what's running?", "how much have we spent today?" or "how is moe doing?".
It costs nothing and offers **Ask an agent anyway**.

Anything that asks for work or judgement ("compare the last three trial runs of moe and say which setting
mattered") starts a run in the whole lab or a chosen study. It can use any procedure, but it can never
approve a gate. Reply to continue it. The ✉ button leaves a note for the next agent instead of starting one.

## Runs are conversations

Open any run and it reads like a chat: the agent's messages, its tool calls folded into groups, its
subagents inline, and a report at the end with its next step as a button.

- **Questions become forms.** The run pauses until you answer, then continues in the same session.
- **Permission requests** show *Allow once / Deny*. A live run waits for you; a campaign's runs are denied at
  once and the denial appears under Needs you.
- **Message** a running agent: it reads your message after its current step. **Reply** to a paused or finished run to continue it.
- **⏸ Pause step** stops the current step and keeps the run open. **Stop** ends it but leaves it
  resumable, and **Resume** continues it.
- **What it wrote** lists every file the run created or edited, openable in place.

The **Runs** page lists every run, filterable by waiting for you, running, queued, finished and failed.
Runs belong to the executor, not to the page: close the dashboard and they keep going.

<figure markdown>
![A run, as a conversation](assets/dashboard-run.png){ .as-shot }
<figcaption>A run opens as a conversation: messages, folded tool calls, what it showed you, and a reply box.</figcaption>
</figure>

## Results

**Results** (`#/artifacts`) is what agents made for you: a plan, a report, a figure, a table, a page, or
a question. An agent publishes with:

```bash
python tools/artifact.py publish --title "Pilot results" --file analysis/pilot.md [--note "…"]
python tools/artifact.py publish --title "Which eval set?" --question "Freeze A or B?" --choices "A;B"
```

Each is shown in place: Markdown with maths, HTML in a sandboxed frame, images, PDFs, tables and text. A
question waits under Needs you until you answer. Your reply goes to the run that asked, or becomes a note
the next agent reads. Publishing asks for a look and is never a gate approval.

## Studies

**Studies** is a pipeline board with a column per room, or a table. A **study page** (`#/study/<slug>`) has:

- a stepper from seed to final, with the gates drawn as doors that glow when they wait for you;
- one primary button for the natural next step, and **Work on it…** for everything else;
- tabs: **Overview**, **Documents**, **Runs**, **Experiments** (budgets, compare runs, start experiments),
  **Instructions** (customise this study only), **Paper** (the PDF, figures and **Claims ↔ evidence**) and
  **Controls** (the research loop, park, kill, revive).

<figure markdown>
![The Studies board](assets/dashboard-studies.png){ .as-shot }
<figcaption>The <strong>Studies</strong> board, a column per room.</figcaption>
</figure>

<figure markdown>
![A study page](assets/dashboard-study.png){ .as-shot }
<figcaption>A <strong>study page</strong>: the stepper with its gates, one next-step button, and the tabs.</figcaption>
</figure>

## Approvals: only you approve

Every approval works the same way. A **gate sheet** shows what you are approving beside the controls, says
exactly what will be written, asks you to confirm, logs it to `lab/.bus/pi-actions.jsonl`, and lets you
**withdraw** it. **Ask for changes…** sends your notes and leaves the gate open.

- **Gate 1: the proposal.** The hypothesis, the frozen evaluation and analysis plan, the budget and the
  kill criteria. You can approve the Gate 2 limits with it. The project repo is created next.
- **Gate 2: full runs.** Edit the number of full runs, minutes per run and total minutes against a live
  capacity readout, then approve. Changing approved values withdraws the approval.
- **Gate 3: finalize the paper.** A readiness checklist, the claims, the meta-review and every review.
  Approving needs you to type the study's name. It allows exactly one `/finalize` run, started by you.
- **The loop brief.** Read it, choose *execute* or *explore*, approve it.
- **A campaign.** *Plan a campaign* sets the direction, how many ideas and how many at once, the hours,
  a spending cap and the limits. Within them the campaign approves Gate 1 for you and derives each project's
  full-run limits. Gate 3 stays yours unless you tick *Papers can be finalized without me*.
- **Revive** brings a parked or killed idea back into Ideas. A reason is required.

<figure markdown>
![The Gate 3 sheet](assets/dashboard-gate3.png){ .as-shot }
<figcaption>The <strong>Gate 3</strong> sheet: the readiness checklist and the approve button beside the review material.</figcaption>
</figure>

**The signature guard** (`tools/signature_guard.py`) is a hook every dashboard run carries, for claude,
codex and opencode. It denies any agent write that would create or change an approval: a gate marker, an
envelope, `gate3-approval.md`, a loop or campaign brief, a registry row moved to `final`, PI-owned
configuration, the PI-action log. Denials appear under Needs you. That is what makes it safe to let agents
run freely.

## Workflow, Library, History

- **Workflow** is everything the lab is made of, all of it editable: the pipeline and its rooms, procedures
  (their method and your own instructions), roles, rules, checks and project types. Edits go into a
  draft. **Review & publish** shows the diff and whether the lab still reads consistently, and a publish can
  be undone. Agents' suggested changes arrive for you to accept or decline. See [Customising the lab](customising.md).
- **Library** holds every document the lab writes, rendered offline: knowledge, notebook, campaigns, and
  one shelf per study. `lab/SYSTEM.md` and the open questions are edited in place.
- **History** lists every event, and every command and note you sent with its status.

## Settings

All customisation is in one panel (`#/settings`), with a note on each section saying whether it applies
to the lab or only this browser.

| Group | Section | What it holds |
|---|---|---|
| This lab | **Agents & models** | the agent CLI cards, default agent and model |
| | **Limits & permissions** | whether the dashboard may start agents; what agents may do without asking; how many at once; time and cost limits; how long runs wait for you; advanced |
| | **Research defaults** | name, where projects go, venue, page limit, budget tier |
| | **This machine & compute** | what the machine offers, where training runs |
| | **Research keys** | Semantic Scholar, OpenAlex and others, kept in the git-ignored `lab/.env.local` and never shown again |
| | **About** | the lab, a terminal in the lab folder, the setup wizard, **stop the server** |
| This browser | **Appearance** | theme, density, motion, speech bubbles, who plays the agents |
| | **Notifications & sound** | desktop notifications; chimes and soft generated music; your phone (an [ntfy](https://ntfy.sh) topic or a Slack, Discord or Teams webhook) |
| How the lab works | links into **Workflow** | procedures, roles, rooms, rules |

Only the title and one line of each blocking item are ever sent to a phone, never files or transcripts.
Music and chimes are off by default and made in the browser. Turn them on in Settings or from the search menu.

## What still happens outside the dashboard

- Editing code and experiment configs, and git commits and pushes. Every document has *open in editor*.
- A `/compete` project's Gate 3 and anything that leaves the lab (arXiv, a submission).
- The CLI's own sign-in, in the terminal window the dashboard opens for it.

For how it works inside (the event bus, tracing, the server and the 3D world) see
[Dashboard internals](internals.md).
