# Dashboard internals

How the dashboard works underneath. For using it, see [The dashboard](dashboard.md).

## The bus

Everything the dashboard shows is backed by a real file. The signal layer is **the bus**: append-only
JSONL, the same approach as the rest of the lab.

- **Mechanical events** come from code, so the scene is truthful even if an agent forgets to narrate:
  `scripts/run.py` and `sweep.py` emit `run_started`, `run_finished` and `sweep_*`, and
  `tools/run_slots.py` emits slot events.
- **Agent events.** At registry changes, gate stops, loop cycles, pivots, kills and write-backs, the
  agent runs `lab_bus.py emit <kind>`.
- **Commands, notes, acks and PI actions** use the same files. The dashboard appends to them. For an
  approval it edits exactly the line it is told to, then checks the file still parses to what it meant.

The event kinds are listed in `tools/lab_bus.py`. The main ones:

- lifecycle: `state_change`, `gate_waiting`, `gate_resolved`, `gate_revoked`;
- experiments: `run_started`, `run_finished`, `sweep_*`, the slot events;
- process: `cycle`, `review_verdict`, `paper_compiled`, `kill`, `writeback`, `replan`,
  `frontier_expand`, `decision_revisit`, `approach_ideate`;
- escalations: `escalation`, `escalation_resolved`;
- agent runs: `agent_launched`, `agent_waiting`, `agent_resumed`, `agent_finished`, `run_report`.

The bus lives in the git-ignored `lab/.bus/` (the lab) and `<project>/.bus/` (each project).

## Tracing: one log per worker

Claude Code hooks (`.claude/settings.json` → `tools/trace_hook.py`), the Codex hooks and the opencode
plugin log every agent's and subagent's activity to one file per worker: `lab/.bus/workers/<id>.jsonl`
in the lab and `<project>/.bus/workers/<id>.jsonl` in each project. They record each subagent's birth,
each tool call as it starts and ends, each spawn with its description, and what each subagent handed back.

`dashboard/sources.py` rebuilds the run, session and subagent tree from these logs. The harness writes
them, not the subagents. They are best-effort and never block a tool call. This works with or without the
dashboard.

Every line of a headless run carries its run id, so a session is joined to its run even before the CLI
reports a session id. A subagent's own subagents nest under their parent, and a worker inside a long tool
call stays on the roster. The run sheet shows the subagent tree, each with a link to its own trace, and a
lineage strip: who started the run (you, a chain, a repeat, a campaign pass) and what it started.

| How the agent started | Traced by | Shown |
|---|---|---|
| A run from the dashboard (claude) | the run's own hook settings; the repo's hooks stand down | Runs, run sheet, world, Today |
| A run from the dashboard (codex) | `-c hooks.*` session flags | same |
| A run from the dashboard (opencode) | the tracer plugin | same |
| A campaign pass and the steps it dispatched | same as their backend | same, plus the campaign card and lineage strip |
| A backend that fires no hooks | the supervisor's fallback log, named by the run | joined to its run |
| Your own session in a terminal or editor (claude, opencode) | the repo's hooks (`python`, else `python3`) | Runs → *Sessions started outside the dashboard*, the world, the agent sheet |
| Your own codex session | `.codex/hooks.json`, once you trust the repo and review its hooks in `/hooks` | same |
| Subagents at any depth | the same hooks | nested under their parent |

## The server

`dashboard/serve.py` is a standard-library `ThreadingHTTPServer` (plus pyyaml) with one route table. Each
area is one module beside it, sharing `ctx.py` (which lab is shown):

- reading: `sources.py` (the snapshot), `workers.py`, `attention.py` (what needs you), `review.py`, `library.py`;
- acting: `runops.py`, `gates.py`, `campaign.py`, `bus.py`, `compose.py` (the lab's definition: draft,
  check, publish, undo), `instructions.py`, `settings.py`, `keys.py`, `system.py`, `artifacts.py`;
- around the lab: `ticker.py` (the scheduler), `labtools.py`, `labs.py`, `machines.py`, `fleet.py`, `term.py`.

The lab's files are the database. `GET /api/state` is a snapshot rebuilt from files and cached for about a
second. `GET /api/events` is Server-Sent Events. Writes are JSON POSTs, each validated, each logged, and
each needing an explicit `confirm` where it widens authority.

**Protection.**

- The server binds `127.0.0.1` only, exclusively on Windows, so two servers can't share a port.
- Host and Origin checks defeat DNS rebinding, and `Origin: null` is refused.
- A per-server `SameSite=Strict`, `HttpOnly` session cookie is required on every `/api` call, so another
  site, a `file://` page or a sandboxed frame can't drive the lab.
- POSTs must be `application/json`. The inline snapshot is `</`-escaped.
- HTML and SVG an agent wrote are served with a CSP sandbox, so they can never act as the dashboard.

## The front end

`static/ui/*.js` is Preact 10 and htm (vendored, no build step) with `static/ui/ui.css`.

- Colours are tokens on `:root`, one set for day and one for night.
- Type: Newsreader for page titles, Instrument Sans for the interface, IBM Plex Mono for labels and data.
  The fonts are bundled (SIL Open Font License), so the dashboard stays offline.
- Hash routes: `#/`, `#/studies`, `#/study/<slug>/<tab>`, `#/runs`, `#/run/<id>`, `#/artifacts/<id>`,
  `#/library/<scope>/<slug>/<file>`, `#/compose/<kind>/<name>` (the Workflow page), `#/settings/<section>`,
  `#/history`, `#/labs`, `#/setup`.
- Quick answers to questions about the live state are `ui/answers.js`. Sound is `ui/sound.js`.

## The 3D world

`static/world3d/`, drawn with three.js:

- `world.js` is the live world, and `scene.js` the one wrapper round it (a quiet stand-in without WebGL);
- `model.js` decides which rooms stand where and who goes in which, `layout.js` the plots;
- `kit.js` (palettes, including the night glow), `components.js`, `newt.js` and `characters.js` are the pieces and the cast;
- `rooms/*.js` are the built-in room looks, and `looks/lab.<type>.json` the starter Lab looks per project type.

The lab's own looks are data in `lab/rooms3d/`. Rooms, their places and their looks are yours to change
under Workflow → Rooms. See [The world](world-design.md) and [Extending](extending.md).

## Demo mode

`newts.py --demo`, then open `/?demo`, shows a synthetic lab. The page answers every request itself and
never reads the real lab, and nothing is written. The documentation screenshots come from it.

## Libraries

Vendored for offline use, with licences in `static/vendor/`: three.js, Preact, htm, marked, DOMPurify and KaTeX.
