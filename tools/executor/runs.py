"""The run queue — every PI-facing mutation of a run.

  enqueue(lab, RunSpec)            validate + write a queued manifest (the scheduler starts it)
  answer(lab, run_id, answers)     answer a pending AskUserQuestion → queued (resume, mode=answer)
  reply(lab, run_id, text)         free-text follow-up → queued (resume, mode=reply)
  resume(lab, run_id)              continue an interrupted/finished session → queued (mode=continue)
  cancel(lab, run_id)              a queued run → killed (cancelled)
  stop(lab, run_id)                stop a live run (the supervisor does a graceful stop), or cancel

Everything but `enqueue` runs under the scheduler lock, so a tick can never race a PI action.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import backends
from .lab import HUB_TARGET, Lab, pos_float, pos_int
from .manifest import (ACTIVE, PAUSED, RESUMABLE, SCHEMA, TERMINAL, all_runs, emit, find_run,
                       new_run_id, now, parse_ts, run_dir, safe_id, scheduler_lock, transition)
from .procs import is_locked, kill_tree
from .spec import ASK, RunSpec, SpecError, SKILL_REGISTRY, ask_label, preamble, render_prompt, slash_command, validate

MAX_ANSWER_BYTES = 4096
MAX_REPLY_CHARS = 4000


def _depth_now() -> int:
    return pos_int(os.environ.get("AUTOSCIENTIST_AGENT_DEPTH", "0") or 0, 0, 0)


def check_enabled(lab: Lab) -> dict:
    """Raise SpecError unless this process may create runs: the PI-owned master switch and the
    launch-depth cap (a launched agent may not launch more). Returns the programmatic config."""
    prog = lab.prog()
    if not prog.get("enabled"):
        raise SpecError("programmatic launching is off (agents.programmatic.enabled: false) — it is a "
                        "PI-owned opt-in; enable it from the dashboard settings or /configure")
    max_depth = pos_int(prog.get("max_depth", 1), 1, 0)
    if _depth_now() >= max_depth:
        raise SpecError(f"launch depth {_depth_now()} >= max_depth {max_depth} — a launched agent may not "
                        "launch further agents; only the top-level orchestrator (the PI) launches")
    return prog


def enqueue(lab: Lab, spec: RunSpec) -> dict:
    prog = check_enabled(lab)
    v = validate(lab, spec)
    backend = spec.backend or prog.get("backend") or "claude"
    if backend not in backends.BACKENDS and backend != "_dummy":
        raise SpecError(f"unknown backend '{backend}' (claude | codex | opencode)")
    bcfg = (prog.get("backends") or {}).get(backend) or {}
    if not backends.resolve_cli(backend, bcfg):
        raise SpecError(f"the {backend} CLI was not found on this machine — install it, or point "
                        f"agents.programmatic.backends.{backend}.command at it")
    adir = lab.agents_dir(v["workdir"])
    base = f"{v['target']}-{v['skill'] or 'run'}-{time.strftime('%Y%m%d-%H%M%S')}"
    run_id, mpath = new_run_id(adir, base)
    rd = run_dir(adir, run_id)
    rd.mkdir(parents=True, exist_ok=True)
    is_ask = v["skill"] == ASK
    prompt = v["prompt"] if is_ask else (spec.prompt_override or render_prompt(lab, v, backend))
    (rd / "prompt.md").write_text(prompt, encoding="utf-8")
    (rd / "preamble.md").write_text(preamble(lab, run_id, v, backend), encoding="utf-8")
    max_minutes = pos_float(spec.max_minutes, 0.0) or pos_float(prog.get("max_minutes"), 240.0) or 240.0
    m = {
        "schema": SCHEMA, "run_id": run_id, "agent_id": run_id,
        "target": v["target"], "subject": v["subject"], "level": v["level"],
        "cwd": str(v["workdir"]), "project": lab.source_of(v["workdir"]),
        "skill": v["skill"], "args": v["args"], "mode": v["cfg"].get("mode"),
        "command": (None if is_ask else slash_command(v)) if v["skill"] else None,
        "kind": "ask" if is_ask else "procedure", "gate3_signed": bool(v.get("gate3_signed")),
        "prompt_summary": prompt.strip()[:200],
        "backend": backend, "model": spec.model or None, "effort": spec.effort or None,
        "permission_mode": spec.permission_mode or None,
        "max_minutes": max_minutes, "max_turns": spec.max_turns,
        "role": spec.role or "orchestrator", "label": spec.label or (ask_label(prompt) if is_ask else v["skill"]),
        "parent": spec.parent, "campaign": spec.campaign, "priority": int(spec.priority or 0),
        "created_by": spec.created_by, "created": now(), "depth": _depth_now(),
        "chain": spec.chain, "chain_step": int(spec.extra.get("chain_step") or 0),
        "repeat_minutes": spec.repeat_minutes, "max_repeats": spec.max_repeats,
        "repeat_index": int(spec.extra.get("repeat_index") or 0),
        "not_before": spec.extra.get("not_before"),
        "status": None, "attempt": 0, "attempts": [], "session_id": None,
        "stream": f"{run_id}.stream.jsonl", "pid": None, "supervisor_pid": None,
        "started": None, "finished": None, "wall_seconds": None, "exit_code": None,
        "last_message": None, "last_action": None, "n_actions": 0, "pending_question": None,
        "answers_given": 0, "denials": 0, "report": None, "usage": {}, "subagents": {},
    }
    transition(lab, mpath, m, "queued", by=spec.created_by or "cli")
    return {**m, "position": queue_position(lab, run_id)}


def queue_position(lab: Lab, run_id: str) -> int:
    queued = sorted((m for _, _, _, m in all_runs(lab) if m.get("status") == "queued"),
                    key=lambda m: (-int(m.get("priority") or 0), m.get("created") or ""))
    for i, m in enumerate(queued, 1):
        if m.get("run_id") == run_id:
            return i
    return 0


def _clear_stop(path: Path, run_id: str) -> None:
    stop = run_dir(Path(path).parent, run_id) / "stop"
    if stop.exists():
        try:
            stop.unlink()
        except OSError:
            pass


def _locate(lab: Lab, run_id: str):
    hit = find_run(lab, run_id)
    if not hit:
        raise SpecError(f"no run '{run_id}'")
    return hit


def _validate_answers(answers) -> dict:
    if not isinstance(answers, dict) or not answers:
        raise SpecError("answers must be a non-empty {question text: answer} object")
    clean = {}
    for k, val in answers.items():
        if not isinstance(k, str) or not k.strip():
            raise SpecError("every answer key must be the question text")
        if isinstance(val, list):
            if not all(isinstance(x, str) for x in val):
                raise SpecError("multi-select answers must be a list of labels")
            val = [x.strip() for x in val if x.strip()]
        elif isinstance(val, str):
            val = val.strip()
        else:
            raise SpecError("each answer must be a label, free text, or a list of labels")
        clean[k] = val
    if len(json.dumps(clean)) > MAX_ANSWER_BYTES:
        raise SpecError("answers too long")
    return clean


def answer(lab: Lab, run_id: str, answers: dict | None = None, response: str | None = None,
           by: str = "dashboard") -> dict:
    """Answer the run's pending question and queue the resume. `response` alone = a free-form
    reply instead of picking options (Claude receives "The user responded: …")."""
    with scheduler_lock(lab):
        target, workdir, path, m = _locate(lab, run_id)
        if m.get("status") not in PAUSED or not m.get("pending_question"):
            raise SpecError(f"run {run_id} is not waiting for an answer (status {m.get('status')})")
        clean = _validate_answers(answers) if answers else {}
        response = (response or "").strip()[:MAX_REPLY_CHARS]
        if not clean and not response:
            raise SpecError("give an answer (pick options or type a reply)")
        rd = run_dir(Path(path).parent, run_id)
        pq = m["pending_question"]
        rec = {"ts": now(), "tool_use_id": pq.get("tool_use_id"), "answers": clean}
        if response:
            rec["response"] = response
        rd.mkdir(parents=True, exist_ok=True)
        tmp = rd / "answer.json.tmp"
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        os.replace(tmp, rd / "answer.json")
        history = m.setdefault("qa", [])
        history.append({"asked_at": pq.get("asked_at"), "question": pq.get("input"),
                        "answers": clean, "response": response or None, "answered_at": rec["ts"]})
        m["qa"] = history[-20:]
        mode = "answer"
        text = None
        if m.get("backend") != "claude":   # no defer hook: the answer rides a plain reply
            mode, text = "reply", _answers_as_text(pq, clean, response)
        _clear_stop(path, run_id)
        transition(lab, path, m, "queued", by=by, reason="answered", pending_question=None,
                   answers_given=int(m.get("answers_given") or 0) + 1, resume={"mode": mode, "text": text},
                   not_before=None)
        emit(lab, workdir, "note", detail=f"PI answered {run_id}", data={"run_id": run_id, "kind": "answer"})
        return m


def _answers_as_text(pq: dict, answers: dict, response: str) -> str:
    lines = ["The PI answered your question:"]
    for k, v in answers.items():
        lines.append(f"- {k}: {', '.join(v) if isinstance(v, list) else v}")
    if response:
        lines.append(response)
    return "\n".join(lines)


def reply(lab: Lab, run_id: str, text: str, by: str = "dashboard") -> dict:
    """A free-text message to a paused or finished run — resumes the same session with it as the
    next user turn. On a run waiting at an AskUserQuestion it becomes that question's reply."""
    text = (text or "").strip()
    if not text:
        raise SpecError("empty reply")
    if len(text) > MAX_REPLY_CHARS:
        raise SpecError(f"reply too long (max {MAX_REPLY_CHARS} chars)")
    hit = _locate(lab, run_id)
    if hit[3].get("status") in PAUSED and hit[3].get("pending_question"):
        return answer(lab, run_id, None, text, by=by)
    check_enabled(lab)
    with scheduler_lock(lab):
        target, workdir, path, m = _locate(lab, run_id)
        if m.get("status") not in RESUMABLE:
            raise SpecError(f"run {run_id} is {m.get('status')} — reply once it has paused or finished")
        if not m.get("session_id"):
            raise SpecError(f"run {run_id} has no session to continue")
        _clear_stop(path, run_id)
        transition(lab, path, m, "queued", by=by, reason="reply", resume={"mode": "reply", "text": text},
                   post_processed=False, not_before=None)
        return m


