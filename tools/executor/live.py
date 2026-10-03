"""Live sessions: the agent CLI stays running and the PI talks to it while it works.

The supervisor owns one run's CLI process. With a live session it also keeps that process's input
open, so a question, a permission request, a message or an interrupt reaches the agent *in place* —
no exit, no resume. The dashboard never talks to the process: it drops a small JSON file into the
run's inbox (`<run>.d/inbox/`) and the supervisor delivers it (`post` / `take`). That keeps the
dashboard restartable and remote labs unchanged.

  Session          one backend's protocol (claude: stream-json input + the stdio control protocol)
  Conversation     the supervisor's side: pending requests, the inbox, deadlines, parking

What a run is waiting on lives in its manifest, in the same shape the one-shot path uses:
  pending_question     {tool_use_id, name, input, asked_at, live: True}   (status waiting_input)
  pending_permissions  [{id, tool, input, ts}]                            (status stays running)

Ask Newt (a free-form run) stays open `linger_minutes` (10) after it answers — status waiting_input
with nothing pending, i.e. "your turn" — so a follow-up goes straight in.

Deadlines (agents.programmatic.live):
  park_minutes (60)            a question nobody answered: end the process; the answer resumes it
  permission_minutes (30)      a permission request nobody decided: deny it with a note
  campaign_question_minutes (30)  in a campaign run, a question with options: take the recommended
                               (first) option, mark it assumed, and carry on
A campaign run's permission requests are denied at once (the PI is away).
"""

from __future__ import annotations

import itertools
import json
import os
import threading
import time
import uuid
from pathlib import Path

from .lab import pos_float
from .manifest import now

INBOX = "inbox"
KINDS = ("answer", "permission", "message", "interrupt")
MAX_INBOX_BYTES = 16 * 1024
_SEQ = itertools.count()


# ── the inbox: dashboard → supervisor ────────────────────────────────────────

def post(rd: Path, item: dict) -> dict:
    """Drop one item for the run's supervisor (atomic; it is picked up within a second)."""
    if item.get("kind") not in KINDS:
        raise ValueError(f"inbox item kind must be one of {KINDS}")
    data = json.dumps({**item, "ts": now()})
    if len(data) > MAX_INBOX_BYTES:
        raise ValueError("inbox item too large")
    d = Path(rd) / INBOX
    d.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns():020d}-{next(_SEQ):06d}-{uuid.uuid4().hex[:6]}"   # ordered even within one clock tick
    tmp = d / f"{name}.tmp"
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, d / f"{name}.json")
    return item


def take(rd: Path) -> list[dict]:
    """Every waiting item, oldest first, removed from the inbox."""
    d = Path(rd) / INBOX
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
        try:
            f.unlink()
        except OSError:
            pass
    return out


# ── backend sessions ─────────────────────────────────────────────────────────
#
# A session speaks one CLI's protocol. The supervisor spawns `argv`, calls `open(proc)`, reads
# `stream(proc)` line by line and passes each JSON object to `handle`, which returns
#   (lines, events): `lines` are stored in the transcript and parsed by backends.parse_events (each
#   backend's lines are translated to the shape its one-shot mode prints, so one parser and one
#   transcript view serve both); `events` are the live ones — request · cancelled · turn_end · limits.
# `send` / `respond` / `interrupt` / `close` may be called from the monitor thread.

class _Session:
    backend = ""

    def __init__(self, prompt: str, session_id: str | None = None, **ctx):
        self.prompt, self.session_id, self.ctx = prompt, session_id or "", ctx
        self.proc = None
        self.closed = False
        self.unread = 0          # messages sent that the agent hasn't picked up yet
        self.error: str | None = None   # a failure the CLI reported without exiting (codex, opencode)
        self.ended = False      # we ended a server process on purpose: its exit code means nothing
        self._wlock = threading.Lock()

    def env(self) -> dict:
        return {}

    def stream(self, proc):
        return proc.stdout

    def _write(self, obj: dict) -> bool:
        with self._wlock:
            if self.closed or not self.proc or not self.proc.stdin:
                return False
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
                return True
            except (BrokenPipeError, OSError, ValueError):
                return False

    def close(self) -> None:
        with self._wlock:
            if self.closed:
                return
            self.closed = True
            try:
                if self.proc and self.proc.stdin:
                    self.proc.stdin.close()
            except OSError:
                pass


