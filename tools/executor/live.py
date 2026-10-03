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

Deadlines (agents.programmatic.live):
  park_minutes (60)            a question nobody answered: end the process; the answer resumes it
  permission_minutes (30)      a permission request nobody decided: deny it with a note
  campaign_question_minutes (30)  in a campaign run, a question with options: take the recommended
                               (first) option, mark it assumed, and carry on
A campaign run's permission requests are denied at once (the PI is away).
"""

from __future__ import annotations

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
    name = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
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

class ClaudeSession:
    """`claude -p --input-format stream-json --permission-prompt-tool stdio`: the same channel the
    Agent SDK uses. User turns and control responses go in on stdin; stdout is the usual stream-json
    plus `control_request`s (can_use_tool: AskUserQuestion and permission prompts)."""

    backend = "claude"

    def __init__(self, prompt: str, session_id: str | None = None):
        self.prompt = prompt
        self.session_id = session_id or ""
        self.proc = None
        self._wlock = threading.Lock()
        self._n = 0
        self.unread = 0          # messages sent that the CLI hasn't echoed back yet (--replay-user-messages)
        self.closed = False

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

    def handle(self, obj: dict) -> list[dict]:
        """Protocol lines → extra events: request, cancelled, turn_end, limits."""
        t = obj.get("type")
        if t == "control_request":
            r = obj.get("request") or {}
            if r.get("subtype") == "can_use_tool":
                tool = r.get("tool_name")
                return [{"event": "request", "id": obj.get("request_id"), "tool": tool,
                         "kind": "question" if tool == "AskUserQuestion" else "permission",
                         "input": r.get("input") or {}, "tool_use_id": r.get("tool_use_id"),
                         "why": r.get("decision_reason") or r.get("description")}]
            # anything else the CLI asks of the host (hook callbacks, MCP) — we register none
            self._write({"type": "control_response", "response": {
                "subtype": "error", "request_id": obj.get("request_id"), "error": "not supported"}})
            return []
        if t == "control_cancel_request":
            return [{"event": "cancelled", "id": obj.get("request_id")}]
        if t == "user" and _is_replay(obj):
            self.unread = max(0, self.unread - 1)
            return []
        if t == "system" and obj.get("subtype") == "init" and obj.get("session_id"):
            self.session_id = obj["session_id"]
        if t == "result":
            return [{"event": "turn_end"}]
        if t == "rate_limit_event":
            info = obj.get("rate_limit_info") or {}
            return [{"event": "limits", "status": info.get("status"), "resets_at": info.get("resetsAt"),
                     "type": info.get("rateLimitType")}]
        return []


def _is_replay(obj: dict) -> bool:
    """A user line echoing a message we sent (not a tool result)."""
    c = (obj.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    return isinstance(c, list) and bool(c) and all(isinstance(b, dict) and b.get("type") == "text" for b in c)


SESSIONS = {"claude": ClaudeSession}


def available(backend: str, prog: dict) -> bool:
    live = prog.get("live")
    if live is False or (isinstance(live, dict) and live.get("enabled") is False):
        return False
    return backend in SESSIONS


def make(backend: str, prompt: str, session_id: str | None = None):
    return SESSIONS[backend](prompt, session_id)


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
        return bool(self.pending)

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
                # the turn is over: end the session unless a message is still on its way in
                if self.s.unread == 0 or t - self._turn_end_at > 30:
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
