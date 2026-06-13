# The dashboard — Marginalia

*Optional. Local-only. Delete the `dashboard/` folder and the lab is unchanged.*

Marginalia renders the lab as the thing it already is — a notebook. The lab's substrate is
append-only ledgers, a registry, ink on paper; the dashboard is one **living daybook spread**
that writes itself, with a tiny measuring-worm named **Pica** in the margin. It keeps you in
the loop while agents iterate: hub lifecycle stages *and* every concurrently-running external
project, live — and it lets you steer those agents by leaving notes.

```bash
uv run --with pyyaml python dashboard/serve.py            # http://127.0.0.1:8787
uv run --with pyyaml python dashboard/serve.py --port 9000
```

It binds `127.0.0.1` only, reads the lab's files, and has exactly **one** write: appending a
PI directive to a bus file. It never signs a gate, edits config, or touches a ledger.

## What it shows — the five bookmarks

Ribbon tabs on the journal's edge. The margin (ticker + Pica + composer) is present in every
view, and a **gate lantern** glows in the masthead whenever a PI gate is waiting — in every
view, because a gate is the one thing that genuinely can't wait for you.

| Bookmark | What it is |
|---|---|
| **Desk** (default) | the open spread. Left page: the **lifecycle rail** — every idea a labelled dot on one inked rule (gates are amber wax-seals; killed/parked dots drop below, struck through, kill reason on hover). Right page: **today's entries**, the merged event stream, ink that draws itself. |
| **Bench** | one **specimen card** per project: state + stage chips, a budget-burn rule for the in-flight run, a hand-inked sparkline of the headline metric, loop status, a hash-generated doodle so each project is recognizable. Sorted needs-you-first. |
| **Gates** | the anteroom — every pending Gate 1/2/3 as a **wax-sealed letter** showing the exact command you run to approve. The dashboard signs nothing. |
| **Ledger** | evidence mode, no animation: the directive threads and the full event log as booktabs tables. A directive `done` with no evidence pointer is flagged amber. |
| **Night Watch** | the 3am pressure valve: a near-static, dark, big-type single column — one quiet row per in-flight run (elapsed/budget bar, last metric, stalled flag), gates pinned on top. |

**Lamplight** (the masthead `◐` toggle, or auto by local clock) is a warm dark theme designed
for a dark room — umber ground, cream ink, no pure white, alerts that pulse slowly. **Diegetic
staleness:** if file-tailing stalls, the masthead desk-clock visibly stops — degraded data can
never read as calm.

## Pica — the buddy that is also the controller

Pica is a geometer moth larva (the "measuring worm") — an *earth-measurer* for a traceability
lab, who inches along progress rules to read them. Posture is an honest one-glance summary of
the whole lab, resolved by priority: **gate-waiting > fresh-failure > success > running >
writing > reading > sleeping**. Pica reads bell-in-hand at a gate, dons goggles and inches a
run's progress rule while it's live, backflips and stamps a clay seal on success, shakes off an
ink-splat on failure, becomes a nib while a paper is written, and curls under a paper-scrap
blanket when the lab sleeps. Speech bubbles quote event fields **verbatim** — if a sentence
can't cite a number from the event line, Pica doesn't say it.

### Leaving a directive (steering the agents)

Click Pica → a composer slides up. Pick a target (the hub, or a specific project), type a note,
pin it. The note is appended to that target's `directives.jsonl` on the bus. **Honest latency:**
agents are Claude Code sessions — they read mail at their *next checkpoint* (a loop cycle, a
stage boundary, session orientation), not mid-thought, and the composer says so. The agent then
acks the directive: `seen`, then `done` (with an evidence pointer — a run id, ledger line, or
commit) or `blocked` (with the reason). You watch it move pending → seen → done in the Ledger.

A directive **steers** within the protocol — it can reprioritize, request a run *within* the
signed envelope, park or kill an idea, answer an open question, or stop a loop. It is **not**
gate approval and cannot change frozen budgets, evals, or gate signatures; a directive that
asks for those comes back `blocked` with the proper command (e.g. `/configure …`). This keeps
the buddy powerful without letting chat smuggle past a PI gate.

## How it stays honest (the bus)

Everything the dashboard shows is backed by a real file (see [Tools](tools.md) and
[Configuration](configuration.md)). The signal layer is **the bus** — append-only JSONL, the
same philosophy as the rest of the lab:

- **Mechanical events** (reliable regardless of agent discipline): `scripts/run.py` and
  `sweep.py` emit `run_started`/`run_finished`/`sweep_*`; `tools/run_slots.py` emits the slot
  events. These fire from code, so the dashboard is truthful even if an agent forgets to narrate.
- **Agent events**: at registry changes, gate stops, loop cycles, kills, and write-backs, the
  agent emits a one-line event via `lab_bus.py emit <kind>`. Live metric ticks aren't duplicated
  onto the bus — the dashboard tails each run's existing `metrics.jsonl` directly.
- **Directives + acks** flow through the same files; the dashboard only ever *appends*.

Event kinds: `session_start/end`, `state_change`, `gate_waiting`, `gate_resolved`,
`run_started/finished`, `sweep_started/finished`, `slot_acquired/released/denied/reclaimed`,
`cycle`, `review_verdict`, `paper_compiled`, `kill`, `writeback`, `directive_seen/done/blocked`,
`note`. The bus lives in gitignored `lab/.bus/` (hub) and `<project>/.bus/` (each project), so
emitting is always safe and cheap; a project spawned before the bus existed still shows
runs/registry/liveness — events only enrich.

## Tech notes

`dashboard/serve.py` is a stdlib `ThreadingHTTPServer` (+ pyyaml) that serves a no-build,
single-page frontend and four endpoints: `GET /api/state` (a full snapshot rebuilt from files
on every request — the lab's files are the database, there is no database of its own),
`GET /api/events` (Server-Sent Events, the snapshot re-pushed when files change, ~1.5 s poll —
Windows-honest, no native file-watcher), and `POST /api/directive` (the only write). The first
HTML response is seeded with the current snapshot inline, so the cold load is instant.
`dashboard/sources.py` holds the tolerant tailers (a bad line is skipped, a moved project is
reported unreachable, never a crash). The frontend (`static/index.html`, `journal.css`,
`app.js`) is vanilla — no build step — and honors `prefers-reduced-motion`.
