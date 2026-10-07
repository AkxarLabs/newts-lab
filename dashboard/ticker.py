"""The executor's scheduler, run inside the dashboard: a daemon thread that starts queued runs, reconciles,
post-processes finished ones and keeps the computer awake while a lab works — for every lab opened in this
server session. Runs never depend on it (each has its own supervisor). When the dashboard stops, a
detached `executor_cli serve --until-idle` takes over any lab that still has work.
"""

from __future__ import annotations

import os
import threading

import ctx
import sources

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


_SCHED: dict = {"thread": None, "stop": None}


_SCHED_HUBS: set = set()   # labs opened in this server session: their queues keep moving after a switch
ctx.on_change(lambda old, new: _SCHED_HUBS.update({old, new}))


def alive() -> bool:
    return bool(_SCHED.get("thread") and _SCHED["thread"].is_alive())


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
