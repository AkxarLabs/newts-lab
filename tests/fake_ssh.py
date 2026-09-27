"""A stand-in for `ssh`, for hermetic remote-machine tests.

`ssh [options] host [command…]`: the "remote" command runs HERE, under bash, with HOME=$FAKE_SSH_HOME; `-L
lport:127.0.0.1:rport` is a real TCP relay; `-N` blocks until killed. `uv run --with pyyaml python` and
`python3` in a command become this interpreter (so the remote dashboard really starts, offline). Behaviour
by env: FAKE_SSH_AUTH=fail → the "Permission denied" an MFA/password host gives a BatchMode client.
Every invocation is appended to $FAKE_SSH_LOG (JSON lines) when set.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

WITH_ARG = {"-o", "-L", "-p", "-i", "-J", "-l", "-F", "-R", "-D", "-S", "-E", "-b", "-c", "-m", "-w", "-W"}


def relay(lport: int, rhost: str, rport: int) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", lport))
    srv.listen(64)

    def pipe(a, b):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve():
        while True:
            c, _ = srv.accept()
            try:
                u = socket.create_connection((rhost, rport), timeout=10)
            except OSError:
                c.close()
                continue
            threading.Thread(target=pipe, args=(c, u), daemon=True).start()
            threading.Thread(target=pipe, args=(u, c), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()


def main() -> int:
    args = sys.argv[1:]
    opts, forwards, flags, i = [], [], set(), 0
    while i < len(args) and args[i].startswith("-"):
        a = args[i]
        if a in WITH_ARG:
            (forwards if a == "-L" else opts).append(args[i + 1])
            i += 2
            continue
        flags.update(a[1:])
        i += 1
    host = args[i] if i < len(args) else ""
    command = " ".join(args[i + 1:])
    if os.environ.get("FAKE_SSH_LOG"):
        with open(os.environ["FAKE_SSH_LOG"], "a", encoding="utf-8") as f:
            f.write(json.dumps({"host": host, "opts": opts, "forwards": forwards, "flags": sorted(flags), "command": command}) + "\n")
    if os.environ.get("FAKE_SSH_AUTH") == "fail" and "BatchMode=yes" in opts:
        sys.stderr.write(f"{host}: Permission denied (publickey,keyboard-interactive).\n")
        return 255
    for spec in forwards:
        lp, rh, rp = spec.split(":")
        try:
            relay(int(lp), rh, int(rp))
        except OSError as e:
            sys.stderr.write(f"bind [127.0.0.1]:{lp}: {e}\nCould not request local forwarding.\n")
            return 255
    rc = 0
    if command:
        py = sys.executable.replace("\\", "/")
        cmd = command.replace("uv run --with pyyaml python", f'"{py}"').replace("python3 ", f'"{py}" ')
        env = {**os.environ}
        if os.environ.get("FAKE_SSH_HOME"):
            env["HOME"] = os.environ["FAKE_SSH_HOME"]
        bash = shutil.which("bash") or "bash"
        rc = subprocess.run([bash, "-c", cmd], env=env, stdin=sys.stdin.buffer if not sys.stdin.isatty() else None).returncode
    if "N" in flags:
        while True:
            time.sleep(3600)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
