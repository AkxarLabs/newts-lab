"""Tests for tools/run_slots.py — the cross-project compute-slot ledger.

main() reads sys.argv; we drive it via monkeypatch.setattr(sys, "argv", [...]) and capture the
exit code. The hub global resolves config (max_concurrent_runs / stale_slot_minutes); SLOTS is
the on-disk ledger dir. Both are overridden onto tmp_path. lab_bus is best-effort; we point its
bus at tmp_path too so no real lab is touched.
"""

from __future__ import annotations

import json
import os
import sys
import time

import yaml
from conftest import load


def _mod(hub, monkeypatch, *, max_runs=1, stale_minutes=360):
    # write a config with the desired caps
    cfg = yaml.safe_load((hub.lab / "config.yaml").read_text(encoding="utf-8"))
    cfg["compute"] = {"max_concurrent_runs": max_runs, "stale_slot_minutes": stale_minutes}
    (hub.lab / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")

    m = load("run_slots")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "SLOTS", hub.lab / ".slots")
    # neutralize the optional bus side-channel so it can't write to the real lab
    if m.lab_bus is not None:
        monkeypatch.setattr(m, "lab_bus", None)
    return m


def _run(m, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["run_slots.py", *argv])
    return m.main()


def test_acquire_under_cap_grants(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch, max_runs=2)
    assert _run(m, monkeypatch, "acquire", "projA", "smoke") == 0
    out = capsys.readouterr().out.strip()
    assert out  # the slot id is printed on stdout
    assert len(list((hub.lab / ".slots").glob("*.json"))) == 1


def test_acquire_over_cap_denied(hub, monkeypatch):
    m = _mod(hub, monkeypatch, max_runs=1)
    assert _run(m, monkeypatch, "acquire", "projA", "run1") == 0
    assert _run(m, monkeypatch, "acquire", "projB", "run2") == 1  # cap = 1, already full


def test_release_frees_a_slot(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch, max_runs=1)
    _run(m, monkeypatch, "acquire", "projA", "run1")
    slot_id = capsys.readouterr().out.strip()
    assert _run(m, monkeypatch, "release", slot_id) == 0
    assert list((hub.lab / ".slots").glob("*.json")) == []
    # and a fresh acquire now succeeds
    assert _run(m, monkeypatch, "acquire", "projB", "run2") == 0


def test_release_unknown_slot_is_not_an_error(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert _run(m, monkeypatch, "release", "does-not-exist") == 0


def test_status_always_zero(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch, max_runs=2)
    _run(m, monkeypatch, "acquire", "projA", "run1")
    capsys.readouterr()
    assert _run(m, monkeypatch, "status") == 0
    out = capsys.readouterr().out
    assert "1/2 slots in use" in out


def test_touch_unknown_slot_returns_1(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert _run(m, monkeypatch, "touch", "nope") == 1


def test_stale_slot_reclaimed_on_any_invocation(hub, monkeypatch):
    # stale threshold tiny; plant an old slot file then invoke status -> it is reclaimed.
    m = _mod(hub, monkeypatch, max_runs=1, stale_minutes=0.01)  # ~0.6s
    slots = hub.lab / ".slots"
    slots.mkdir(parents=True, exist_ok=True)
    stale = slots / "old-slot.json"
    stale.write_text(json.dumps({"project": "p", "label": "l", "acquired": 0}), encoding="utf-8")
    old = time.time() - 600
    os.utime(stale, (old, old))  # mtime well past the 0.6s threshold
    _run(m, monkeypatch, "status")
    assert not stale.exists()  # reclaimed