def _answer_labels(req: dict, item: dict) -> list[list[str]]:
    """The PI's answer as one label list per question, in order (free text where nothing was picked)."""
    ans = item.get("answers") or {}
    out = []
    for q in (req.get("input") or {}).get("questions") or []:
        v = ans.get(q.get("question"))
        out.append(v if isinstance(v, list) else [v] if v else [str(item.get("response") or "")])
    return out


class ClaudeSession(_Session):
    """`claude -p --input-format stream-json --permission-prompt-tool stdio`: the same channel the
    Agent SDK uses. User turns and control responses go in on stdin; stdout is the usual stream-json
    plus `control_request`s (can_use_tool: AskUserQuestion and permission prompts)."""

    backend = "claude"
    _n = 0

    def open(self, proc) -> None:
        self.proc = proc
        self._control({"subtype": "initialize", "hooks": None})
        self.send(self.prompt)

    def _control(self, request: dict) -> bool:
        self._n += 1
        return self._write({"type": "control_request", "request_id": f"newts_{self._n}", "request": request})

    def send(self, text: str) -> bool:
        ok = self._write({"type": "user", "message": {"role": "user", "content": text},
                          "parent_tool_use_id": None, "session_id": self.session_id})
        if ok:
            self.unread += 1
        return ok

    def interrupt(self) -> bool:
        return self._control({"subtype": "interrupt"})

    def respond(self, req: dict, item: dict) -> bool:
        """Answer one pending request: a question (item: answers/response) or a permission
        (item: allow/message)."""
        inp = req.get("input") or {}
        if req["kind"] == "question":
            if item.get("allow") is False:
                resp = {"behavior": "deny", "message": item.get("message") or "The PI declined to answer."}
            else:
                ans = {k: (", ".join(v) if isinstance(v, list) else v) for k, v in (item.get("answers") or {}).items()}
                upd = {**inp, "answers": ans}
                if item.get("response"):
                    upd["response"] = str(item["response"])
                resp = {"behavior": "allow", "updatedInput": upd}
        elif item.get("allow"):
            resp = {"behavior": "allow", "updatedInput": inp}
        else:
            resp = {"behavior": "deny", "message": item.get("message") or "The PI denied this."}
        return self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": req["id"], "response": resp}})

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        t = obj.get("type")
        if t == "control_request":
            r = obj.get("request") or {}
            if r.get("subtype") == "can_use_tool":
                tool = r.get("tool_name")
                return [obj], [{"event": "request", "id": obj.get("request_id"), "tool": tool,
                                "kind": "question" if tool == "AskUserQuestion" else "permission",
                                "input": r.get("input") or {}, "tool_use_id": r.get("tool_use_id"),
                                "why": r.get("decision_reason") or r.get("description")}]
            # anything else the CLI asks of the host (hook callbacks, MCP) — we register none
            self._write({"type": "control_response", "response": {
                "subtype": "error", "request_id": obj.get("request_id"), "error": "not supported"}})
            return [obj], []
        if t == "control_cancel_request":
            return [obj], [{"event": "cancelled", "id": obj.get("request_id")}]
        if t == "user" and _is_replay(obj):
            self.unread = max(0, self.unread - 1)
            return [obj], []
        if t == "system" and obj.get("subtype") == "init" and obj.get("session_id"):
            self.session_id = obj["session_id"]
        if t == "result":
            return [obj], [{"event": "turn_end"}]
        if t == "rate_limit_event":
            info = obj.get("rate_limit_info") or {}
            return [obj], [{"event": "limits", "status": info.get("status"), "resets_at": info.get("resetsAt"),
                            "type": info.get("rateLimitType")}]
        return [obj], []


