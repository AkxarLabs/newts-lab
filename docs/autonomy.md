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
compute is reachable from it; `claude -p` is for headless one-shots (CI), not loops.

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
   statement against its evidence files before it propagates: author-response verdicts
   and analysis interpretations at `standard`; meta-review flaws and loop progress
   claims at `strict`.
5. **Hard stops** — kill criteria checked every cycle; anti-burn backoff; frozen
   settings untouchable by any feedback; PI escalation for stalemates.

## First time?

Run `/setup-lab` once — a five-minute interview that writes your `lab/config.yaml`
(compute, autonomy appetite, oversight level, models, API keys, optionally a
`lab/SYSTEM.md` describing your machine), verifies the environment, and seeds your
first research directions. Then pick your mode: `/ideate <direction>` to walk the
lifecycle, `/adopt` if you're bringing existing work, `/advance` to go stage by
stage, or `/autopilot` to sleep on it.
