"""Open a visible terminal window on this machine running one command — for the things a CLI must do
with the person at the keyboard (signing in, installing). The dashboard asks for a *purpose*, never a
command: every command line here is fixed, so a web page can't make this machine run anything else.

    uv run python tools/terminal.py login claude      # opens a window running `claude auth login`

The window stays open after the command finishes so its output can be read. Credentials are typed into
the CLI's own login flow (usually a browser page); nothing here sees them.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# purpose → how to phrase the command for a backend (the resolved CLI path is filled in)
LOGIN = {"claude": ["auth", "login"], "codex": ["login"], "opencode": ["auth", "login"]}
INSTALL = {
    "claude": {"win32": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"irm https://claude.ai/install.ps1 | iex\"",
               "*": "curl -fsSL https://claude.ai/install.sh | bash"},
    "codex": {"*": "npm install -g @openai/codex"},
    "opencode": {"*": "npm install -g opencode-ai"},
}
TITLE = "Newts' Lab"


def install_command(backend: str) -> str | None:
    table = INSTALL.get(backend) or {}
    return table.get(sys.platform) or table.get("*")


def login_argv(backend: str, cli: list[str]) -> list[str] | None:
    if backend not in LOGIN or not cli:
        return None
    return [*cli, *LOGIN[backend]]


def _quote_win(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv)


def open_terminal(command: str | list[str], cwd: str | Path | None = None, *, title: str = TITLE) -> dict:
    """Start a new, visible console window running `command`; returns {"ok", "how"} or {"error"}."""
    cwd = str(cwd or Path.home())
    if sys.platform == "win32":
        line = command if isinstance(command, str) else _quote_win(command)
        # a NEW console (not this server's), kept open with /k so the result stays readable
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        try:
            subprocess.Popen(["cmd.exe", "/k", f"title {title} & {line}"], cwd=cwd, creationflags=flags,
                             close_fds=True)
        except OSError as e:
            return {"error": f"could not open a console window: {e}"}
        return {"ok": True, "how": "a new Command Prompt window"}
    line = command if isinstance(command, str) else " ".join(shlex.quote(a) for a in command)
    script = f"cd {shlex.quote(cwd)} && {line}; echo; echo '(you can close this window)'"
    if sys.platform == "darwin":
        osa = ('tell application "Terminal"\nactivate\ndo script ' +
               '"' + script.replace("\\", "\\\\").replace('"', '\\"') + '"\nend tell')
        try:
            subprocess.Popen(["osascript", "-e", osa], close_fds=True)
        except OSError as e:
            return {"error": f"could not open Terminal: {e}"}
        return {"ok": True, "how": "a new Terminal window"}
    keep = f"{script}; exec bash"
    for exe, args in (("x-terminal-emulator", ["-e", "bash", "-lc", keep]),
                      ("gnome-terminal", ["--", "bash", "-lc", keep]),
                      ("konsole", ["-e", "bash", "-lc", keep]),
                      ("xfce4-terminal", ["-x", "bash", "-lc", keep]),
                      ("xterm", ["-T", title, "-e", "bash", "-lc", keep])):
        if shutil.which(exe):
            try:
                subprocess.Popen([exe, *args], close_fds=True, start_new_session=True)
            except OSError:
                continue
            return {"ok": True, "how": f"a new {exe} window"}
    return {"error": "no terminal emulator found — run the command yourself: " + line}


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in ("login", "install"):
        print(__doc__)
        return 2
    purpose, backend = sys.argv[1], sys.argv[2]
    if purpose == "install":
        cmd = install_command(backend)
        res = open_terminal(cmd) if cmd else {"error": f"no install command for {backend}"}
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from executor import backends
        argv = login_argv(backend, backends.resolve_cli(backend, {}) or [])
        res = open_terminal(argv) if argv else {"error": f"{backend} is not installed"}
    print(res)
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
