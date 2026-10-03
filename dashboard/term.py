"""In-browser terminal sessions for the dashboard — for machines with no desktop (a remote box, a server
you reached over SSH) where "open a terminal window" has nowhere to go.

A session runs ONE fixed command chosen by purpose (tools/terminal.py's table: a CLI's own login, an
installer, or a login shell in the lab folder), never a command line from the page. On POSIX it runs under
a real PTY, so interactive logins and TUIs (opencode's provider picker, `claude auth login`'s paste-the-code
prompt) behave exactly as in a terminal; on Windows it falls back to pipes (the dashboard prefers a real
console window there). Output is kept in a bounded buffer and polled by the page (the server is stdlib;
no websockets):

    POST /api/term/open   {purpose, backend?, cols?, rows?}  → {id}
    GET  /api/term/read?id=&offset=                          → {data (base64), offset, exited, code}
    POST /api/term/write  {id, data}      POST /api/term/resize {id, cols, rows}      POST /api/term/close {id}
"""

from __future__ import annotations

import base64
import os
import secrets
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_BUF = 1 << 20        # keep the last 1 MB of output per session
MAX_SESSIONS = 8
REAP_AFTER_S = 600       # forget a finished session this long after it ends
S = None                 # the serve module (bound at import)


def bind(serve_module) -> None:
    global S
    S = serve_module


def has_pty() -> bool:
    return os.name == "posix"


def desktop() -> bool:
    """Can this machine open a terminal WINDOW the PI will see? (Not over SSH, and with a display.)"""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


class Session:
    def __init__(self, argv: list[str], cwd: str, purpose: str, cols: int = 100, rows: int = 28):
        self.id = secrets.token_hex(8)
        self.argv, self.cwd, self.purpose = argv, cwd, purpose
        self.buf = bytearray()
        self.base = 0                  # absolute offset of buf[0]
        self.lock = threading.Lock()
        self.exited, self.code, self.ended = False, None, None
        self.master = None
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "NEWTS_TERMINAL": "1"}
        if has_pty():
            import pty
            master, slave = pty.openpty()
            self._winsize(slave, cols, rows)
            self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=slave, stdout=slave, stderr=slave,
                                         start_new_session=True, close_fds=True)
            os.close(slave)
            self.master = master
        else:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, creationflags=flags, bufsize=0)
        threading.Thread(target=self._pump, daemon=True).start()

    @staticmethod
    def _winsize(fd, cols, rows):
        try:
            import fcntl
            import struct
            import termios
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(2, rows), max(10, cols), 0, 0))
        except Exception:  # noqa: BLE001
            pass

    def _append(self, data: bytes) -> None:
        with self.lock:
            self.buf += data
            over = len(self.buf) - MAX_BUF
            if over > 0:
                del self.buf[:over]
                self.base += over

    def _pump(self) -> None:
        try:
            while True:
                if self.master is not None:
                    try:
                        chunk = os.read(self.master, 65536)
                    except OSError:       # EIO: the child closed the PTY
                        chunk = b""
                else:
                    chunk = self.proc.stdout.read1(65536) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(4096)
                    if chunk:   # a pipe has no line discipline: give xterm the CRs it expects
                        chunk = chunk.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
                if not chunk:
                    break
                self._append(chunk)
        finally:
            try:
                self.code = self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.code = None
            self.exited, self.ended = True, time.time()
            self._append(f"\r\n\x1b[2m[finished{'' if self.code in (0, None) else f' with exit code {self.code}'}]\x1b[0m\r\n".encode())
            if self.master is not None:
                try:
                    os.close(self.master)
                except OSError:
                    pass

    def read(self, offset: int) -> dict:
        with self.lock:
            start = max(offset, self.base)
            data = bytes(self.buf[start - self.base:])
            end = self.base + len(self.buf)
        return {"ok": True, "data": base64.b64encode(data).decode("ascii"), "offset": end,
                "skipped": start - offset if offset < self.base else 0, "exited": self.exited, "code": self.code}

    def write(self, data: str) -> None:
        if self.exited:
            return
        raw = data.encode("utf-8")
        if self.master is not None:
            os.write(self.master, raw)
        else:
            self.proc.stdin.write(raw.replace(b"\r", b"\r\n") if raw.endswith(b"\r") else raw)
            self.proc.stdin.flush()

    def resize(self, cols: int, rows: int) -> None:
        if self.master is not None:
            self._winsize(self.master, cols, rows)

    def close(self) -> None:
        if not self.exited:
            try:
                sys.path.insert(0, str(Path(S.__file__).resolve().parents[1] / "tools"))
                from executor.procs import kill_tree
                kill_tree(self.proc.pid)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except OSError:
                    pass


SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def _reap() -> None:
    now = time.time()
    for k, s in list(SESSIONS.items()):
        if s.exited and s.ended and now - s.ended > REAP_AFTER_S:
            SESSIONS.pop(k, None)


def command_for(purpose: str, backend: str | None) -> tuple[list[str] | None, str | None]:
    """The fixed argv for a purpose — (argv, error)."""
    tools = Path(S.__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    import terminal   # noqa: E402
    if purpose == "shell":
        if os.name == "posix":
            return [os.environ.get("SHELL") or "/bin/bash", "-l"], None
        return [os.environ.get("COMSPEC") or "cmd.exe"], None
    if backend not in ("claude", "codex", "opencode"):   # (= executor.backends.BACKENDS)
        return None, "unknown backend"
    if purpose == "install":
        cmd = terminal.install_command(backend)
        if not cmd:
            return None, f"no install command known for {backend}"
        return (["bash", "-lc", cmd] if os.name == "posix" else ["cmd.exe", "/c", cmd]), None
    if purpose == "login":
        if S.executor is None:
            return None, "the executor is not available"
        prog = (S.sources._load_yaml(S.LAB / "config.yaml").get("agents") or {}).get("programmatic") or {}
        cli = S.executor.backends.resolve_cli(backend, (prog.get("backends") or {}).get(backend) or {})
        argv = terminal.login_argv(backend, cli or [])
        return (argv, None) if argv else (None, f"{backend} is not installed yet — install it first")
    return None, "unknown purpose"


def open_session(body: dict) -> tuple[dict, int]:
    purpose, backend = str(body.get("purpose") or ""), body.get("backend")
    argv, err = command_for(purpose, backend)
    if err:
        return {"error": err}, 400
    with _LOCK:
        _reap()
        live = [s for s in SESSIONS.values() if not s.exited]
        if len(live) >= MAX_SESSIONS:
            return {"error": "too many open terminals — close one first"}, 400
        try:
            cols, rows = int(body.get("cols") or 100), int(body.get("rows") or 28)
        except (TypeError, ValueError):
            cols, rows = 100, 28
        try:
            s = Session(argv, str(S.HUB), purpose, cols, rows)
        except OSError as e:
            return {"error": f"could not start it: {e}"}, 500
        SESSIONS[s.id] = s
    S._pi_log({"action": f"term.{purpose}", "backend": backend, "argv": argv[:4]})
    if S.executor is not None:
        try:
            S.executor.backends._AUTH_CACHE.clear()
        except AttributeError:
            pass
    S.sources._EXEC_CACHE["ts"] = 0
    title = {"login": f"Sign in to {backend}", "install": f"Install {backend}", "shell": "Terminal"}[purpose]
    return {"ok": True, "id": s.id, "title": title, "pty": has_pty(), "command": " ".join(shlex.quote(a) for a in argv)}, 200


def _get(body_or_q: dict) -> Session | None:
    return SESSIONS.get(str(body_or_q.get("id") or ""))


def read(q: dict) -> tuple[dict, int]:
    s = _get(q)
    if not s:
        return {"error": "no such terminal"}, 404
    try:
        off = int(q.get("offset") or 0)
    except ValueError:
        off = 0
    return s.read(off), 200


def write(body: dict) -> tuple[dict, int]:
    s = _get(body)
    if not s:
        return {"error": "no such terminal"}, 404
    data = body.get("data")
    if not isinstance(data, str) or len(data) > 65536:
        return {"error": "data must be text"}, 400
    try:
        s.write(data)
    except OSError as e:
        return {"error": str(e)}, 400
    return {"ok": True}, 200


def resize(body: dict) -> tuple[dict, int]:
    s = _get(body)
    if not s:
        return {"error": "no such terminal"}, 404
    try:
        s.resize(int(body.get("cols")), int(body.get("rows")))
    except (TypeError, ValueError):
        return {"error": "cols/rows"}, 400
    return {"ok": True}, 200


def close(body: dict) -> tuple[dict, int]:
    s = _get(body)
    if not s:
        return {"ok": True}, 200
    s.close()
    return {"ok": True}, 200
