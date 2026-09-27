"""Start Newts' Lab: the dashboard server for this lab, then your browser.

    uv run --with pyyaml python newts.py                 # this lab, http://127.0.0.1:8787 (or the next free port)
    uv run --with pyyaml python newts.py --hub ../my-lab # another lab
    uv run --with pyyaml python newts.py --no-browser

Or double-click `Start Newts Lab.cmd` (Windows) / `start-newts.command` (macOS) / run `./start-newts.sh`.
If the dashboard is already running for this lab, it just opens the browser. Everything else — creating
or switching labs, signing in to an agent CLI, setup, launching work — happens in the dashboard.
Ctrl-C (or Settings → About → Stop server) stops the server; agent runs keep going on their own.
"""

from __future__ import annotations

import argparse
import json
import socket
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Start Newts' Lab (the dashboard) and open it in your browser.")
    ap.add_argument("--hub", default=str(HERE), help="the lab to open (default: this folder)")
    ap.add_argument("--port", type=int, default=None, help="default: 8787, or the next free port")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--demo", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    hub = Path(a.hub).expanduser().resolve()
    if not (hub / "lab" / "config.yaml").exists():
        print(f"{hub} is not a Newts' Lab (no lab/config.yaml). Open the dashboard from a lab folder, "
              "or create one from the dashboard's lab picker.")
        return 2

    # already running for this lab? just open it
    for port in ([a.port] if a.port else PORTS):
        info = ping(port)
        if info and Path(info.get("lab") or "").resolve() == hub:
            url = f"http://127.0.0.1:{port}/"
            print(f"Newts' Lab is already running for {info.get('name')} — {url}")
            if not a.no_browser:
                webbrowser.open(url)
            return 0

    port = a.port or next((p for p in PORTS if port_free(p)), None)
    if port is None:
        print(f"ports {PORTS.start}–{PORTS.stop - 1} are all busy — pass --port <free port>")
        return 3
    url = f"http://127.0.0.1:{port}/"

    if not a.no_browser:
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
