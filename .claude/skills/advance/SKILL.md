---
name: advance
description: Stage-gated semi-autonomous mode — run exactly the next lifecycle stage for one idea, then stop with a verification summary for the PI. Optional argument; the idea slug (otherwise the most advanced unblocked idea is picked).
---

# Advance One Stage

The middle autonomy mode: more hands-on than `/autopilot`, less typing than invoking
each procedure yourself. One `/advance` = **one lifecycle stage, then a hard stop** —
the PI verifies the stage's output before the next `/advance`. Nothing here changes
the protocol: the same procedures run, the same gates stop; this skill only adds the
"do the next thing, then wait" discipline.

## 1. Select the idea

- With `<slug>`: use its registry row.
- Without: pick the non-terminal idea **closest to a paper** (furthest along the
  lifecycle) that is not waiting on a PI gate or a PI-queued decision. If everything is
  gate-blocked, report what awaits the PI and stop — that *is* the answer. (This is the
  selection rule `/lab-status` cites for its "advance next" recommendation.)

## 2. Run exactly the next stage

The **Next-action column** of the registry row disambiguates sub-states that share one
registry state (e.g. `scoping` before vs. after `/scope`); read it alongside the state.

| Registry state (+ next action) | This `/advance` does | Ends at |
|---|---|---|
| `seed` | reflect + triage this one idea (the `/ideate` reflect/triage phases, critics included) | `triaged` or killed |
| `triaged` or `lit-review` (next action `/lit-review`) | `/lit-review` through the novelty verdict | `lit-review` complete, next action `/scope` (state set by `/scope`), or killed |
| `scoping`, `decisions.md` incomplete | `/scope` through the value re-verification | `scoping`, next action `/propose`, or killed |
| `scoping`, next action `/propose` | `/propose` — assemble and present the proposal | **Gate 1: stop** (state `proposal`) |
| `proposal`, Gate 1 pending | nothing — report what awaits the PI | — |
| `proposal`, next action `/spawn-project` (Gate 1 approved) | `/spawn-project` | `active`, smoke green |
| `active`, planned PLAN.md rows remain | `/experiment` — **one attempt** (config → staged run → ledger → commit) | attempt recorded |
| `active`, plan rows exhausted + budget for iteration remains | one `/improve` operator cycle | cycle recorded |
| `active`, explore exhausted + PI requests divergence | one `/ideate --in-project <slug>` round (scoped to the frozen set; output = candidate approaches) | candidates triaged; headline-changing survivors routed to `/propose` (**Gate 1**) or a successor `/ideate` |
| `active`, `/improve` plateaued or iteration budget spent | `/analyze` | routed (more exps / `writing` / kill) |
| `analysis` | `/analyze` | routed |
| `writing` | `/make-figures` + `/write-paper` through the compiled draft | `internal-review` |
| `internal-review` | one `/review-paper` cycle (audit → ensemble → author response) | accept → **Gate 3: stop**; else revision routed |
| `final` / `killed` / `parked` | nothing — report the state | — |

Stage-boundary rules:
- **Never cross a PI gate.** At Gate 1 and Gate 3, present the artifact and stop —
  even if the PI is "probably fine with it". FULL runs inside an `active` stage still
  follow Gate 2 (approval or signed envelope) exactly as in any other mode.
- One stage only. If `/analyze` routes back to experiments, that's the *next*
  `/advance`, not this one.
- Kills found mid-stage are recorded normally (kill criteria don't wait for hand-offs).

## 3. Stop and report (the hand-off)

End every `/advance` with a verification summary:
1. **What ran and what changed** — files written, states moved, runs launched (ids).
2. **What to verify** — the 2–4 artifacts worth the PI's read (e.g. the novelty
   verdict, decisions.md's riskiest decision, the ledger entry, the draft's claims).
3. **What the next `/advance` would do** — so "continue" is an informed yes.

Then the standard write-back (registry + notebook — hard rule 11 applies per session,
and a stage is a session's worth of work).
