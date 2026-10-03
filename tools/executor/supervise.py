"""Run one agent attempt and record everything it does.

`run_process` is the drain loop (spawn → capture stdout → parse → watchdog / stop marker / heartbeat
→ exit).

`supervise` is the body of `executor_cli.py supervise --run <id>`: a small process that owns exactly
one run while it is active. It holds the run's OS lock (its liveness signal), keeps the manifest
current (session id the moment it is known, last action, subagents, heartbeat), classifies the exit
(completed / waiting_input / timeout / killed / failed), and emits the bus events. The dashboard or
CLI that spawned it can die at any time without affecting the run.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import backends, live
from .lab import Lab, labfiles, pos_float, pos_int
from .manifest import (append_jsonl, emit, now, read_manifest, run_dir, transition, worker_line,
                       write_manifest)
from .procs import NEW_GROUP, NO_WINDOW, RunLock, graceful_stop, kill_tree, python_exe

MIN_ATTEMPT_SECONDS = 300          # a resumed attempt always gets at least 5 minutes
MAX_SUBAGENTS = 60


@dataclass
class ProcResult:
    rc: int | None = None
    breached: bool = False
    stopped: bool = False
    cli_missing: bool = False
    parked: bool = False                # live: a question nobody answered — the process was ended to wait
    started: bool = False               # the CLI reported its session (it got past start-up)
    session_id: str | None = None
    last_message: str | None = None
    result: dict | None = None          # the backend's final result event (claude: stop_reason, cost)
    n_actions: int = 0
    wall: float = 0.0
    events: list = field(default_factory=list)


def run_process(cmd: list[str], *, cwd: Path, env: dict, stream_path: Path, backend: str,
                max_seconds: float, max_bytes: int = 200 * 1024 * 1024, stdin_text: str | None = None,
                on_spawn=None, on_event=None, stop_file: Path | None = None, heartbeat=None,
                heartbeat_every: float = 10.0, grace: float = 10.0, popen_flags: dict | None = None,
                live=None, conv=None) -> ProcResult:
    """Spawn `cmd`, stream its stdout into `stream_path` (capped at `max_bytes`), parse every line,
    and enforce the wall clock. Never raises for child failures — the result says what happened.
    `live` (a live.Session) keeps stdin open and turns protocol lines into events; `conv` (its
    live.Conversation) is ticked by the monitor, and the clock stops while the agent waits on the PI."""
    res = ProcResult()
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, cwd=str(cwd), env=env,
                                stdin=subprocess.PIPE if (stdin_text is not None or live) else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                **(popen_flags if popen_flags is not None else NEW_GROUP))
    except (FileNotFoundError, PermissionError, OSError):
        res.cli_missing = True
        return res
    if on_spawn:
        on_spawn(proc.pid)
    if live:
        live.open(proc)
    elif stdin_text is not None:
        def _feed():
            try:
                proc.stdin.write(stdin_text)
                proc.stdin.close()
            except (BrokenPipeError, OSError, ValueError):
                pass
        threading.Thread(target=_feed, daemon=True).start()

    done = threading.Event()

    def _monitor():
        deadline = t0 + max_seconds
        next_beat = time.time() + heartbeat_every
        last = time.time()
        while not done.wait(0.5):
            if conv is not None:
                if conv.waiting():
                    deadline += time.time() - last   # waiting on the PI doesn't count
                try:
                    if conv.tick() and not res.parked:
                        res.parked = True
                        kill_tree(proc.pid)
                except Exception:  # noqa: BLE001 — the conversation must never kill the drain
                    pass
            last = time.time()
            if time.time() >= deadline and not res.breached and not res.stopped:
                res.breached = True
                kill_tree(proc.pid)
            if stop_file is not None and not res.stopped and not res.breached and stop_file.exists():
                res.stopped = True
                graceful_stop(proc, grace)
            if heartbeat and time.time() >= next_beat:
                next_beat = time.time() + heartbeat_every
                try:
                    heartbeat()
                except Exception:  # noqa: BLE001 — a heartbeat failure must never kill the drain
                    pass

    mon = threading.Thread(target=_monitor, daemon=True)
    mon.start()
    written, truncated = 0, False

    def store(sf, line: str) -> None:
        nonlocal written, truncated
        if max_bytes <= 0 or written < max_bytes:
            sf.write(line)
            sf.flush()
            written += len(line.encode("utf-8", "replace"))
            if max_bytes > 0 and written >= max_bytes and not truncated:
                sf.write('{"_truncated":"transcript hit max_transcript_mb; further output is parsed '
                         'for activity but no longer stored"}\n')
                sf.flush()
                truncated = True

    with Path(stream_path).open("a", encoding="utf-8") as sf:
        for line in (live.stream(proc) if live else proc.stdout):  # type: ignore[union-attr]
            if not live:
                store(sf, line)
            s = line.strip()
            if not s or not s.startswith("{"):
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            if live:   # the session translates its protocol: store + parse what it returns
                lines, evs = live.handle(obj)
                for o in lines:
                    store(sf, json.dumps(o) + "\n")
                evs = [ev for o in lines for ev in backends.parse_events(backend, o)] + evs
            else:
                evs = backends.parse_events(backend, obj)
            for ev in evs:
                e = ev.get("event")
                if e == "start":
                    res.started = True
                if ev.get("session_id") and not res.session_id:   # the FIRST session id wins (opencode
                    res.session_id = ev["session_id"]              # child sessions must not overwrite it)
                if e == "result":
                    if ev.get("last_message"):
                        res.last_message = ev["last_message"]
                    res.result = ev
                elif e == "action":
                    res.n_actions += 1
                if on_event:
                    try:
                        on_event(ev)
                    except Exception:  # noqa: BLE001
                        pass
    done.set()
    if live:
        live.close()
    proc.wait()
    mon.join(timeout=grace + 2)
    res.rc = proc.returncode
    if live and live.ended and not (res.stopped or res.breached or res.parked):
        res.rc = 0
    if live and live.error and not (res.stopped or res.breached or res.parked):
        res.rc = res.rc or 1   # the CLI reported a failure without exiting (codex / opencode servers)
        res.last_message = live.error
    res.wall = round(time.time() - t0, 1)
    return res


def classify(res: ProcResult) -> str:
    """Terminal/paused status for one finished attempt. A deferred question is classified by the
    stop reason, never by the exit code."""
    if res.cli_missing:
        return "failed"
    if res.parked:
        return "waiting_input"
    if res.stopped and res.rc != 0:
        return "killed"
    if res.breached and res.rc != 0:
        return "timeout"
    return "completed" if res.rc == 0 else "failed"


# ── the per-run supervisor ───────────────────────────────────────────────────

class _State:
    """The supervisor's in-memory manifest, written atomically under a lock (drain + heartbeat
    threads both touch it). Throttled: activity writes at most once a second."""

    def __init__(self, lab: Lab, path: Path, m: dict):
        self.lab, self.path, self.m = lab, path, m
        self.lock = threading.RLock()
        self._last = 0.0

    def write(self, force: bool = False) -> None:
        with self.lock:
            if force or time.time() - self._last >= 1.0:
                self.m["heartbeat"] = now()
                write_manifest(self.path, self.m)
                self._last = time.time()

    def transition(self, to: str, *, by: str = "supervisor", reason: str | None = None, **fields) -> None:
        with self.lock:
            self.m["heartbeat"] = now()
            transition(self.lab, self.path, self.m, to, by=by, reason=reason, **fields)
            self._last = time.time()


def _env_local(lab: Lab) -> dict:
    """lab/.env.local (git-ignored; written by the dashboard's Research keys form): KEY=value lines a run
    inherits (e.g. S2_API_KEY). Never overrides what the executor itself sets."""
    return {k: v for k, v in labfiles.read_env(lab.lab / ".env.local").items()
            if k.replace("_", "").isalnum() and not k.startswith(("NEWTS_", "AUTOSCIENTIST_"))}


_CONTINUE = ("This session was interrupted before it finished ({why}). Check what was already done "
             "(the ledgers and git are the memory), then continue the procedure from where it stopped.")


def _late_text(item: dict) -> str:
    """An answer or message that arrived after the session ended, as the resumed session's first turn."""
    if item.get("kind") == "message":
        return str(item.get("text") or "")
    lines = ["The PI answered your question:"]
    for k, v in (item.get("answers") or {}).items():
        lines.append(f"- {k}: {', '.join(v) if isinstance(v, list) else v}")
    if item.get("response"):
        lines.append(str(item["response"]))
    return "\n".join(lines)


def _say(msg: str) -> None:
    """One line to <run>.d/supervisor.log (our stdout) — how an early exit explains itself."""
    print(f"[{now()}] supervise: {msg}", flush=True)


def supervise(lab: Lab, run_id: str, target: str) -> int:
    _say(f"start run={run_id} target={target} pid={os.getpid()}")
    workdir = lab.target_dir(target)
    if not workdir:
        _say(f"exit 2: no workdir for target {target!r}")
        return 2
    adir = lab.agents_dir(workdir)
    mpath = adir / f"{run_id}.json"
    m = read_manifest(mpath, patience=5.0)
    if m is None:
        _say(f"exit 2: manifest unreadable at {mpath}")
        return 2
    rd = run_dir(adir, run_id)
    lock = RunLock(rd / "lock")
    # A reconcile probe (is_locked) holds the lock for an instant to test liveness — retry briefly.
    # A genuine second supervisor holds it for the whole run, so it still loses after the retries.
    deadline = time.time() + 5.0
    while not lock.try_acquire():
        if time.time() > deadline:
            _say("exit 3: another supervisor owns this run")
            return 3
        time.sleep(0.05)
    try:
        m = read_manifest(mpath, patience=5.0) or m   # re-read under the lock
        if m.get("status") not in ("starting", "resuming"):
            _say(f"exit 4: status is {m.get('status')!r} (stale spawn)")
            return 4
        rc = _attempt(lab, Path(workdir), adir, mpath, m, rd)
        _say(f"done rc={rc} status={m.get('status')}")
        return rc
    finally:
        lock.release()
        # the dashboard may have been closed hours ago: make sure someone keeps scheduling the rest
        try:
            from .scheduler import ensure_ticker   # noqa: PLC0415 — scheduler imports this module's peers
            if ensure_ticker(lab):
                _say("no scheduler was running — started `executor_cli serve --until-idle`")
        except Exception as e:  # noqa: BLE001 — never let this affect the run's outcome
            _say(f"ensure_ticker: {e}")


_RETRY_ONESHOT = -1


def _attempt(lab: Lab, workdir: Path, adir: Path, mpath: Path, m: dict, rd: Path) -> int:
    """One attempt of a run: live when its backend has a live session and the PI didn't turn that off;
    when the live session can't even start on this machine, the same attempt runs one-shot."""
    st = _State(lab, mpath, m)
    b = backends.get(m.get("backend"))
    entry_status = m.get("status")
    is_live = b.has_live and live.enabled(lab.prog()) and not m.get("no_live")
    while True:
        rc = _run(lab, b, st, workdir, adir, rd, is_live)
        if rc != _RETRY_ONESHOT:
            return rc
        m["status"], is_live = entry_status, False


def _prepare(lab: Lab, b, st: _State, workdir: Path, rd: Path, is_live: bool):
    """The Attempt (CLI, prompt, env, the backend's sidecars) — or an exit code when it can't start."""
    m, run_id, prog = st.m, st.m["run_id"], lab.prog()
    bcfg = (prog.get("backends") or {}).get(b.name) or {}
    cli = backends.resolve_cli(b.name, bcfg)
    if not cli:
        st.transition("failed", reason=f"backend CLI not found: {b.name}", finished=now(),
                      last_message=f"backend CLI '{b.name}' not found — install it, or set "
                                   f"agents.programmatic.backends.{b.name}.command")
        emit(lab, workdir, "agent_finished", detail=run_id, status="failed",
             data={"reason": "cli-not-found", "run_id": run_id})
        return 1
    ver = backends.cli_version(cli) if b.probe_version else None
    m["cli"], m["cli_version"] = (cli[-1] if len(cli) == 1 else " ".join(cli)), backends.version_str(ver)
    resuming = m.get("status") == "resuming"
    resume = m.get("resume") or {}
    if not resuming:
        prompt = (rd / "prompt.md").read_text(encoding="utf-8") if (rd / "prompt.md").exists() else ""
    elif (resume.get("mode") or "continue") in ("answer", "reply"):
        prompt = resume.get("text") or ""
    else:
        prompt = _CONTINUE.format(why=m.get("reason") or m.get("status") or "unknown")
    if b.preassign_session and not m.get("session_id"):
        m["session_id"] = str(uuid.uuid4())   # resumable even if it dies before its first line
    attempt = int(m.get("attempt") or 0) + 1
    env = {**os.environ, "NEWTS_RUN_ID": run_id, "NEWTS_RUN_DIR": str(rd), "NEWTS_HUB": str(lab.hub),
           "NEWTS_RUN_TARGET": str(m.get("target")), "NEWTS_ATTEMPT": str(attempt),
           "NEWTS_RUN_SUBJECT": str(m.get("subject") or ""), "NEWTS_RUN_SKILL": str(m.get("skill") or ""),
           "AUTOSCIENTIST_AGENT_DEPTH": str(pos_int(m.get("depth"), 0, 0) + 1)}
    if m.get("skill") == "finalize" and m.get("gate3_signed"):
        env.pop("AUTOSCIENTIST_NO_GATE3", None)   # the PI signed Gate 3 in the dashboard for exactly this run
    else:
        env["AUTOSCIENTIST_NO_GATE3"] = "1"   # Gate 3 is never delegated — guard.py finalization hard-stops it
    env.update(_env_local(lab))
    env["NEWTS_PYTHON"] = python_exe()   # the opencode tracer plugin shells out to trace_hook.py with it
    preamble = (rd / "preamble.md").read_text(encoding="utf-8") if (rd / "preamble.md").exists() else ""
    a = backends.Attempt(lab=lab, m=m, workdir=workdir, rd=rd, prog=prog, cli=cli, ver=ver, prompt=prompt,
                         preamble=preamble, resuming=resuming, live=is_live, env=env, python=python_exe(),
                         guard=backends.SIGNATURE_GUARD if backends.SIGNATURE_GUARD.is_file() else None,
                         tracer=backends.TRACE_HOOK if backends.TRACE_HOOK.is_file() else None)
    try:
        b.prepare(a)
        a.command = b.command(a)
    except SystemExit as e:
        st.transition("failed", reason=str(e), finished=now(), last_message=str(e))
        emit(lab, workdir, "agent_finished", detail=run_id, status="failed", data={"run_id": run_id})
        return 1
    return a


def _run(lab: Lab, b, st: _State, workdir: Path, adir: Path, rd: Path, is_live: bool) -> int:
    m, run_id = st.m, st.m["run_id"]
    a = _prepare(lab, b, st, workdir, rd, is_live)
    if isinstance(a, int):
        return a
    prog, cmd, attempt = a.prog, a.command, int(m.get("attempt") or 0) + 1
    max_minutes = pos_float(m.get("max_minutes"), 240.0) or 240.0
    used = sum(pos_float(x.get("wall_seconds"), 0.0) for x in (m.get("attempts") or []))
    stream = adir / (m.get("stream") or f"{run_id}.stream.jsonl")
    append_jsonl(stream, {"_attempt": attempt, "ts": now(), "resume": (m.get("resume") or {}).get("mode"),
                          "notes": cmd.notes or None})
    stop_file = rd / "stop"
    if stop_file.exists():   # the PI pressed stop while the run was still starting
        stop_file.unlink()
        st.transition("killed", reason="stopped by the PI before it started", finished=now())
        emit(lab, workdir, "agent_finished", detail=run_id, status="killed", data={"run_id": run_id})
        return 2
    m.setdefault("attempts", []).append({"n": attempt, "started": now(), "finished": None, "pid": None,
                                         "exit_code": None, "stop_reason": None, "wall_seconds": None,
                                         "resume": (m.get("resume") or {}).get("mode")})
    m.update(attempt=attempt, pending_question=None, transport="live" if is_live else "oneshot")
    m.pop("pending_permissions", None)
    sess = conv = None
    if is_live:
        sess = b.session(a)
        a.env.update(sess.env())
        conv = live.Conversation(sess, st, rd, prog, note=lambda kind, detail=None, **d: emit(
            lab, workdir, kind, detail=detail or run_id, idea=m.get("subject"), data={"run_id": run_id, **d}),
            log=lambda obj: append_jsonl(stream, obj))
    rec = _Recorder(lab, st, workdir, conv, None if cmd.fires_hooks else (lab.bus_of(workdir) / "workers" / f"{run_id}.jsonl"))
    res = run_process(cmd.argv, cwd=workdir, env=a.env, stream_path=stream, backend=b.name,
                      max_seconds=max(max_minutes * 60 - used, MIN_ATTEMPT_SECONDS),
                      max_bytes=pos_int(prog.get("max_transcript_mb", 200), 200, 0) * 1024 * 1024,
                      stdin_text=cmd.stdin_text, on_spawn=rec.on_spawn, on_event=rec.on_event, stop_file=stop_file,
                      heartbeat=lambda: st.write(force=True), popen_flags=NO_WINDOW, live=sess, conv=conv)
    if is_live and not (res.started or res.stopped or res.parked or res.breached) and res.rc and res.wall < 60:
        # the live session never got going here (an old CLI, a flag it doesn't know): retry one-shot
        _say(f"live session ended at start-up (exit {res.rc}) — retrying this attempt one-shot")
        m["attempts"].pop()
        m["attempt"], m["no_live"] = attempt - 1, f"exit {res.rc} at start-up"
        append_jsonl(stream, {"_note": "live session failed at start-up; retrying one-shot", "ts": now()})
        return _RETRY_ONESHOT
    return _finish(lab, b, st, workdir, rd, res, conv, rec, a.cli, max_minutes)


class _Recorder:
    """Keeps the manifest current from the normalized event stream (drain thread; under st.lock)."""

    def __init__(self, lab: Lab, st: _State, workdir: Path, conv, wlog: Path | None):
        self.lab, self.st, self.workdir, self.conv, self.wlog = lab, st, workdir, conv, wlog
        m = st.m
        self.m, self.run_id = m, m["run_id"]
        self.role = m.get("role") or "orchestrator"
        src = lab.source_of(workdir)
        self.idea = m.get("subject") or (src if src != "hub" else None)
        self.subagents: dict = m.setdefault("subagents", {})
        self.resuming = m.get("status") == "resuming"

    def on_spawn(self, pid) -> None:
        m = self.m
        m["attempts"][-1]["pid"] = pid
        self.st.transition("running", reason=None, pid=pid, supervisor_pid=os.getpid(), started=m.get("started") or now())
        emit(self.lab, self.workdir, "agent_resumed" if self.resuming else "agent_launched", detail=self.run_id,
             data={"backend": m.get("backend"), "role": self.role, "pid": pid, "run_id": self.run_id,
                   "attempt": m.get("attempt"), "skill": m.get("skill")})
        self._worker("start", status="working", subject=m.get("subject"))

    def _worker(self, event: str, **fields) -> None:
        if self.wlog:   # a backend that fires no hooks: the supervisor writes its worker log
            worker_line(self.wlog, worker_id=self.run_id, role=self.role, event=event, idea=self.idea,
                        run_id=self.run_id, session_id=self.m.get("session_id") or self.run_id, **fields)

    def on_event(self, ev: dict) -> None:
        with self.st.lock:   # the heartbeat thread serializes `m` concurrently
            self._event(ev)

    def _event(self, ev: dict) -> None:
        e, m, subagents = ev.get("event"), self.m, self.subagents
        if e in ("request", "cancelled", "turn_end", "limits"):
            if self.conv:
                self.conv.on_event(ev)
            return
        if e == "start":
            if ev.get("session_id") and not m.get("session_id"):
                m["session_id"] = ev["session_id"]
            if ev.get("model"):
                m["model_used"] = ev["model"]
            self.st.write(force=True)
            return
        if e == "action":
            parent, act = ev.get("parent"), {"ts": now(), "tool": ev.get("tool"), "summary": ev.get("summary")}
            target = subagents[parent] if parent in subagents else m
            target["n_actions"] = int(target.get("n_actions") or 0) + 1
            target["last_action"] = act
            tu, spawn = ev.get("tool_use_id"), ev.get("spawn")
            if spawn and tu and tu not in subagents and len(subagents) < MAX_SUBAGENTS:
                subagents[tu] = {"type": spawn["subagent_type"], "description": spawn["description"],
                                 "status": "working", "started": now(), "finished": None, "n_actions": 0,
                                 "last_action": None, "result": None, "parent": parent,
                                 "background": bool(spawn.get("background"))}
                if spawn.get("child_session"):   # codex thread id / opencode child session id
                    subagents[tu]["session"] = spawn["child_session"]
            self._worker("action", tool=ev.get("tool"), kind=ev.get("kind"), summary=ev.get("summary"))
        elif e == "begin":
            m["in_tool"] = {"ts": now(), "tool": ev.get("tool"), "summary": ev.get("summary")}
        elif e == "tool_result":
            sa = subagents.get(ev.get("tool_use_id"))
            if sa and sa.get("background") and not ev.get("is_error"):
                sa["launched"] = (ev.get("text") or "")[:300]   # the launch ack — it's still working
            elif sa:
                sa.update(status="failed" if ev.get("is_error") else "done", finished=now(),
                          result=(ev.get("text") or "")[:1200])
            m.pop("in_tool", None)
        elif e == "text" and not ev.get("parent"):
            m["last_text"] = (ev.get("text") or "")[:800]
        elif e == "denied":
            m["denials"] = int(m.get("denials") or 0) + 1
        elif e == "result":
            if ev.get("last_message"):
                m["last_message"] = str(ev["last_message"])[:2000]
            u = m.setdefault("usage", {})
            if ev.get("cost_usd") is not None:
                u["cost_usd"] = ev["cost_usd"]
            if isinstance(ev.get("usage"), dict):
                u["tokens"] = {k: v for k, v in ev["usage"].items() if isinstance(v, (int, float))}
            if ev.get("num_turns") is not None:
                u["turns"] = ev["num_turns"]
            if ev.get("denials"):
                m["denials"] = max(int(m.get("denials") or 0), int(ev["denials"]))
        elif e == "usage" and isinstance(ev.get("usage"), dict):
            u = m.setdefault("usage", {})
            if "cost_delta" in ev:   # per model step (opencode) → accumulate
                tok = u.setdefault("tokens", {})
                for k, v in ev["usage"].items():
                    tok[k] = tok.get(k, 0) + v
                if isinstance(ev.get("cost_delta"), (int, float)):
                    u["cost_usd"] = round(float(u.get("cost_usd") or 0) + ev["cost_delta"], 6)
            else:                    # per turn totals (codex)
                u["tokens"] = ev["usage"]
        self.st.write()


def _finish(lab: Lab, b, st: _State, workdir: Path, rd: Path, res: ProcResult, conv, rec: _Recorder,
            cli: list[str], max_minutes: float) -> int:
    """Classify the attempt, record it, and move the run on (finished · parked · queued again)."""
    m, run_id = st.m, st.m["run_id"]
    status = classify(res)
    late = []
    if conv:
        late = conv.leftover + [i for i in live.take(rd) if i.get("kind") in ("answer", "message")]
        m.pop("pending_permissions", None)
        if status in ("failed", "waiting_input") and any(r["kind"] == "question" for r in conv.pending.values()):
            status = "waiting_input"   # it ended (or was parked) while asking — the answer resumes it
    m["attempts"][-1].update(finished=now(), exit_code=res.rc, wall_seconds=res.wall,
                             stop_reason=(res.result or {}).get("stop_reason"))
    m.pop("resume", None)
    m.pop("in_tool", None)
    for sa in rec.subagents.values():   # anything still "working" when the session ended didn't report back
        if sa.get("status") == "working":
            done = sa.get("background") and b.waits_for_background and status == "completed"
            sa.update(status="done" if done else "unfinished", **({"finished": now()} if done else {}))
    if res.session_id and not m.get("session_id"):
        m["session_id"] = res.session_id
    if res.last_message:
        m["last_message"] = str(res.last_message)[:2000]
    total_wall = round(sum(pos_float(x.get("wall_seconds"), 0.0) for x in m["attempts"]), 1)
    reason = fkind = lreset = None
    if res.cli_missing:
        reason = f"could not execute {cli[0]}"
        m["last_message"] = f"backend CLI could not be executed: {' '.join(cli)}"
    elif status == "timeout":
        reason, fkind = f"max_minutes={max_minutes:g} breached", "timeout"
    elif status == "killed":
        reason = "stopped by the PI"
    if status == "failed":
        # how to treat it: a campaign waits out a usage limit, backs off a transient error, pauses on sign-in
        blob = f"{res.last_message or ''} {json.dumps(res.result or {})[:4000]}"
        fkind = "cli_missing" if res.cli_missing else backends.failure_kind(blob)
        reason = reason or {"auth": b.sign_in_hint, "usage_limit": "usage limit reached — resume later"}.get(fkind) \
            or f"exit {res.rc}"
        lreset = backends.limit_reset(blob) if fkind == "usage_limit" else None
    if status != "waiting_input":
        rec._worker("stop", status="done")

    if status == "waiting_input" and late and m.get("pending_question"):
        status = "completed"   # answered just as it was parked: resume with the answer (below)
    if late and status in ("completed", "waiting_input"):
        st.transition("queued", by="supervisor", reason="PI message after the session ended",
                      resume={"mode": "reply", "text": "\n\n".join(_late_text(i) for i in late)},
                      pending_question=None, wall_seconds=total_wall, exit_code=res.rc, pid=None,
                      post_processed=False, not_before=None)
        return 0
    if status == "waiting_input":   # parked: the question stays in Needs you; the answer resumes it
        st.transition("waiting_input", reason="asking the PI (parked)", wall_seconds=total_wall,
                      exit_code=res.rc, pid=None)
        return 0
    st.transition(status, reason=reason, finished=now(), exit_code=res.rc, wall_seconds=total_wall, pid=None,
                  failure_kind=fkind, limit_reset=lreset)
    emit(lab, workdir, "agent_finished", detail=run_id, status=status, idea=m.get("subject"),
         data={"exit_code": res.rc, "run_id": run_id, "attempt": m.get("attempt"), "skill": m.get("skill")})
    return 0 if status == "completed" else 2
