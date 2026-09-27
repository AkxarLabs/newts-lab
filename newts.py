"""Start Newts' Lab: the dashboard server for this lab, then your browser.

    uv run --with pyyaml python newts.py                 # this lab, http://127.0.0.1:8787 (or the next free port)
    uv run --with pyyaml python newts.py --hub ../my-lab # another lab
    uv run --with pyyaml python newts.py --no-browser
    uv run --with pyyaml python newts.py --background    # detach: keeps running after you log out (remote boxes)
    uv run --with pyyaml python newts.py --status | --stop

Or double-click `Start Newts Lab.cmd` (Windows) / `start-newts.command` (macOS) / run `./start-newts.sh`.
If the dashboard is already running for this lab, it just opens the browser. Everything else — creating
or switching labs, connecting other machines, signing in to an agent CLI, setup, launching work — happens
in the dashboard. Ctrl-C (or Settings → About → Stop server) stops the server; agent runs keep going.

On a machine you reached over SSH (no desktop), it prints the one line to run on your own computer to
reach it:  ssh -N -L 8787:127.0.0.1:<port> you@this-machine  → then open http://127.0.0.1:8787.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
PORTS = range(8787, 8800)


def home() -> Path:
    return Path(os.environ.get("NEWTS_HOME") or (Path.home() / ".newts"))


def lab_key(hub: Path) -> str:
    return hashlib.sha1(str(hub.resolve()).lower().encode("utf-8")).hexdigest()[:12]


def state_file(hub: Path) -> Path:
    return home() / "servers" / f"{lab_key(hub)}.json"


def _ephemeral(exe: str) -> bool:
    """True for `uv run --with …`'s throwaway environment (…/builds-v0/.tmpXXXX/…) — uv deletes it when
    that command exits, which would strand a detached server and every agent run it spawns."""
    places = [exe, sys.prefix] if exe == sys.executable else [exe]
    for where in places:                     # unresolved: the venv's python is a symlink out of it
        parts = Path(os.path.abspath(where)).parts
        if "builds-v0" in parts or any(x.startswith(".tmp") for x in parts[-4:]):
            return True
    return False


def stable_python() -> str:
    """A Python that outlives this launcher: this one if it's already stable, else ~/.newts/py (a small
    venv with pyyaml, created once by uv). The dashboard, its detached agent-run supervisors and their
    hooks all run on it."""
    if not _ephemeral(sys.executable):
        return sys.executable
    venv = home() / "py"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    ok = py.exists() and subprocess.run([str(py), "-c", "import yaml"], capture_output=True).returncode == 0
    if not ok:
        uv = shutil.which("uv")
        if not uv:
            return sys.executable
        home().mkdir(parents=True, exist_ok=True)
        subprocess.run([uv, "venv", "--quiet", "--allow-existing", str(venv)], capture_output=True)
        r = subprocess.run([uv, "pip", "install", "--quiet", "--python", str(py), "pyyaml"], capture_output=True, text=True)
        if r.returncode != 0 or not py.exists():
            return sys.executable
    return str(py)


def ping(port: int, timeout: float = 0.6) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data if data.get("app") == "newts-lab" else None
    except (OSError, ValueError):
        return None


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def headless() -> bool:
    """No local browser to open: an SSH session, or Linux without a display."""
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return True
    return sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def tunnel_hint(port: int) -> str:
    user = getpass.getuser()
    host = socket.getfqdn() or socket.gethostname()
    return (f"This machine has no browser of its own. On YOUR computer run:\n\n"
            f"    ssh -N -L 8787:127.0.0.1:{port} {user}@{host}\n\n"
            f"then open http://127.0.0.1:8787 (any free local port works in place of 8787).\n"
            f"Or add this machine in your local dashboard (Labs → Add a machine) and it does this for you.")


def running_for(hub: Path, port: int | None = None) -> tuple[int, dict] | None:
    """(port, ping) of a dashboard already serving this lab, if any."""
    cands = [port] if port else []
    try:
        st = json.loads(state_file(hub).read_text(encoding="utf-8"))
        cands.append(int(st.get("port")))
    except (OSError, ValueError, TypeError):
        pass
    cands += list(PORTS)
    seen = set()
    for p in cands:
        if not p or p in seen:
            continue
        seen.add(p)
        info = ping(p)
        if info and Path(info.get("lab") or "").resolve() == hub.resolve():
            return p, info
    return None


def _procs():
    sys.path.insert(0, str(HERE / "tools"))
    from executor import procs   # noqa: E402 — detached spawning + tree kill, per platform
    return procs


def stop(hub: Path) -> dict:
    hit = running_for(hub)
    try:
        st = json.loads(state_file(hub).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    pid = (hit[1].get("pid") if hit else None) or st.get("pid")
    if not pid:
        return {"ok": True, "note": "not running"}
    try:
        _procs().kill_tree(int(pid))
    except Exception as e:  # noqa: BLE001
        return {"error": f"could not stop pid {pid}: {e}"}
    for _ in range(40):
        if not (hit and ping(hit[0], 0.3)):
            break
        time.sleep(0.1)
    try:
        state_file(hub).unlink()
    except OSError:
        pass
    return {"ok": True, "note": f"stopped the dashboard (pid {pid}); agent runs keep going"}


def background(hub: Path, port: int | None, demo: bool) -> dict:
    """Start (or find) a detached dashboard for this lab; return {ok, port, pid, lab, already}."""
    hit = running_for(hub, port)
    if hit and (not port or hit[0] == port):
        return {"ok": True, "port": hit[0], "pid": hit[1].get("pid"), "lab": str(hub), "name": hit[1].get("name"),
                "already": True}
    if hit and port and hit[0] != port:
        stop(hub)                                   # the caller needs exactly `port` (a tunnel points there)
    if port and not port_free(port):
        return {"error": f"port {port} is in use by something else"}
    port = port or next((p for p in PORTS if port_free(p)), None)
    if port is None:
        return {"error": "no free port in 8787–8799 — pass --port"}
    logs = home() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log = (logs / f"{lab_key(hub)}.log").open("ab")
    argv = [sys.executable, str(Path(__file__).resolve()), "--hub", str(hub), "--port", str(port), "--no-browser",
            *(["--demo"] if demo else [])]
    procs = _procs()
    child = subprocess.Popen(argv, cwd=str(hub), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             env={**os.environ, "NEWTS_BACKGROUND": "1"}, close_fds=True, **procs.DETACHED)
    for _ in range(150):
        info = ping(port, 0.3)
        if info:
            st = {"pid": info.get("pid") or child.pid, "port": port, "lab": str(hub), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
            state_file(hub).parent.mkdir(parents=True, exist_ok=True)
            state_file(hub).write_text(json.dumps(st), encoding="utf-8")
            return {"ok": True, "port": port, "pid": st["pid"], "lab": str(hub), "name": info.get("name"), "already": False}
        if child.poll() is not None:
            break
        time.sleep(0.1)
    return {"error": f"the dashboard did not start — see {logs / (lab_key(hub) + '.log')}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Start Newts' Lab (the dashboard) and open it in your browser.")
    ap.add_argument("--hub", default=str(HERE), help="the lab to open (default: this folder)")
    ap.add_argument("--port", type=int, default=None, help="default: 8787, or the next free port")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--background", action="store_true", help="detach; keeps running after this shell exits")
    ap.add_argument("--status", action="store_true", help="is a dashboard running for this lab?")
    ap.add_argument("--stop", action="store_true", help="stop this lab's dashboard (agent runs keep going)")
    ap.add_argument("--json", action="store_true", help="machine-readable output (used by remote connections)")
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    py = stable_python()
    if py != sys.executable and not os.environ.get("NEWTS_REEXEC"):
        # move onto the stable interpreter first (see stable_python), same arguments
        return subprocess.run([py, str(Path(__file__).resolve()), *sys.argv[1:]],
                              env={**os.environ, "NEWTS_REEXEC": "1"}).returncode
    hub = Path(a.hub).expanduser().resolve()
    say = (lambda d: print(json.dumps(d))) if a.json else None
    if not (hub / "lab" / "config.yaml").exists():
        msg = (f"{hub} is not a Newts' Lab (no lab/config.yaml). Open the dashboard from a lab folder, "
               "or create one from the dashboard's Labs page.")
        (say or print)({"error": msg} if say else msg)
        return 2

    if a.stop:
        res = stop(hub)
        (say or (lambda d: print(d.get("note") or d.get("error"))))(res)
        return 0 if res.get("ok") else 1
    if a.status:
        hit = running_for(hub)
        res = {"ok": True, "running": bool(hit), "port": hit[0] if hit else None,
               "pid": hit[1].get("pid") if hit else None, "lab": str(hub)}
        (say or (lambda d: print(f"running on http://127.0.0.1:{d['port']} (pid {d['pid']})" if d["running"] else "not running")))(res)
        return 0
    if a.background:
        res = background(hub, a.port, a.demo)
        if say:
            say(res)
        elif res.get("ok"):
            print(f"Newts' Lab is {'already ' if res.get('already') else ''}running in the background for "
                  f"{res.get('name')} on http://127.0.0.1:{res['port']} (pid {res['pid']}). Stop it with --stop.")
            if headless():
                print(tunnel_hint(res["port"]))
        else:
            print(res.get("error"))
        return 0 if res.get("ok") else 1

    # already running for this lab? just open it
    hit = running_for(hub, a.port)
    if hit:
        url = f"http://127.0.0.1:{hit[0]}/"
        print(f"Newts' Lab is already running for {hit[1].get('name')} — {url}")
        if headless():
            print(tunnel_hint(hit[0]))
        elif not a.no_browser:
            webbrowser.open(url)
        return 0

    port = a.port or next((p for p in PORTS if port_free(p)), None)
    if port is None:
        print(f"ports {PORTS.start}–{PORTS.stop - 1} are all busy — pass --port <free port>")
        return 3
    url = f"http://127.0.0.1:{port}/"

    if headless() and not os.environ.get("NEWTS_BACKGROUND"):
        print(tunnel_hint(port))
    elif not a.no_browser:
        def opener():
            for _ in range(100):
                if ping(port, 0.3):
                    webbrowser.open(url)
                    return
                time.sleep(0.15)
        threading.Thread(target=opener, daemon=True).start()

    sys.path.insert(0, str(HERE / "dashboard"))
    import serve   # noqa: E402 — the dashboard server, in this process
    sys.argv = ["serve.py", "--hub", str(hub), "--port", str(port), *(["--demo"] if a.demo else [])]
    return serve.main()


if __name__ == "__main__":
    raise SystemExit(main())
