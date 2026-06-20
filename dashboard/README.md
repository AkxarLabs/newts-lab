# Vivarium — the lab as a living world (optional dashboard)

A local-only, no-build dashboard that renders the lab as a hand-drawn, 2.5D **living lab world**
in the design language of the game *Rain World* — muted, painterly, cozy-melancholic. Each
lifecycle stage is a **room**; every idea and project is a cute **critter** living in its room;
every working agent or subagent is its own colour-coded **worker critter** (with a click-to-inspect
action history); and a small unique creature named **Newt** moves through it all as your control
handle. Optional: delete this folder and the lab is unchanged.

```bash
uv run --with pyyaml python dashboard/serve.py        # http://127.0.0.1:8787
```

**See it alive without a session — demo mode.** Append `?demo` to the URL
(`http://127.0.0.1:8787/?demo`, add `&lamp=day` for daylight) to load a synthetic, living lab:
studies/projects in every room, agents that spawn, despawn, and stroll around. Click a room (or a
buddy) to zoom in and watch the crew move. It's pure client-side and touches no lab files.

- `serve.py`   — stdlib HTTP server. Reads: `/api/state` (snapshot), `/api/events` (SSE),
                 `POST /api/read` (a whitelisted read-only text view — lab knowledge / a gate's
                 proposal/claims/envelope). Writes: `POST /api/directive` & `POST /api/command`
                 (append to the bus), `POST /api/gate` (PI-confirmed Gate 1/2 approval; Gate 3
                 refused), `POST /api/tool` (run a whitelisted read-only tool).
- `sources.py` — read-only, tolerant tailers over the registry, the event bus, run records,
                 slots, in-flight liveness, and the per-worker traceability logs
                 (`.bus/workers/*.jsonl`) folded into `snapshot().workers[]`.
- `static/`    — the single-page frontend: `index.html`, `terrarium.css`, `app.js`. The whole
                 world (rooms + critters + Newt + the worker critters) is drawn on a single
                 **hand-drawn Canvas-2D** surface — vanilla JS, no deps, no build, fully offline.
                 No WebGL, nothing vendored; `prefers-reduced-motion` / `?static` renders the same
                 scene as a still frame.
- `static/assets/` — the only **runtime** art, served at `/static/assets/`: `buddy/` (the layered
                 axolotl — `body`, `body_closed`, `gills`, `tail`, plus the 8-frame `walk` sheet) and
                 `dark/` + `light/` room close-ups (one per room). This is the complete set the page
                 loads; nothing here is optional.
- `assets-src/` — the **source** art (NOT served, **gitignored**): the raw generations under
                 `buddy/` & `rooms/{dark,light}/`, plus `previews/`. Local provenance/regeneration
                 only — the dashboard never reads it, so it's kept out of git history (it's large)
                 and can be deleted without affecting the running app.

The worker critters are backed by a **lab feature, independent of this folder**: Claude Code hooks
(`tools/trace_hook.py`) write one per-worker log per agent (`.bus/workers/<id>.jsonl`) — delete
`dashboard/` and the traces are still written.

Full guide — the views, the rooms, Newt's poses, the worker critters & legend, the inspector, the
camera, and the gate/control contract: **docs/dashboard.md**. The signal layer it reads (the bus +
`lab_bus.py`) ships with the lab and works without it.
