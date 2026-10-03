"""Live sessions: the agent CLI stays running and the PI talks to it while it works.

The supervisor owns one run's CLI process. With a live session it also keeps that process's input
open, so a question, a permission request, a message or an interrupt reaches the agent *in place* —
no exit, no resume. The dashboard never talks to the process: it drops a small JSON file into the
run's inbox (`<run>.d/inbox/`) and the supervisor delivers it (`post` / `take`). That keeps the
dashboard restartable and remote labs unchanged.

  Session          the base each backend's session extends (backends/claude.py, codex.py, opencode.py)
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


# ── the session base (each backend's own session lives in backends/<name>.py) ──
#
# The supervisor spawns the backend's argv, calls `open(proc)`, reads `stream(proc)` line by line and
# passes each JSON object to `handle`, which returns (lines, events): `lines` are stored in the
# transcript and parsed by the backend's one-shot parser (each session translates its protocol to the
# shape its one-shot mode prints, so one parser and one transcript view serve both); `events` are the
# live ones — request · cancelled · turn_end · limits. `send` / `respond` / `interrupt` / `close` may
# be called from the monitor thread.

class Session:
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


def answer_labels(req: dict, item: dict) -> list[list[str]]:
    """The PI's answer as one label list per question, in order (free text where nothing was picked)."""
    ans = item.get("answers") or {}
    out = []
    for q in (req.get("input") or {}).get("questions") or []:
        v = ans.get(q.get("question"))
        out.append(v if isinstance(v, list) else [v] if v else [str(item.get("response") or "")])
    return out


def enabled(prog: dict) -> bool:
    """agents.programmatic.live: on unless `false` or `{enabled: false}`."""
    v = prog.get("live")
    return not (v is False or (isinstance(v, dict) and v.get("enabled") is False))


# ── the supervisor's side ────────────────────────────────────────────────────

class Conversation:
    """Pending requests, the inbox and the deadlines for one live attempt. `st` is the supervisor's
    manifest state (`st.m`, `st.lock`, `st.write`, `st.transition`); `say` logs; `note(kind, **data)`
    emits a bus event."""

    def __init__(self, session, st, rd: Path, prog: dict, note=None, log=None):
        self.s, self.st, self.rd = session, st, Path(rd)
        cfg = prog.get("live") if isinstance(prog.get("live"), dict) else {}
        self.park_after = pos_float(cfg.get("park_minutes"), 60.0) * 60
        self.perm_after = pos_float(cfg.get("permission_minutes"), 30.0) * 60
        self.assume_after = pos_float(cfg.get("campaign_question_minutes"), 30.0) * 60
        self.campaign = bool(st.m.get("campaign"))
        self.linger = pos_float(cfg.get("linger_minutes"), 10.0) * 60 if st.m.get("kind") == "ask" else 0.0
        self.idle = False                      # Ask Newt: answered, waiting for the PI's next message
        self.note = note or (lambda *a, **k: None)
        self.log = log or (lambda obj: None)   # a line in the run's transcript: what the PI said
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
                self.log({"_pi": "message", "text": str(item.get("text") or ""), "ts": now()})
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
        asked_at = (self.st.m.get("pending_question") or {}).get("asked_at")
        self.s.respond(req, item)
        self.log({"_pi": "answer" if req["kind"] == "question" else "permission", "by": by, "ts": now(),
                  "answers": item.get("answers"), "response": item.get("response"), "allow": item.get("allow"),
                  "tool": req.get("tool")})
        self._drop(req["id"])
        m = self.st.m
        if req["kind"] == "question":
            m.setdefault("qa", []).append({"asked_at": asked_at,
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
