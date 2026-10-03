"""Headless runs from the dashboard: launch, answer, reply, stop, the live transcript, the executor
settings switch, and the scheduler thread (and its hand-off when the dashboard stops).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading

import ctx  # noqa: E402
import settings  # noqa: E402
from bus import COMMAND_ACTIONS, append_command  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


# Read-only / safe tools the dashboard may run directly. Never anything that trains or writes.
# audit_claims runs tools/audit_claims.py (reads claims.yaml + artifacts, prints PASS/FAIL/MANUAL — writes nothing).
SAFE_TOOLS = {"check_lab", "show_config", "status", "compare", "inbox", "slots", "audit_claims"}


# dashboard command → the procedure that consumes it (the directive is still written first, so a
# session already running there sees it too; the launched run's inbox checkpoint acts on it)
COMMAND_TO_RUN = {"start_loop": "research-loop", "run_smoke": "experiment", "request_run": "experiment",
                  "analyze": "analyze", "ideate": "ideate"}


def _xlab():
    return executor.Lab(ctx.HUB)


def _run_ref(body: dict) -> str | None:
    rid = body.get("run_id") or body.get("id")
    return rid if (isinstance(rid, str) and ctx.ID_OK.match(rid.strip()) and ".." not in rid) else None


def launch_run(body: dict, by: str = "dashboard", gate3: bool = False) -> tuple[dict, int]:
    """Queue one whitelisted procedure run — or, with `prompt`, the PI's free-form instruction. The
    scheduler thread starts it within ~2 s (or at once). `gate3` is never read from the request: only
    gates.gate3_sign passes it, right after the PI's typed Gate-3 signature."""
    if executor is None:
        return ctx.no_executor()
    if not body.get("confirm"):
        return {"error": "launching needs explicit confirm"}, 400
    try:
        max_minutes = float(body["max_minutes"]) if body.get("max_minutes") not in (None, "") else None
        repeat = float(body["repeat_minutes"]) if body.get("repeat_minutes") not in (None, "") else None
        max_rep = int(body["max_repeats"]) if body.get("max_repeats") not in (None, "") else None
    except (TypeError, ValueError):
        return {"error": "max_minutes / repeat_minutes / max_repeats must be numbers"}, 400
    prompt = body.get("prompt")
    if prompt is not None and not isinstance(prompt, str):
        return {"error": "prompt must be text"}, 400
    spec = executor.RunSpec(
        prompt=prompt, gate3=bool(gate3),
        skill=str(body.get("skill") or ""), target=str(body.get("target") or "hub"),
        args=str(body.get("args") or ""), backend=body.get("backend") or None,
        model=body.get("model") or None, effort=body.get("effort") or None, max_minutes=max_minutes,
        chain=str(body.get("chain") or "off"), repeat_minutes=repeat, max_repeats=max_rep, created_by=by)
    try:
        m = executor.enqueue(_xlab(), spec)
    except executor.SpecError as e:
        return {"error": str(e)}, 400
    ctx.pi_log({"action": "run.launch", "run_id": m["run_id"], "skill": m.get("skill"), "target": m.get("target"),
             "args": m.get("args"), "backend": m.get("backend"), "by": by,
             "prompt": (prompt or "")[:2000] or None})
    ctx.KICK.set()
    return {"ok": True, "run_id": m["run_id"], "position": m.get("position"), "status": m["status"],
            "command": m.get("command"), "label": m.get("label"),
            "note": f"queued (#{m.get('position')}) — it starts as soon as a slot is free"}, 200


def _run_op(kind: str, body: dict) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    rid = _run_ref(body)
    if not rid:
        return {"error": "invalid run id"}, 400
    lab = _xlab()
    try:
        if kind == "answer":
            answers = body.get("answers")
            m = executor.answer(lab, rid, answers if isinstance(answers, dict) and answers else None,
                                str(body.get("text") or body.get("response") or "") or None)
        elif kind == "reply":
            m = executor.reply(lab, rid, str(body.get("text") or ""))
        elif kind == "stop":
            if not body.get("confirm"):
                return {"error": "stopping a run needs explicit confirm"}, 400
            m = executor.stop(lab, rid)
        elif kind == "resume":
            m = executor.resume(lab, rid)
        elif kind == "cancel":
            m = executor.cancel(lab, rid)
        elif kind == "interrupt":
            m = executor.interrupt(lab, rid)
        else:
            return {"error": "unknown operation"}, 400
    except executor.SpecError as e:
        return {"error": str(e)}, 400
    ctx.pi_log({"action": f"run.{kind}", "run_id": rid})
    ctx.KICK.set()
    live_now = m.get("transport") == "live" and m.get("status") in ("running", "waiting_input", "starting", "resuming")
    notes = {"answer": "answered" + ("" if live_now else " — the run resumes in a moment"),
             "reply": "sent to the running agent" if live_now else "sent — the session resumes with it",
             "interrupt": "interrupted — it stops this turn and waits for your message",
             "stop": "stopping (POSIX: graceful, then killed; Windows: killed at once — the session stays resumable)",
             "resume": "queued to resume", "cancel": "cancelled"}
    return {"ok": True, "run_id": rid, "status": m.get("status"), "note": notes[kind]}, 200


