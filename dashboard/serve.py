"""Vivarium — the Kartr Lab, rendered as a living terrarium. Optional, local-only.

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
  READS (safe, read-only file views, on demand):
    POST /api/read        a small whitelisted text view (lab knowledge; a gate's proposal/
                          claims/envelope) from fixed roots + a sanitized slug. Never writes.

It cannot run an agent skill (that's the Claude session) and it never signs Gate 3 or
fakes a result. Binds 127.0.0.1 only. Delete the dashboard/ folder and the lab is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
    # max(existing d-NNN) + 1 — NOT a line count: a withdrawn/edited/missing row must never
    # cause a reissued id (which would collide and mis-route acks/withdraws onto a live directive).
    hi = 0
    if directives_path.exists():
        for line in directives_path.read_text(encoding="utf-8-sig").splitlines():
            for m in re.findall(r'"id"\s*:\s*"d-(\d+)"', line):
                hi = max(hi, int(m))
    return f"d-{hi + 1:03d}"


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
    """Append-only audit trail of PI actions taken through the dashboard. `default=str` keeps it
    robust to YAML-parsed values (e.g. an `expires:` date) that aren't natively JSON-serializable."""
    (LAB / ".bus").mkdir(parents=True, exist_ok=True)
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (LAB / ".bus" / "pi-actions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


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
        proposal = HUB / "studies" / idea / "proposal.md"
        if not proposal.exists():
            return {"error": f"no proposal at studies/{idea}/proposal.md"}
        with proposal.open("a", encoding="utf-8") as f:
            f.write(f"\n\n<!-- PI Gate 1 approved via Vivarium dashboard {ts} -->\n")
        append_command(idea, "gate1_approved", {}, "Gate 1 approved (PI via dashboard) — proceed to /spawn-project")
        _emit_hub("gate_resolved", idea=idea, detail="Gate 1 approved (PI via dashboard)")
        _pi_log({"action": "approve_gate", "gate": 1, "idea": idea})
        return {"ok": True, "gate": 1, "idea": idea,
                "note": "Proposal signed; the agent will transition the registry and spawn the project at its next checkpoint."}
    # gate 2 — sign the project's control.yaml gate2_envelope (the canonical machine-readable
    # signature). READ via YAML to VALIDATE the envelope; WRITE via a targeted regex so the
    # file's comments/formatting survive.
    pdir = sources._project_path({"id": idea, "project": ""})
    control = (pdir / "control.yaml") if pdir else None
    if not control or not control.exists():
        return {"error": f"no control.yaml for {idea} (spawn the project first)"}
    text = control.read_text(encoding="utf-8-sig")
    if "pi_signed:" not in text:
        return {"error": "control.yaml has no gate2_envelope.pi_signed field"}
    env = sources._load_yaml(control).get("gate2_envelope") or {}
    if env.get("pi_signed"):
        return {"error": "gate2_envelope is already signed (pi_signed: true) — nothing to do"}
    expires = str(env.get("expires") or "").strip()
    if expires and expires.lower() not in ("null", "none") and expires < time.strftime("%Y-%m-%d"):
        return {"error": f"gate2_envelope expired ({expires}) — update the envelope in control.yaml before signing"}
    warnings = []
    if not any(env.get(k) for k in ("full_runs", "per_run_max_minutes", "total_max_minutes")):
        warnings.append("envelope authorizes nothing (all caps are 0/null) — signing it is a no-op; every FULL run will still need fresh PI approval")
    import re
    text = re.sub(r"pi_signed:\s*false", "pi_signed: true", text, count=1)
    text = re.sub(r"signed_via:\s*null", f"signed_via: dashboard:{ts}", text, count=1)
    control.write_text(text, encoding="utf-8")
    env_after = sources._load_yaml(control).get("gate2_envelope") or {}
    _emit_hub("gate_resolved", idea=idea, detail="Gate 2 envelope signed (PI via dashboard)")
    _pi_log({"action": "approve_gate", "gate": 2, "idea": idea, "control": str(control),
             "envelope_before": env, "envelope_after": env_after})
    return {"ok": True, "gate": 2, "idea": idea, "warnings": warnings or None,
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
        # compare.py requires a subcommand (`list`); status.py takes none.
        cmd, cwd = [py, str(script)] + (["list", "--last", "20"] if name == "compare" else []), pdir
    try:
        out = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        return {"ok": True, "tool": name, "exit": out.returncode,
                "output": (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.stderr.strip() else "")}
    except subprocess.TimeoutExpired:
        return {"error": f"{name} timed out"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} failed: {e}"}


# ── read-only document viewer (lab knowledge · a gate's proposal/claims) ─────
#
# Surfaces a few SMALL, READ-ONLY text files so the PI can read context in-dashboard
# (the lab's learning; a proposal/claims at a gate). Reads only from fixed roots with a
# sanitized slug — never writes, never executes. Gate 3 stays non-signable; this only
# *shows* the draft + claims so a finalization decision can be made in a session.

import re as _re

_SLUG_RE = _re.compile(r"[^A-Za-z0-9._-]")
_DOC_CLIP = 16000   # never stream a whole repo — clip each file


def _slug(s: str) -> str:
    return _SLUG_RE.sub("", (s or "").strip())[:80]


def _read_clip(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    txt = path.read_text(encoding="utf-8-sig", errors="replace")
    return txt if len(txt) <= _DOC_CLIP else txt[:_DOC_CLIP] + "\n\n… (clipped — open the file for the rest)"


def read_doc(what: str, idea: str | None = None, gate: int | None = None, run: str | None = None) -> dict:
    if what == "run":
        slug, rid = _slug(idea or ""), _slug(run or "")
        if not slug or not rid:
            return {"error": "need a project + run id"}
        pdir = sources._project_path({"id": slug, "project": ""})
        if not pdir:
            return {"error": f"no project dir for {slug}"}
        rdir = pdir / "runs" / rid
        secs = []
        for fn in ("metrics.json", "meta.json", "config.yaml"):
            f = rdir / fn
            if f.exists():
                secs.append({"title": f"runs/{rid}/{fn}", "text": _read_clip(f)})
        stream = rdir / "metrics.jsonl"
        if stream.exists():
            lines = [ln for ln in _read_clip(stream).splitlines() if ln.strip()]
            if lines:
                secs.append({"title": f"runs/{rid}/metrics.jsonl · last {min(8, len(lines))} of {len(lines)}",
                             "text": "\n".join(lines[-8:])})
        if not secs:
            return {"error": f"no artifacts under {slug}/runs/{rid} (runs are gitignored; the project may be elsewhere)"}
        return {"ok": True, "title": f"{slug} · {rid}", "sections": secs}

    if what == "knowledge":
        secs = []
        for name in ("FINDINGS", "FAILURES", "OPEN-QUESTIONS"):
            secs.append({"title": name.replace("-", " ").title(),
                         "text": _read_clip(LAB / "knowledge" / f"{name}.md") or "(none recorded yet)"})
        nb_dir = LAB / "notebook"
        entries = sorted(nb_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if nb_dir.exists() else []
        dated = [f for f in entries if f.name.lower() != "readme.md"]
        latest = (dated or entries)[0] if (dated or entries) else None
        if latest:
            secs.append({"title": "Latest notebook entry · " + latest.name, "text": _read_clip(latest)})
        return {"ok": True, "title": "Lab knowledge", "sections": secs}

    if what == "gate":
        slug = _slug(idea or "")
        if not slug:
            return {"error": "no idea given"}
        try:
            gate = int(gate or 0)
        except (TypeError, ValueError):
            gate = 0
        if gate == 1:
            f = HUB / "studies" / slug / "proposal.md"
            return {"ok": True, "title": f"Gate 1 · {slug} · proposal",
                    "sections": [{"title": f"studies/{slug}/proposal.md",
                                  "text": _read_clip(f) or f"no proposal at studies/{slug}/proposal.md"}]}
        if gate == 2:
            pdir = sources._project_path({"id": slug, "project": ""})
            ctrl = (pdir / "control.yaml") if pdir else None
            env = (sources._load_yaml(ctrl).get("gate2_envelope") if ctrl and ctrl.exists() else None)
            secs = [{"title": "gate2_envelope (control.yaml)",
                     "text": json.dumps(env, indent=2, default=str) if env else "no gate2_envelope found — spawn the project first"}]
            if ctrl and ctrl.exists():
                secs.append({"title": "control.yaml", "text": _read_clip(ctrl)})
            return {"ok": True, "title": f"Gate 2 · {slug} · the FULL-run envelope", "sections": secs}
        if gate == 3:
            pdir = HUB / "studies" / slug / "paper"
            secs = [{"title": f"studies/{slug}/paper/claims.yaml", "text": _read_clip(pdir / "claims.yaml") or "no claims.yaml yet"}]
            if pdir.exists():
                for md in sorted(pdir.glob("*review*.md")) + sorted(pdir.glob("*meta*.md")):
                    secs.append({"title": md.name, "text": _read_clip(md)})
            return {"ok": True, "title": f"Gate 3 · {slug} · claims + review (read-only)",
                    "sections": secs, "note": "Gate 3 is never signed from the dashboard — read here, then /finalize in a session."}
        return {"error": f"unknown gate {gate}"}
    return {"error": f"unknown document '{what}'"}


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    # Demo mode is a debugging/showcase world, NOT a user-facing dashboard feature. It is OFF unless
    # the server is started with `--demo` (or VIVARIUM_DEMO=1); only then is window.__VIV_DEMO__ injected
    # so a `?demo` URL activates the synthetic lab. There is no in-dashboard control to enable it.
    demo = False

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

    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

    def _local_only(self) -> bool:
        """True iff this is a same-origin localhost request. Guards state-changing POSTs (the
        dashboard can sign Gate 1/2) against DNS-rebinding from a malicious page the PI visits:
        a rebound request still carries the attacker's Host header, which is rejected here."""
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):            # [::1]:port -> ::1
            host = host.split("]", 1)[0].lstrip("[")
        elif host.count(":") == 1:          # 127.0.0.1:port -> 127.0.0.1
            host = host.rsplit(":", 1)[0]
        if host and host not in self._LOCAL_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            from urllib.parse import urlparse
            if (urlparse(origin).hostname or "") not in self._LOCAL_HOSTS:
                return False
        return True

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
        demo = "true" if self.demo else "false"
        html = html.replace(
            "</head>", f"<script>window.__STATE__={seed};window.__VIV_DEMO__={demo};</script></head>", 1)
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
        if not self._local_only():
            return self._json({"error": "refused: cross-origin/non-localhost POST"}, 403)
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
            try:
                gate = int(body.get("gate", 0))
            except (TypeError, ValueError):
                return self._json({"error": "gate must be 1 or 2"}, 400)
            if gate not in (1, 2):
                return self._json({"error": "dashboard signs only Gate 1 or Gate 2"}, 400)
            res = approve_gate(body.get("idea", ""), gate)
            return self._json(res, 200 if res.get("ok") else 400)
        if p.startswith("/api/tool"):
            return self._json(run_tool(body.get("name", ""), body.get("idea")))
        if p.startswith("/api/read"):
            return self._json(read_doc(body.get("what", ""), body.get("idea"), body.get("gate"), body.get("run")))
        if p.startswith("/api/withdraw"):
            append_withdraw(body.get("target", "hub"), body.get("id", ""))
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")


def main() -> int:
    cfg = sources._load_yaml(LAB / "config.yaml").get("dashboard") or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8787)))
    parser.add_argument("--demo", action="store_true",
                        help="enable the synthetic demo world (debugging/showcase; visit /?demo). "
                             "Off by default; also enabled by VIVARIUM_DEMO=1.")
    args = parser.parse_args()
    Handler.demo = bool(args.demo) or os.environ.get("VIVARIUM_DEMO", "").lower() in ("1", "true", "yes")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Vivarium — the living lab · http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    if Handler.demo:
        print(f"  demo mode ENABLED (debugging) · synthetic world at http://127.0.0.1:{args.port}/?demo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nlights out in the vivarium.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
