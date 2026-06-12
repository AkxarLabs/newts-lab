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
- Without: pick the non-terminal idea **closest to a paper** that is not waiting on a
  PI gate or a PI-queued decision (the same choice `/lab-status` would recommend).
  If everything is gate-blocked, report what awaits the PI and stop — that *is* the
  answer.

## 2. Run exactly the next stage

| Registry state | This `/advance` does | Ends at |
|---|---|---|
| `seed` | reflect + triage this one idea (the `/ideate` reflect/triage phases, critics included) | `triaged` or killed |
| `triaged` | `/lit-review` through the novelty verdict | `scoping` or killed |
| `lit-review` | finish the lit review → novelty verdict | `scoping` or killed |
| `scoping` | `/scope` through the value re-verification | proposal-ready or killed |
| scoping done | `/propose` — assemble and present the proposal | **Gate 1: stop** |
| `proposal` + Gate 1 approved | `/spawn-project` | `active`, smoke green |
| `active`, planned rows remain | `/experiment` — **one attempt** (config → staged run → ledger → commit) | attempt recorded |
| `active`, baseline established + plan rows exhausted | one `/improve` operator cycle | cycle recorded |
| `active`, plan complete or plateaued | `/analyze` | routed (more exps / `writing` / kill) |
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
