"""Tests for tools/lab_bus.py — the append-only event bus + directive inbox."""

from __future__ import annotations

import json
import types

from conftest import REPO, load


def _mod(hub, monkeypatch, bus_dir=None):
    m = load("lab_bus")
    bus = bus_dir or (hub.lab / ".bus")
    monkeypatch.setattr(m, "BUS", bus)
    monkeypatch.setattr(m, "SOURCE", "hub")
    return m, bus


def _lines(bus):
    f = bus / "events.jsonl"
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── drift guard: the project-template copy is byte-identical to the hub's ──────────
# lab_bus.py auto-detects hub vs project at runtime (IS_HUB), so ONE source serves both and the
# two files must stay byte-for-byte equal — a new KIND or directive-ack tweak in the hub copy
# must not leave projects on stale bus semantics (the dashboard reads both).

def test_template_lab_bus_byte_identical_to_hub():
    hub = (REPO / "tools" / "lab_bus.py").read_text(encoding="utf-8")
    tpl = (REPO / "templates" / "project" / "scripts" / "lab_bus.py").read_text(encoding="utf-8")
    assert hub == tpl, "tools/lab_bus.py and templates/project/scripts/lab_bus.py have drifted"


def test_template_trace_hook_byte_identical_to_hub():
    hub = (REPO / "tools" / "trace_hook.py").read_text(encoding="utf-8")
    tpl = (REPO / "templates" / "project" / "scripts" / "trace_hook.py").read_text(encoding="utf-8")
    assert hub == tpl, "tools/trace_hook.py and templates/project/scripts/trace_hook.py have drifted"


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


def test_cmd_escalate_stamps_resolvable_id(hub, monkeypatch):
    # the escalation carries a stable id so it can later be RESOLVED (escalation_resolved --data ref=<id>)
    m, bus = _mod(hub, monkeypatch)
    args = types.SimpleNamespace(idea="demo", detail="blocked on frozen", severity=None)
    m.cmd_escalate(args)
    assert str(_lines(bus)[-1]["data"]["id"]).startswith("e-")


def test_cmd_escalate_ids_are_unique_within_a_second(hub, monkeypatch):
    # two identical escalations emitted in the same (coarse-resolution) tick must NOT collide onto one
    # id — else resolving one would resolve both. Random ids, not clock-derived.
    m, bus = _mod(hub, monkeypatch)
    args = types.SimpleNamespace(idea="demo", detail="same detail", severity=None)
    m.cmd_escalate(args)
    m.cmd_escalate(args)
    ids = [r["data"]["id"] for r in _lines(bus) if r["kind"] == "escalation"]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_escalation_resolved_is_a_known_kind(hub, monkeypatch):
    m, _ = _mod(hub, monkeypatch)
    assert "escalation_resolved" in m.KINDS   # so `emit escalation_resolved --data ref=<id>` is accepted


def test_inbox_shows_directive_target(hub, monkeypatch, capsys):
    # M2: a directive aimed at a specific idea that landed on this bus names its target in the inbox
    m, bus = _mod(hub, monkeypatch)
    _write_directives(bus, [{"id": "d-001", "ts": "t", "text": "park it", "target": "spark-1"}])
    m.cmd_inbox(types.SimpleNamespace())
    assert "spark-1" in capsys.readouterr().out


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


def test_executor_kinds_and_run_report_autofills_run_id(hub, monkeypatch):
    """Headless runs emit a machine-readable footer; its run id comes from NEWTS_RUN_ID when omitted."""
    import types
    m, bus = _mod(hub, monkeypatch)
    assert {"agent_waiting", "agent_resumed", "run_report"} <= m.KINDS
    monkeypatch.setenv("NEWTS_RUN_ID", "hub-propose-x-1")
    m.cmd_emit(types.SimpleNamespace(kind="run_report", idea=None, run_id=None, stage=None, status=None,
                                     detail=None, data=["next=/spawn-project x", "needs_pi=gate1", "summary=ready"]))
    ev = m._read_jsonl(bus / "events.jsonl")[-1]
    assert ev["kind"] == "run_report" and ev["run_id"] == "hub-propose-x-1"
    assert ev["data"] == {"next": "/spawn-project x", "needs_pi": "gate1", "summary": "ready"}