def permission_run(body: dict) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    rid = _run_ref(body)
    if not rid:
        return {"error": "invalid run id"}, 400
    n = body.get("n")
    if isinstance(n, bool) or not isinstance(n, (int, str)) or not str(n).strip() or len(str(n)) > 80:
        return {"error": "n must be the request id"}, 400
    try:
        executor.permission_decision(_xlab(), rid, n, bool(body.get("allow")), str(body.get("message") or ""))
    except executor.SpecError as e:
        return {"error": str(e)}, 400
    ctx.pi_log({"action": "run.permission", "run_id": rid, "n": n, "allow": bool(body.get("allow"))})
    return {"ok": True}, 200


def ack_attention(body: dict) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    try:
        rec = executor.attention.ack(_xlab(), str(body.get("id") or ""), str(body.get("action") or "dismiss"))
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"ok": True, "ack": rec}, 200


def resolve_escalation(body: dict) -> tuple[dict, int]:
    """'Mark handled' on an escalation: emit escalation_resolved on the bus that raised it."""
    ref = str(body.get("ref") or "")
    if not re.match(r"^e-[0-9a-f]{6,32}$", ref):
        return {"error": "invalid escalation id"}, 400
    src = str(body.get("source") or "hub")
    bus = ctx.LAB / ".bus" if src in ("hub", "") else ((ctx.pdir(src) / ".bus") if (ctx.safe_id(src) and ctx.pdir(src)) else None)
    if bus is None:
        return {"error": f"unknown source '{src}'"}, 400
    bus.mkdir(parents=True, exist_ok=True)
    with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ctx.ts(), "source": src or "hub",
                            "kind": "escalation_resolved", "detail": "handled by the PI (dashboard)",
                            "data": {"ref": ref}}) + "\n")
    ctx.pi_log({"action": "escalation.resolve", "ref": ref, "source": src})
    return {"ok": True}, 200


def set_programmatic(body: dict) -> tuple[dict, int]:
    """Flip agents.programmatic.enabled in lab/config.yaml (settings.write_config). It widens autonomy, so
    it needs an explicit confirm and is logged."""
    if not body.get("confirm"):
        return {"error": "changing the master switch needs explicit confirm"}, 400
    enabled = bool(body.get("enabled"))
    err = settings.write_config({("agents", "programmatic", "enabled"): enabled})
    if err:
        return {"error": err}, 400
    ctx.pi_log({"action": "executor.enable", "enabled": enabled})
    ctx.KICK.set()
    return {"ok": True, "enabled": enabled,
            "note": ("programmatic launching ON — the dashboard can now start headless sessions"
                     if enabled else "programmatic launching OFF — nothing new starts; running runs finish")}, 200


def run_detail(run_id: str) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    hit = executor.find_run(_xlab(), run_id or "")
    if not hit:
        return {"error": "no such run"}, 404
    target, workdir, path, m = hit
    out = sources._compact_run(m)
    out.update(qa=m.get("qa") or [], attempts=m.get("attempts") or [], args=m.get("args"),
               transcript=str(path.parent / (m.get("stream") or f"{run_id}.stream.jsonl")), cwd=m.get("cwd"))
    return {"ok": True, "run": out}, 200


def _tail_entry(backend: str, obj: dict, labels: dict) -> list[dict]:
    if "_attempt" in obj:
        r = obj.get("resume")
        return [{"k": "attempt", "t": f"— attempt {obj['_attempt']}" + (f" ({r})" if r else "") + " —",
                 "ts": obj.get("ts")}]
    if "_truncated" in obj:
        return [{"k": "raw", "t": obj["_truncated"]}]
    if "_pi" in obj:   # what the PI said to a live session (written by the supervisor)
        kind = obj["_pi"]
        if kind == "message":
            t = obj.get("text") or ""
        elif kind == "answer":
            t = "; ".join(f"{k} → {', '.join(v) if isinstance(v, list) else v}" for k, v in (obj.get("answers") or {}).items())
            t = (t + (" — " if t else "") + (obj.get("response") or "")).strip()
        else:
            t = f"{'allowed' if obj.get('allow') else 'denied'} {obj.get('tool') or 'the action'}"
        by = obj.get("by") or "PI"
        return [{"k": "you", "t": t[:4000], "by": "you" if by == "PI" else by, "kind": kind, "ts": obj.get("ts")}]
    out = []
    for ev in executor.backends.parse_events(backend, obj):
        who = labels.get(ev.get("parent")) if ev.get("parent") else None
        e = ev.get("event")
        if e == "text":
            out.append({"k": "text", "t": ev["text"][:4000], "who": who})
        elif e == "action":
            out.append({"k": "tool", "tool": ev.get("tool"), "t": ev.get("summary") or "", "who": who})
        elif e == "tool_result":
            if ev.get("tool_use_id") in labels:
                out.append({"k": "sub", "t": (ev.get("text") or "")[:2000], "who": labels[ev["tool_use_id"]]})
            elif ev.get("is_error"):
                out.append({"k": "err", "t": (ev.get("text") or "")[:600], "who": who})
        elif e == "result":
            stop = ev.get("stop_reason")
            out.append({"k": "end", "t": (ev.get("last_message") or "")[:4000], "stop": stop,
                        "cost": ev.get("cost_usd")})
        elif e == "start":
            out.append({"k": "start", "t": f"session {str(ev.get('session_id') or '')[:8]} started"})
        elif e == "denied":
            out.append({"k": "err", "t": f"denied: {ev.get('tool')}"})
    return out


