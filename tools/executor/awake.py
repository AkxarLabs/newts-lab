"""Keep the computer awake while the lab works (a campaign is active, or any agent run is live), and let it
sleep again as soon as nothing is. Nothing here changes a system setting: it holds the same temporary
"don't sleep" request a video player holds, released when the lab is idle or the process exits.

  Windows  SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) from a thread that stays alive
           (the request belongs to the calling thread)
  macOS    `caffeinate -i -w <our pid>`            (ends by itself if we die)
  Linux    `systemd-inhibit --what=sleep … sleep infinity`, when systemd-inhibit exists

Config: lab/config.yaml `lab.keep_awake: auto | off` (default auto). The display may still turn off; on a
laptop, closing the lid on battery still sleeps — that is the OS's (and the PI's) call.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading

_state = {"held": False, "reason": None, "proc": None, "thread": None, "stop": None}
_lock = threading.Lock()


def available() -> tuple[bool, str]:
    if os.name == "nt":
        return True, "Windows power request"
    if sys.platform == "darwin":
        return (bool(shutil.which("caffeinate")), "caffeinate" if shutil.which("caffeinate") else "caffeinate not found")
    if shutil.which("systemd-inhibit"):
        return True, "systemd-inhibit"
    return False, "no systemd-inhibit on this machine — keep it awake yourself"


def status() -> dict:
    ok, how = available()
    return {"available": ok, "held": _state["held"], "reason": _state["reason"],
            "detail": (f"holding ({how}): {_state['reason']}" if _state["held"] else how)}


def _win_thread(stop: threading.Event) -> None:
    import ctypes   # noqa: PLC0415
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    k = ctypes.windll.kernel32
    k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    try:
        while not stop.wait(30):
            k.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    finally:
        k.SetThreadExecutionState(ES_CONTINUOUS)


def hold(reason: str) -> bool:
    with _lock:
        _state["reason"] = reason
        if _state["held"]:
            return True
        ok, _how = available()
        if not ok:
            return False
        try:
            if os.name == "nt":
                stop = threading.Event()
                t = threading.Thread(target=_win_thread, args=(stop,), name="newts-keep-awake", daemon=True)
                t.start()
                _state.update(thread=t, stop=stop)
            elif sys.platform == "darwin":
                _state["proc"] = subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                _state["proc"] = subprocess.Popen(["systemd-inhibit", "--what=sleep", "--who=Newts' Lab",
                                                   f"--why={reason[:80]}", "--mode=block", "sleep", "infinity"],
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        _state["held"] = True
        return True


def release() -> None:
    with _lock:
        if not _state["held"]:
            return
        if _state.get("stop"):
            _state["stop"].set()
        p = _state.get("proc")
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except OSError:
                pass
        _state.update(held=False, reason=None, proc=None, thread=None, stop=None)


def enabled(lab) -> bool:
    """`lab.keep_awake` — auto (default) or off (YAML also reads a bare `off` as false)."""
    v = (lab.config().get("lab") or {}).get("keep_awake", "auto")
    return not (v is False or str(v).strip().lower() in ("off", "false", "no", "0"))


def update(lab) -> dict:
    """Hold while something is working, release when idle. Called from the dashboard's scheduler loop."""
    from .manifest import ACTIVE, all_runs   # noqa: PLC0415
    from . import campaigns                   # noqa: PLC0415
    if not enabled(lab):
        release()
        return status()
    live = sum(1 for *_x, m in all_runs(lab) if m.get("status") in ACTIVE)
    camps = [c for c in campaigns.all_states(lab) if c.get("status") in ("active", "finishing", "stopping")]
    if live or camps:
        hold(f"{live} agent run(s) working" + (f", {len(camps)} campaign(s) active" if camps else ""))
    else:
        release()
    return status()