def resume(lab: Lab, run_id: str, by: str = "dashboard") -> dict:
    check_enabled(lab)
    with scheduler_lock(lab):
        target, workdir, path, m = _locate(lab, run_id)
        if m.get("status") not in TERMINAL:
            raise SpecError(f"run {run_id} is {m.get('status')} — only a finished/failed/stopped run resumes")
        if not m.get("session_id"):
            raise SpecError(f"run {run_id} never got a session id — start a new run instead")
        _clear_stop(path, run_id)
        transition(lab, path, m, "queued", by=by, reason="resume", resume={"mode": "continue"},
                   post_processed=False, not_before=None)
        return m


def cancel(lab: Lab, run_id: str, by: str = "dashboard") -> dict:
    with scheduler_lock(lab):
        target, workdir, path, m = _locate(lab, run_id)
        if m.get("status") != "queued":
            raise SpecError(f"run {run_id} is {m.get('status')} — only a queued run can be cancelled")
        transition(lab, path, m, "killed", by=by, reason="cancelled", finished=now())
        return m


def stop(lab: Lab, run_id: str, by: str = "dashboard") -> dict:
    """Stop a run. Queued → cancelled. Active → the supervisor sees the stop marker and stops the
    child (POSIX: SIGTERM then kill after a grace period; Windows: hard tree kill — the session
    stays resumable either way). A dead supervisor → kill the pid directly and record it."""
    hit = _locate(lab, run_id)
    if hit[3].get("status") == "queued":
        return cancel(lab, run_id, by=by)
    with scheduler_lock(lab):
        target, workdir, path, m = _locate(lab, run_id)
        st = m.get("status")
        if st in PAUSED:
            transition(lab, path, m, "killed", by=by, reason="stopped while waiting for the PI",
                       finished=now(), pending_question=None)
            return m
        if st not in ACTIVE:
            raise SpecError(f"run {run_id} is not running (status {st})")
        rd = run_dir(Path(path).parent, run_id)
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "stop").write_text(now(), encoding="utf-8")
        age = time.time() - (parse_ts(m.get("status_ts")) or 0)
        if st in ("starting", "resuming") and age < 60:
            return m   # its supervisor is still coming up: it finds the marker and records the stop
        if not is_locked(rd / "lock"):
            if m.get("pid"):
                kill_tree(m["pid"])
            transition(lab, path, m, "killed", by=by, reason="stopped by the PI (supervisor gone)",
                       finished=now(), pid=None)
        return m


def list_runs(lab: Lab, limit: int | None = None) -> list[dict]:
    runs = [m for _, _, _, m in all_runs(lab)]
    runs.sort(key=lambda m: m.get("created") or m.get("started") or "", reverse=True)
    return runs[:limit] if limit else runs


def permission_decision(lab: Lab, run_id: str, n: int, allow: bool, message: str = "",
                        by: str = "dashboard") -> dict:
    """The PI's decision on a pending permission request (only when permission_wait_seconds > 0)."""
    target, workdir, path, m = _locate(lab, run_id)
    rd = run_dir(Path(path).parent, run_id)
    req = rd / f"perm-{int(n)}.json"
    if not req.exists():
        raise SpecError("no such permission request")
    dec = rd / f"perm-{int(n)}.decision.json"
    if dec.exists():
        raise SpecError("that request was already decided")
    dec.write_text(json.dumps({"allow": bool(allow), "message": message[:500], "ts": now(), "by": by}),
                   encoding="utf-8")
    return {"ok": True}


__all__ = ["enqueue", "answer", "reply", "resume", "cancel", "stop", "list_runs", "queue_position",
           "check_enabled", "permission_decision", "SKILL_REGISTRY", "HUB_TARGET", "safe_id"]
