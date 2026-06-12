# Autonomous operation

How to run the lab while you sleep — and exactly what you'll find in the morning.

## The one-command night

```text
claude
> /overnight
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

| Gate | Interactive mode | Campaign mode |
|---|---|---|
| Gate 1 (proposal) | you approve each | **delegated within signed bounds** (budget caps, kill criteria present, `novel` verdict, scoping passed) — anything outside queues for you |
| Gate 2 (FULL runs) | you approve / envelope | envelope derived from the campaign brief into each project's `control.yaml` |
| Gate 3 (finalize) | you approve each | **never delegated** |

Everything else runs exactly as in interactive mode — compute slots, budget watchdogs,
append-only ledgers, oversight checks, the author-response discipline. A campaign is
normal operation minus waiting for you, not a relaxed mode.

## Three sizes of autonomy

| You want | Command | Scope |
|---|---|---|
| one project pushed overnight | `/research-loop <slug>` | experiments only, under a signed `LOOP_BRIEF.md` |
| iterate a metric after the pipeline works | `/improve <slug>` | operator loop, parallel worktree variants |
| ideas → reviewed paper drafts, end to end | `/overnight` | the whole lifecycle, under a campaign brief |

For resilience across a long night, wrap the campaign in the harness's loop facility
(`/loop /overnight continue <campaign-file>`): every step is recoverable from the
append-only Campaign Log, so a re-entered session resumes instead of restarting.

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
(compute, autonomy appetite, oversight level, models, API keys), verifies the
environment, and seeds your first research directions. Then either walk the lifecycle
interactively (`/ideate <direction>`) or go straight to `/overnight`.
