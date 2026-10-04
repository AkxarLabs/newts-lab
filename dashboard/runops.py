"""Headless runs from the dashboard: launch, answer, reply, stop, the live transcript, the executor
settings switch, and the bus commands that start a procedure. (The scheduler thread is ticker.py.)
"""

from __future__ import annotations

import json
from pathlib import Path

import ctx  # noqa: E402
import settings  # noqa: E402
from bus import COMMAND_ACTIONS, append_command  # noqa: E402
import sources  # noqa: E402
import workers  # noqa: E402
import attention  # noqa: E402
import ticker  # noqa: E402

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


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


def lab_pause(body: dict) -> tuple[dict, int]:
    """POST /api/lab/pause {paused: true|false, confirm: true} → {ok, paused, stopped: [run ids], note}.
    Pausing stops every live run (resumable) and starts nothing — no queued run, no campaign pass, no chain or
    repeat — until the PI resumes; campaigns the pause paused carry on then. Idempotent; logged."""
    if executor is None:
        return ctx.no_executor()
    if not isinstance(body.get("paused"), bool):
        return {"error": "say paused: true (pause the lab) or paused: false (resume it)"}, 400
    if not body.get("confirm"):
        return {"error": "pausing or resuming the lab needs explicit confirm"}, 400
    lab = _xlab()
    try:
        if body["paused"]:
            out = executor.pause.pause(lab, by="PI (dashboard)", reason=str(body.get("reason") or "") or None)
        else:
            out = executor.pause.resume(lab, by="PI (dashboard)")
    except (executor.SpecError, OSError, TimeoutError) as e:
        return {"error": str(e)}, 400
    stopped = out.get("stopped") or []
    ctx.pi_log({"action": "lab.pause" if body["paused"] else "lab.resume", "already": out.get("already"),
                "stopped": stopped, "campaigns": out.get("campaigns")})
    ctx.KICK.set()
    camps = out.get("campaigns") or []
    if body["paused"]:
        note = ("the lab was already paused" if out.get("already") else "the lab is paused") + " — nothing new starts"
        note += f"; stopped {len(stopped)} running agent(s) (each can be resumed)" if stopped else "; no agent was running"
        note += f"; {len(camps)} campaign(s) paused" if camps else ""
        note += "; queued runs wait until you resume"
    else:
        note = "the lab was not paused" if out.get("already") else "the lab is running again — queued runs start now"
        note += f"; {len(camps)} campaign(s) carry on" if camps else ""
        left = out.get("stopped_earlier") or []
        note += f"; the {len(left)} run(s) the pause stopped stay stopped — resume them from their cards" if left else ""
    return {"ok": True, "paused": bool(body["paused"]), "stopped": stopped, "note": note,
            "campaigns": camps, "already": bool(out.get("already"))}, 200


def run_detail(run_id: str) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    hit = executor.find_run(_xlab(), run_id or "")
    if not hit:
        return {"error": "no such run"}, 404
    target, workdir, path, m = hit
    out = workers.compact_run(m)
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
        attention.recheck_executor(cli=True)
    h = executor.health(_xlab())
    h["available"] = True
    h["thread_alive"] = ticker.alive()
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


# ── what a run wrote: the files its Write/Edit/patch actions touched, for the run sheet to open ─────────
_TEXT_KINDS = {".md": "md", ".markdown": "md", ".txt": "text", ".log": "text", ".json": "text", ".yaml": "text",
               ".yml": "text", ".py": "text", ".tex": "text", ".csv": "text", ".toml": "text", ".sh": "text"}
_IMG = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def _written(run_id: str) -> tuple[list[Path], dict] | None:
    hit = executor.find_run(_xlab(), run_id or "") if executor else None
    if not hit:
        return None
    target, workdir, path, m = hit
    stream = path.parent / (m.get("stream") or f"{run_id}.stream.jsonl")
    base = Path(m.get("cwd") or workdir)
    seen: dict[str, Path] = {}
    try:
        with stream.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                for ev in executor.backends.parse_events(m.get("backend") or "claude", obj):
                    for p in ev.get("files") or []:
                        fp = Path(p) if Path(p).is_absolute() else base / p
                        seen.setdefault(str(fp.resolve()), fp.resolve())
    except OSError:
        pass
    return list(seen.values()), m


def run_files(q: dict) -> tuple[dict, int]:
    if executor is None:
        return ctx.no_executor()
    got = _written(q.get("run_id", ""))
    if got is None:
        return {"error": "no such run"}, 404
    files, m = got
    out = []
    for fp in files:
        ex = fp.is_file()
        out.append({"path": str(fp), "name": fp.name, "exists": ex, "size": fp.stat().st_size if ex else 0,
                    "kind": _TEXT_KINDS.get(fp.suffix.lower()) or ("image" if fp.suffix.lower() in _IMG else
                                                                  "pdf" if fp.suffix.lower() == ".pdf" else "other")})
    return {"ok": True, "files": out}, 200


def _allowed(q: dict) -> Path | None:
    """Only a file this run itself wrote (by its own transcript) — never an arbitrary path."""
    got = _written(q.get("run_id", "")) if executor else None
    if not got:
        return None
    want = str(Path(q.get("path") or "").resolve()) if q.get("path") else ""
    return next((fp for fp in got[0] if str(fp) == want and fp.is_file()), None)


def run_file(q: dict) -> tuple[dict, int]:
    """GET /api/run/file?run_id=&path= → the text of a file the run wrote (Markdown is rendered by the page)."""
    fp = _allowed(q)
    if not fp:
        return {"error": "not a file this run wrote"}, 404
    if fp.suffix.lower() not in _TEXT_KINDS:
        return {"error": "not a text file"}, 400
    return {"ok": True, "path": str(fp), "kind": _TEXT_KINDS[fp.suffix.lower()],
            "text": fp.read_text(encoding="utf-8", errors="replace")[:400_000]}, 200


def run_file_raw(q: dict):
    """FILE route for an image or a PDF the run wrote."""
    fp = _allowed(q)
    if not fp:
        return None
    ct = _IMG.get(fp.suffix.lower()) or ("application/pdf" if fp.suffix.lower() == ".pdf" else None)
    return (fp, ct) if ct else None
