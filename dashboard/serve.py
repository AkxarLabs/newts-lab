"""Marginalia — the AutoScientist lab daybook. Optional, local-only dashboard.

    uv run --with pyyaml python dashboard/serve.py [--port 8787]

A tiny stdlib HTTP server that renders the lab as a living notebook: it READS the lab's
files (registry, run records, the event bus, slots, in-flight run liveness) and serves a
no-build single-page frontend. Its ONLY write is appending a PI directive to a bus file —
it never signs a gate, edits config, or touches a ledger.

Endpoints:
    GET  /                 the frontend (dashboard/static/)
    GET  /api/state        full snapshot, rebuilt from files (cold render)
    GET  /api/events       Server-Sent Events: the snapshot, re-pushed when files change
    POST /api/directive    {target: "hub"|<slug>, text: "..."}  -> appends to directives.jsonl
    POST /api/withdraw     {target, id}                          -> appends a withdrawal line

Binds 127.0.0.1 only. Delete the dashboard/ folder and the lab is unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
LAB = HUB / "lab"
STATIC = HERE / "static"
sys.path.insert(0, str(HERE))

import sources  # noqa: E402


def _next_id(directives_path: Path) -> str:
    n = 0
    if directives_path.exists():
        for line in directives_path.read_text(encoding="utf-8-sig").splitlines():
            if '"id"' in line:
                n += 1
    return f"d-{n + 1:03d}"


def _bus_dir(target: str) -> Path:
    if target in ("hub", "", None):
        return LAB / ".bus"
    pdir = sources._project_path({"id": target, "project": ""})
    return (pdir / ".bus") if pdir else (LAB / ".bus")


def append_directive(target: str, text: str) -> dict:
    bus = _bus_dir(target)
    bus.mkdir(parents=True, exist_ok=True)
    path = bus / "directives.jsonl"
    rec = {"id": _next_id(path), "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "from": "PI via dashboard", "text": text}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def append_withdraw(target: str, ref: str) -> None:
    bus = _bus_dir(target)
    bus.mkdir(parents=True, exist_ok=True)
    with (bus / "directives.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "withdraw", "ref": ref,
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index.html") or self.path.startswith("/?"):
            return self._serve_index()
        if self.path.startswith("/api/state"):
            try:
                return self._json(sources.snapshot())
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
        if self.path.startswith("/api/events"):
            return self._serve_sse()
        if self.path.startswith("/static/") or self.path.count("/") == 1:
            return self._serve_static(self.path.lstrip("/"))
        self._send(404, b"not found", "text/plain")

    def _serve_index(self) -> None:
        """Serve index.html with the current snapshot seeded inline, so the first paint
        already has data (fast cold load, and reliable static/headless rendering)."""
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        try:
            seed = json.dumps(sources.snapshot())
        except Exception:  # noqa: BLE001
            seed = "null"
        html = html.replace("</head>", f"<script>window.__STATE__={seed};</script></head>", 1)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static(self, rel: str) -> None:
        rel = rel.split("?")[0].replace("static/", "")
        target = (STATIC / rel).resolve()
        if STATIC not in target.parents and target != STATIC or not target.exists():
            return self._send(404, b"not found", "text/plain")
        ctype = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                 ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), f"{ctype}; charset=utf-8")

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = None
        try:
            while True:
                try:
                    snap = sources.snapshot()
                    payload = json.dumps(snap)
                except Exception:  # noqa: BLE001
                    payload = json.dumps({"error": "snapshot failed"})
                if payload != last:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last = payload
                else:  # heartbeat keeps the connection alive through proxies
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)
        if self.path.startswith("/api/directive"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._json({"error": "empty directive"}, 400)
            rec = append_directive(body.get("target", "hub"), text)
            return self._json({"ok": True, "directive": rec})
        if self.path.startswith("/api/withdraw"):
            append_withdraw(body.get("target", "hub"), body.get("id", ""))
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")


def main() -> int:
    parser = argparse.ArgumentParser()
    cfg = sources._load_yaml(LAB / "config.yaml").get("dashboard") or {}
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8787)))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Marginalia — the lab daybook · http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nclosing the daybook.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