def _is_replay(obj: dict) -> bool:
    """A user line echoing a message we sent (not a tool result)."""
    c = (obj.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    return isinstance(c, list) and bool(c) and all(isinstance(b, dict) and b.get("type") == "text" for b in c)


def _snake(s: str) -> str:
    return "".join("_" + ch.lower() if ch.isupper() else ch for ch in str(s))


class CodexSession(_Session):
    """`codex app-server`: JSON-RPC (without the "jsonrpc" field) over stdio. One thread; each user
    message is a turn (or steers the running one). Approvals and `requestUserInput` arrive as server
    requests. Lines are translated to `codex exec --json` ThreadEvents for the transcript.

    ctx: thread = the thread/start params (cwd, model, approvalPolicy, sandbox, config, developerInstructions)."""

    backend = "codex"

    def __init__(self, prompt, session_id=None, **ctx):
        super().__init__(prompt, session_id, **ctx)
        self._id = 0
        self._calls: dict = {}
        self.turn: str | None = None
        self.usage: dict | None = None

    def _rpc(self, method: str, params: dict) -> int:
        self._id += 1
        self._calls[self._id] = method
        self._write({"id": self._id, "method": method, "params": params})
        return self._id

    def open(self, proc) -> None:
        self.proc = proc
        self._rpc("initialize", {"clientInfo": {"name": "newts-lab", "title": "Newts' Lab", "version": "1"},
                                 "capabilities": {"experimentalApi": True}})

    def send(self, text: str) -> bool:
        inp = [{"type": "text", "text": text}]
        if self.turn:
            self._rpc("turn/steer", {"threadId": self.session_id, "input": inp, "expectedTurnId": self.turn})
            return True
        self.unread += 1
        self._rpc("turn/start", {"threadId": self.session_id, "input": inp})
        return True

    def interrupt(self) -> bool:
        if self.turn:
            self._rpc("turn/interrupt", {"threadId": self.session_id, "turnId": self.turn})
        return True

    def respond(self, req: dict, item: dict) -> bool:
        if req["kind"] == "question":
            qs = (req.get("input") or {}).get("questions") or []
            labels = _answer_labels(req, item)
            result = {"answers": {q.get("id"): {"answers": [x for x in a if x]} for q, a in zip(qs, labels)}}
        else:
            result = {"decision": "accept" if item.get("allow") else "decline"}
        return self._write({"id": req["rpc_id"], "result": result})

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        m = obj.get("method")
        p = obj.get("params") or {}
        if m and "id" in obj:                                      # a server → client request
            return self._request(obj["id"], m, p)
        if "id" in obj:                                            # a response to one of ours
            return self._response(self._calls.pop(obj["id"], None), obj)
        if m == "turn/started":
            self.turn = (p.get("turn") or {}).get("id")
            self.unread = 0
            return [{"type": "turn.started"}], []
        if m in ("item/started", "item/completed"):
            it = p.get("item") or {}
            if it.get("type") in ("userMessage", "reasoning", "plan"):
                return [], []
            item = {_snake(k): (_snake(v) if k in ("type", "tool") and isinstance(v, str) else v) for k, v in it.items()}
            if item.get("type") == "collab_agent_tool_call":
                item["type"] = "collab_tool_call"
            return [{"type": m.replace("/", "."), "item": item}], []
        if m == "thread/tokenUsage/updated":
            self.usage = (p.get("tokenUsage") or {}).get("total")
            return [], []
        if m == "turn/completed":
            t = p.get("turn") or {}
            self.turn = None
            u = self.usage or {}
            lines = [{"type": "turn.completed", "usage": {"input_tokens": u.get("inputTokens", 0),
                                                         "cached_input_tokens": u.get("cachedInputTokens", 0),
                                                         "output_tokens": u.get("outputTokens", 0)}}]
            if t.get("status") == "failed":
                msg = self.error or ((t.get("error") or {}).get("message")) or "turn failed"
                self.error = msg
                lines.append({"type": "turn.failed", "error": {"message": msg}})
            return lines, [{"event": "turn_end"}]
        if m == "error" and not p.get("willRetry"):
            e = p.get("error") or {}
            info = e.get("codexErrorInfo")
            self.error = f"{e.get('message') or 'codex error'}" + (f" ({info})" if info else "")
            return [{"type": "error", "message": self.error}], []
        if m == "account/rateLimits/updated":
            rl = p.get("rateLimits") or {}
            prim = rl.get("primary") or {}
            hit = rl.get("rateLimitReachedType") or (prim.get("usedPercent") or 0) >= 100
            return [], [{"event": "limits", "status": "rejected" if hit else "allowed",
                         "resets_at": prim.get("resetsAt"), "type": rl.get("limitId")}]
        if m == "serverRequest/resolved":
            return [], [{"event": "cancelled", "id": f"codex-{p.get('requestId')}"}]
        return [], []

    def _response(self, method, obj) -> tuple[list[dict], list[dict]]:
        if obj.get("error"):
            if method == "turn/steer":                  # the turn ended meanwhile: start a new one
                self.turn = None
                return [], []
            self.error = f"{method}: {(obj['error'] or {}).get('message')}"
            self.close()
            return [{"type": "error", "message": self.error}], []
        res = obj.get("result") or {}
        if method == "initialize":
            self._write({"method": "initialized"})
            params = dict(self.ctx.get("thread") or {})
            if self.session_id:
                self._rpc("thread/resume", {"threadId": self.session_id, **params})
            else:
                self._rpc("thread/start", params)
        elif method in ("thread/start", "thread/resume"):
            self.session_id = (res.get("thread") or {}).get("id") or self.session_id
            self.send(self.prompt)
            return [{"type": "thread.started", "thread_id": self.session_id}], []
        elif method == "turn/start":
            self.turn = (res.get("turn") or {}).get("id") or self.turn
        return [], []

    def _request(self, rid, method: str, p: dict) -> tuple[list[dict], list[dict]]:
        key = f"codex-{rid}"
        if method == "item/tool/requestUserInput":
            qs = [{"id": q.get("id"), "question": q.get("question"), "header": q.get("header"),
                   "multiSelect": False, "options": q.get("options") or []} for q in p.get("questions") or []]
            return [], [{"event": "request", "id": key, "rpc_id": rid, "kind": "question",
                         "tool": "request_user_input", "input": {"questions": qs}}]
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            cmd = method.startswith("item/command")
            inp = {"command": p.get("command")} if cmd else {"file_path": p.get("grantRoot") or "file changes"}
            return [], [{"event": "request", "id": key, "rpc_id": rid, "kind": "permission",
                         "tool": "Bash" if cmd else "Edit", "input": inp, "why": p.get("reason")}]
        self._write({"id": rid, "error": {"code": -32601, "message": f"{method} is not supported here"}})
        return [], []


class OpencodeSession(_Session):
    """`opencode serve` on a random local port with a per-run password; the session is driven over
    HTTP (prompt_async, question/permission replies, abort) and watched on its event stream (SSE).
    Lines are translated to `opencode run --format json` for the transcript (root session only; a
    subagent shows as its finished `task` tool, and live child activity comes from the tracer plugin).

    ctx: workdir, model ("provider/model"), agent, system (the standing instructions)."""

    backend = "opencode"

    def __init__(self, prompt, session_id=None, **ctx):
        super().__init__(prompt, session_id, **ctx)
        self.url = None
        self.password = uuid.uuid4().hex
        self.busy = False
        self._seen: set = set()
        self._resp = None

    def env(self) -> dict:
        return {"OPENCODE_SERVER_PASSWORD": self.password, "OPENCODE_SERVER_USERNAME": "opencode"}

    def open(self, proc) -> None:
        self.proc = proc

    def _http(self, method: str, path: str, body=None, timeout: float = 30):
        import base64
        import urllib.request
        req = urllib.request.Request(
            self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Basic " + base64.b64encode(f"opencode:{self.password}".encode()).decode(),
                     "Content-Type": "application/json", "x-opencode-directory": str(self.ctx.get("workdir") or "")})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            t = r.read().decode("utf-8", "replace")
        return json.loads(t) if t.strip() else None

    def stream(self, proc):
        import re
        for line in proc.stdout:        # wait for "opencode server listening on http://127.0.0.1:PORT"
            hit = re.search(r"listening on (http://\S+)", line)
            if hit:
                self.url = hit.group(1).rstrip("/")
                break
        if not self.url:
            return
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()   # keep the pipe drained
        try:
            self._resp = self._open_events()
            if not self.session_id:
                self.session_id = (self._http("POST", "/session", {"title": self.ctx.get("title") or "newts run"}) or {})["id"]
            yield json.dumps({"type": "_session", "sessionID": self.session_id})
            self.send(self.prompt)
            for raw in self._resp:
                if self.closed:
                    return
                s = raw.decode("utf-8", "replace").strip()
                if s.startswith("data:"):
                    yield s[5:].strip()
        except (OSError, ValueError, KeyError, TypeError) as e:
            if not self.closed:
                self.error = f"opencode server: {e}"

    def _open_events(self):
        import base64
        import urllib.request
        req = urllib.request.Request(self.url + "/event", headers={
            "Authorization": "Basic " + base64.b64encode(f"opencode:{self.password}".encode()).decode(),
            "x-opencode-directory": str(self.ctx.get("workdir") or "")})
        return urllib.request.urlopen(req, timeout=24 * 3600)

    def send(self, text: str) -> bool:
        body = {"parts": [{"type": "text", "text": text}]}
        model = str(self.ctx.get("model") or "")
        if "/" in model:
            prov, mid = model.split("/", 1)
            body["model"] = {"providerID": prov, "modelID": mid}
        if self.ctx.get("agent"):
            body["agent"] = self.ctx["agent"]
        if self.ctx.get("system"):
            body["system"] = self.ctx["system"]
        try:
            self._http("POST", f"/session/{self.session_id}/prompt_async", body)
        except OSError:
            return False
        self.unread += 1
        return True

    def interrupt(self) -> bool:
        try:
            self._http("POST", f"/session/{self.session_id}/abort")
            return True
        except OSError:
            return False

    def respond(self, req: dict, item: dict) -> bool:
        try:
            if req["kind"] == "question":
                if item.get("allow") is False:
                    self._http("POST", f"/question/{req['id']}/reject")
                else:
                    self._http("POST", f"/question/{req['id']}/reply", {"answers": _answer_labels(req, item)})
            else:
                body = {"reply": "once" if item.get("allow") else "reject"}
                if not item.get("allow") and item.get("message"):
                    body["message"] = item["message"]
                self._http("POST", f"/permission/{req['id']}/reply", body)
            return True
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = self.ended = True
        if self.proc and self.proc.poll() is None:   # the server goes; its event stream ends with it
            from .procs import kill_tree             # (closing the response from this thread could block)
            kill_tree(self.proc.pid)

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        t, p = obj.get("type"), obj.get("properties") or {}
        root = self.session_id
        if t == "_session":
            return [{"type": "step_start", "sessionID": root, "part": {"type": "step-start"}}], []
        if t == "message.part.updated":
            part = p.get("part") or {}
            if part.get("sessionID") != root:
                return [], []
            pt, key = part.get("type"), part.get("id")
            if pt == "tool" and (part.get("state") or {}).get("status") in ("completed", "error") and key not in self._seen:
                self._seen.add(key)
                return [{"type": "tool_use", "sessionID": root, "part": part}], []
            if pt == "text" and (part.get("time") or {}).get("end") and key not in self._seen:
                self._seen.add(key)
                return [{"type": "text", "sessionID": root, "part": part}], []
            if pt == "step-finish" and key not in self._seen:
                self._seen.add(key)
                return [{"type": "step_finish", "sessionID": root, "part": part}], []
            return [], []
        if t == "session.status" and p.get("sessionID") == root:
            kind = (p.get("status") or {}).get("type")
            if kind == "busy":
                self.busy, self.unread = True, 0
            elif kind == "idle" and self.busy:
                self.busy = False
                return [], [{"event": "turn_end"}]
            return [], []
        if t == "question.asked":
            qs = [{"question": q.get("question"), "header": q.get("header"), "multiSelect": bool(q.get("multiple")),
                   "options": q.get("options") or []} for q in p.get("questions") or []]
            return [], [{"event": "request", "id": p.get("id"), "kind": "question", "tool": "question",
                         "input": {"questions": qs}}]
        if t == "permission.asked":
            meta = p.get("metadata") or {}
            inp = {"command": meta.get("command")} if meta.get("command") else {"file_path": ", ".join(p.get("patterns") or [])}
            return [], [{"event": "request", "id": p.get("id"), "kind": "permission", "tool": p.get("permission"),
                         "input": inp}]
        if t in ("question.replied", "question.rejected", "permission.replied"):
            return [], [{"event": "cancelled", "id": p.get("requestID")}]
        if t == "session.error" and p.get("sessionID") in (None, root):
            err = p.get("error") or {}
            self.error = (err.get("data") or {}).get("message") or err.get("name") or "opencode error"
            return [{"type": "error", "sessionID": root, "error": err}], []
        return [], []


