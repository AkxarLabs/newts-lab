"""Remote machines, from one local dashboard.

The local dashboard can open a lab that lives on another machine you reach over SSH. It starts (or finds)
that lab's own dashboard server there (`newts.py --background`), holds an SSH tunnel to it, and the local
server proxies the page's API calls through the tunnel (serve.py). Everything a lab does — file reads, agent
runs, the terminal — happens on the machine the lab lives on; this module only manages the connection.

  registry   ~/.newts/machines.json (NEWTS_HOME overrides): {machines: [{id, name, host, labs: [...], facts}]}
  hosts      suggestions parsed from ~/.ssh/config (named Host entries)
  probe      one non-interactive SSH call: OS, tools (uv, git, python3, agent CLIs), GPUs, schedulers, labs
  connect    key auth: start the remote server + a supervised `ssh -N -L` tunnel (BatchMode, restarts itself)
             MFA / password: a local terminal window runs the same SSH (you sign in there; it stays the tunnel)
  create     copy this template over SSH (`git archive | ssh … tar -x`) and run tools/new_lab.py there

`NEWTS_SSH` overrides the ssh command (the tests use a fake). Nothing here ever handles a password.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import ctx  # noqa: E402



def _home() -> Path:
    return Path(os.environ.get("NEWTS_HOME") or (Path.home() / ".newts"))


def _file() -> Path:
    return _home() / "machines.json"


def _load() -> list[dict]:
    try:
        return [m for m in json.loads(_file().read_text(encoding="utf-8")).get("machines", []) if isinstance(m, dict)]
    except (OSError, ValueError, AttributeError):
        return []


def _save(ms: list[dict]) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"machines": ms}, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def _get(mid: str) -> dict | None:
    return next((m for m in _load() if m.get("id") == mid), None)


def _put(m: dict) -> None:
    ms = [x for x in _load() if x.get("id") != m["id"]]
    ms.append(m)
    _save(ms)


_HOST_RE = re.compile(r"^[A-Za-z0-9_.@:\[\]-]{1,200}$")
_PATH_BAD = re.compile(r"[\"`$\\\n\r;&|<>]")


def _clean_host(h: str) -> str | None:
    h = str(h or "").strip()
    return h if _HOST_RE.match(h) and not h.startswith("-") else None


def _clean_path(p: str) -> str | None:
    p = str(p or "").strip()
    if not p or _PATH_BAD.search(p.replace("~", "")) or p.startswith("-"):
        return None
    return p


def _rpath(p: str) -> str:
    """A remote path as a double-quoted shell word; a leading ~ becomes $HOME (it doesn't expand in quotes)."""
    if p == "~":
        return '"$HOME"'
    if p.startswith("~/"):
        return '"$HOME/' + p[2:] + '"'
    return '"' + p + '"'


# ── ssh ──────────────────────────────────────────────────────────────────────

def ssh_cmd() -> list[str]:
    env = os.environ.get("NEWTS_SSH")
    if env:
        return shlex.split(env, posix=(os.name != "nt")) if not env.startswith("[") else json.loads(env)
    return [shutil.which("ssh") or "ssh"]


def _opts(batch: bool) -> list[str]:
    o = ["-o", "ConnectTimeout=12", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=4"]
    if batch:
        o += ["-o", "BatchMode=yes"]
    if os.name == "posix":   # reuse one sign-in (MFA once, then quiet) — OpenSSH on Windows can't multiplex
        cdir = _home() / "ssh"
        cdir.mkdir(parents=True, exist_ok=True)
        o += ["-o", "ControlMaster=auto", "-o", f"ControlPath={cdir}/%C", "-o", "ControlPersist=8h"]
    return o


def _run(host: str, script: str, timeout: float = 60, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    argv = [*ssh_cmd(), *_opts(True), host, "bash -lc " + shlex.quote(script)]
    return subprocess.run(argv, input=stdin, capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)


_AUTH_FAIL = re.compile(r"permission denied|keyboard-interactive|password|verification code|authentication|"
                        r"too many authentication|host key verification failed", re.I)


def _why(r: subprocess.CompletedProcess) -> tuple[str, str]:
    """(kind, message) of a failed ssh call: auth (needs interactive sign-in) | hostkey | network | remote."""
    err = (r.stderr or b"").decode("utf-8", "replace").strip()
    if r.returncode == 255:
        if re.search(r"host key verification failed|REMOTE HOST IDENTIFICATION HAS CHANGED", err, re.I):
            return "hostkey", "the host key isn't trusted yet — connect once in a terminal to accept it"
        if _AUTH_FAIL.search(err):
            return "auth", "this machine needs an interactive sign-in (password / MFA)"
        return "network", err.splitlines()[-1] if err else "could not reach it"
    return "remote", err.splitlines()[-1] if err else f"exit {r.returncode}"


PATH_PREFIX = 'export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"'
TOOLS = ["uv", "git", "python3", "claude", "codex", "opencode", "sbatch", "sinfo", "squeue", "qsub", "bsub", "nvidia-smi", "rocm-smi"]


def probe_script(labs: list[str]) -> str:
    lines = [PATH_PREFIX,
             'echo "os=$(uname -s)"', 'echo "arch=$(uname -m)"', 'echo "hostname=$(hostname)"', 'echo "home=$HOME"',
             'echo "cpus=$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null)"']
    lines += [f'echo "cmd.{t}=$(command -v {t} 2>/dev/null)"' for t in TOOLS]
    lines += ['command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | head -16 | sed "s/^/gpu=/"',
              'command -v sinfo >/dev/null 2>&1 && sinfo -h -o "%P|%l|%G|%a" 2>/dev/null | head -24 | sed "s/^/partition=/"',
              '[ -n "$MODULESHOME" ] && echo "modules=yes"']
    for p in labs:
        lines.append(f'[ -f {_rpath(p)}/lab/config.yaml ] && echo "lab={p}"; true')
    lines.append("true")
    return "\n".join(lines)


def parse_probe(text: str) -> dict:
    facts: dict = {"gpus": [], "partitions": [], "labs": [], "tools": {}}
    for line in text.splitlines():
        k, _, v = line.partition("=")
        v = v.strip()
        if k.startswith("cmd."):
            facts["tools"][k[4:]] = v or None
        elif k == "gpu":
            facts["gpus"].append(v)
        elif k == "partition":
            name, lim, gres, avail = (v.split("|") + ["", "", "", ""])[:4]
            facts["partitions"].append({"name": name.rstrip("*"), "default": name.endswith("*"), "time_limit": lim,
                                        "gres": gres, "up": avail == "up"})
        elif k == "lab":
            facts["labs"].append(v)
        elif k in ("os", "arch", "hostname", "home", "cpus", "modules"):
            facts[k] = v
    t = facts["tools"]
    facts["scheduler"] = "slurm" if t.get("sbatch") else "pbs" if t.get("qsub") else "lsf" if t.get("bsub") else None
    return facts


def ssh_hosts() -> list[str]:
    """Named hosts in ~/.ssh/config (no wildcards/negations) — suggestions for 'Add a machine'."""
    out = []
    try:
        text = (Path.home() / ".ssh" / "config").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        m = re.match(r"\s*Host\s+(.+)$", line, re.I)
        if not m:
            continue
        for h in m.group(1).split():
            if not any(c in h for c in "*?!") and h not in out:
                out.append(h)
    return out


# ── connections ──────────────────────────────────────────────────────────────

class Conn:
    def __init__(self, machine: dict, lab: str):
        self.machine, self.lab = machine, lab
        self.key = f"{machine['id']}::{lab}"
        seed = int(hashlib.sha1(self.key.encode("utf-8")).hexdigest(), 16)
        self.rport = 20000 + seed % 9000             # the remote dashboard's port (stable per machine + lab)
        self.lport = _free_port(30000 + seed % 9000)  # this computer's end of the tunnel
        self.state, self.error, self.cookie, self.name = "idle", None, None, None
        self.tunnel: subprocess.Popen | None = None
        self.window = False
        self.want = False
        self._lock = threading.Lock()

    def info(self) -> dict:
        return {"machine": self.machine["id"], "host": self.machine["host"], "name": self.machine.get("name") or self.machine["host"],
                "lab": self.lab, "lab_name": self.name, "state": self.state, "error": self.error, "port": self.lport,
                "window": self.window}

    # the remote side: make sure the lab's dashboard runs on exactly rport
    def _start_cmd(self) -> str:
        launcher = self.machine.get("launcher") or "newts.py"
        py = self.machine.get("python") or "uv run --with pyyaml python"
        return (f"{PATH_PREFIX}; cd {_rpath(self.lab)} && {py} {launcher} --hub . --background --json --port {self.rport}")

    def connect(self, interactive: bool) -> dict:
        with self._lock:
            self.want, self.error = True, None
            if self.alive():
                self.state = "connected"
                return {"ok": True, "state": "connected"}
            if interactive:
                return self._connect_window()
            self.state = "starting"
            try:
                r = _run(self.machine["host"], self._start_cmd(), timeout=180)
            except subprocess.TimeoutExpired:
                self.state, self.error = "error", "the remote dashboard did not start within 3 minutes"
                return {"error": self.error}
            if r.returncode != 0:
                kind, msg = _why(r)
                out = (r.stdout or b"").decode("utf-8", "replace")
                last = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "")
                if last:
                    try:
                        msg = json.loads(last).get("error") or msg
                    except ValueError:
                        pass
                if "uv: command not found" in (r.stderr or b"").decode("utf-8", "replace"):
                    msg = "uv isn't installed on that machine — use “Install uv” first"
                self.state, self.error = ("auth" if kind == "auth" else "error"), msg
                return {"error": msg, "needs_interactive": kind == "auth"}
            out = (r.stdout or b"").decode("utf-8", "replace")
            last = next((ln for ln in reversed(out.splitlines()) if ln.strip().startswith("{")), "{}")
            try:
                started = json.loads(last)
            except ValueError:
                started = {}
            if not started.get("ok"):
                self.state, self.error = "error", started.get("error") or "the remote dashboard did not start"
                return {"error": self.error}
            self.name = started.get("name")
            self._open_tunnel()
            if not self._wait(40):
                self.state, self.error = "error", "the tunnel did not come up"
                return {"error": self.error}
            self.state = "connected"
            threading.Thread(target=self._supervise, daemon=True).start()
            return {"ok": True, "state": "connected", "name": self.name}

    def _open_tunnel(self) -> None:
        argv = [*ssh_cmd(), *_opts(True), "-N", "-o", "ExitOnForwardFailure=yes",
                "-L", f"{self.lport}:127.0.0.1:{self.rport}", self.machine["host"]]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.tunnel = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.PIPE, creationflags=flags)

    def _connect_window(self) -> dict:
        terminal = ctx.tool("terminal")
        keep = "echo; echo 'Connected — keep this window open while you use this lab.'; while true; do sleep 3600; done"
        argv = [*ssh_cmd(), *_opts(False), "-t", "-o", "ExitOnForwardFailure=yes",
                "-L", f"{self.lport}:127.0.0.1:{self.rport}", self.machine["host"],
                "bash -lc " + shlex.quote(f"{self._start_cmd()}; {keep}")]
        res = terminal.open_terminal(argv, title=f"Newts' Lab — {self.machine.get('name') or self.machine['host']}")
        if not res.get("ok"):
            self.state, self.error = "error", res.get("error")
            return {"error": res.get("error"), "command": " ".join(shlex.quote(a) for a in argv)}
        self.window, self.state = True, "waiting"
        threading.Thread(target=self._await_window, daemon=True).start()
        return {"ok": True, "state": "waiting", "note": "Sign in in the terminal window that opened — this connects by itself."}

    def _await_window(self) -> None:
        if self._wait(300):
            self.state = "connected"
        elif self.state == "waiting":
            self.state, self.error = "error", "no connection yet — finish signing in in the terminal window, then Connect again"

    def _wait(self, secs: float) -> bool:
        t0 = time.time()
        while time.time() - t0 < secs:
            if self.tunnel is not None and self.tunnel.poll() is not None:
                err = (self.tunnel.stderr.read() or b"").decode("utf-8", "replace") if self.tunnel.stderr else ""
                self.error = err.strip().splitlines()[-1] if err.strip() else "the tunnel closed"
                return False
            if self.alive(refresh=True):
                return True
            time.sleep(0.4)
        return False

    def _supervise(self) -> None:
        delay = 2.0
        while self.want and not self.window:
            if self.tunnel is not None and self.tunnel.poll() is None:
                time.sleep(2)
                continue
            if not self.want:
                break
            self.state = "reconnecting"
            time.sleep(delay)
            try:
                self._open_tunnel()
                if self._wait(30):
                    self.state, delay = "connected", 2.0
                    continue
            except OSError:
                pass
            delay = min(60.0, delay * 2)

    def alive(self, refresh: bool = False) -> bool:
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.lport, timeout=3)
            c.request("GET", "/api/ping")
            r = c.getresponse()
            info = json.loads(r.read() or b"{}")
            if info.get("app") != "newts-lab":
                return False
            self.name = info.get("name") or self.name
            if refresh or not self.cookie:
                self.refresh_cookie()
            return True
        except (OSError, ValueError, http.client.HTTPException):
            return False

    def refresh_cookie(self) -> None:
        try:
            c = http.client.HTTPConnection("127.0.0.1", self.lport, timeout=10)
            c.request("GET", "/", headers={"Host": f"127.0.0.1:{self.lport}"})
            r = c.getresponse()
            r.read()
            ck = r.getheader("Set-Cookie") or ""
            self.cookie = ck.split(";", 1)[0] or None
        except (OSError, http.client.HTTPException):
            pass

    def disconnect(self, stop_remote: bool = False) -> None:
        self.want = False
        if self.tunnel is not None and self.tunnel.poll() is None:
            self.tunnel.terminate()
        self.tunnel, self.state = None, "idle"
        if stop_remote and not self.window:
            launcher = self.machine.get("launcher") or "newts.py"
            py = self.machine.get("python") or "uv run --with pyyaml python"
            try:
                _run(self.machine["host"], f"{PATH_PREFIX}; cd {_rpath(self.lab)} && {py} {launcher} --hub . --stop", timeout=60)
            except subprocess.TimeoutExpired:
                pass