def run_tail(run_id: str, offset: int = 0) -> tuple[dict, int]:
    """New transcript lines since byte `offset`, compacted for display. Whole lines only; a first
    call on a big transcript starts near the end. The raw transcript never leaves this machine."""
    if executor is None:
        return ctx.no_executor()
    hit = executor.find_run(_xlab(), run_id or "")
    if not hit:
        return {"error": "no such run"}, 404
    target, workdir, path, m = hit
    stream = path.parent / (m.get("stream") or f"{run_id}.stream.jsonl")
    cap = int((ctx.config().get("dashboard") or {}).get("tail_max_kb") or 64) * 1024
    try:
        size = stream.stat().st_size
    except OSError:
        return {"ok": True, "offset": 0, "eof": True, "status": m.get("status"), "lines": []}, 200
    skipped = 0
    if offset <= 0 and size > cap * 4:
        offset = skipped = size - cap * 4
    offset = max(0, min(int(offset), size))
    with stream.open("rb") as f:
        f.seek(offset)
        chunk = f.read(cap)
    if skipped:   # align to the next full line
        nl = chunk.find(b"\n")
        chunk, offset = (chunk[nl + 1:], offset + nl + 1) if nl >= 0 else (b"", offset)
    end = chunk.rfind(b"\n")
    chunk = chunk[:end + 1] if end >= 0 else b""
    new_offset = offset + len(chunk)
    labels = {k: f"{v.get('type')}" + (f" · {v['description'][:40]}" if v.get("description") else "")
              for k, v in (m.get("subagents") or {}).items()}
    lines = []
    for raw in chunk.decode("utf-8", "replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            lines.append({"k": "raw", "t": raw[:600]})
            continue
        if isinstance(obj, dict):
            lines += _tail_entry(m.get("backend") or "claude", obj, labels)
    return {"ok": True, "offset": new_offset, "eof": new_offset >= size, "status": m.get("status"),
            "skipped": skipped or None, "lines": lines}, 200


def run_log(run_id: str) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    hit = executor.find_run(_xlab(), run_id or "")
    if not hit:
        return {"error": "no such run"}, 404
    _t, _w, path, m = hit
    log = path.parent / f"{m.get('run_id') or run_id}.d" / "supervisor.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")[-8000:]
    except OSError:
        text = ""
    return {"ok": True, "text": text}, 200


def executor_health(fresh: bool = False) -> tuple[dict, int]:
    if executor is None:
        return {"available": False, "enabled": False}, 200
    if fresh:   # "check again" after a sign-in
        sources.recheck_executor(cli=True)
    h = executor.health(_xlab())
    h["available"] = True
    h["thread_alive"] = bool(_SCHED.get("thread") and _SCHED["thread"].is_alive())
    return h, 200


def command_launch(target: str, action: str, args: dict, text: str) -> dict | None:
    """The run a dashboard command should start when the executor is on (None = directive only)."""
    skill = COMMAND_TO_RUN.get(action)
    if not skill or executor is None:
        return None
    body = {"skill": skill, "target": target or "hub", "confirm": True}
    if action == "ideate":
        if target not in ("hub", "", None) and ctx.pdir(target):
            body["args"] = f"--in-project {target}"
        else:
            body["target"], body["args"] = "hub", str((args or {}).get("direction") or "")
    out, code = launch_run(body, by=f"command:{action}")
    return out


def command_stop_loop(target: str) -> list[str]:
    """stop_loop also stops any live /research-loop run on that project (the directive still goes out)."""
    if executor is None:
        return []
    stopped = []
    lab = _xlab()
    for m in executor.list_runs(lab):
        if m.get("skill") == "research-loop" and m.get("target") == target and m.get("status") in executor.ACTIVE:
            try:
                executor.stop(lab, m["run_id"], by="command:stop_loop")
                stopped.append(m["run_id"])
            except executor.SpecError:
                pass
    return stopped