SESSIONS = {"claude": ClaudeSession, "codex": CodexSession, "opencode": OpencodeSession}


def available(backend: str, prog: dict) -> bool:
    live = prog.get("live")
    if live is False or (isinstance(live, dict) and live.get("enabled") is False):
        return False
    return backend in SESSIONS


def make(backend: str, prompt: str, session_id: str | None = None, **ctx):
    return SESSIONS[backend](prompt, session_id, **ctx)


# ── the supervisor's side ────────────────────────────────────────────────────

class Conversation:
    """Pending requests, the inbox and the deadlines for one live attempt. `st` is the supervisor's
    manifest state (`st.m`, `st.lock`, `st.write`, `st.transition`); `say` logs; `note(kind, **data)`
    emits a bus event."""

    def __init__(self, session, st, rd: Path, prog: dict, note=None):
        self.s, self.st, self.rd = session, st, Path(rd)
        cfg = prog.get("live") if isinstance(prog.get("live"), dict) else {}
        self.park_after = pos_float(cfg.get("park_minutes"), 60.0) * 60
        self.perm_after = pos_float(cfg.get("permission_minutes"), 30.0) * 60
        self.assume_after = pos_float(cfg.get("campaign_question_minutes"), 30.0) * 60
        self.campaign = bool(st.m.get("campaign"))
        self.linger = pos_float(cfg.get("linger_minutes"), 10.0) * 60 if st.m.get("kind") == "ask" else 0.0
        self.idle = False                      # Ask Newt: answered, waiting for the PI's next message
        self.note = note or (lambda *a, **k: None)
        self.pending: dict[str, dict] = {}     # request id → request (+ "t0")
        self.parked = False
        self.leftover: list[dict] = []         # messages that arrived too late for this process
        self._turn_end_at: float | None = None

    # events from the drain thread (under st.lock)
    def on_event(self, ev: dict) -> None:
        e = ev.get("event")
        m = self.st.m
        if e == "request":
            req = {**ev, "t0": time.time()}
            if self.campaign and req["kind"] == "permission":
                self._answer(req, {"allow": False, "message": "The PI is away (campaign run): permission requests "
                                   "are denied. Do without it, or report it in the run footer."}, by="campaign policy")
                return
            self.pending[req["id"]] = req
            if req["kind"] == "question":
                self.st.transition("waiting_input", reason="asking the PI", pending_question={
                    "tool_use_id": req["id"], "name": req.get("tool"), "input": req.get("input"),
                    "asked_at": now(), "live": True})
                qs = (req.get("input") or {}).get("questions") or []
                self.note("agent_waiting", question=(qs[0].get("question") if qs and isinstance(qs[0], dict) else None))
            else:
                perms = m.setdefault("pending_permissions", [])
                perms.append({"id": req["id"], "tool": req.get("tool"), "input": req.get("input"),
                              "why": req.get("why"), "ts": now()})
                self.st.write(force=True)
        elif e == "cancelled":
            self._drop(ev.get("id"))
        elif e == "turn_end":
            self._turn_end_at = time.time()
        elif e == "limits" and ev.get("resets_at"):
            m["limits"] = {"status": ev.get("status"), "resets_at": ev.get("resets_at"), "type": ev.get("type")}

    def waiting(self) -> bool:
        """True while the agent waits on the PI (the run's clock is paused)."""
        return bool(self.pending) or self.idle

    def tick(self) -> bool:
        """Called by the monitor every half second: deliver the inbox, apply deadlines, end the
        session when its turn is over. True = park: stop the process now."""
        for item in take(self.rd):
            with self.st.lock:
                self._deliver(item)
        t = time.time()
        with self.st.lock:
            for req in list(self.pending.values()):
                age = t - req["t0"]
                if req["kind"] == "permission" and age >= self.perm_after:
                    self._answer(req, {"allow": False, "message": "No decision from the PI in time; treat it as "
                                       "denied and continue without it."}, by="deadline")
                elif req["kind"] == "question" and self.campaign and age >= self.assume_after:
                    ans = _recommended(req)
                    if ans:
                        self._answer(req, {"answers": ans}, by="assumed")
                        self.st.m.setdefault("assumed", []).append({"ts": now(), "answers": ans,
                                                                    "questions": (req.get("input") or {}).get("questions")})
                        self.note("note", detail="assumed the recommended answer", answers=ans)
                    elif age >= self.park_after:
                        self._park()
                elif req["kind"] == "question" and age >= self.park_after:
                    self._park()
            if self._turn_end_at and not self.pending and not self.s.closed:
                # the turn is over: end the session — unless a message is still on its way in, or
                # this is Ask Newt waiting for the PI's next message
                if self.s.unread and t - self._turn_end_at <= 30:
                    pass
                elif self.linger and t - self._turn_end_at < self.linger:
                    if not self.idle:
                        self.idle = True
                        self.st.transition("waiting_input", reason="your turn")
                else:
                    self.s.close()
        return self.parked

    def _deliver(self, item: dict) -> None:
        k = item.get("kind")
        if self.s.closed:
            if k in ("answer", "message"):
                self.leftover.append(item)
            return
        if k == "message":
            if self.s.send(str(item.get("text") or "")):
                self._turn_end_at = None
                if self.idle:
                    self.idle = False
                    self.st.transition("running", reason=None)
                self.note("note", detail="PI message delivered")
            else:
                self.leftover.append(item)
        elif k == "interrupt":
            self.s.interrupt()
        elif k in ("answer", "permission"):
            req = self.pending.get(str(item.get("request_id"))) or self._only(k)
            if req:
                self._answer(req, item, by=item.get("by") or "PI")
            elif k == "answer":
                self.leftover.append(item)

    def _only(self, kind: str):
        want = "question" if kind == "answer" else "permission"
        reqs = [r for r in self.pending.values() if r["kind"] == want]
        return reqs[0] if len(reqs) == 1 else None

    def _answer(self, req: dict, item: dict, by: str) -> None:
        self.s.respond(req, item)
        self._drop(req["id"])
        m = self.st.m
        if req["kind"] == "question":
            m.setdefault("qa", []).append({"asked_at": (m.get("pending_question") or {}).get("asked_at"),
                                           "question": req.get("input"), "answers": item.get("answers"),
                                           "response": item.get("response"), "answered_at": now(), "by": by})
            m["qa"] = m["qa"][-20:]
        else:
            log = self.rd / "permissions.jsonl"
            try:
                with log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": now(), "tool": req.get("tool"), "input": req.get("input"),
                                        "decision": "allow" if item.get("allow") else "deny",
                                        "by": "PI" if by == "PI" else by}) + "\n")
            except OSError:
                pass

    def _drop(self, rid) -> None:
        req = self.pending.pop(str(rid), None) if rid is not None else None
        if not req:
            return
        m = self.st.m
        if req["kind"] == "question":
            if m.get("status") == "waiting_input":
                self.st.transition("running", reason=None, pending_question=None)
        else:
            m["pending_permissions"] = [p for p in m.get("pending_permissions") or [] if p.get("id") != req["id"]]
            if not m["pending_permissions"]:
                m.pop("pending_permissions", None)
            self.st.write(force=True)

    def _park(self) -> None:
        """Nobody answered: the supervisor ends the process. The question stays in Needs you; the
        answer resumes the session (as a message)."""
        self.parked = True


def _recommended(req: dict) -> dict:
    """The first option of every question (the preamble asks agents to put their recommendation
    first), or {} when a question has no options."""
    out = {}
    for q in (req.get("input") or {}).get("questions") or []:
        opts = q.get("options") or []
        if not opts or not isinstance(opts[0], dict) or not opts[0].get("label"):
            return {}
        out[q.get("question")] = opts[0]["label"]
    return out
