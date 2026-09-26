"""Newts' Lab executor — launch, supervise, pause/answer, resume, and stop headless agent runs.

The dashboard is one client of this package; `tools/executor_cli.py` is another; agent_runner.py's
blocking `launch` reuses its drain loop. Deleting dashboard/ changes nothing here.

    from executor import Lab, RunSpec, enqueue, tick
    lab = Lab()                                   # this hub (or Lab(path) for another)
    enqueue(lab, RunSpec(skill="propose", target="my-idea", created_by="cli"))
    tick(lab)                                     # starts it in a detached supervisor

See docs/dashboard.md ("Running procedures") and docs/autonomy.md for the model.
"""

from __future__ import annotations

import os

from . import attention, backends
from .lab import HUB_TARGET, Lab
from .manifest import ACTIVE, PAUSED, RESUMABLE, STATUSES, TERMINAL, all_runs, find_run, ledger
from .runs import (answer, cancel, check_enabled, enqueue, list_runs, permission_decision,
                   queue_position, reply, resume, stop)
from .scheduler import brake, caps, daily_usage, last_tick, reconcile, tick, tick_loop
from .spec import NEVER, SKILL_REGISTRY, RunSpec, SpecError
from .supervise import supervise as run_supervisor


def health(lab: Lab) -> dict:
    """What the dashboard badge shows: is launching possible, which CLIs exist, caps, load."""
    prog = lab.prog()
    runs = [m for *_x, m in all_runs(lab)]
    clis = {}
    for b in backends.BACKENDS:
        bcfg = (prog.get("backends") or {}).get(b) or {}
        pre = backends.resolve_cli(b, bcfg)
        ver = backends.cli_version(pre) if (pre and b == prog.get("backend", "claude")) else None
        clis[b] = {"found": bool(pre), "path": (pre[-1] if pre else None), "version": backends.version_str(ver),
                   "shim": bool(pre and os.name == "nt" and pre[-1].lower().endswith((".cmd", ".bat")))}
    return {
        "enabled": bool(prog.get("enabled")),
        "backend": prog.get("backend") or "claude",
        "permission_mode": prog.get("permission_mode") or "auto",
        "clis": clis,
        "caps": caps(lab),
        "daily": daily_usage(runs),
        "brake": brake(lab, runs),
        "active": sum(1 for m in runs if m.get("status") in ACTIVE),
        "queued": sum(1 for m in runs if m.get("status") == "queued"),
        "waiting": sum(1 for m in runs if m.get("status") in PAUSED),
        "last_tick": last_tick(lab),
    }


__all__ = [
    "Lab", "HUB_TARGET", "RunSpec", "SpecError", "SKILL_REGISTRY", "NEVER",
    "enqueue", "answer", "reply", "resume", "cancel", "stop", "list_runs", "queue_position",
    "check_enabled", "permission_decision", "tick", "tick_loop", "reconcile", "run_supervisor",
    "caps", "brake", "daily_usage", "last_tick", "health", "attention", "backends",
    "find_run", "all_runs", "ledger", "ACTIVE", "PAUSED", "RESUMABLE", "TERMINAL", "STATUSES",
]
