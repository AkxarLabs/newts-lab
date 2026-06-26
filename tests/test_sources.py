"""Tests for dashboard/sources.py — the read-only world model the dashboard renders."""

from __future__ import annotations

import json

from conftest import load


def _mod(hub, monkeypatch):
    m = load("dashboard/sources")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def test_parse_registry_reads_rows(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", title="Demo", state="active", project="../projects/demo")
    rows = m.parse_registry()
    assert len(rows) == 1
    assert rows[0]["id"] == "demo"
    assert rows[0]["state"] == "active"
    assert rows[0]["title"] == "Demo"


def test_parse_registry_skips_header_and_divider(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # empty registry (header only) -> no rows
    assert m.parse_registry() == []


def test_snapshot_cold_when_registry_empty(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    snap = m.snapshot()
    assert snap["cold"] is True
    # documented keys present
    for key in ("items", "events", "workers", "slots", "directives", "gates_waiting", "cold"):
        assert key in snap


def test_snapshot_not_cold_with_a_row(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    snap = m.snapshot()
    assert snap["cold"] is False
    assert len(snap["items"]) == 1
    assert snap["items"][0]["id"] == "demo"
    assert snap["items"][0]["has_project"] is True


def test_snapshot_gates_waiting_counts_gate_next_action(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", project="-", next="awaiting PI Gate 1")
    snap = m.snapshot()
    assert snap["gates_waiting"] == 1


def test_project_path_prefers_explicit_column(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", in_root=False)
    p = m._project_path({"id": "demo", "project": str(proj)})
    assert p == proj.resolve()


def test_project_path_falls_back_to_projects_root(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")  # under projects_root
    p = m._project_path({"id": "demo", "project": "-"})
    assert p == proj.resolve()


def test_project_path_unreachable_returns_none(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # no such project anywhere
    assert m._project_path({"id": "ghost", "project": "-"}) is None


# ── workers feed ──────────────────────────────────────────────────────────────

def _worker_log(bus_dir, name, lines):
    wdir = bus_dir / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    with (wdir / name).open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def test_workers_marks_done(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    _worker_log(bus, "w1.jsonl", [
        {"ts": "2026-06-19T10:00:00", "role": "experiment-runner", "event": "start"},
        {"ts": "2026-06-19T10:01:00", "event": "action", "tool": "Read", "summary": "Read: x",
         "kind": "read"},
        {"ts": "2026-06-19T10:02:00", "event": "stop"},
    ])
    workers = m._workers(bus, None)
    assert len(workers) == 1
    w = workers[0]
    assert w["role"] == "experiment-runner"
    assert w["status"] == "done"  # saw a stop event
    assert w["n_actions"] == 1


def test_workers_marks_working(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    # fresh activity, no stop -> working (file mtime is now)
    _worker_log(bus, "w2.jsonl", [
        {"ts": "2026-06-19T10:00:00", "role": "orchestrator", "event": "start"},
        {"ts": "2026-06-19T10:01:00", "event": "action", "tool": "Edit", "summary": "Edit: y",
         "kind": "edit"},
    ])
    workers = m._workers(bus, None)
    assert workers[0]["status"] == "working"


# ── editor deep-links + paper status ───────────────────────────────────────────

def test_snapshot_includes_editor_scheme(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # the fixture config has no `editor` key -> the documented default
    assert m.snapshot()["editor"] == "vscode"


def test_editor_scheme_reads_config(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text("dashboard:\n  editor: cursor\n", encoding="utf-8")
    assert m.editor_scheme() == "cursor"


def test_paper_status_none_without_pdf(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m._paper_status("demo") is None


def test_paper_status_reports_pdf_and_tex(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    pdir = hub.root / "studies" / "demo" / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "main.pdf").write_bytes(b"%PDF-1.5")
    (pdir / "main.tex").write_text("x", encoding="utf-8")
    st = m._paper_status("demo")
    assert st and st["pdf"] is True and isinstance(st["mtime"], int)
    assert st["tex"].endswith("main.tex")


def test_snapshot_item_carries_paper(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    pdir = hub.root / "studies" / "demo" / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "main.pdf").write_bytes(b"%PDF")
    it = m.snapshot()["items"][0]
    assert it["paper"] and it["paper"]["pdf"] is True


def test_claims_count(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m._claims_count("demo") == 0                  # no file
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n  - id: C002\n", encoding="utf-8")
    assert m._claims_count("demo") == 2


def test_claims_count_counts_only_dict_items(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    # a bare-string list item must NOT be counted — parity with serve.claims_map's dict filter,
    # so the "claims (N)" button never disagrees with the rendered rows
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n  - just a string\n  - id: C002\n", encoding="utf-8")
    assert m._claims_count("demo") == 2


def test_snapshot_item_carries_claims_count(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n", encoding="utf-8")
    assert m.snapshot()["items"][0]["claims"] == 1