_SCHED: dict = {"thread": None, "stop": None}


_SCHED_HUBS: set = set()   # labs opened in this server session: their queues keep moving after a switch
ctx.on_change(lambda old, new: _SCHED_HUBS.update({old, new}))


def start_scheduler() -> bool:
    """The executor's scheduler loop, in a daemon thread. Runs never depend on it (each has its own
    supervisor); it only starts queued runs, reconciles, and post-processes finished ones."""
    if executor is None or (_SCHED["thread"] and _SCHED["thread"].is_alive()):
        return False
    stop = threading.Event()
    os.environ["NEWTS_TICKER"] = "dashboard"
    from executor import awake  # noqa: PLC0415

    def loop():
        while not stop.is_set():
            busy = False
            for hub in [ctx.HUB, *[h for h in list(_SCHED_HUBS) if h != ctx.HUB]]:
                try:
                    lab = executor.Lab(hub)
                    executor.tick(lab)
                    busy = executor.scheduler.has_work(lab) or busy
                except Exception:  # noqa: BLE001 — one bad pass must never kill the loop
                    pass
            try:   # keep the computer awake while any lab this server schedules is working
                if busy and awake.enabled(executor.Lab(ctx.HUB)):
                    awake.hold("the lab is working")
                else:
                    awake.release()
            except Exception:  # noqa: BLE001
                pass
            ctx.KICK.wait(2.0)
            ctx.KICK.clear()

    t = threading.Thread(target=loop, name="executor-scheduler", daemon=True)
    _SCHED.update(thread=t, stop=stop)
    t.start()
    return True


def run_tool(name: str, idea: str | None = None) -> dict:
    if name not in SAFE_TOOLS:
        return {"error": f"tool '{name}' is not in the read-only whitelist"}
    py = sys.executable
    pdir = ctx.pdir(idea) if idea else None
    cmd, cwd = None, ctx.HUB
    if name == "check_lab":
        cmd = [py, str(ctx.HUB / "tools" / "check_lab.py")]
    elif name == "show_config":
        cmd = [py, str(ctx.HUB / "tools" / "show_config.py")] + ([str(pdir)] if pdir else [])
    elif name == "slots":
        cmd = [py, str(ctx.HUB / "tools" / "run_slots.py"), "status"]
    elif name == "audit_claims":
        s = ctx.slug(idea or "")
        if not s:
            return {"error": "audit_claims needs an idea slug"}
        rel_tol = (ctx.config().get("critique") or {}).get("claim_rel_tol", 1e-3)
        cmd = [py, str(ctx.HUB / "tools" / "audit_claims.py"), f"studies/{s}/paper", "--rel-tol", str(rel_tol)]
    elif name == "inbox":
        if pdir:
            cmd, cwd = [py, str(pdir / "scripts" / "lab_bus.py"), "inbox"], pdir
        else:
            cmd = [py, str(ctx.HUB / "tools" / "lab_bus.py"), "inbox"]
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


def handoff_scheduler() -> None:
    """The dashboard is going away: if any lab it scheduled still has queued runs or a campaign to keep, hand
    the scheduling to a detached `executor_cli serve --until-idle` so the work doesn't stall."""
    if executor is None:
        return
    for hub in {ctx.HUB, *_SCHED_HUBS}:
        try:
            lab = executor.Lab(hub)
            if executor.scheduler.has_work(lab):
                (lab.lab / ".bus" / "scheduler.lease").unlink(missing_ok=True)   # our lease ends with us
                if executor.scheduler.ensure_ticker(lab):
                    print(f"  work is still queued for {hub.name} — a background scheduler keeps it going")
        except Exception:  # noqa: BLE001
            pass


def command_post(body: dict) -> tuple[dict, int]:
    """A structured command on a bus (bus.COMMAND_ACTIONS) — and, with `launch`, the run that consumes it."""
    action = body.get("action")
    if action not in COMMAND_ACTIONS:
        return {"error": f"unknown action (allowed: {sorted(COMMAND_ACTIONS)})"}, 400
    try:
        rec = append_command(body.get("target", "hub"), action, body.get("args") or {}, body.get("text") or "")
    except ValueError as e:
        return {"error": str(e)}, 400
    out = {"ok": True, "command": rec}
    if body.get("launch"):   # also START the procedure that consumes it (executor on)
        if action == "stop_loop":
            out["stopped"] = command_stop_loop(rec.get("target") or "hub")
        else:
            out["launch"] = command_launch(rec.get("target") or "hub", action, body.get("args") or {},
                                           body.get("text") or "")
    return out, 200
