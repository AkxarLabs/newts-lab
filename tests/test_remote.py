"""Remote machines from one local dashboard (dashboard/machines.py + the serve.py proxy), end to end with a
fake `ssh` (tests/fake_ssh.py): the "remote" is a second lab on this machine with its own real dashboard
server, reached through a real TCP relay standing in for `ssh -L`."""

from __future__ import annotations

import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from conftest import REPO, load

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(not BASH, reason="the fake ssh runs remote commands with bash")


@pytest.fixture
def env(hub, tmp_path, monkeypatch):
    home = tmp_path / "newts-home"
    monkeypatch.setenv("NEWTS_HOME", str(home))
    monkeypatch.setenv("NEWTS_SSH", json.dumps([sys.executable, str(REPO / "tests" / "fake_ssh.py")]))
    monkeypatch.setenv("FAKE_SSH_HOME", str(tmp_path / "remote-home"))
    monkeypatch.setenv("FAKE_SSH_LOG", str(tmp_path / "ssh.jsonl"))
    (tmp_path / "remote-home").mkdir()
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    local = tmp_path / "local"
    (local / "lab").mkdir(parents=True)
    (local / "lab" / "config.yaml").write_text("lab:\n  name: \"Local lab\"\ndashboard:\n  port: 8787\n", encoding="utf-8")
    (local / "lab" / "REGISTRY.md").write_text("# Lab Registry\n", encoding="utf-8")
    (hub.lab / "config.yaml").write_text('lab:\n  name: "Remote lab"\n  projects_root: "../projects"\n', encoding="utf-8")
    m = load("dashboard/serve")
    for tgt in (m.ctx,):
        monkeypatch.setattr(tgt, "HUB", local)
        monkeypatch.setattr(tgt, "LAB", local / "lab")
    yield m, hub, tmp_path
    m.ctx.set_remote(None)
    for c in list(m.machines.CONNS.values()):
        c.disconnect()
    subprocess.run([sys.executable, str(REPO / "newts.py"), "--hub", str(hub.root), "--stop"], capture_output=True, timeout=60)


def test_ssh_config_hosts_and_probe_parsing(env, tmp_path, monkeypatch):
    m, _hub, _ = env
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host lambda\n  HostName 1.2.3.4\nHost hpc hpc-gpu\nHost *.cluster !x\nHost *\n", encoding="utf-8")
    monkeypatch.setattr(m.machines.Path, "home", staticmethod(lambda: tmp_path))
    assert m.machines.ssh_hosts() == ["lambda", "hpc", "hpc-gpu"]
    f = m.machines.parse_probe("os=Linux\narch=x86_64\ncmd.uv=/home/u/.local/bin/uv\ncmd.sbatch=/usr/bin/sbatch\ncmd.git=\n"
                               "gpu=GPU 0: NVIDIA A100\npartition=gpu*|2-00:00:00|gpu:a100:4|up\nlab=~/labs/a\n")
    assert f["os"] == "Linux" and f["tools"]["uv"] and f["tools"]["git"] is None and f["scheduler"] == "slurm"
    assert f["gpus"] == ["GPU 0: NVIDIA A100"] and f["partitions"][0] == {"name": "gpu", "default": True,
                                                                         "time_limit": "2-00:00:00", "gres": "gpu:a100:4", "up": True}
    assert f["labs"] == ["~/labs/a"]
    assert m.machines._rpath("~/x y") == '"$HOME/x y"' and m.machines._clean_path('a"; rm -rf /') is None
    assert m.machines._clean_host("-oProxyCommand=evil") is None


@needs_bash
def test_probe_and_auth_failure(env, monkeypatch):
    m, hub, _ = env
    out, code = m.machines.add_machine({"host": "box", "name": "Box"})
    assert code == 200 and out["probe"]["ok"], out
    assert out["machine"]["facts"]["os"] and "uv" in out["machine"]["facts"]["tools"]
    res, _ = m.machines.add_lab({"id": "box", "path": hub.root.as_posix()})
    assert res["exists"]
    monkeypatch.setenv("FAKE_SSH_AUTH", "fail")
    res, _ = m.machines.probe({"id": "box"})
    assert res["kind"] == "auth" and res["needs_interactive"]


