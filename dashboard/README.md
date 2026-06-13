# Vivarium — the lab as a living terrarium (optional dashboard)

A local-only, no-build dashboard that renders the lab as a warm glass terrarium — ideas are
plants, projects are jars on a shelf, slots are fireflies, and a pink axolotl named **Newt**
lives in the pool and is your control handle. Optional: delete this folder and the lab is
unchanged.

```bash
uv run --with pyyaml python dashboard/serve.py        # http://127.0.0.1:8787
```

- `serve.py`   — stdlib HTTP server. Reads: `/api/state` (snapshot), `/api/events` (SSE).
                 Writes: `POST /api/directive` & `POST /api/command` (append to the bus),
                 `POST /api/gate` (PI-confirmed Gate 1/2 approval; Gate 3 refused),
                 `POST /api/tool` (run a whitelisted read-only tool).
- `sources.py` — read-only, tolerant tailers over the registry, the event bus, run records,
                 slots, and in-flight liveness.
- `static/`    — the single-page frontend: `index.html`, `terrarium.css`, `app.js` (Newt is an
                 inline SVG). No build step.

Full guide — the views, Newt's poses, the command console, and the gate/control contract:
**docs/dashboard.md**. The signal layer it reads (the bus + `lab_bus.py`) ships with the lab
and works without it.
