"""Newts' Lab executor — launch, supervise, pause/answer, resume, and stop headless agent runs.

The dashboard is one client of this package; `tools/executor_cli.py` is another. Deleting
dashboard/ changes nothing here.

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
from .runs import (answer, cancel, check_enabled, enqueue, interrupt, list_runs, permission_decision,
                   queue_position, reply, resume, stop)
from .scheduler import brake, caps, daily_usage, last_tick, reconcile, tick, tick_loop
from .spec import NEVER, SKILL_REGISTRY, RunSpec, SpecError
from .supervise import supervise as run_supervisor


_ENV_AUTH = {"claude": ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                         "CLAUDE_CODE_USE_FOUNDRY"),
             "codex": ("CODEX_API_KEY", "OPENAI_API_KEY")}


def health(lab: Lab) -> dict:
    """What the dashboard badge shows: is launching possible, which CLIs exist, caps, load."""
    prog = lab.prog()
    runs = [m for *_x, m in all_runs(lab)]
    clis = {}
    for b in backends.BACKENDS:
        bcfg = (prog.get("backends") or {}).get(b) or {}
        pre = backends.resolve_cli(b, bcfg)
        ver = backends.cli_version(pre) if pre else None
        clis[b] = {"found": bool(pre), "path": (pre[-1] if pre else None), "version": backends.version_str(ver),
                   "shim": bool(pre and os.name == "nt" and pre[-1].lower().endswith((".cmd", ".bat")))}
        if pre:
            auth = backends.cli_auth(pre, backend=b)
            # an API key / cloud provider in the environment also works without an interactive login
            env_auth = any(os.environ.get(k) for k in _ENV_AUTH.get(b, ()))
            clis[b]["logged_in"] = None if auth is None else (auth["logged_in"] or env_auth)
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
        "config": {**{k: prog.get(k) for k in CONFIG_KEYS if k in prog},
                   **{k: v for k, v in (prog.get("live") if isinstance(prog.get("live"), dict) else {}).items()
                      if k in LIVE_KEYS},
                   "live": prog.get("live") is not False and (prog.get("live") or {}).get("enabled", True)
                   if isinstance(prog.get("live"), (dict, type(None))) else bool(prog.get("live"))},
        "auto_spawn_on_gate1": bool((lab.dashboard_cfg() or {}).get("auto_spawn_on_gate1")),
    }


# agents.programmatic keys the dashboard settings panel may change (PI-owned; the dashboard is the PI's
# localhost console, every change is confirmed and logged). The master switch has its own endpoint.
CONFIG_KEYS = ("backend", "model", "permission_mode", "max_minutes", "max_concurrent", "max_concurrent_total",
               "hub_max_concurrent", "daily_max_runs", "daily_max_minutes", "chain_max_steps")
LIVE_KEYS = ("park_minutes", "permission_minutes", "campaign_question_minutes", "linger_minutes")


__all__ = [
    "Lab", "HUB_TARGET", "RunSpec", "SpecError", "SKILL_REGISTRY", "NEVER",
    "enqueue", "answer", "reply", "resume", "cancel", "stop", "list_runs", "queue_position",
    "check_enabled", "permission_decision", "interrupt", "CONFIG_KEYS", "tick", "tick_loop", "reconcile", "run_supervisor",
    "caps", "brake", "daily_usage", "last_tick", "health", "attention", "backends",
    "find_run", "all_runs", "ledger", "ACTIVE", "PAUSED", "RESUMABLE", "TERMINAL", "STATUSES",
]
