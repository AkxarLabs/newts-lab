"""Tests for tools/lab_bus.py — the append-only event bus + directive inbox."""

from __future__ import annotations

import json
import types

from conftest import load


def _mod(hub, monkeypatch, bus_dir=None):
    m = load("lab_bus")
    bus = bus_dir or (hub.lab / ".bus")
    monkeypatch.setattr(m, "BUS", bus)
    monkeypatch.setattr(m, "SOURCE", "hub")
    return m, bus


def _lines(bus):
    f = bus / "events.jsonl"
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_kinds_include_escalation_and_approach_ideate(hub, monkeypatch):
    m, _ = _mod(hub, monkeypatch)
    assert "escalation" in m.KINDS
    assert "approach_ideate" in m.KINDS


def test_emit_appends_json_line_with_kind(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    m.emit("state_change", idea="demo", detail="seed->triaged")
    rows = _lines(bus)
    assert len(rows) == 1
    assert rows[0]["kind"] == "state_change"
    assert rows[0]["idea"] == "demo"
    assert rows[0]["source"] == "hub"


def test_emit_is_append_only(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    m.emit("note", detail="one")
    m.emit("cycle", detail="two")
    rows = _lines(bus)
    assert [r["kind"] for r in rows] == ["note", "cycle"]


def test_cmd_escalate_emits_escalation_kind(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    args = types.SimpleNamespace(idea="demo", detail="headline reopen fired", severity="high")
    assert m.cmd_escalate(args) == 0
    rows = _lines(bus)
    assert rows[-1]["kind"] == "escalation"
    assert rows[-1]["data"]["severity"] == "high"


# ── directive resolution ──────────────────────────────────────────────────────

def _write_directives(bus, records):
    bus.mkdir(parents=True, exist_ok=True)
    with (bus / "directives.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_unresolved_directive_is_pending(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    _write_directives(bus, [{"id": "d-001", "ts": "t", "text": "prioritize demo"}])
    pending = m.unresolved_directives()
    assert len(pending) == 1
    assert pending[0]["id"] == "d-001"
    assert pending[0]["_status"] == "pending"


def test_directive_dropped_after_done_ack(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    _write_directives(bus, [{"id": "d-001", "ts": "t", "text": "prioritize demo"}])
    # ack done references the directive id via data.ref
    m.emit("directive_done", data={"ref": "d-001"})
    assert m.unresolved_directives() == []


def test_directive_still_pending_after_only_seen_ack(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    _write_directives(bus, [{"id": "d-001", "ts": "t", "text": "do x"}])
    m.emit("directive_seen", data={"ref": "d-001"})
    pending = m.unresolved_directives()
    assert len(pending) == 1
    assert pending[0]["_status"] == "seen"


def test_directive_dropped_when_withdrawn(hub, monkeypatch):
    m, bus = _mod(hub, monkeypatch)
    _write_directives(bus, [
        {"id": "d-001", "ts": "t", "text": "do x"},
        {"kind": "withdraw", "ref": "d-001", "ts": "t2"},
    ])
    assert m.unresolved_directives() == []
