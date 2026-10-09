# The dashboard — Newts' Lab's product surface

A local-only, no-build dashboard: start it, pick or create a lab, and do everything from there.

- **Set up**: connect an agent and sign in through its own login, choose the limits, and run the
  `/setup-lab` interview.
- **Work**: start any procedure or type an instruction, and watch each run as a conversation.
- **Decide**: answer the agents' questions and approve the three gates, loop briefs and campaigns.
  Only you can: a guard in every run makes sure of it.

The lab is drawn behind it as a 3D tabletop: a room per stage of the research round your desk, a card
per study, a newt per run and a smaller one per subagent. Delete this folder and the lab still works
from a terminal.

```bash
uv run --with pyyaml python newts.py                                   # starts it + opens the browser (http://127.0.0.1:8787)
uv run --with pyyaml python dashboard/serve.py --hub ../other-lab     # the server directly, for another lab
```

Runs go through `tools/executor/`, each in a detached supervisor that outlives this server. See
`docs/dashboard.md` for the tour and `docs/internals.md` for how it works.

**See it alive without a session — demo mode (debugging).** Demo is a synthetic, living lab —
studies/projects in every room, agents that spawn, despawn, and stroll around — for development and
screenshots. It's a debugging mode, so it's **off by default and not exposed in the UI**: start the
server with `--demo` (or `VIVARIUM_DEMO=1`), then visit `/?demo`:

```bash
uv run --with pyyaml python dashboard/serve.py --demo   # then open http://127.0.0.1:8787/?demo
```

A bare `?demo` on a normally-served dashboard is inert. Demo is pure client-side and touches no
lab files — **including its controls**: the Approve buttons, commands, and notes in demo are
simulated no-ops (blocked client-side) and record nothing.

- `serve.py`   — stdlib HTTP server. Reads: `/api/state` (snapshot), `/api/events` (SSE),
                 `POST /api/read` (a whitelisted read-only text view — a gate's composed review
                 bundle), the **Library** trio `GET /api/library` / `POST /api/libdoc` /
                 `GET /api/libfile` (the document tree + one doc's text + a doc-relative image;
                 fixed roots, containment-checked, extension-whitelisted). Writes:
                 `POST /api/directive` & `POST /api/command` (append to the bus; `launch:true`
                 also starts the consuming procedure), `POST /api/gate` (PI-confirmed Gate 1/2/3
                 signature — Gate 3 via product.gate3_sign), `POST /api/tool` (run a whitelisted read-only tool).
                 Executor: `POST /api/run` (+ `/answer` `/reply` `/stop` `/resume` `/cancel`
                 `/permission`), `POST /api/attention/ack`, `POST /api/escalation/resolve`,
                 `POST /api/executor/enable`, `GET /api/run` · `/api/run/tail` · `/api/run/log` ·
                 `/api/executor/health`; a scheduler thread starts queued runs.
- `sources.py` — read-only, tolerant tailers over the registry, the event bus, run records,
                 slots, in-flight liveness, headless runs (`.bus/agents/*.json`), the one
                 "needs you" queue, and the per-worker traceability logs (`.bus/workers/*.jsonl`)
                 folded into `snapshot().workers[]` as a run → session → subagent tree.
- `product.py` — the PI actions beyond the gates and the launcher: labs (open / create / switch), a
                 terminal window for a CLI's own sign-in, Gate 3 (typed signature + the one /finalize
                 run), revoke, the envelope editor, LOOP_BRIEF / campaign signing, revive, SYSTEM.md,
                 Lab settings, research keys (`lab/.env.local`), setup state, stop the server.
- `artifacts.py` — what agents published for the PI (`tools/artifact.py`, `lab/.bus/artifacts/`):
                 `GET /api/artifacts` · `/api/artifact` · `/api/artifact/file` (HTML/SVG served with a
                 CSP sandbox), `POST /api/artifact/reply` (to the publishing run, else a note to the
                 study) · `/api/artifact/seen`.
- `static/`    — the single-page frontend: `index.html`, `ui/` (Preact + htm, no build: `core.js`,
                 `components.js`, `runs.js`, `composer.js`, `gates.js`, `library.js`, `studies.js`,
                 `home.js`, `settings.js`, `setup.js`, `demo.js`, `artifacts.js`, `sound.js`,
                 `app.js`, `ui.css`) over the world in
                 `world3d/` (three.js: `world.js` the live world, `scene.js` the VivScene wrapper +
                 a quiet stand-in without WebGL, `model.js` / `layout.js` the logic and the plots,
                 `kit.js` / `components.js` / `newt.js` / `characters.js` the pieces and the cast,
                 `rooms/*.js` the built-in looks, `looks/` the starter Lab looks per project type;
                 see docs/world-design.md). Fully offline.
- `static/vendor/` — the **Library** reader's pinned, offline renderers (marked · DOMPurify ·
                 KaTeX + woff2 fonts), and three.js (r169) for the world. The one place third-party
                 code lives; provenance, versions, and licenses in `static/vendor/README.md`. Everything else stays dependency-free.
- `static/assets/` — the only **runtime** art, served at `/static/assets/`: `buddy/` (the layered
                 axolotl — `body`, `body_closed`, `gills`, `tail`, plus the 8-frame `walk` sheet). This is
                 the complete set the page loads; nothing here is optional.
- `assets-src/` — the **source** art (NOT served, **gitignored**): the raw generations under
                 `buddy/` & `rooms/{dark,light}/`, plus `previews/`. Local provenance/regeneration
                 only — the dashboard never reads it, so it's kept out of git history (it's large)
                 and can be deleted without affecting the running app.

The sub-newts are backed by a **lab feature, independent of this folder**: Claude Code hooks
(`tools/trace_hook.py`) write one per-worker log per agent (`.bus/workers/<id>.jsonl`) — delete
`dashboard/` and the traces are still written.

Full guide — the views, the rooms, Newt's poses, the sub-newts & legend, the inspector, the
camera, and the gate/control contract: **docs/dashboard.md**. The signal layer it reads (the bus +
`lab_bus.py`) ships with the lab and works without it.
