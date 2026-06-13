# The dashboard — Vivarium

*Optional. Local-only. Delete the `dashboard/` folder and the lab is unchanged.*

A **vivarium** is an enclosure for keeping and watching living things — which is exactly what
this is. The lab is rendered as a warm glass **terrarium**: every idea is a plant at its
growth stage, every project a specimen jar on a wooden shelf, compute slots are fireflies, a
hanging lantern lights up when a gate needs you — and a small pink axolotl named **Newt** lives
in the pool at the bottom, reacting to everything and acting as your control handle. It keeps
you in the loop while agents iterate (hub lifecycle *and* every running external project, live)
and it lets you **drive** them.

```bash
uv run --with pyyaml python dashboard/serve.py            # http://127.0.0.1:8787
uv run --with pyyaml python dashboard/serve.py --port 9000
```

Binds `127.0.0.1` only and reads the lab's files. It is the PI's control surface but stays
honest about what it can do (see [Controls](#controls-what-newt-can-actually-do)).

## What it shows — the views

The terrarium pool (Newt + the gate lantern + the slot fireflies) is present under every view.

| View | What it is |
|---|---|
| **Terrarium** (default) | the living scene. **Sprouts** along the front = early-stage ideas (a seed → sprout → bud → bloom as they move `seed→…→proposal`); **jars** on the shelf = projects, each showing state/stage chips, a budget-burn bar for the in-flight run, a hand-drawn sparkline of the headline metric, loop status, and a `✎` badge when commands are awaiting the agent. Tap any plant or jar to steer it. |
| **Shelf** | every project up close as a card, with **command** and read-only **tool** buttons (status / compare / config / inbox) per project. |
| **Gates** | your sign-off. Each pending Gate 1/2/3 as a sealed letter. **Gate 1 & 2 carry a one-click Approve button** (confirm + logged); **Gate 3** shows the command only — finalization is always done in a session. |
| **Ledger** | evidence: the commands & notes you’ve issued (with their `pending → seen → done` state and evidence pointer) and the full event log, as tables. A `done` with no evidence is flagged. |
| **Night** | the 3am view: a calm dark column, one quiet row per in-flight run (elapsed/budget bar, last metric, stalled flag), gates pinned on top. |

**Lamplight** (the `🌙` toggle, or auto by local clock) turns the terrarium to night — deep
teal glass, a moon, glowing jars, no pure white. If file-tailing stalls, the masthead clock
turns red, so degraded data never reads as calm.

## Newt — the buddy that is also the controller

Newt is an **axolotl** — famous for *regeneration*, which is exactly what the lab does when it
discards an assumption and regrows a plan (the explore-mode `decision_revisit`/`replan`), with a
wink at Newton. His posture is an honest one-glance summary of the whole lab, by priority:
**gate-waiting > fresh-failure > success > regenerating (a pivot) > running > writing > idle >
asleep**. He naps under the surface when the lab is cold, blows bubbles while runs are live,
sparkles on a success, droops under a little rain cloud on a failure, sprouts a glowing
regen-bud when the loop reopens a decision, and holds up a letter when you’re composing a
command. Speech bubbles quote event fields **verbatim** — no number Newt can’t cite to an event.

## Controls — what Newt can actually do

Tap **Newt** (or any plant/jar) to open the **command console**. One honest constraint shapes
all of it: the dashboard is a local Python server — it can’t *run* an agent skill (that’s the
Claude session). So it works in three tiers:

1. **Structured commands** → the bus. Buttons like *Start loop ▸ execute/explore*, *Stop loop*,
   *Run smoke*, *Request a run*, *Analyze*, *Prioritize*, *Park*, *Kill* (and *Ideate* for the
   hub) append a `kind:"command"` directive to the target’s `directives.jsonl`. The running
   agent picks it up at its **next checkpoint** (a loop cycle / session start — the console says
   so) and executes it **in-protocol**, then acks `seen → done`(+evidence) / `blocked`. A
   command is never gate approval and can’t change a frozen/PI-owned setting.
2. **Read-only tools** → run now. The Shelf’s per-project buttons execute whitelisted, side-effect-free
   tools (`check_lab`, `show_config`, `status`, `compare`, `inbox`, slot status) as subprocesses
   and show the output in a drawer. Nothing that trains or writes.
3. **PI gate approval** (Gate 1 & 2 only). Because the server is local and you are the PI, the
   Gates view (or a jar’s console) can record your approval directly: Gate 1 signs the proposal
   and leaves the agent a `gate1_approved` command to transition + spawn; Gate 2 flips
   `gate2_envelope.pi_signed: true` (with `signed_via: dashboard:<ts>`) in `control.yaml`. Every
   gate click needs an explicit confirm and is written to `lab/.bus/pi-actions.jsonl`.
   **Gate 3 is never approvable here** — sending anything outside the lab is always done in a
   session. That is the one hard line.

You can also leave a **free-text note** from the same console when no button fits.

## How it stays honest (the bus)

Everything shown is backed by a real file. The signal layer is **the bus** — append-only JSONL,
the same philosophy as the rest of the lab:

- **Mechanical events** (reliable regardless of agent discipline): `scripts/run.py` and
  `sweep.py` emit `run_started`/`run_finished`/`sweep_*`; `tools/run_slots.py` emits slot events.
  These fire from code, so the scene is truthful even if an agent forgets to narrate.
- **Agent events**: at registry changes, gate stops, loop cycles, pivots, kills, and write-backs
  the agent emits via `lab_bus.py emit <kind>`. Live metric ticks aren’t duplicated — the
  dashboard tails each run’s `metrics.jsonl` directly.
- **Commands, directives, acks, and PI gate actions** flow through the same files; the dashboard
  only ever *appends* (and, for a Gate-2 sign, edits the one `pi_signed` line it’s told to).

Event kinds: `session_start/end`, `state_change`, `gate_waiting`, `gate_resolved`,
`run_started/finished`, `sweep_started/finished`, `slot_acquired/released/denied/reclaimed`,
`cycle`, `review_verdict`, `paper_compiled`, `kill`, `writeback`, `directive_seen/done/blocked`,
`frontier_expand` (explore loop proposed new lines), `decision_revisit` (reopened a design
decision), `replan` (a pivot landed), `note`. The bus lives in gitignored `lab/.bus/` (hub) and
`<project>/.bus/` (each project); a project spawned before the bus existed still shows
runs/registry/liveness — events only enrich.

## Tech notes

`dashboard/serve.py` is a stdlib `ThreadingHTTPServer` (+ pyyaml) serving a no-build single-page
scene. Endpoints: `GET /api/state` (a snapshot rebuilt from files on every request — the lab’s
files are the database), `GET /api/events` (Server-Sent Events, ~1.5 s poll — Windows-honest, no
native watcher), `POST /api/directive` and `POST /api/command` (append to the bus), `POST /api/tool`
(run a whitelisted read-only tool), `POST /api/gate` (record a confirmed Gate 1/2 approval; Gate 3
refused). The first HTML response is seeded with the snapshot inline for an instant cold load.
`dashboard/sources.py` holds the tolerant tailers (a bad line is skipped, a moved project is
reported unreachable, never a crash). The frontend (`static/index.html`, `terrarium.css`,
`app.js`) is vanilla and honors `prefers-reduced-motion`. A handy deep link: `?open=<idea|hub>`
opens the command console straight to that target.
