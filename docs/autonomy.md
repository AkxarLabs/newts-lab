# Autonomy & modes

The lab runs at whatever level of autonomy you choose — from "I invoke every
procedure myself" to "one signature, read the drafts in the morning". Same
procedures, same gates, same integrity machinery in every mode; the modes differ
only in **who decides when the next step starts**.

## The four modes

| Mode | You | Command | Hand-off points |
|---|---|---|---|
| **Manual** | invoke each procedure | `/ideate`, `/lit-review`, … `/finalize` | every step is yours |
| **Stage-gated** | verify between stages | `/advance [slug]` | after *every* lifecycle stage |
| **Project loop** | sign a brief per project | `/research-loop <slug>` · `/improve <slug>` | experiments run unattended; analysis and writing wait for you |
| **Full autopilot** | sign one campaign brief | `/autopilot` | only the three PI gates (Gate 1 delegated within bounds; Gate 3 never) |

And you can **enter the lifecycle anywhere**: `/adopt` scaffolds the prerequisites
for an idea, a settled design, or an existing code/results repo you already have, so
any slice of the workflow is usable alone — lit-review only, experiments only, or
just the review machinery on a finished draft. Skipped stages are recorded as
PI-waived; numbers without artifacts still can't enter papers.

### Stage-gated: `/advance`

The semi-autonomous middle. Each `/advance` runs **exactly the next lifecycle stage**
for one idea, then stops with a verification summary: what changed, the 2–4 artifacts
worth your read, and what the next `/advance` would do. Your loop is *review →
`/advance` → review*. It never crosses a PI gate, and one stage means one stage — if
analysis routes back to experiments, that's the next `/advance`.

### Project loop: `execute` vs `explore`

`/research-loop <slug>` (and `/improve`) run a project's experiments unattended under a
signed `LOOP_BRIEF.md`. The brief's **`Mode:`** field chooses how much rope the loop has —
the PI's signature scopes it:

- **`execute`** (default) — run the approved `PLAN.md`: planned experiments → ablations →
  multi-seed confirmation → `/improve` operators (draft/debug/improve/crossover). When the
  plan is exhausted, the loop stops. A faithful, predictable plan-runner.
- **`explore`** — the autonomous in-project iterator (AutoResearch-style, with the lab's
  guardrails). When the plan is exhausted *with budget left*, instead of stopping the loop may
  **expand the frontier** — propose new, results-grounded experiment lines (each with a
  pre-written success criterion) — and **reopen a design decision** baked in at scoping time
  when the evidence fires its `decisions.md` **`Revisit if:`** trigger (retiring the lines that
  depended on it and re-planning under the new choice). All of this stays inside the **frozen
  set** (eval/test/seeds/budgets/kill-criteria, never touched), the **Gate-2 envelope**, and
  the `loop.explore_*` caps; the anti-burn backoff still ends a fruitless search.

  Frontier-`expand` is **incremental iteration WITHIN the headline hypothesis** — it is *not*
  divergent method-ideation. Generating a genuinely new *approach* to the project's problem is a
  separate, gated act: **`/ideate --in-project <slug>`** (the in-project mode of `/ideate` — a
  divergent approach generator scoped to the frozen set, whose output is candidate approaches, not
  experiments). It has **two independent PI-owned switches**: the ENABLE flag `ideation.in_project`
  (default `true`; a kill-switch — `false` turns the `--in-project` capability OFF) and the APPROVAL
  knob `ideation.in_project_approval`. See the `/ideate` skill for its
  generate→critique→tournament→triage pipeline and the re-enter-`/propose`-or-successor-idea rule.

