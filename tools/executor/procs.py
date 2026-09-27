"""Portable process control: spawn flags, liveness, tree kill, graceful stop, and the supervisor
liveness lock.

Liveness of a *supervisor* is an OS file lock, never a pid probe: the kernel releases the lock the
instant the holder dies (crash, kill -9, reboot), so there are no PID-reuse false positives and no
`tasklist`/`ps` parsing. Pids are used only to kill.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# A killable process group so the whole tree can be reaped (mirrors templates/project/scripts/sweep.py).
NEW_GROUP = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})

# A supervisor must outlive the process that spawned it (the dashboard, a CLI tick): detach it from
# the parent's console/session entirely, and never pop a console window on Windows.
if os.name == "nt":
    # DETACHED_PROCESS: no console inherited from the parent (closing the dashboard's terminal can't
    # take the supervisor down). Its own children are console apps, so the supervisor spawns them with
    # NO_WINDOW — otherwise Windows would allocate a visible console for each agent CLI.
    DETACHED = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS}
    NO_WINDOW = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, "CREATE_NO_WINDOW", 0)}
else:
    DETACHED = {"start_new_session": True}
    NO_WINDOW = {"start_new_session": True}


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                 capture_output=True, text=True, check=False,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        except OSError:
            return False
        return f'"{pid}"' in out  # CSV quotes the PID column; the "No tasks" banner won't contain it
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def kill_tree(pid) -> None:
    """Hard-kill a process and its descendants. Never raises."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            pgid = os.getpgid(pid)
            # Safety belt: every child we spawn is its own session leader (NEW_GROUP), so pgid==pid.
            # If a caller ever spawned one WITHOUT a new session, pgid is OUR group and killpg would
            # kill us too — target the pid alone instead.
            if pgid == os.getpgid(0):
                os.kill(pid, signal.SIGKILL)
            else:
                os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


def graceful_stop(proc: subprocess.Popen, grace: float = 10.0) -> None:
    """Ask a child to stop, then kill its tree. POSIX: SIGTERM to the group (claude -p exits 143 and
    leaves the session resumable), wait `grace`, then SIGKILL. Windows has no portable graceful signal
    for a detached group, so it is a hard tree kill (documented; the session stays resumable)."""
    if proc.poll() is not None:
        return
    if os.name != "nt":
        try:
            pgid = os.getpgid(proc.pid)
            if pgid != os.getpgid(0):
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            return
        deadline = time.time() + grace
        while time.time() < deadline:
            if proc.poll() is not None:
                return
            time.sleep(0.1)
    kill_tree(proc.pid)


class RunLock:
    """An exclusive, non-blocking OS lock on `<run>.d/lock`, held for a supervisor's whole life.

    `try_acquire()` → True if we now hold it. A second process gets False while the holder lives;
    the kernel frees it when the holder dies, which is how reconcile detects a dead supervisor.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None

    def try_acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 — held open for the lock's lifetime
        try:
            fh.seek(0, os.SEEK_END)
            if fh.tell() == 0:
                fh.write(b"L")
                fh.flush()
            fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if not self._fh:
            return
        with contextlib.suppress(OSError):
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            self._fh.close()
        self._fh = None

    @property
    def held(self) -> bool:
        return self._fh is not None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def is_locked(path: Path) -> bool:
    """True if some live process holds the RunLock at `path` (i.e. a supervisor is alive)."""
    if not Path(path).exists():
        return False
    probe = RunLock(path)
    if probe.try_acquire():
        probe.release()
        return False
    return True


@contextlib.contextmanager
def excl_lock(path: Path, *, wait: float = 30.0, stale_after: float = 120.0):
    """A cross-process mutex via O_EXCL create (same idiom as tools/run_slots.py). A crashed holder's
    lock older than `stale_after` seconds is reclaimed. Raises TimeoutError if still busy after `wait`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + wait
    fd = None
    while fd is None:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - path.stat().st_mtime > stale_after:
                    path.unlink()
                    continue
            if time.time() > deadline:
                raise TimeoutError(f"lock busy: {path.name}") from None
            time.sleep(0.05)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            path.unlink()


def _ephemeral(exe: str) -> bool:
    """`uv run --with …`'s throwaway environment (…/builds-v0/.tmpXXXX/…): uv deletes it when that command
    exits — any detached process started with it (a supervisor, a scheduler, a hook) would then find no
    interpreter. Checked on the unresolved path: the venv's python is a symlink out of it."""
    for where in ([exe, sys.prefix] if exe == sys.executable else [exe]):
        parts = Path(os.path.abspath(where)).parts
        if "builds-v0" in parts or any(x.startswith(".tmp") for x in parts[-4:]):
            return True
    return False


_STABLE: dict = {}


def python_exe() -> str:
    """The interpreter to run helper scripts (supervisor, hooks, MCP host) with — the one running now
    (known to have pyyaml), unless it is uv's throwaway environment: then a durable one, ~/.newts/py (a
    small venv with pyyaml, made once by uv — the same one newts.py uses). Absolute, so no PATH lookup can
    pick a different python."""
    exe = sys.executable or "python"
    if not _ephemeral(exe) or os.environ.get("NEWTS_KEEP_PYTHON"):
        return exe
    if _STABLE.get("py"):
        return _STABLE["py"]
    import shutil   # noqa: PLC0415
    venv = Path(os.environ.get("NEWTS_HOME") or (Path.home() / ".newts")) / "py"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    ok = py.exists() and subprocess.run([str(py), "-c", "import yaml"], capture_output=True).returncode == 0
    if not ok:
        uv = shutil.which("uv")
        if uv:
            venv.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([uv, "venv", "--quiet", "--allow-existing", str(venv)], capture_output=True)
            subprocess.run([uv, "pip", "install", "--quiet", "--python", str(py), "pyyaml"], capture_output=True)
        ok = py.exists() and subprocess.run([str(py), "-c", "import yaml"], capture_output=True).returncode == 0
    _STABLE["py"] = str(py) if ok else exe
    return _STABLE["py"]
