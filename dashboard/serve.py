"""Vivarium — the AutoScientist lab, rendered as a living terrarium. Optional, local-only.

    uv run --with pyyaml python dashboard/serve.py [--port 8787]

A tiny stdlib HTTP server that READS the lab's files (registry, run records, the event
bus, slots, in-flight liveness) and serves a no-build single-page scene. It is the PI's
control surface — but it stays honest about what it can and can't do:

  WRITES (the only ones):
    POST /api/directive   free-text note to an agent's inbox      -> directives.jsonl
    POST /api/command     a STRUCTURED command (start_loop, …)    -> directives.jsonl
                          the running agent executes it at its next checkpoint, in-protocol
    POST /api/gate        record a PI gate approval (Gate 1 or 2) -> proposal / control.yaml
                          local-only, explicit-confirm, logged. GATE 3 IS NEVER OFFERED.
  RUNS (safe, read-only subprocesses, on demand):
    POST /api/tool        a whitelisted read-only tool (check_lab/show_config/status/…)

It cannot run an agent skill (that's the Claude session) and it never signs Gate 3 or
fakes a result. Binds 127.0.0.1 only. Delete the dashboard/ folder and the lab is unchanged.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

# Structured command actions the dashboard may issue (the agent executes them in-protocol).
COMMAND_ACTIONS = {
    "start_loop", "stop_loop", "set_mode", "run_smoke", "request_run",
    "prioritize", "park", "kill", "analyze", "ideate",
}
# Read-only / safe tools the dashboard may run directly. Never anything that trains or writes.
SAFE_TOOLS = {"check_lab", "show_config", "status", "compare", "inbox", "slots"}


# ── bus writers (directives, commands) ──────────────────────────────────────

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


def _append(target: str, rec: dict) -> dict:
    bus = _bus_dir(target)
    bus.mkdir(parents=True, exist_ok=True)
    path = bus / "directives.jsonl"
    rec.setdefault("id", _next_id(path))
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    rec.setdefault("from", "PI via dashboard")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def append_directive(target: str, text: str) -> dict:
    return _append(target, {"text": text})


def append_command(target: str, action: str, args: dict, text: str) -> dict:
    return _append(target, {"kind": "command", "action": action, "args": args or {},
                            "text": text or action.replace("_", " ")})


def append_withdraw(target: str, ref: str) -> None:
    _append(target, {"kind": "withdraw", "ref": ref})


def _pi_log(rec: dict) -> None:
    """Append-only audit trail of PI actions taken through the dashboard."""
    (LAB / ".bus").mkdir(parents=True, exist_ok=True)
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (LAB / ".bus" / "pi-actions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def _emit_hub(kind: str, **fields) -> None:
    (LAB / ".bus").mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "hub", "kind": kind}
    rec.update(fields)
    with (LAB / ".bus" / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ── gate approval (PI-only, local, explicit) ─────────────────────────────────

def approve_gate(idea: str, gate: int) -> dict:
    """Record a PI gate approval. Gate 1: sign the proposal + leave the follow-through
    command for the agent. Gate 2: flip control.yaml gate2_envelope.pi_signed. Gate 3 is
    never handled here — finalization/sending outside the lab is always done in a session."""
    if gate == 3:
        return {"error": "Gate 3 (finalization) is never approved from the dashboard — do it in a session."}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    if gate == 1:
        proposal = HUB / "ideas" / idea / "proposal.md"
        if not proposal.exists():
            return {"error": f"no proposal at ideas/{idea}/proposal.md"}
        with proposal.open("a", encoding="utf-8") as f:
            f.write(f"\n\n<!-- PI Gate 1 approved via Vivarium dashboard {ts} -->\n")
        append_command(idea, "gate1_approved", {}, "Gate 1 approved (PI via dashboard) — proceed to /spawn-project")
        _emit_hub("gate_resolved", idea=idea, detail="Gate 1 approved (PI via dashboard)")
        _pi_log({"action": "approve_gate", "gate": 1, "idea": idea})
        return {"ok": True, "gate": 1, "idea": idea,
                "note": "Proposal signed; the agent will transition the registry and spawn the project at its next checkpoint."}
    # gate 2 — flip pi_signed in the project's control.yaml (the canonical machine-readable signature)
    pdir = sources._project_path({"id": idea, "project": ""})
    control = (pdir / "control.yaml") if pdir else None
    if not control or not control.exists():
        return {"error": f"no control.yaml for {idea} (spawn the project first)"}
    text = control.read_text(encoding="utf-8-sig")
    if "pi_signed:" not in text:
        return {"error": "control.yaml has no gate2_envelope.pi_signed field"}
    import re
    text = re.sub(r"pi_signed:\s*false", "pi_signed: true", text, count=1)
    text = re.sub(r"signed_via:\s*null", f"signed_via: dashboard:{ts}", text, count=1)
    control.write_text(text, encoding="utf-8")
    _emit_hub("gate_resolved", idea=idea, detail="Gate 2 envelope signed (PI via dashboard)")
    _pi_log({"action": "approve_gate", "gate": 2, "idea": idea, "control": str(control)})
    return {"ok": True, "gate": 2, "idea": idea,
            "note": "gate2_envelope.pi_signed set true (signed_via: dashboard). FULL runs within the envelope are now authorized."}


# ── safe tool runner (read-only subprocesses) ────────────────────────────────

def run_tool(name: str, idea: str | None = None) -> dict:
    if name not in SAFE_TOOLS:
        return {"error": f"tool '{name}' is not in the read-only whitelist"}
    py = sys.executable
    pdir = sources._project_path({"id": idea, "project": ""}) if idea else None
    cmd, cwd = None, HUB
    if name == "check_lab":
        cmd = [py, str(HUB / "tools" / "check_lab.py")]
    elif name == "show_config":
        cmd = [py, str(HUB / "tools" / "show_config.py")] + ([str(pdir)] if pdir else [])
    elif name == "slots":
        cmd = [py, str(HUB / "tools" / "run_slots.py"), "status"]
    elif name == "inbox":
        if pdir:
            cmd, cwd = [py, str(pdir / "scripts" / "lab_bus.py"), "inbox"], pdir
        else:
            cmd = [py, str(HUB / "tools" / "lab_bus.py"), "inbox"]
    elif name in ("status", "compare"):
        if not pdir:
            return {"error": f"'{name}' needs a project (pass idea)"}
        script = pdir / "scripts" / f"{name}.py"
        cmd, cwd = [py, str(script)] + (["--last", "20"] if name == "compare" else []), pdir
    try:
        out = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        return {"ok": True, "tool": name, "exit": out.returncode,
                "output": (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.stderr.strip() else "")}
    except subprocess.TimeoutExpired:
        return {"error": f"{name} timed out"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} failed: {e}"}


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

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
        if (STATIC not in target.parents and target != STATIC) or not target.exists():
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
                    payload = json.dumps(sources.snapshot())
                except Exception:  # noqa: BLE001
                    payload = json.dumps({"error": "snapshot failed"})
                if payload != last:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last = payload
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        body = self._body()
        p = self.path
        if p.startswith("/api/directive"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._json({"error": "empty directive"}, 400)
            return self._json({"ok": True, "directive": append_directive(body.get("target", "hub"), text)})
        if p.startswith("/api/command"):
            action = body.get("action")
            if action not in COMMAND_ACTIONS:
                return self._json({"error": f"unknown action (allowed: {sorted(COMMAND_ACTIONS)})"}, 400)
            rec = append_command(body.get("target", "hub"), action, body.get("args") or {}, body.get("text") or "")
            return self._json({"ok": True, "command": rec})
        if p.startswith("/api/gate"):
            if not body.get("confirm"):
                return self._json({"error": "gate approval needs explicit confirm"}, 400)
            res = approve_gate(body.get("idea", ""), int(body.get("gate", 0)))
            return self._json(res, 200 if res.get("ok") else 400)
        if p.startswith("/api/tool"):
            return self._json(run_tool(body.get("name", ""), body.get("idea")))
        if p.startswith("/api/withdraw"):
            append_withdraw(body.get("target", "hub"), body.get("id", ""))
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")


def main() -> int:
    cfg = sources._load_yaml(LAB / "config.yaml").get("dashboard") or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8787)))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Vivarium — the living lab · http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nlights out in the vivarium.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
