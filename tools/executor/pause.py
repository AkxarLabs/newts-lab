"""Pause the lab — one switch that stops everything.

  pause(lab)   write lab/.bus/paused.json {since, by, reason}; mark every running campaign "paused by the lab";
               then stop every live run (the same resumable stop as the per-run Stop). Queued runs stay queued.
  resume(lab)  clear the flag; campaigns the pause paused carry on (only those); queued runs start again on
               the next tick. Runs the pause stopped are NOT restarted (each can be resumed from its card).

While the flag is set `scheduler.tick()` starts nothing: no queued run, no campaign pass or dispatch, no
chain / repeat follow-up (finished runs are post-processed after the resume). Both calls are idempotent
and leave an event on the hub bus (`lab_paused` / `lab_resumed`).
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from .lab import Lab
from .manifest import ACTIVE, PAUSED, all_runs, emit, now, run_dir, scheduler_lock
from .procs import is_locked
from .spec import SpecError


def flag_path(lab: Lab) -> Path:
    return lab.lab / ".bus" / "paused.json"


def state(lab: Lab) -> dict | None:
    """{since, by, reason, stopped} while the lab is paused, else None."""
    try:
        d = json.loads(flag_path(lab).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else {"since": None, "by": None}


def is_paused(lab: Lab) -> bool:
    return flag_path(lab).exists()


def _write(lab: Lab, d: dict) -> None:
    p = flag_path(lab)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _running(path, m: dict) -> bool:
    """A run with an agent process behind it: active, or a live session waiting on the PI. (A parked
    question has no process and stays in Needs you; a queued run stays queued.)"""
    st = m.get("status")
    if st in ACTIVE:
        return True
    if st in PAUSED and m.get("transport") == "live":
        return is_locked(run_dir(Path(path).parent, m.get("run_id") or "") / "lock")
    return False


def pause(lab: Lab, by: str = "PI", reason: str | None = None) -> dict:
    """Pause the lab. Returns {paused: True, already, since, stopped: [run ids], campaigns: [names]}."""
    from . import campaigns   # noqa: PLC0415
    from .runs import stop as stop_run   # noqa: PLC0415
    with scheduler_lock(lab):
        cur = state(lab)
        already = cur is not None
        live = [(p, m) for _t, _w, p, m in all_runs(lab) if _running(p, m)]
        ids = [m["run_id"] for _p, m in live if m.get("run_id")]
        if not already:
            cur = {"since": now(), "by": by, "reason": (reason or "").strip()[:300] or None, "stopped": []}
        cur["stopped"] = list(dict.fromkeys((cur.get("stopped") or []) + ids))[-200:]
        _write(lab, cur)
        paused_camps = []
        for st in campaigns.all_states(lab):
            name = st.get("name")
            mine = [m["run_id"] for _p, m in live if m.get("campaign") == name]
            if st.get("status") in ("active", "finishing", "stopping") and not st.get("paused_by_lab"):
                st.update(lab_paused_from=st["status"], status="paused", paused_by_lab=True,
                          paused_reason="the whole lab is paused")
                campaigns._event(st, "paused with the lab")   # noqa: SLF001
                paused_camps.append(name)
            if mine and st.get("paused_by_lab"):
                st["lab_pause_stopped"] = list(dict.fromkeys((st.get("lab_pause_stopped") or []) + mine))[-100:]
            if name in paused_camps or (mine and st.get("paused_by_lab")):
                campaigns.save(lab, st)
    stopped = []
    for _p, m in live:   # outside the lock: stop() takes it itself
        try:
            stop_run(lab, m["run_id"], by="lab-pause")
            stopped.append(m["run_id"])
        except (SpecError, OSError):
            pass
    if not already or stopped:
        emit(lab, lab.hub, "lab_paused", detail=f"the lab was paused by {by}" + (f" — stopped {len(stopped)} run(s)" if stopped else ""),
             data={"by": by, "stopped": stopped, "campaigns": paused_camps, "reason": cur.get("reason")})
    return {"paused": True, "already": already, "since": cur.get("since"), "by": cur.get("by"),
            "stopped": stopped, "campaigns": paused_camps}


def resume(lab: Lab, by: str = "PI") -> dict:
    """Resume the lab. Returns {paused: False, already, campaigns: [names resumed], stopped_earlier: [...]}."""
    from . import campaigns   # noqa: PLC0415
    with scheduler_lock(lab):
        cur = state(lab)
        already = cur is None
        with contextlib.suppress(FileNotFoundError):
            flag_path(lab).unlink()
        resumed = []
        for st in campaigns.all_states(lab):
            if not st.get("paused_by_lab"):
                continue
            back = st.get("lab_paused_from") or "active"
            st.update(status=back if st.get("status") == "paused" else st.get("status"), paused_by_lab=False,
                      lab_paused_from=None, paused_reason=None, next_cycle_at=None)
            campaigns._event(st, "resumed with the lab")   # noqa: SLF001
            campaigns.save(lab, st)
            resumed.append(st.get("name"))
    if not already:
        emit(lab, lab.hub, "lab_resumed", detail=f"the lab was resumed by {by}", data={"by": by, "campaigns": resumed})
    return {"paused": False, "already": already, "campaigns": resumed,
            "stopped_earlier": list((cur or {}).get("stopped") or [])}