def _free_port(start: int) -> int:
    for p in list(range(start, start + 50)) + list(range(30000, 39000, 7)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise OSError("no free local port for a tunnel")


CONNS: dict[str, Conn] = {}


def conn_for(mid: str, lab: str) -> Conn | None:
    m = _get(mid)
    if not m:
        return None
    key = f"{mid}::{lab}"
    c = CONNS.get(key)
    if c is None:
        c = CONNS[key] = Conn(m, lab)
    c.machine = m
    return c


# ── the API (local-only routes) ──────────────────────────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "machine"


def list_machines() -> tuple[dict, int]:
    out = []
    for m in _load():
        labs = []
        for lab in m.get("labs") or []:
            c = CONNS.get(f"{m['id']}::{lab['path']}")
            labs.append({**lab, **({"state": c.state, "error": c.error, "lab_name": c.name} if c else {"state": "idle"})})
        out.append({**m, "labs": labs})
    cur = ctx.REMOTE.info() if ctx.REMOTE else None
    return {"ok": True, "machines": out, "suggestions": [h for h in ssh_hosts() if not any(x["host"] == h for x in out)],
            "current": cur}, 200


def add_machine(body: dict) -> tuple[dict, int]:
    host = _clean_host(body.get("host"))
    if not host:
        return {"error": "a host: an SSH alias from ~/.ssh/config, or user@hostname"}, 400
    name = str(body.get("name") or host).strip()[:60]
    mid = _slug(name)
    if _get(mid):
        return {"error": f"a machine named {name} already exists"}, 400
    m = {"id": mid, "name": name, "host": host, "labs": [], "facts": None, "added": ctx.ts()}
    _put(m)
    ctx.pi_log({"action": "machine.add", "id": mid, "host": host})
    res, _ = probe({"id": mid})
    return {"ok": True, "machine": _get(mid), "probe": res}, 200


def remove_machine(body: dict) -> tuple[dict, int]:
    mid = str(body.get("id") or "")
    for k, c in list(CONNS.items()):
        if k.startswith(mid + "::"):
            c.disconnect()
            CONNS.pop(k, None)
    _save([m for m in _load() if m.get("id") != mid])
    return {"ok": True}, 200


def probe(body: dict) -> tuple[dict, int]:
    m = _get(str(body.get("id") or ""))
    if not m:
        return {"error": "no such machine"}, 404
    try:
        r = _run(m["host"], probe_script([lab["path"] for lab in m.get("labs") or []]), timeout=45)
    except subprocess.TimeoutExpired:
        m["facts"], m["reach"] = None, {"ok": False, "kind": "network", "error": "timed out"}
        _put(m)
        return {"error": "timed out reaching it", "kind": "network"}, 200
    if r.returncode != 0:
        kind, msg = _why(r)
        m["reach"] = {"ok": False, "kind": kind, "error": msg}
        _put(m)
        return {"ok": False, "kind": kind, "error": msg, "needs_interactive": kind == "auth"}, 200
    facts = parse_probe((r.stdout or b"").decode("utf-8", "replace"))
    m["facts"], m["reach"], m["probed"] = facts, {"ok": True}, ctx.ts()
    for lab in m.get("labs") or []:
        lab["exists"] = lab["path"] in facts["labs"]
    _put(m)
    return {"ok": True, "facts": facts}, 200


def add_lab(body: dict) -> tuple[dict, int]:
    m = _get(str(body.get("id") or ""))
    path = _clean_path(body.get("path"))
    if not m or not path:
        return {"error": "a machine and a lab folder path"}, 400
    labs = [x for x in m.get("labs") or [] if x.get("path") != path]
    labs.append({"path": path, "name": str(body.get("name") or "").strip()[:80] or None})
    m["labs"] = labs
    _put(m)
    res, _ = probe({"id": m["id"]})
    exists = path in ((res.get("facts") or {}).get("labs") or [])
    return {"ok": True, "exists": exists, "probe": res,
            "note": "added" if exists else "added — but there is no lab/config.yaml there yet (create one, or check the path)"}, 200


def open_lab(body: dict) -> tuple[dict, int]:
    """Connect (if needed) and make this remote lab the dashboard's current lab."""
    mid, path = str(body.get("id") or ""), _clean_path(body.get("path"))
    c = conn_for(mid, path or "")
    if not c or not path:
        return {"error": "no such machine / lab"}, 404
    interactive = bool(body.get("interactive")) or (c.machine.get("reach") or {}).get("kind") == "auth"
    res = c.connect(interactive)
    if res.get("ok") and res.get("state") == "connected":
        ctx.set_remote(c)
        _remember(mid, path, True)    # opened once → kept connected in the background (the overview reads it)
        ctx.pi_log({"action": "lab.open_remote", "machine": mid, "path": path})
    return res, 200 if (res.get("ok") or res.get("needs_interactive")) else 400


def _remember(mid: str, path: str, keep: bool) -> None:
    m = _get(mid)
    if not m:
        return
    for lab in m.get("labs") or []:
        if lab.get("path") == path:
            lab["keep_connected"] = keep
    _put(m)


def use_lab(body: dict) -> tuple[dict, int]:
    """After an interactive connect finishes: switch to it if it's up."""
    c = CONNS.get(f"{body.get('id')}::{body.get('path')}")
    if not c or c.state != "connected":
        return {"error": "not connected yet", "state": c.state if c else "idle"}, 400
    ctx.set_remote(c)
    return {"ok": True}, 200


def disconnect(body: dict) -> tuple[dict, int]:
    c = CONNS.get(f"{body.get('id')}::{body.get('path')}")
    if not c:
        return {"ok": True}, 200
    current = ctx.REMOTE is c
    if current:
        ctx.set_remote(None)          # the dashboard falls back to this computer's lab
    _remember(str(body.get("id") or ""), str(body.get("path") or ""), False)   # Disconnect means: stop keeping it
    c.disconnect(stop_remote=bool(body.get("stop_remote")))
    return {"ok": True, "was_current": current, "note": "disconnected — agents on that machine keep running"}, 200


def local(body: dict) -> tuple[dict, int]:
    """Back to a lab on this computer."""
    ctx.set_remote(None)
    return {"ok": True}, 200


def create_lab(body: dict) -> tuple[dict, int]:
    """A new lab on a remote machine: this template's committed files over SSH, then new_lab.py there."""
    m = _get(str(body.get("id") or ""))
    dest = _clean_path(body.get("path"))
    name = re.sub(r"[\"'`$\\]", "", str(body.get("name") or "").strip())[:80]
    if not m or not dest or not body.get("confirm"):
        return {"error": "a machine, a folder and confirm"}, 400
    tpl = ctx.ROOT
    try:
        tar = subprocess.run(["git", "-C", str(tpl), "archive", "--format=tar", "HEAD"], capture_output=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": f"could not package the template: {e}"}, 500
    if not tar:
        return {"error": "the template is not a git checkout — can't package it"}, 500
    tmp = f".newts/tpl-{int(time.time())}"
    r = _run(m["host"], f'mkdir -p "$HOME/{tmp}" && tar -x -C "$HOME/{tmp}"', timeout=300, stdin=tar)
    if r.returncode != 0:
        kind, msg = _why(r)
        return {"error": msg, "needs_interactive": kind == "auth"}, 400
    nm = f' --name "{name}"' if name else ""
    r = _run(m["host"], f'{PATH_PREFIX}; cd "$HOME/{tmp}" && python3 tools/new_lab.py {_rpath(dest)}{nm}; rc=$?; cd; rm -rf "$HOME/{tmp}"; exit $rc',
             timeout=300)
    out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
    if r.returncode != 0:
        return {"error": (out.strip().splitlines() or ["could not create the lab"])[-1]}, 400
    add_lab({"id": m["id"], "path": dest, "name": name})
    ctx.pi_log({"action": "lab.create_remote", "machine": m["id"], "path": dest})
    return {"ok": True, "note": f"created {name or dest} on {m.get('name')}"}, 200


def install_uv(body: dict) -> tuple[dict, int]:
    """Open a local terminal window running uv's installer on that machine (you watch it)."""
    m = _get(str(body.get("id") or ""))
    if not m:
        return {"error": "no such machine"}, 404
    terminal = ctx.tool("terminal")
    argv = [*ssh_cmd(), *_opts(False), "-t", m["host"], "bash -lc " + shlex.quote("curl -LsSf https://astral.sh/uv/install.sh | sh")]
    res = terminal.open_terminal(argv, title=f"Install uv on {m.get('name')}")
    return (res, 200) if res.get("ok") else (res, 500)
