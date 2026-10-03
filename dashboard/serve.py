"""Vivarium — the Newts' Lab dashboard: the HTTP server. Optional, local-only.

    uv run --with pyyaml python dashboard/serve.py [--port 8787] [--hub <another lab's hub root>]
    (or just: uv run --with pyyaml python newts.py — starts this and opens the browser)

A stdlib HTTP server for the no-build single-page app in static/. This module is the server and its
wiring only: every JSON endpoint is one line in GET_ROUTES / POST_ROUTES (below), pointing at the
module that owns that area —

    sources       reads the lab (the snapshot the page renders; nothing there writes)
    ctx           the lab being shown (or the remote one proxied), the PI's audit log, shared helpers
    runops        headless runs (tools/executor): launch, answer, reply, stop, tail; the scheduler thread
    gates/review  signing Gates 1-3, revoke, envelope, loop brief, revive / what the PI reads to sign
    campaign      campaigns: sign, control, preflight
    settings      lab/config.yaml (one writer), keys, notifications, documents, the System page, setup
    instructions  the Workflow page (the PI's instructions per procedure / stage / role)
    bus · library · labs · machines · fleet · term   notes to agents · the library · labs on this
                  computer · remote machines · the across-labs overview · in-browser terminals

  WRITES are PI actions only: explicit (a confirm), validated, and logged to lab/.bus/pi-actions.jsonl.
  Gate 3 is signed only with a typed confirmation and allows exactly one /finalize run. Runs start only
  through the executor (the unmodified agent CLI, as the logged-in user, in a detached supervisor that
  outlives this server) and only when the PI has enabled programmatic launching; every gate and hard
  rule binds a launched run exactly as in a session, and every run carries the signature guard.
  PROTECTION: 127.0.0.1 only; Host/Origin checks (DNS rebinding); a per-server SameSite=Strict session
  cookie on every /api call; JSON bodies only (no simple cross-site form POSTs). Delete dashboard/ and
  the lab is unchanged (the executor has its own CLI: tools/executor_cli.py).
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
sys.path.insert(0, str(HERE))

# The dashboard's modules — each one area of the product; all share ctx (the lab being shown), none
# imports this one. These re-exports keep `serve.<name>` working for tests and older callers.
import ctx  # noqa: E402
import sources  # noqa: E402
import term  # noqa: E402
import machines  # noqa: E402
import bus  # noqa: E402
import runops  # noqa: E402
import labs  # noqa: E402
import gates  # noqa: E402
import campaign  # noqa: E402
import settings  # noqa: E402
import instructions  # noqa: E402
import fleet  # noqa: E402
from bus import COMMAND_ACTIONS, _BUS_LOCK, _next_id, _bus_dir, _append, _file_lock, append_directive, append_command, _find_ref_bus, append_withdraw  # noqa: E402,F401
from gates import _sign_gate2_block, approve_gate  # noqa: E402,F401
from review import _DOC_CLIP, _read_clip, _filesec, _read_full, _HEADING, _md_section, _gate1_bundle, _pilot_evidence, _gate2_accounting, _gate2_bundle, _find_review_files, _meta_verdict, _gate3_bundle, _as_list, _within, _claim_project_dir, claims_map, read_doc  # noqa: E402,F401
from runops import COMMAND_TO_RUN, _xlab, _run_ref, launch_run, _run_op, permission_run, ack_attention, resolve_escalation, set_programmatic, run_detail, _tail_entry, run_tail, run_log, executor_health, command_launch, command_stop_loop, _SCHED, _SCHED_HUBS, start_scheduler, handoff_scheduler, SAFE_TOOLS, run_tool  # noqa: E402,F401
from settings import EXEC_CONFIG, set_executor_config, write_config  # noqa: E402,F401
from library import _LIB_EXTS, _LIB_CLIP, _LIB_SECTION_CAP, _lib_root, _lib_entry, _lib_docs, _lib_glob, _dated_first, _lab_group, _STUDY_CORE_ORDER, _PROJECT_DOC_ORDER, _study_group, lib_tree, lib_doc, lib_file, _FIG_EXTS, _FIG_CTYPE, _paper_dir, paper_pdf, figure_list, figure_file  # noqa: E402,F401

executor = sources.executor   # tools/executor, or None (the dashboard then stays observe-and-sign)
TOKEN = secrets.token_urlsafe(24)    # this server process's session secret (the cookie below)
SERVER = None                        # the running HTTP server (labs.server_stop shuts it down)
VERSION = "2.0"

# The lab this dashboard shows: a local hub (ctx.HUB), or a lab on another machine reached through an SSH
# tunnel (ctx.REMOTE, a machines.Conn) — then every /api/* call except the local-only ones is proxied.
LOCAL_ONLY_PREFIXES = ("/api/ping", "/api/labs", "/api/machines", "/api/server/stop", "/api/fleet")
LOCAL_ONLY_EXACT = {"/api/terminal"}


def _is_local_route(route: str) -> bool:
    return route in LOCAL_ONLY_EXACT or route.startswith(LOCAL_ONLY_PREFIXES)


def _inject_remote(raw: bytes, conn) -> bytes:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw
    if isinstance(obj, dict):
        obj["remote"] = conn.info()
    return json.dumps(obj).encode("utf-8")


# A short shared snapshot cache. ThreadingHTTPServer serves each SSE client on its own thread and each
# re-reads the whole lab; with the TTL under the 1.5 s SSE tick a single client always recomputes fresh
# (never staler than one tick), while N concurrent clients + the index seed share one read instead of N.
_SNAP_LOCK = threading.Lock()


_SNAP_TTL = 1.0


_snap_cache = {"ts": 0.0, "value": None, "sig": None}


def _sig(snap: dict) -> str:
    """A change signature that ignores the wall clock (`now`), so SSE pushes a new snapshot only when
    the lab actually changed — the client stops re-rendering every 1.5 s."""
    import hashlib
    body = {k: v for k, v in snap.items() if k != "now"}
    return hashlib.sha1(json.dumps(body, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _snapshot_cached(with_sig: bool = False):
    now = time.time()
    with _SNAP_LOCK:
        if _snap_cache["value"] is not None and (now - _snap_cache["ts"]) < _SNAP_TTL:
            return (_snap_cache["value"], _snap_cache["sig"]) if with_sig else _snap_cache["value"]
    snap = sources.snapshot()   # compute OUTSIDE the lock — never serialize the file reads
    try:
        snap["lab_info"] = {"name": labs.lab_name(ctx.HUB), "path": str(ctx.HUB), "setup": settings.setup_status(),
                            "desktop": term.desktop(), "pty": term.has_pty(), "platform": sys.platform}
    except Exception:  # noqa: BLE001
        snap["lab_info"] = {"name": ctx.HUB.name, "path": str(ctx.HUB)}
    sig = _sig(snap)
    with _SNAP_LOCK:
        _snap_cache["ts"], _snap_cache["value"], _snap_cache["sig"] = now, snap, sig
    return (snap, sig) if with_sig else snap


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
        self._send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _cookie_name(self) -> str:
        return f"newts_{self.server.server_address[1]}" if getattr(self, "server", None) else "newts"

    def _has_session(self) -> bool:
        """The SameSite=Strict cookie set with the page: a cross-site request never carries it."""
        raw = self.headers.get("Cookie") or ""
        want = self._cookie_name()
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == want and secrets.compare_digest(v, TOKEN):
                return True
        return False

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        length = max(0, min(length, 1 << 20))   # ignore a non-numeric/absurd Content-Length; cap at 1 MB
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
        if origin == "null":                 # a sandboxed frame / file:// page — never the dashboard
            return False
        if origin:
            from urllib.parse import urlparse
            if (urlparse(origin).hostname or "") not in self._LOCAL_HOSTS:
                return False
        return True

    def do_GET(self):
        # The index seed and every /api/* GET carry the full lab snapshot (titles, metrics, directives,
        # the paper). Guard them with the same localhost/same-origin check as the POSTs so a DNS-rebound
        # page the PI visits can't READ the lab (it still carries the attacker's Host header). Static
        # assets (js/css/art) are not sensitive and stay open.
        sensitive = (self.path in ("/",) or self.path.startswith("/index.html")
                     or self.path.startswith("/?") or self.path.startswith("/api/"))
        if sensitive and not self._local_only():
            return self._send(403, b"refused: cross-origin/non-localhost request", "text/plain")
        if self.path == "/" or self.path.startswith("/index.html") or self.path.startswith("/?"):
            return self._serve_index()
        if self.path.startswith("/api/ping"):   # the launcher's "is it up, and which lab?" (no session)
            return self._json({"ok": True, "app": "newts-lab", "version": VERSION, "lab": str(ctx.HUB),
                               "name": labs.lab_name(ctx.HUB), "pid": os.getpid()})
        if self.path.startswith("/api/") and not self._has_session():
            return self._json({"error": "no dashboard session — reload the page"}, 403)
        route = self.path.split("?", 1)[0]
        if ctx.REMOTE is not None and route.startswith("/api/") and not _is_local_route(route):
            return self._proxy("GET")
        if route in GET_ROUTES:
            try:
                body, code = GET_ROUTES[route](self._query())
            except Exception as e:  # noqa: BLE001
                body, code = {"error": str(e)}, 500
            return self._json(body, code)
        if route == "/api/events":
            return self._serve_sse()
        if self.path.startswith("/api/paper"):
            return self._serve_paper()
        if self.path.startswith("/api/figs"):
            return self._serve_figs()
        if self.path.startswith("/api/figure"):
            return self._serve_figure()
        if self.path.startswith("/api/libfile"):
            q = self._query()
            hit = lib_file(q.get("scope", ""), q.get("slug"), q.get("rel", ""))
            if not hit:
                return self._send(404, b"no such file", "text/plain")
            return self._serve_bytes(hit[0], hit[1])
        if self.path.startswith("/static/") or self.path.count("/") == 1:
            return self._serve_static(self.path.lstrip("/"))
        self._send(404, b"not found", "text/plain")

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _serve_bytes(self, f: Path, ctype: str) -> None:
        try:
            self._send(200, f.read_bytes(), ctype)
        except OSError:
            self._send(404, b"unreadable", "text/plain")

    def _serve_paper(self) -> None:
        f = paper_pdf(self._query().get("idea", ""))
        if not f:
            return self._send(404, b"no compiled paper (studies/<slug>/paper/main.pdf)", "text/plain")
        self._serve_bytes(f, "application/pdf")

    def _serve_figs(self) -> None:
        self._json({"figures": figure_list(self._query().get("idea", ""))})

    def _serve_figure(self) -> None:
        q = self._query()
        f = figure_file(q.get("idea", ""), q.get("name", ""))
        if not f:
            return self._send(404, b"no such figure", "text/plain")
        self._serve_bytes(f, _FIG_CTYPE.get(f.suffix.lower(), "application/octet-stream"))

    def _proxy(self, method: str):
        """Forward this request to the remote lab's own dashboard through its tunnel."""
        conn = ctx.REMOTE
        route = self.path.split("?", 1)[0]
        raw = None
        if method == "POST":
            try:
                n = max(0, min(int(self.headers.get("Content-Length") or 0), 1 << 20))
            except ValueError:
                n = 0
            raw = self.rfile.read(n)
        streaming = route == "/api/events"
        r = hc = None
        for attempt in (0, 1):
            try:
                hc = http.client.HTTPConnection("127.0.0.1", conn.lport, timeout=None if streaming else 120)
                headers = {"Host": f"127.0.0.1:{conn.lport}", "Cookie": conn.cookie or ""}
                if raw is not None:
                    headers["Content-Type"] = "application/json"
                hc.request(method, self.path, body=raw, headers=headers)
                r = hc.getresponse()
            except (OSError, http.client.HTTPException):
                if conn.state == "connected":
                    conn.state = "reconnecting"
                name = conn.info()["name"]
                return self._json({"error": f"lost the connection to {name} — reconnecting", "remote": conn.info()}, 502)
            if r.status == 403 and attempt == 0:
                body = r.read()
                if b"session" in body:        # the remote server restarted: new session token
                    conn.refresh_cookie()
                    continue
                return self._send(403, body, r.getheader("Content-Type") or "application/json")
            break
        ctype = r.getheader("Content-Type") or "application/octet-stream"
        if streaming and r.status == 200:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    line = r.fp.readline()
                    if not line:
                        break
                    if line.startswith(b"data: "):
                        line = b"data: " + _inject_remote(line[6:].strip(), conn) + b"\n"
                    self.wfile.write(line)
                    if line in (b"\n", b"\r\n"):
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                hc.close()
            return None
        data = r.read()
        hc.close()
        if route == "/api/state" and ctype.startswith("application/json"):
            data = _inject_remote(data, conn)
        return self._send(r.status, data, ctype)

    def _remote_seed(self) -> str:
        conn = ctx.REMOTE
        try:
            hc = http.client.HTTPConnection("127.0.0.1", conn.lport, timeout=30)
            hc.request("GET", "/api/state", headers={"Host": f"127.0.0.1:{conn.lport}", "Cookie": conn.cookie or ""})
            r = hc.getresponse()
            data = r.read()
            if r.status == 403:
                conn.refresh_cookie()
                return "null"
            return _inject_remote(data, conn).decode("utf-8")
        except (OSError, http.client.HTTPException):
            return "null"

    def _serve_index(self) -> None:
        try:
            html = (STATIC / "index.html").read_text(encoding="utf-8")
        except OSError:
            return self._send(500, b"dashboard assets missing (dashboard/static/index.html)", "text/plain")
        try:
            # `</` -> `<\/` so a snapshot string containing "</script>" (an event detail, a registry
            # title, a directive, a worker-trace summary — any of which can carry text an agent copied
            # from an untrusted source) can't break out of this inline <script> and inject live HTML.
            # json.dumps does NOT escape `<` or `/`, so this one replace is the whole XSS defense here.
            seed = (self._remote_seed() if ctx.REMOTE is not None else json.dumps(_snapshot_cached())).replace("</", "<\\/")
        except Exception:  # noqa: BLE001
            seed = "null"
        demo = "true" if self.demo else "false"
        html = html.replace(
            "</head>", f"<script>window.__STATE__={seed};window.__VIV_DEMO__={demo};</script></head>", 1)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # the session: HttpOnly (no script reads it), SameSite=Strict (no cross-site request carries it),
        # per port (two dashboards on one machine don't clobber each other)
        self.send_header("Set-Cookie", f"{self._cookie_name()}={TOKEN}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, rel: str) -> None:
        rel = rel.split("?")[0].replace("static/", "", 1)   # only the route prefix, never a nested "static/"
        target = (STATIC / rel).resolve()
        if (STATIC not in target.parents and target != STATIC) or not target.exists():
            return self._send(404, b"not found", "text/plain")
        ctype = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                 ".svg": "image/svg+xml", ".woff2": "font/woff2", ".woff": "font/woff",
                 ".ttf": "font/ttf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".webp": "image/webp", ".json": "application/json", ".map": "application/json",
                 ".txt": "text/plain"}.get(target.suffix, "application/octet-stream")
        charset = "; charset=utf-8" if ctype.startswith(("text/", "application/j", "image/svg")) else ""
        self._send(200, target.read_bytes(), f"{ctype}{charset}")

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
                    snap, sig = _snapshot_cached(with_sig=True)
                    payload = None if sig == last else json.dumps(snap)
                except Exception:  # noqa: BLE001
                    snap, sig, payload = {}, "error", json.dumps({"error": "snapshot failed"})
                if payload is not None:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    last = sig
                else:   # nothing changed: just move the clock (no re-render on the client)
                    self.wfile.write(f"event: tick\ndata: {json.dumps({'now': snap.get('now')})}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def do_POST(self):
        if not self._local_only():
            return self._json({"error": "refused: cross-origin/non-localhost POST"}, 403)
        if not self._has_session():
            return self._json({"error": "no dashboard session — reload the page"}, 403)
        ctype = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            return self._json({"error": "requests must be JSON (Content-Type: application/json)"}, 415)
        route = self.path.split("?", 1)[0]
        if ctx.REMOTE is not None and not _is_local_route(route):
            return self._proxy("POST")
        try:
            return self._dispatch_post()
        except Exception as e:  # noqa: BLE001 — a handler bug / dirty input must never kill the thread
            return self._json({"error": f"internal error: {e}"}, 500)

    def _dispatch_post(self):
        body = self._body()
        if not isinstance(body, dict):
            return self._json({"error": "body must be a JSON object"}, 400)
        fn = POST_ROUTES.get(self.path.split("?", 1)[0])
        if fn is None:
            return self._send(404, b"not found", "text/plain")
        out, code = fn(body)
        return self._json(out, code)


# ── routes: every JSON endpoint, one line each — fn(query) / fn(body) → (body, http code) ───────────
# (/api/events, the paper, figures and library files are streams / files, served in Handler.do_GET;
# the local-only ones are never proxied to a remote lab: LOCAL_ONLY_*)

def _res(out: dict) -> tuple[dict, int]:
    return out, 400 if out.get("error") else 200


def _int(v, default: int = 0) -> int:
    try:
        return int(v or default)
    except (TypeError, ValueError):
        return default


GET_ROUTES = {
    "/api/state": lambda q: (_snapshot_cached(), 200),
    "/api/run": lambda q: run_detail(q.get("run_id", "")),
    "/api/run/tail": lambda q: run_tail(q.get("run_id", ""), _int(q.get("offset"))),
    "/api/run/log": lambda q: run_log(q.get("run_id", "")),
    "/api/executor/health": lambda q: executor_health(fresh=bool(q.get("fresh"))),
    "/api/library": lambda q: (lib_tree(), 200),
    "/api/machines": lambda q: machines.list_machines(),
    "/api/labs": lambda q: labs.labs_list(),
    "/api/fleet": lambda q: fleet.fleet(),
    "/api/summary": lambda q: ({"ok": True, **fleet.lab_summary(ctx.HUB)}, 200),
    "/api/gate3/readiness": lambda q: (gates.gate3_readiness(ctx.safe_id(q.get("idea", "")) or "-"), 200),
    "/api/doc": lambda q: settings.doc_get(q.get("which", "")),
    "/api/workflow/item": lambda q: instructions.workflow_item(q),
    "/api/campaign/preflight": lambda q: campaign.campaign_preflight(q),
    "/api/workflow/proposal": lambda q: instructions.workflow_proposal_get(q),
    "/api/lab/config": lambda q: settings.lab_config_get(),
    "/api/keys": lambda q: settings.keys_status(),
    "/api/notify": lambda q: settings.notify_status(),
    "/api/setup": lambda q: ({"ok": True, **settings.setup_status()}, 200),
    "/api/term/read": lambda q: term.read(q),
    "/api/system": lambda q: settings.system_info(q),
}

POST_ROUTES = {
    "/api/run": lambda b: launch_run(b),
    "/api/run/answer": lambda b: _run_op("answer", b),
    "/api/run/reply": lambda b: _run_op("reply", b),
    "/api/run/interrupt": lambda b: _run_op("interrupt", b),
    "/api/run/stop": lambda b: _run_op("stop", b),
    "/api/run/resume": lambda b: _run_op("resume", b),
    "/api/run/cancel": lambda b: _run_op("cancel", b),
    "/api/run/permission": lambda b: permission_run(b),
    "/api/attention/ack": lambda b: ack_attention(b),
    "/api/escalation/resolve": lambda b: resolve_escalation(b),
    "/api/executor/enable": lambda b: set_programmatic(b),
    "/api/executor/config": lambda b: set_executor_config(b),
    "/api/labs/open": lambda b: labs.labs_open(b),
    "/api/labs/create": lambda b: labs.labs_create(b),
    "/api/labs/forget": lambda b: labs.labs_forget(b),
    "/api/terminal": lambda b: labs.terminal_open(b),
    "/api/gate/revoke": lambda b: gates.gate_revoke(b),
    "/api/finalize": lambda b: gates.finalize_start(b),
    "/api/envelope": lambda b: gates.envelope_set(b),
    "/api/loopbrief/sign": lambda b: gates.loopbrief_sign(b),
    "/api/campaign": lambda b: campaign.campaign_create(b),
    "/api/campaign/control": lambda b: campaign.campaign_control(b),
    "/api/revive": lambda b: gates.revive(b),
    "/api/doc/save": lambda b: settings.doc_save(b),
    "/api/workflow/save": lambda b: instructions.workflow_save(b),
    "/api/workflow/proposal": lambda b: instructions.workflow_proposal(b),
    "/api/lab/config": lambda b: settings.lab_config_set(b),
    "/api/keys": lambda b: settings.keys_set(b),
    "/api/notify": lambda b: settings.notify_set(b),
    "/api/notify/test": lambda b: settings.notify_test(b),
    "/api/setup/complete": lambda b: settings.setup_complete(b),
    "/api/server/stop": lambda b: labs.server_stop(b),
    "/api/machines/add": lambda b: machines.add_machine(b),
    "/api/machines/remove": lambda b: machines.remove_machine(b),
    "/api/machines/probe": lambda b: machines.probe(b),
    "/api/machines/add-lab": lambda b: machines.add_lab(b),
    "/api/machines/create-lab": lambda b: machines.create_lab(b),
    "/api/machines/open": lambda b: machines.open_lab(b),
    "/api/machines/use": lambda b: machines.use_lab(b),
    "/api/machines/disconnect": lambda b: machines.disconnect(b),
    "/api/fleet/keep": lambda b: fleet.set_keep(b),
    "/api/machines/local": lambda b: machines.local(b),
    "/api/machines/install-uv": lambda b: machines.install_uv(b),
    "/api/system/scheduler": lambda b: settings.system_scheduler_set(b),
    "/api/term/open": lambda b: term.open_session(b),
    "/api/term/write": lambda b: term.write(b),
    "/api/term/resize": lambda b: term.resize(b),
    "/api/term/close": lambda b: term.close(b),
    "/api/directive": bus.directive_post,
    "/api/withdraw": bus.withdraw_post,
    "/api/command": runops.command_post,
    "/api/gate": gates.gate_post,
    "/api/tool": lambda b: _res(run_tool(b.get("name", ""), b.get("idea"))),
    "/api/read": lambda b: _res(read_doc(b.get("what", ""), b.get("idea"), b.get("gate"), b.get("run"))),
    "/api/libdoc": lambda b: _res(lib_doc(b.get("scope", ""), b.get("slug"), b.get("rel", ""))),
    "/api/claims": lambda b: _res(claims_map(b.get("idea"))),
}


def _use_hub(path: str) -> None:
    """Point the dashboard (and its sources / executor) at another lab's hub root."""
    hub = Path(path).resolve()
    if not (hub / "lab").is_dir():
        raise SystemExit(f"--hub {hub}: no lab/ directory there")
    switch_hub(hub)


switch_hub = ctx.switch_hub   # (the lab picker; caches clear themselves through ctx.on_change)


def _forget_snapshot(_old=None, _new=None) -> None:
    with _SNAP_LOCK:
        _snap_cache.update(ts=0.0, value=None, sig=None)


ctx.on_change(_forget_snapshot)


class LabServer(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets a second server silently share the port; bind exclusively instead."""
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return   # a client (a tab, a tunnel) went away mid-request — routine, not an error
        super().handle_error(request, client_address)

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--hub", default=None)
    known, _ = pre.parse_known_args()
    if known.hub:
        _use_hub(known.hub)
    cfg = sources._load_yaml(ctx.LAB / "config.yaml").get("dashboard") or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--hub", default=None, help="serve another lab (its hub root); default: this repo")
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8787)))
    parser.add_argument("--demo", action="store_true",
                        help="enable the synthetic demo world (debugging/showcase; visit /?demo). "
                             "Off by default; also enabled by VIVARIUM_DEMO=1.")
    args = parser.parse_args()
    Handler.demo = bool(args.demo) or os.environ.get("VIVARIUM_DEMO", "").lower() in ("1", "true", "yes")
    global SERVER
    try:
        server = LabServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        print(f"port {args.port} is busy ({e}) — start with --port <another>, or use newts.py (it picks one)")
        return 3
    SERVER = ctx.SERVER = server
    labs.remember_lab(ctx.HUB)
    _SCHED_HUBS.add(ctx.HUB)
    print(f"Vivarium — the living lab · http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    if executor is None:
        print("  executor: not available (tools/executor missing) — observe-and-sign only")
    elif cfg.get("executor", True) is False:
        print("  executor: disabled for this dashboard (dashboard.executor: false) — observe-and-sign only")
    else:
        start_scheduler()
        fleet.start_keeper()
        on = bool((sources._load_yaml(ctx.LAB / "config.yaml").get("agents") or {}).get("programmatic", {}).get("enabled"))
        print("  executor: scheduler running · programmatic launching is "
              + ("ON" if on else "OFF (enable it in the dashboard settings, or /configure)"))
    if Handler.demo:
        print(f"  demo mode ENABLED (debugging) · synthetic world at http://127.0.0.1:{args.port}/?demo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nlights out in the vivarium.")
    handoff_scheduler()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())