The boundary is **mechanical**: each decision is flagged `Headline: yes/no` at scope time.
Reopening a *non-headline* decision and expanding the frontier are fully autonomous; reopening
a **headline** decision (the central hypothesis the proposal's novelty rests on), touching the
frozen set, or exceeding the envelope **escalates** — a PI note in manual/`execute`, or under a
signed `/autopilot` campaign the same delegation-bounds + overseer `support` check used for a
Gate-1 self-approval. A headline reopen is **not a dead end**: it routes to in-project
method-ideation — **`/ideate --in-project <slug>`** (enabled by `ideation.in_project: true` and
approval-gated by `ideation.in_project_approval`: PI-gated in manual runs, auto within campaign
bounds + overseer `support`; **if `ideation.in_project: false` the `--in-project` route is OFF —
fall back to** a successor hub `/ideate`) —
whose surviving approaches re-enter `/propose` (a mini-proposal that crosses Gate 1) or spawn a
successor idea, never entering experiments on a bare PI note. A pivot is never silent: it lands in
`decisions.md`, PLAN.md's Re-planning log, and the event bus (so the dashboard shows it live).
Default is `execute`, so nothing changes until you sign a brief that says `explore`.

**Enabling `explore` (what to flip, and who may).** Two independent switches, both PI-owned:

1. **Mode** — set `Mode: explore` in the project's `LOOP_BRIEF.md` when you authorize the loop
   (under `/autopilot`, set the campaign brief's "Loop mode for spawned projects" line instead;
   it flows into each spawned brief). This alone lets the loop **reopen non-headline decisions**
   when their `Revisit if:` triggers fire.
2. **Expansion caps** — to also allow open-ended **frontier expansion**, set
   `loop.explore_max_expansion_rounds` > 0 (and optionally `…_new_lines_per_round`) in the
   project's `control.yaml` — `/configure <slug> set loop.explore_max_expansion_rounds=2`. With
   the default `0`, an `explore` loop revisits decisions but does not expand the frontier.

Both are PI-owned (they widen the agent's authority), so `/configure` only changes them on an
explicit PI request — or transitively when an `/autopilot` campaign brief's delegation bounds
cover them. Per-decision `Headline: yes/no` flags are set by `/scope` and live in
`studies/<slug>/decisions.md`; changing one is a decisions.md edit, not a config key.

### Full autopilot: the one-command night

```text
claude
> /autopilot
```

Ten minutes of questions (direction, how many ideas, total budget, what proposal
shapes you pre-approve), one signature on a **campaign brief**, and the lab runs the
full pipeline unattended: ideation → lit review → scoping → proposal → project →
experiments → analysis → figures → paper → internal review — for several ideas as a
portfolio, advancing one idea's reading/writing while another's training run is in
flight.

**What you wake up to:** a morning report leading the lab notebook — drafts awaiting
your Gate 3 read (title, headline result with run ids, ensemble review score, open
items), ideas killed cheaply overnight (with reasons — kills are knowledge), and any
decisions that exceeded your delegation. Papers arrive at `internal-review`: drafted,
claims-audited, bibliography-verified, ensemble-reviewed. Gate 3 stays yours unless you tick
**Papers may finalize without me** on the brief (below).

### Walk away: a campaign from the dashboard

The usual way to run autopilot is the dashboard. **Start something → Plan a campaign** (or **Start a
campaign and walk away** in the setup wizard and on a quiet lab) takes:

- a direction;
- how many ideas, and how many at once;
- how long it may run;
- the compute bounds (they become each project's FULL-run envelope);
- optionally, an agent-hours budget and the Gate 3 box.

A **Before you walk away** check confirms that agents may start, the CLI is installed and signed in, it
won't stop for permissions, the projects folder is writable, and that LaTeX and keep-awake are available.
Then you sign once.

From then on the **campaign keeper**, part of the executor's scheduler rather than an agent, carries it:

- **Passes.** It runs `/autopilot continue` passes. Each pass looks at every idea and *dispatches* its
  next step (lit review, scoping, a proposal, the research loop, the paper…) as its own run. The keeper
  checks each step before starting it: a launchable procedure, a study of this campaign that isn't
  waiting for you, not a duplicate, within the brief's parallelism. Steps are capped, traced, and
  linked to the pass that started them.
- **Whatever happens to one run, the campaign goes on:**
  - a timeout starts the next pass right away;
  - a usage limit waits until it lifts (read from the CLI's message; that backend's queue is held too);
  - a network error backs off (2, 5, 15, 30, 60 min);
  - a failed step is retried up to 3 times.

  It stops to ask you only when it can't go on: the CLI needs signing in, or N passes in a row failed
  ("stalled").
- **Only that study waits.** A step that needs you (a proposal outside your bounds, a kill decision)
  shows in **Needs you**; the rest of the campaign carries on.
- **Questions while you're away.** A campaign's agents may still ask, with options and their
  recommendation first. Answer in time and it goes straight to the running agent; otherwise, after
  `live.campaign_question_minutes` (30), the agent takes its recommendation and **Needs you** shows
  *Assumed …* (reply to the run to change it). A question a pass leaves on the campaign card can be
  answered there: the next pass gets your answer.
- **It ends** at the deadline, the agent-hours budget, a pass reporting everything done, or your
  **Stop**, with one final pass that writes the morning report.
- **Gate 3, if you ticked the box:** once `/review-paper` accepts a paper, the keeper re-runs the four
  paper audits itself. If they're clean, the PDF and claims exist and nothing is escalated, it records
  Gate 3 (`signed_via: campaign:…`) and runs `/finalize`. That run makes the reproducibility pass,
  locks the artifacts and writes knowledge back. Nothing is ever sent outside the lab.
  - **Take Gate 3 back** on the campaign card and no paper of that campaign finalizes without you (a
    running `/finalize` is stopped).
  - **Hold** one study to keep just that one for yourself.

**Nothing depends on a window.** The launchers start the dashboard in the background: closing the window
doesn't stop anything, and Settings → About & server stops it. If the dashboard does stop with work
queued, it hands the scheduling to a background `executor_cli serve --until-idle`, and a finishing run
starts one if nobody is scheduling. While agents work or a campaign runs, the computer is kept awake
(Settings → Lab → *Keep the computer awake*). Closing a laptop lid on battery still sleeps; that is the
OS's decision.

The campaign card (Home and Studies) shows progress against the deadline, each study (waiting for you?
held?), what every pass did, the steps it started or refused and why, and questions a pass left. From it
you can Pause, Resume, Stop, take Gate 3 back, or hold a study.

## The authorization model (why this is safe to sleep through)

| Gate | Interactive modes | Campaign mode |
|---|---|---|
| Gate 1 (proposal) | you approve each | **delegated within signed bounds** (budget caps, kill criteria present, `novel` verdict, scoping passed) — anything outside queues for you |
| Gate 2 (FULL runs) | you approve / envelope | envelope derived from the campaign brief into each project's `control.yaml` |
| Gate 3 (finalize) | you approve each (in a session, or signed in the dashboard with a typed confirmation) | only if you tick **Papers may finalize without me**: the executor's campaign keeper (never an agent) records it once the paper passed internal review and its own run of the four paper audits is clean; you can revoke it, or hold one study, any time before /finalize |

Everything else runs exactly as in interactive mode — compute slots, budget watchdogs,
append-only ledgers, oversight checks, the author-response discipline. A campaign is
normal operation minus waiting for you, not a relaxed mode.

## Autonomy inside the project directory

A spawned project is autonomously operable on its own: it ships an **`AGENTS.md`** —
the project protocol and single source of truth (orientation order, autonomy bounds from
`control.yaml`, when to parallelize with subagents, the cold-start checklist, write-back
duties) — and a thin **`CLAUDE.md`** that imports it (`@AGENTS.md`) plus a few Claude-native
notes. The same manual drives Claude Code and any other agent (Codex/opencode), so `cd
project && claude` (or `codex`/`opencode`) is a complete working session with no hub context
needed. `scripts/check_project.py` lints readiness and suggests the next procedure.

Optionally, give the agent your machine's ground truth in a **`SYSTEM.md`** —
hardware and its honest concurrency limits, data/cache locations, scheduling
etiquette, forbidden actions, known quirks. Write it once at the hub
(`lab/SYSTEM.md`, offered during `/setup-lab`, template at `templates/SYSTEM.md`);
`/spawn-project` copies it into each project where you can tailor it. It is PI-owned:
agents — including experiment subagents — read and obey it like `control.yaml`, and
never edit it. No SYSTEM.md simply means "no constraints beyond the protocol".

The implementation agent decides for itself when to use subagents: parallel worktree
variants when several mechanism-distinct ideas are ready (capped by
`parallelism.max_parallel_subagents` and compute slots), sequential otherwise —
parallelism is a throughput tool, not a requirement.

## Keeping it running: the built-in `/loop`

Claude Code ships a scheduler: `/loop [interval] <prompt-or-skill>` re-runs a prompt
(or a skill, with arguments) while the session sits open. Our skills and `/loop` are
**complementary layers, not alternatives**:

- The **skill** is the procedure and the authorization: what to do, what's
  pre-approved (signed briefs, budget envelopes, gate delegation), the append-only
  ledgers that make every step resumable, the morning report.
- **`/loop`** is the re-entry scheduler: if a session crashes, compacts badly, or a
  step errors out at 3am, the next firing re-enters the skill and the Campaign/Loop
  Log resumes the work instead of restarting it.

Bare `/loop continue working` would re-prompt without any of the first layer — no
gates, no signed budgets, no recoverable state, no write-back — which is exactly the
unattended failure mode the briefs exist to prevent.

Canonical invocations:

```text
> /autopilot                                        # interactive part: sign the brief
> /loop 30m /autopilot continue lab/campaigns/<file>  # then the resilient night
> /loop /research-loop <slug>                       # a single project's loop, re-entered
```

What to know about `/loop` itself: it is **session-scoped** — it fires only while the
Claude Code session is open and idle (keep the machine awake), expires after 7 days,
and is restored by `claude --resume`. For unattended runs start the session with
permissions that won't stop to ask — `permissions.allow` rules in `.claude/settings.json`
covering the project's commands (the reliable way), and/or a non-stopping
`--permission-mode` (`auto` broadly approves in-repo work; `acceptEdits` covers file edits
but still prompts for shell) — a permission prompt at 3am blocks the night. Related
built-ins, for completeness:
`/goal` drives toward a single checkable condition (good for "make the smoke test
pass", too narrow for a campaign); cloud routines (`/schedule`) run without an open
session but in a fresh clone — only useful if your lab state is pushed and your
compute is reachable from it. (`claude -p` headless is also how the lab launches *project*
agents programmatically — see the next section.)

**No open session at all — the executor.** The re-entry loop above needs a terminal kept open. The
executor (`tools/executor/`, driven from the dashboard or `tools/executor_cli.py`) replaces it:
launch `/autopilot continue lab/campaigns/<file>` with a repeat interval
(`executor_cli.py enqueue --skill autopilot --args <file> --repeat-minutes 30`, or the dashboard's
run box) and each cycle is a fresh headless session, started by the scheduler when it's due — until
a stop condition, a needs-PI report, or `--max-repeats`. `/advance` works the same way with
*keep going until a gate* (`--chain loop`): each stage launches the next one it reports, and stops at
the first gate. See [Headless runs](#headless-runs-the-executor) below.

## Programmatic agents & multi-project fleets

A single session orchestrates work by spawning **worktree subagents** (the Task tool) for
parallel experiment *variants* — but those are short-lived, fire-and-return, and **cannot spawn
their own subagents** (subagent rule 6). So one session cannot run several long-running project
loops at once: a research loop *is* a top-level session, not a subagent. The lab scales to many
projects the other way — **multiple top-level sessions over shared files** — and
the executor (below) is how the hub launches them programmatically instead of by hand:

```bash
uv run --with pyyaml python tools/executor_cli.py enqueue --target <slug> --prompt-file <brief>   # one headless session, in the project repo
uv run --with pyyaml python tools/executor_cli.py list                                            # every run, its state
uv run --with pyyaml python tools/executor_cli.py stop --target <slug> | --campaign <name>        # stop them
```

For several projects at once, start a campaign from the dashboard: its keeper dispatches each project's
steps as their own runs, within the caps and the brief's parallelism. Launching is gated like the rest:
`agents.programmatic.enabled` is PI-owned and OFF by default, and a launched agent can't launch more
(`max_depth`). `ideation.in_project` and the Gate-2 `pi_signed` chain. Every launched agent **inherits every gate**:
FULL runs still need a signed `gate2_envelope` (`guard.py full-run`), and **Gate 3 is never
delegated** — a launched agent stops its pipeline at `internal-review`, never `final`. The PI can
**stop** any launched agent live: a dashboard/bus `kill`/`park` directive (picked up at the agent's
next `lab_bus.py inbox` checkpoint), `executor_cli.py stop`, or `compute.max_concurrent_runs: 0` (no
session can acquire a training slot). The number of autonomous agents the lab may spin up is itself a
gated, PI-signed quantity — full autonomy *with* the brakes left in.

## Headless runs (the executor)

The **executor** (`tools/executor/`) is what the dashboard uses: any **whitelisted** procedure (or the
PI's free-form instruction), hub-level or in a project, becomes a *run* with a durable record and a life
of its own.

```bash
uv run --with pyyaml python tools/executor_cli.py enqueue --skill propose --target my-idea
uv run --with pyyaml python tools/executor_cli.py serve                 # the scheduler (the dashboard runs one too)
uv run --with pyyaml python tools/executor_cli.py list | show <run> | attention
uv run --with pyyaml python tools/executor_cli.py answer <run> --pick "Which project type?=empirical"
uv run --with pyyaml python tools/executor_cli.py reply|resume|stop|cancel <run>
```

- **A run outlives whoever started it.** Each run gets a detached supervisor process that owns it:
  it spawns the agent CLI, captures the full transcript (`<bus>/agents/<run>.stream.jsonl`), keeps the
  manifest (`<run>.json`) current, enforces `max_minutes`, and records every state change in
  `lab/.bus/runs.jsonl`. The supervisor holds an OS lock for its whole life; the kernel releases it on
  any death, which is how the scheduler tells a crashed run from a live one (no pid guessing).
- **States:** `queued → starting → running → completed | waiting_input | failed | timeout | killed`;
  a paused (`waiting_input`) or ended run resumes **the same session** on an answer, a reply, or
  *resume* (`claude -p --resume <session>`).
- **Live sessions: the agent keeps running while it waits for you.** Every run is a *live
  session* by default (`tools/executor/live.py`), over each CLI's own two-way protocol:
  - claude: `claude -p --input-format stream-json --permission-prompt-tool stdio` (the channel the
    Agent SDK uses);
  - codex: `codex app-server` (approvals and `request_user_input` are server requests; a message
    mid-turn steers the turn);
  - opencode: `opencode serve` on a random local port with a per-run password (its `question` tool
    and permission prompts arrive on the event stream).

  In all three:
  - a question (`AskUserQuestion`) or a permission prompt reaches the supervisor, shows in *Needs
    you*, and your answer goes straight back to the running agent — no exit, no resume;
  - a message you send while it works is read in the same turn; *interrupt* stops the current turn;
  - the dashboard never talks to the process: it drops a file into the run's inbox
    (`<run>.d/inbox/`), which the supervisor delivers within a second, so a dashboard restart or a
    remote lab changes nothing;
  - the run's clock stops while it waits on you.

  Deadlines (`agents.programmatic.live.*`): a question nobody answers is **parked** after
  `park_minutes` (60): the process ends, the question stays in *Needs you*, and your answer resumes
  the same session. A permission request nobody decides is denied after `permission_minutes` (30).
  In a campaign run the PI is away, so a permission request is denied at once.
- **The fallback: one-shot runs.** When a live session can't start (an old CLI), the attempt
  re-runs one-shot (`claude -p`, `codex exec`, `opencode run`), and `live: false` makes that the
  default. A one-shot run asks by stating its question and ending its turn, and your reply resumes the
  session; anything its permission mode doesn't allow is denied (and listed under *Needs you*).
- **Caps and brakes:** `max_concurrent_total`, `hub_max_concurrent` (1 — hub sessions share the
  registry), per-project `max_concurrent`, `daily_max_runs` / `daily_max_minutes`, and the master
  switch itself — all `agents.programmatic.*`, all PI-owned. Training still serializes through
  `compute.max_concurrent_runs`.
- **Gates are untouched.** The executor never signs anything. A run that reaches a gate reports
  `needs_pi` and stops. The unmodified CLI runs as the logged-in user; the executor never reads or
  handles credentials.
- **Only the PI signs: the signature guard.** Every executor run carries `tools/signature_guard.py`:
  - where it's installed: a PreToolUse hook in claude's per-run settings, the codex `-c hooks` flags,
    and an opencode plugin loaded through a per-run `OPENCODE_CONFIG_DIR`;
  - what it compares: every write BEFORE vs AFTER;
  - what it denies: an agent creating or changing a Gate-1 marker, an envelope's `pi_signed` /
    `signed_via` or a signed envelope's values, `gate3-approval.md`, a LOOP_BRIEF / campaign
    authorization, a registry row to `final` without a signed Gate 3, PI-owned `lab/config.yaml`
    keys (the `/setup-lab` and `/configure` interviews excepted, but never `agents.programmatic.*`),
    or the PI-action log;
  - what it blocks in the shell: `AUTOSCIENTIST_GATE2_OK`, `--skip-guard`, `--pi-approved`, and
    clearing `AUTOSCIENTIST_NO_GATE3`.

  Signatures delegated by a PI-signed campaign brief still pass, because they name the brief, and so
  does an envelope the PI approved together with Gate 1 (`· envelope approved` in the proposal's
  marker). Denials are logged to the run's `permissions.jsonl` and show under *Needs you*. The guard
  fails open on its own crash (a bug must not wedge a run); the gates' own checks (`guard.py`)
  remain behind it.
- **`/finalize` has exactly one door.** It is not in the launchable whitelist. The PI signing Gate 3
  in the dashboard (typing the study's name) writes `studies/<slug>/paper/gate3-approval.md`
  (`signed_via: dashboard:<ts>`) and starts that one run with `AUTOSCIENTIST_NO_GATE3` unset. Chains,
  repeats, campaigns and free-form runs can never start it.
- **Free-form runs.** The dashboard's *Ask Newt* sends the PI's own instruction as a run (skill `ask`,
  `enqueue --prompt`-style). It gets the same preamble and hooks, can use any procedure, doesn't
  chain, and can't sign.

**Subscriptions.** Headless `claude -p` draws from your plan's usage like any session (Anthropic
paused a planned move of headless usage to a separate credit in June 2026; check their current terms).
Plan limits assume ordinary individual use — the daily brake exists so an unattended lab stays within it.

## The integrity stack (what keeps unattended ≠ unhinged)

Confabulation compounds across LLM steps — a wrong review point becomes a wrong
revision becomes a fabricated ablation. The lab's layered answer, all active during
campaigns:

1. **Mechanical floors** — watchdog-enforced budgets; `audit_claims.py` (every number
   traces to an artifact, re-checked after every revision round); `s2.py verify`
   (every citation checked against the real record); compute slots.
2. **Fresh-context ensembles** — reviewers who never saw the paper written, calibrated
   to the human scoring mean, median-aggregated, minority veto.
3. **Validated feedback** — every critique gets an evidenced ACCEPT / REBUT /
   NEEDS-EXPERIMENT author response; the taste rubric strips generic and misdirected
   critique of any force; new claims require new runs.
4. **Overseers** (`oversight.level`) — dedicated verification subagents that check a
   statement against its evidence files before it propagates: at `standard`,
   author-response verdicts, analysis interpretations, `/autopilot` Gate-1 self-approvals,
   explore-mode decision reopens (the `Revisit if:` trigger-fired claim and any campaign
   headline-reopen bounds check), the phantom-experiment sweep, and any meta-review refutation
   that would unlock accept; at `strict`, also grading meta-review fatal flaws and loop
   progress claims.
5. **Hard stops** — kill criteria checked every cycle; anti-burn backoff; frozen
   settings untouchable by any feedback; PI escalation for stalemates.

A project loop can also escalate **up to the hub mid-run**: at a headline reopen, a block on
a frozen/PI-owned setting, or FULL work outside the envelope, it emits `lab_bus.py escalate`
alongside the local PI note, so the request surfaces in `/lab-status` and the dashboard
without waiting for loop exit. Escalation requests PI attention — it never grants a gate.

## First time?

Run `/setup-lab` once — a five-minute interview that writes your `lab/config.yaml`
(compute, autonomy appetite, oversight level, models, API keys, optionally a
`lab/SYSTEM.md` describing your machine), verifies the environment, and seeds your
first research directions. Then pick your mode: `/ideate <direction>` to walk the
lifecycle, `/adopt` if you're bringing existing work, `/advance` to go stage by
stage, or `/autopilot` to sleep on it.
