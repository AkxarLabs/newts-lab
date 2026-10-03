"""dashboard/term.py — in-browser terminal sessions (fixed commands; a PTY on POSIX, pipes on Windows)."""

from __future__ import annotations

import base64
import json
import os
import sys
import time

import pytest

from conftest import REPO, load

FAKE = REPO / "tests" / "fake_claude.py"


@pytest.fixture
def m(hub, monkeypatch):
    (hub.lab / "config.yaml").write_text(
        "agents:\n  programmatic:\n    enabled: true\n    backends:\n      claude:\n"
        f"        command: {json.dumps([sys.executable, str(FAKE)])}\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    mod = load("dashboard/serve")
    for tgt in (mod.ctx,):
        monkeypatch.setattr(tgt, "HUB", hub.root)
        monkeypatch.setattr(tgt, "LAB", hub.lab)
    return mod


def _drain(term, sid, want, timeout=20):
    out, off, t0 = b"", 0, time.time()
    while time.time() - t0 < timeout:
        r, _ = term.read({"id": sid, "offset": off})
        out += base64.b64decode(r["data"])
        off = r["offset"]
        if want in out or r["exited"]:
            return out, r
        time.sleep(0.05)
    return out, r


def test_session_round_trip(m):
    s = m.term.Session([sys.executable, "-u", "-c", "import sys; print('ready'); l=sys.stdin.readline(); print('got', l.strip())"],
                       str(REPO), "test")
    m.term.SESSIONS[s.id] = s
    out, _ = _drain(m.term, s.id, b"ready")
    assert b"ready" in out
    m.term.write({"id": s.id, "data": "hello\r"})
    out, r = _drain(m.term, s.id, b"got hello")
    assert b"got hello" in out
    out, r = _drain(m.term, s.id, b"[finished")
    assert r["exited"]


@pytest.mark.skipif(os.name != "posix", reason="a real PTY is POSIX-only")
def test_pty_is_a_tty_and_resizes(m):
    s = m.term.Session([sys.executable, "-u", "-c", "import os,sys,time; print('tty', os.isatty(0)); time.sleep(0.5); print(os.get_terminal_size())"],
                       str(REPO), "test", cols=91, rows=17)
    m.term.SESSIONS[s.id] = s
    out, _ = _drain(m.term, s.id, b"columns")
    assert b"tty True" in out and b"columns=91" in out


def test_only_fixed_purposes(m, hub):
    assert m.term.open_session({"purpose": "exec", "backend": "claude"})[1] == 400
    assert m.term.open_session({"purpose": "login", "backend": "rm -rf"})[1] == 400
    out, code = m.term.open_session({"purpose": "login", "backend": "claude"})
    assert code == 200, out
    assert "fake_claude.py" in out["command"] and "auth login" in out["command"]
    m.term.close({"id": out["id"]})
    pi = [json.loads(x) for x in (hub.lab / ".bus" / "pi-actions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert pi[-1]["action"] == "term.login"
    assert m.term.read({"id": "nope"})[1] == 404
