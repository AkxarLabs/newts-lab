"""Run one agent attempt and record everything it does.

`run_process` is the drain loop (spawn → capture stdout → parse → watchdog / stop marker / heartbeat
→ exit), shared by the detached per-run supervisor below and by agent_runner.py's blocking `launch`.

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
from .lab import Lab, pos_float, pos_int
from .manifest import (append_jsonl, emit, now, read_manifest, run_dir, transition, worker_line,
                       write_manifest)
from .procs import NEW_GROUP, NO_WINDOW, RunLock, graceful_stop, kill_tree, python_exe

PKG = Path(__file__).resolve().parent
SIGNATURE_GUARD = PKG.parent / "signature_guard.py"   # only the PI signs — see tools/signature_guard.py
GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"
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


TRACE_HOOK = Path(__file__).resolve().parents[1] / "trace_hook.py"
TRACE_EVENTS = ("SessionStart", "SubagentStart", "PreToolUse", "PostToolUse", "SubagentStop", "SessionEnd")


def _claude_sidecars(rd: Path, bus: Path) -> Path:
    """Per-run settings: the signature guard, the tracer, and ONE permission — the lab's own bus
    commands (`lab_bus.py emit|escalate`: the run footer, a campaign's dispatch). Those only append an
    event to the lab's record, and the run can't report back without them; claude's `auto` classifier
    was seen refusing the footer. Everything else stays with the PI's permission mode. The tracer runs
    here with this interpreter's absolute path; the repo's own `.claude/settings.json` hooks
    (`--from-repo`) stand down for the run (NEWTS_TRACE_FLAGS=1), so a machine with only `python3` — or
    a repo whose tracing files are stale — is still traced, once."""
    py = python_exe()
    pre = []
    if SIGNATURE_GUARD.is_file():
        pre.append({"matcher": GUARD_MATCHER, "hooks": [
            {"type": "command", "command": f'"{py}" "{SIGNATURE_GUARD}"', "timeout": 15}]})
    hooks = {"PreToolUse": pre}
    if TRACE_HOOK.is_file():
        trace = {"type": "command", "command": f'"{py}" "{TRACE_HOOK}"', "timeout": 10}
        for ev in TRACE_EVENTS:
            entry = {"matcher": "*", "hooks": [trace]} if ev in ("PreToolUse", "PostToolUse") else {"hooks": [trace]}
            hooks.setdefault(ev, []).append(entry)
    b = bus.as_posix()
    allow = [f"Bash({exe} {path} {sub}:*)" for exe in ("python", "python3", f'"{py}"', py)
             for path in (b, f'"{b}"') for sub in ("emit", "escalate")]
    settings = {"hooks": hooks, "permissions": {"allow": allow}}
    sp = rd / "settings.json"
    sp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return sp


def _env_local(lab: Lab) -> dict:
    """lab/.env.local (git-ignored; written by the dashboard's Research keys form): KEY=value lines a run
    inherits (e.g. S2_API_KEY). Never overrides what the executor itself sets."""
    out = {}
    try:
        text = (lab.lab / ".env.local").read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k and k.replace("_", "").isalnum() and not k.startswith(("NEWTS_", "AUTOSCIENTIST_")):
            out[k] = v.strip().strip('"').strip("'")
    return out


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


def _attempt(lab: Lab, workdir: Path, adir: Path, mpath: Path, m: dict, rd: Path) -> int:
    prog = lab.prog()
    backend = m.get("backend") or "claude"
    bcfg = (prog.get("backends") or {}).get(backend) or {}
    st = _State(lab, mpath, m)
    resume = m.get("resume") or None
    entry_status = m.get("status")
    resuming = entry_status == "resuming"
    # live by default; one-shot when the backend has no live session, the PI turned it off, or it
    # failed to start on this machine before
    is_live = live.available(backend, prog) and not m.get("no_live")
    attempt = int(m.get("attempt") or 0) + 1
    run_id = m["run_id"]
    bus_source = lab.source_of(workdir)

    cli = backends.resolve_cli(backend, bcfg)
    if not cli:
        st.transition("failed", reason=f"backend CLI not found: {backend}", finished=now(),
                      last_message=f"backend CLI '{backend}' not found — install it, or set "
                                   f"agents.programmatic.backends.{backend}.command")
        emit(lab, workdir, "agent_finished", detail=run_id, status="failed",
             data={"reason": "cli-not-found", "run_id": run_id})
        return 1
    ver = backends.cli_version(cli) if backend in ("claude", "codex") else None
    m["cli"] = cli[-1] if len(cli) == 1 else " ".join(cli)
    m["cli_version"] = backends.version_str(ver)

    # the prompt for this attempt
    prompt: str | None
    if not resuming:
        prompt = (rd / "prompt.md").read_text(encoding="utf-8") if (rd / "prompt.md").exists() else ""
    else:
        mode = (resume or {}).get("mode") or "continue"
        if mode in ("answer", "reply"):
            prompt = (resume or {}).get("text") or ""
        else:
            prompt = _CONTINUE.format(why=m.get("reason") or m.get("status") or "unknown")
    preamble_text = (rd / "preamble.md").read_text(encoding="utf-8") if (rd / "preamble.md").exists() else ""

    if backend == "claude" and not m.get("session_id"):
        m["session_id"] = str(uuid.uuid4())   # pre-assigned: resumable even if it dies before init
    resume_sid = m.get("session_id") if resuming else None

    env = dict(os.environ)
    depth = pos_int(m.get("depth"), 0, 0)
    env_extra = {"NEWTS_RUN_ID": run_id, "NEWTS_RUN_DIR": str(rd), "NEWTS_HUB": str(lab.hub),
                 "NEWTS_RUN_TARGET": str(m.get("target")), "NEWTS_ATTEMPT": str(attempt),
                 "NEWTS_RUN_SUBJECT": str(m.get("subject") or ""),
                 "NEWTS_RUN_SKILL": str(m.get("skill") or "")}
    env.update(env_extra)
    env["AUTOSCIENTIST_AGENT_DEPTH"] = str(depth + 1)
    if m.get("skill") == "finalize" and m.get("gate3_signed"):
        env.pop("AUTOSCIENTIST_NO_GATE3", None)   # the PI signed Gate 3 in the dashboard for exactly this run
    else:
        env["AUTOSCIENTIST_NO_GATE3"] = "1"   # Gate 3 is never delegated — guard.py finalization hard-stops it
    env.update(_env_local(lab))
    env["NEWTS_PYTHON"] = python_exe()   # the opencode tracer plugin shells out to trace_hook.py with it
    if backend == "claude":
        # `claude -p` waits for background SUBAGENTS before exiting, but only up to a 10-minute ceiling;
        # a lab runner in a long PILOT must not be cut off — the executor's own watchdog bounds the run.
        env.setdefault("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")
    if backend == "opencode":
        env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
        if bcfg.get("permission"):
            env["OPENCODE_PERMISSION"] = json.dumps(bcfg["permission"])
    if backend == "_dummy":
        env["NEWTS_RESUME_SID"] = resume_sid or m.get("session_id") or ""
        env["NEWTS_RESUME_MODE"] = (resume or {}).get("mode") or ""

    settings_path = sys_prompt = None
    if backend == "claude":
        settings_path = _claude_sidecars(rd, (lab.hub / "tools" / "lab_bus.py") if m.get("level") == "hub"
                                         else (workdir / "scripts" / "lab_bus.py"))
        if TRACE_HOOK.is_file():
            env["NEWTS_TRACE_FLAGS"] = "1"   # the repo's own trace hooks (--from-repo) stand down: one line per event
        if preamble_text:
            sys_prompt = rd / "preamble.md"
    add_dirs = [lab.hub] if (backend == "claude" and m.get("level") == "project") else []
    guard = SIGNATURE_GUARD if SIGNATURE_GUARD.is_file() else None
    codex_hooks = backends.codex_hook_overrides(workdir, bcfg, python_exe(), guard=guard) if backend == "codex" else None
    if backend == "opencode" and guard:
        cfg_dir = backends.opencode_guard_dir(rd, guard, python_exe())
        if cfg_dir and not env.get("OPENCODE_CONFIG_DIR"):
            env["OPENCODE_CONFIG_DIR"] = str(cfg_dir)
    if codex_hooks and any("trace_hook" in str(x) for x in codex_hooks):
        env["NEWTS_TRACE_FLAGS"] = "1"   # a trusted repo's own .codex/hooks.json then stands down (no double log)
    oc_traced = backend == "opencode" and backends.opencode_traced(workdir)

    try:
        rc_cmd = backends.build_run_command(
            backend, prompt=prompt, workdir=workdir, prog=prog, cli=cli, model=m.get("model"),
            permission_mode=m.get("permission_mode"), effort=m.get("effort"),
            session_id=m.get("session_id") if (backend == "claude" and not resuming) else None,
            resume_sid=resume_sid if backend in ("claude", "opencode", "codex") else None,
            max_turns=m.get("max_turns"), add_dirs=add_dirs, settings_path=settings_path,
            system_prompt_file=sys_prompt, preamble=preamble_text, cli_ver=ver,
            codex_hooks=codex_hooks, opencode_traced=oc_traced, live=is_live)
    except SystemExit as e:
        st.transition("failed", reason=str(e), finished=now(), last_message=str(e))
        emit(lab, workdir, "agent_finished", detail=run_id, status="failed", data={"run_id": run_id})
        return 1

    max_minutes = pos_float(m.get("max_minutes"), 240.0) or 240.0
    used = sum(pos_float(a.get("wall_seconds"), 0.0) for a in (m.get("attempts") or []))
    budget = max(max_minutes * 60 - used, MIN_ATTEMPT_SECONDS)
    max_bytes = pos_int(prog.get("max_transcript_mb", 200), 200, 0) * 1024 * 1024
    stream = adir / (m.get("stream") or f"{run_id}.stream.jsonl")
    append_jsonl(stream, {"_attempt": attempt, "ts": now(), "resume": (resume or {}).get("mode"),
                          "notes": rc_cmd.notes or None})
    stop_file = rd / "stop"
    if stop_file.exists():   # the PI pressed stop while the run was still starting
        stop_file.unlink()
        st.transition("killed", reason="stopped by the PI before it started", finished=now())
        emit(lab, workdir, "agent_finished", detail=run_id, status="killed", data={"run_id": run_id})
        return 2
    wlog = None if rc_cmd.fires_hooks else (lab.bus_of(workdir) / "workers" / f"{run_id}.jsonl")
    role = m.get("role") or "orchestrator"
    idea = m.get("subject") or (bus_source if bus_source != "hub" else None)
    m.setdefault("attempts", [])
    m["attempts"].append({"n": attempt, "started": now(), "finished": None, "pid": None,
                          "exit_code": None, "stop_reason": None, "wall_seconds": None,
                          "resume": (resume or {}).get("mode")})
    m["attempt"] = attempt
    m["pending_question"] = None
    m.pop("pending_permissions", None)
    m["transport"] = "live" if is_live else "oneshot"
    subagents: dict = m.setdefault("subagents", {})
    sess = conv = None
    if is_live:
        eff_model = backends._eff_model(m.get("model") or prog.get("model"), bcfg)
        ctx = {}
        if backend == "codex":
            ctx["thread"] = backends.codex_thread(bcfg, workdir, eff_model, m.get("effort"), preamble_text,
                                                  hooks=bool(codex_hooks))
        elif backend == "opencode":
            ctx = {"workdir": workdir, "model": eff_model if eff_model != "inherit" else None,
                   "agent": bcfg.get("agent"), "system": preamble_text or None, "title": m.get("label")}
        sess = live.make(backend, prompt or "", m.get("session_id") if (resuming or backend == "claude") else None, **ctx)
        env.update(sess.env())
        conv = live.Conversation(sess, st, rd, prog, note=lambda kind, detail=None, **d: emit(
            lab, workdir, kind, detail=detail or run_id, idea=m.get("subject"), data={"run_id": run_id, **d}),
            log=lambda obj: append_jsonl(adir / (m.get("stream") or f"{run_id}.stream.jsonl"), obj))

    def on_spawn(pid):
        m["attempts"][-1]["pid"] = pid
        st.transition("running", reason=None, pid=pid, supervisor_pid=os.getpid(),
                      started=m.get("started") or now())
        emit(lab, workdir, "agent_resumed" if resuming else "agent_launched", detail=run_id,
             data={"backend": backend, "role": role, "pid": pid, "run_id": run_id, "attempt": attempt,
                   "skill": m.get("skill")})
        if wlog:
            worker_line(wlog, worker_id=run_id, role=role, event="start", status="working", idea=idea,
                        run_id=run_id, session_id=m.get("session_id") or run_id, subject=m.get("subject"))

    def on_event(ev):
        with st.lock:   # the heartbeat thread serializes `m` concurrently
            _on_event(ev)

    def _on_event(ev):
        e = ev.get("event")
        if e in ("request", "cancelled", "turn_end", "limits"):
            if conv:
                conv.on_event(ev)
            return
        if e == "start":
            if ev.get("session_id") and not m.get("session_id"):
                m["session_id"] = ev["session_id"]
            if ev.get("model"):
                m["model_used"] = ev["model"]
            st.write(force=True)
            return
        if e == "action":
            parent = ev.get("parent")
            act = {"ts": now(), "tool": ev.get("tool"), "summary": ev.get("summary")}
            if parent and parent in subagents:
                sa = subagents[parent]
                sa["n_actions"] = int(sa.get("n_actions") or 0) + 1
                sa["last_action"] = act
            else:
                m["n_actions"] = int(m.get("n_actions") or 0) + 1
                m["last_action"] = act
            tu = ev.get("tool_use_id")
            if ev.get("spawn") and tu and tu not in subagents and len(subagents) < MAX_SUBAGENTS:
                subagents[tu] = {
                    "type": ev["spawn"]["subagent_type"], "description": ev["spawn"]["description"],
                    "status": "working", "started": now(), "finished": None, "n_actions": 0,
                    "last_action": None, "result": None, "parent": parent,
                    "background": bool(ev["spawn"].get("background"))}
                if ev["spawn"].get("child_session"):   # codex thread id / opencode child session id
                    subagents[tu]["session"] = ev["spawn"]["child_session"]
            if wlog:
                worker_line(wlog, worker_id=run_id, role=role, event="action", tool=ev.get("tool"),
                            kind=ev.get("kind"), summary=ev.get("summary"), idea=idea, run_id=run_id,
                            session_id=m.get("session_id") or run_id)
        elif e == "begin":
            m["in_tool"] = {"ts": now(), "tool": ev.get("tool"), "summary": ev.get("summary")}
        elif e == "tool_result":
            tu = ev.get("tool_use_id")
            if tu and tu in subagents:
                sa = subagents[tu]
                if sa.get("background") and not ev.get("is_error"):
                    sa["launched"] = (ev.get("text") or "")[:300]   # the launch ack — it's still working
                else:
                    sa["status"] = "failed" if ev.get("is_error") else "done"
                    sa["finished"] = now()
                    sa["result"] = (ev.get("text") or "")[:1200]
            m.pop("in_tool", None)
        elif e == "text" and not ev.get("parent"):
            m["last_text"] = (ev.get("text") or "")[:800]
        elif e == "denied":
            m["denials"] = int(m.get("denials") or 0) + 1
        elif e == "result":
            if ev.get("last_message"):
                m["last_message"] = str(ev["last_message"])[:2000]
            if ev.get("cost_usd") is not None or ev.get("usage"):
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
            if "cost_delta" in ev:   # opencode: one step_finish per model step → accumulate
                tok = u.setdefault("tokens", {})
                for k, v in ev["usage"].items():
                    tok[k] = tok.get(k, 0) + v
                if isinstance(ev.get("cost_delta"), (int, float)):
                    u["cost_usd"] = round(float(u.get("cost_usd") or 0) + ev["cost_delta"], 6)
            else:                    # codex: turn.completed carries the turn's totals
                u["tokens"] = ev["usage"]
        st.write()

    res = run_process(rc_cmd.argv, cwd=workdir, env=env, stream_path=stream, backend=backend,
                      max_seconds=budget, max_bytes=max_bytes, stdin_text=rc_cmd.stdin_text,
                      on_spawn=on_spawn, on_event=on_event, stop_file=stop_file,
                      heartbeat=lambda: st.write(force=True), popen_flags=NO_WINDOW, live=sess, conv=conv)

    if is_live and not (res.started or res.stopped or res.parked or res.breached) and res.rc and res.wall < 60:
        # the live session never got going on this machine (an old CLI, a flag it doesn't know): this
        # run continues one-shot, from the same starting point
        _say(f"live session ended at start-up (exit {res.rc}) — retrying this attempt one-shot")
        m["attempts"].pop()
        m["attempt"] = attempt - 1
        m["no_live"] = f"exit {res.rc} at start-up"
        m["status"] = entry_status
        append_jsonl(stream, {"_note": "live session failed at start-up; retrying one-shot", "ts": now()})
        return _attempt(lab, workdir, adir, mpath, m, rd)

    status = classify(res)
    late = []
    if conv:
        late = conv.leftover + [i for i in live.take(rd) if i.get("kind") in ("answer", "message")]
        m.pop("pending_permissions", None)
        if status in ("failed", "waiting_input") and any(r["kind"] == "question" for r in conv.pending.values()):
            status = "waiting_input"   # it ended (or was parked) while asking — the answer resumes it
    a = m["attempts"][-1]
    a.update(finished=now(), exit_code=res.rc, wall_seconds=res.wall,
             stop_reason=(res.result or {}).get("stop_reason"))
    m.pop("resume", None)
    m.pop("in_tool", None)
    for sa in subagents.values():   # anything still "working" when the session ended didn't report back
        if sa.get("status") == "working":
            # a background subagent is waited for before `claude -p` exits (no wait ceiling): it finished
            ok_bg = sa.get("background") and backend == "claude" and status == "completed"
            sa["status"] = "done" if ok_bg else "unfinished"
            if ok_bg:
                sa["finished"] = now()
    if res.session_id and backend != "claude" and not m.get("session_id"):
        m["session_id"] = res.session_id
    if res.last_message:
        m["last_message"] = str(res.last_message)[:2000]
    total_wall = round(sum(pos_float(x.get("wall_seconds"), 0.0) for x in m["attempts"]), 1)
    reason = None
    if res.cli_missing:
        reason = f"could not execute {cli[0]}"
        m["last_message"] = f"backend CLI could not be executed: {' '.join(cli)}"
    elif status == "timeout":
        reason = f"max_minutes={max_minutes:g} breached"
    elif status == "killed":
        reason = "stopped by the PI"
    elif status == "failed":
        reason = f"exit {res.rc}"
        low = str(res.last_message or "").lower()
        if backend == "claude" and any(k in low for k in ("not logged in", "/login", "authentication_failed",
                                                             "failed to authenticate", "oauth session expired")):
            reason = "the claude CLI is not logged in — in a terminal run `claude`, then /login (your own account)"
        elif backend == "codex" and any(k in low for k in ("not logged in", "401", "unauthorized", "codex login")):
            reason = "the codex CLI is not signed in — in a terminal run `codex login` (your own account)"
        elif backend == "opencode" and any(k in low for k in ("no provider", "api key", "providermodelnotfound",
                                                               "unauthorized", "401")):
            reason = "opencode has no working provider for this model — run `opencode auth login`, or set " \
                     "agents.programmatic.backends.opencode.model to a provider/model you have"
        elif "rate limit" in low or "usage limit" in low:
            reason = "usage limit reached — resume later"
    # how to treat it: a campaign waits out a usage limit, backs off a transient error, pauses on sign-in
    fkind = lreset = None
    if status == "timeout":
        fkind = "timeout"
    elif status == "failed":
        blob = f"{res.last_message or ''} {reason or ''} {json.dumps(res.result or {})[:4000]}"
        fkind = "cli_missing" if res.cli_missing else backends.failure_kind(blob)
        if fkind == "usage_limit":
            lreset = backends.limit_reset(blob)

    if wlog and status != "waiting_input":
        worker_line(wlog, worker_id=run_id, role=role, event="stop", status="done", idea=idea)

    if status == "waiting_input" and late and m.get("pending_question"):
        status = "completed"   # answered just as it was parked: resume with the answer (below)
    if late and status in ("completed", "waiting_input"):
        text = "\n\n".join(_late_text(i) for i in late)
        st.transition("queued", by="supervisor", reason="PI message after the session ended",
                      resume={"mode": "reply", "text": text}, pending_question=None,
                      wall_seconds=total_wall, exit_code=res.rc, pid=None, post_processed=False, not_before=None)
        return 0

    if status == "waiting_input":   # parked: the question stays in Needs you; the answer resumes it
        st.transition("waiting_input", reason="asking the PI (parked)", wall_seconds=total_wall,
                      exit_code=res.rc, pid=None)
        return 0

    st.transition(status, reason=reason, finished=now(), exit_code=res.rc, wall_seconds=total_wall, pid=None,
                  failure_kind=fkind, limit_reset=lreset)
    emit(lab, workdir, "agent_finished", detail=run_id, status=status, idea=m.get("subject"),
         data={"exit_code": res.rc, "run_id": run_id, "attempt": attempt, "skill": m.get("skill")})
    return 0 if status == "completed" else 2
