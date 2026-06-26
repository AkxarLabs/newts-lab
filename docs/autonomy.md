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
claims-audited, bibliography-verified, ensemble-reviewed. **Never "final"** — Gate 3
is constitutionally yours.

## The authorization model (why this is safe to sleep through)

| Gate | Interactive modes | Campaign mode |
|---|---|---|
| Gate 1 (proposal) | you approve each | **delegated within signed bounds** (budget caps, kill criteria present, `novel` verdict, scoping passed) — anything outside queues for you |
| Gate 2 (FULL runs) | you approve / envelope | envelope derived from the campaign brief into each project's `control.yaml` |
| Gate 3 (finalize) | you approve each | **never delegated** |

Everything else runs exactly as in interactive mode — compute slots, budget watchdogs,
append-only ledgers, oversight checks, the author-response discipline. A campaign is
normal operation minus waiting for you, not a relaxed mode.

## Autonomy inside the project directory

A spawned project is autonomously operable on its own: it ships a **`CLAUDE.md`**
(the project protocol — orientation order, autonomy bounds from `control.yaml`,
when to parallelize with subagents, write-back duties) and an **`AGENTS.md`** (the
same for any other agent, plus a cold-start checklist), so `cd project && claude`
is a complete working session with no hub context needed. `scripts/check_project.py`
lints readiness and suggests the next procedure.

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
and is restored by `claude --resume`. For unattended runs start the session with a
permission mode that won't stop to ask (`claude --permission-mode acceptEdits`, or
`permissions.allow` rules in `.claude/settings.json` covering the project's commands)
— a permission prompt at 3am blocks the night. Related built-ins, for completeness:
`/goal` drives toward a single checkable condition (good for "make the smoke test
pass", too narrow for a campaign); cloud routines (`/schedule`) run without an open
session but in a fresh clone — only useful if your lab state is pushed and your
compute is reachable from it. (`claude -p` headless is also how the lab launches *project*
agents programmatically — see the next section.)

## Programmatic agents & multi-project fleets

A single session orchestrates work by spawning **worktree subagents** (the Task tool) for
parallel experiment *variants* — but those are short-lived, fire-and-return, and **cannot spawn
their own subagents** (subagent rule 6). So one session cannot run several long-running project
loops at once: a research loop *is* a top-level session, not a subagent. The lab scales to many
projects the other way — **multiple top-level sessions over shared files** — and
`tools/agent_runner.py` is how the hub launches them programmatically instead of by hand:

```bash
uv run --with pyyaml python tools/agent_runner.py launch --project <slug> \
    --role orchestrator --prompt-file <brief>     # one headless session, in the project repo
uv run --with pyyaml python tools/agent_runner.py list|reconcile|kill --project <slug>
```

- **Backends, via config (default claude).** `agents.programmatic.backend: claude` runs `claude -p`
  (headless); `codex` runs `codex exec`. Each launched agent is a **top-level** session in the
  project's cwd (so it *can* spawn its own experiment-runners) — **not** a nested subagent — and is
  **depth-capped** (`max_depth: 1`) so it can't launch more.
- **Permissions: `auto` + an engine allowlist, blocked ops escalate.** A launched Claude agent runs
  `--permission-mode auto` (`agents.programmatic.permission_mode`), which broadly auto-approves work
  inside the project repo yet still blocks dangerous ops (curl|bash, force-push, destructive git,
  irreversible deletes). The project's `.claude/settings.json` `permissions.allow` pre-approves the
  routine engine commands (`uv run *`, file edits) so they never stall or accumulate blocks. A genuinely
  blocked op is **denied, never silently bypassed**, and the agent raises a `lab_bus.py escalate` the PI
  answers via a dashboard directive — the existing human-in-loop channel, no per-call approval UI needed.
  (`bypassPermissions` is deliberately *not* the default; `dontAsk` is the stricter fail-closed
  alternative if a project wants only the allowlist to run.) A **Codex** agent gets the equivalent from
  its OS-enforced sandbox: `--sandbox workspace-write -a never` (edit + run inside the repo, network off
  by default; a sandbox-forbidden op fails and escalates the same way). Every one of these safety knobs is
  a **dedicated per-backend config key** — `agents.programmatic.permission_mode` (and
  `backends.claude.permission_mode`), `backends.codex.{sandbox,approval,network_access}` — so they can be
  tuned as needed; the same flags are *refused* in `extra_args` so they can't be smuggled past review.
- **Nothing is lost.** Running in the project cwd means the project's `.claude/settings.json` hooks
  (Claude backends) and `run.py` already emit run/worker signals into `<project>/.bus/`. On top of
  that the launcher persists the **full stdout transcript** (`<project>/.bus/agents/<id>.stream.jsonl`),
  a **manifest** (`<id>.json`, status `running`→terminal, pid, timing — reconciled on crash like a
  killed run), `agent_launched`/`agent_finished` **bus events**, and a synthesized **worker log** for
  non-Claude backends — so the dashboard catches every launched agent as its own room/sprite, live.
- **Coordination is the existing slot ledger.** N launched sessions advance their CPU-light stages in
  parallel; **training still serializes** through `tools/run_slots.py` (`compute.max_concurrent_runs`).
  No new lock — the file-based substrate already arbitrates cross-project compute.
- **`/autopilot` concurrency.** `autopilot.max_concurrent_projects` (default **1**) keeps autopilot
  on one project end-to-end; set it `>1` (with `agents.programmatic.enabled: true`) and autopilot
  becomes a coordinator that launches one headless session per project.

**Human-in-the-loop, by construction.** Programmatic launching *widens* autonomy (N autonomous
sessions writing to N repos), so it is **PI-owned and OFF by default** (`agents.programmatic.enabled:
false`) — flipped on only by `/configure` or a PI-signed campaign brief, exactly like
`ideation.in_project` and the Gate-2 `pi_signed` chain. Every launched agent **inherits every gate**:
FULL runs still need a signed `gate2_envelope` (`guard.py full-run`), and **Gate 3 is never
delegated** — a launched agent stops its pipeline at `internal-review`, never `final`. The PI can
**stop** any launched agent live: a dashboard/bus `kill`/`park` directive (picked up at the agent's
next `lab_bus.py inbox` checkpoint), `agent_runner.py kill`, or `compute.max_concurrent_runs: 0` (no
session can acquire a training slot). The number of autonomous agents the lab may spin up is itself a
gated, PI-signed quantity — full autonomy *with* the brakes left in.

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