def _serve(m):
    srv = m.LabServer(("127.0.0.1", 0), m.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    c.request("GET", "/")
    r = c.getresponse()
    r.read()
    return srv, port, r.getheader("Set-Cookie").split(";", 1)[0]


def _req(port, cookie, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    h = {"Cookie": cookie}
    if body is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(body)
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    return r.status, r.read()


@needs_bash
def test_connect_proxy_and_lose_the_tunnel(env):
    m, hub, tmp_path = env
    m.machines.add_machine({"host": "box", "name": "Box"})
    mach = m.machines._get("box")
    mach["launcher"] = (REPO / "newts.py").as_posix()          # the remote lab would ship its own newts.py
    m.machines._put(mach)
    m.machines.add_lab({"id": "box", "path": hub.root.as_posix()})
    srv, port, cookie = _serve(m)
    try:
        res, code = m.machines.open_lab({"id": "box", "path": hub.root.as_posix()})
        assert code == 200 and res["state"] == "connected", res
        assert m.ctx.REMOTE is not None
        # reads go to the remote lab, tagged with where they came from
        st, raw = _req(port, cookie, "GET", "/api/state")
        snap = json.loads(raw)
        assert st == 200 and snap["remote"]["machine"] == "box" and snap["lab_info"]["name"] == "Remote lab"
        # writes land in the remote lab's files
        st, raw = _req(port, cookie, "POST", "/api/directive", {"target": "hub", "text": "from afar"})
        assert st == 200, raw
        assert "from afar" in (hub.lab / ".bus" / "directives.jsonl").read_text(encoding="utf-8")
        # local-only routes stay local
        st, raw = _req(port, cookie, "GET", "/api/machines")
        assert json.loads(raw)["current"]["machine"] == "box"
        # the event stream is proxied (first snapshot carries the remote tag)
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.request("GET", "/api/events", headers={"Cookie": cookie})
        r = c.getresponse()
        line = b""
        t0 = time.time()
        while not line.startswith(b"data: ") and time.time() - t0 < 15:
            line = r.fp.readline()
        assert b'"remote"' in line
        c.close()
        # lose the tunnel → a clear 502, not a hang
        conn = m.ctx.REMOTE
        conn.want = False
        conn.tunnel.kill()
        conn.tunnel.wait(10)
        time.sleep(0.5)
        st, raw = _req(port, cookie, "GET", "/api/state")
        assert st == 502 and b"lost the connection" in raw
        # back to this computer
        m.machines.local({})
        st, raw = _req(port, cookie, "GET", "/api/state")
        assert st == 200 and "remote" not in json.loads(raw)
        # disconnecting the lab on screen falls back to this computer (and says so, for the page to reload)
        m.ctx.set_remote(conn)
        res, _ = m.machines.disconnect({"id": "box", "path": hub.root.as_posix()})
        assert res["was_current"] and m.ctx.REMOTE is None
    finally:
        srv.shutdown()


@needs_bash
def test_create_a_lab_on_a_remote_machine(env):
    m, _hub, tmp_path = env
    m.machines.add_machine({"host": "box", "name": "Box"})
    dest = (tmp_path / "remote-home" / "labs" / "new-one").as_posix()
    res, code = m.machines.create_lab({"id": "box", "path": dest, "name": "Far lab", "confirm": True})
    assert code == 200, res
    assert (tmp_path / "remote-home" / "labs" / "new-one" / "lab" / "config.yaml").exists()
    assert any(l["path"] == dest for l in m.machines._get("box")["labs"])


def test_detached_processes_never_run_on_uvs_throwaway_python():
    """`uv run --with …` runs in builds-v0/.tmpXXXX, deleted when uv exits — a detached server (and the agent
    supervisors it spawns) must re-exec on a stable interpreter first. The venv's python is a symlink out of
    that directory, so detection must not resolve it."""
    newts, procs = load("newts.py"), load("tools/executor/procs.py")
    if os.name == "nt":
        assert procs._ephemeral(r"C:\Users\u\AppData\Local\uv\cache\builds-v0\.tmpAb12\Scripts\python.exe")
        assert not procs._ephemeral(r"C:\Users\u\lab\.venv\Scripts\python.exe")
    else:
        assert procs._ephemeral("/home/u/.cache/uv/builds-v0/.tmpQy7eFf/bin/python")
        assert not procs._ephemeral("/usr/bin/python3")
        assert not procs._ephemeral("/home/u/lab/.venv/bin/python")
    if not procs._ephemeral(sys.executable):
        assert newts.stable_python() == sys.executable   # the launcher uses the executor's one finder


@needs_bash
def test_one_overview_across_this_computer_and_a_remote_lab(env):
    """The fleet: every lab with what needs you — this computer's from its files, a remote one read through
    its tunnel (/api/summary) — and opening a remote lab keeps it connected until Disconnect."""
    m, hub, tmp_path = env
    hub.add_registry_row("idea-g", state="proposal", next="Gate 1 — review and sign")
    (hub.root / "studies" / "idea-g").mkdir(parents=True, exist_ok=True)
    m.machines.add_machine({"host": "box", "name": "Box"})
    mach = m.machines._get("box")
    mach["launcher"] = (REPO / "newts.py").as_posix()
    m.machines._put(mach)
    m.machines.add_lab({"id": "box", "path": hub.root.as_posix()})
    res, code = m.machines.open_lab({"id": "box", "path": hub.root.as_posix()})
    assert code == 200 and res["state"] == "connected", res
    assert m.machines._get("box")["labs"][0]["keep_connected"] is True     # opened once → kept
    m.fleet._keep_once()                                                    # the keeper reads its summary
    conn = m.machines.CONNS[f"box::{hub.root.as_posix()}"]
    assert conn.summary and conn.summary["needs"] >= 1 and any(t["kind"] == "gate" for t in conn.summary["top"])
    out, _ = m.fleet.fleet()
    remote = next(x for x in out["labs"] if x["kind"] == "remote")
    assert remote["current"] and remote["summary"]["needs"] >= 1 and remote["state"] == "connected"
    assert out["needs_total"] >= 1
    m.machines.disconnect({"id": "box", "path": hub.root.as_posix()})
    assert m.machines._get("box")["labs"][0]["keep_connected"] is False
    assert m.fleet.set_keep({"id": "box", "path": hub.root.as_posix(), "keep": True})[1] == 200
    assert m.fleet.set_keep({"id": "nope", "path": "x", "keep": True})[1] == 404


def test_a_lab_summary_counts_what_needs_you(env):
    m, hub, tmp_path = env
    hub.add_registry_row("idea-s", state="proposal", next="Gate 1 pending")
    (hub.root / "studies" / "idea-s").mkdir(parents=True, exist_ok=True)
    s = m.fleet.lab_summary(hub.root)
    assert s["ok"] and s["needs"] == 1 and s["top"][0]["kind"] == "gate" and s["studies"] >= 1
    (hub.root / "studies" / "idea-s" / "proposal.md").write_text("<!-- PI Gate 1 approved via Vivarium dashboard x -->",
                                                                encoding="utf-8")
    m.fleet._CACHE.clear()
    assert m.fleet.lab_summary(hub.root)["needs"] == 0          # signed → no longer waiting
