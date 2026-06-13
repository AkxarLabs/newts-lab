# Marginalia — the lab daybook (optional dashboard)

A local-only, no-build dashboard that renders the lab as a living notebook and keeps you in
the loop while agents iterate. Optional: delete this folder and the lab is unchanged.

```bash
uv run --with pyyaml python dashboard/serve.py        # http://127.0.0.1:8787
```

- `serve.py`   — stdlib HTTP server: `/api/state` (snapshot), `/api/events` (SSE),
                 `POST /api/directive` (the only write — appends a PI note to the bus).
- `sources.py` — read-only, tolerant tailers over the registry, the event bus, run records,
                 slots, and in-flight liveness.
- `static/`    — the single-page frontend: `index.html`, `journal.css`, `app.js` (+ Pica,
                 the inline-SVG inchworm). No build step.

Full guide, the five views, Pica, and the directive contract: **docs/dashboard.md**.
The signal layer it reads (the bus + `lab_bus.py`) ships with the lab and works without it.
