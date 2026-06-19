"""Tests for tools/guard.py — the mechanical lifecycle guards.

Each c_* function returns an exit code: 0 OK · 1 BLOCKED · 2 WARN. We call them directly with
a tiny SimpleNamespace args object and assert the code.
"""

from __future__ import annotations

import time
import types

from conftest import load


def _mod(hub, monkeypatch):
    m = load("guard")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def _proposal(hub, slug, text):
    p = hub.root / "ideas" / slug / "proposal.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── spawn (Gate 1) ────────────────────────────────────────────────────────────

def test_spawn_blocked_without_proposal(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m.c_spawn(types.SimpleNamespace(slug="x")) == 1


def test_spawn_blocked_without_gate1_marker(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _proposal(hub, "demo", "# Proposal\nNo approval here.\n")
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_spawn(types.SimpleNamespace(slug="demo")) == 1


def test_spawn_ok_with_gate1_marker(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _proposal(hub, "demo", "# Proposal\n\nPI Gate 1 approved.\n")
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_spawn(types.SimpleNamespace(slug="demo")) == 0


# ── full-run (Gate 2 envelope) ────────────────────────────────────────────────

def _future():
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * 30))


def _past():
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 30))


def test_full_run_ok_signed_unexpired_nonzero(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _future(), "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 0


def test_full_run_blocked_unsigned(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={"pi_signed": False, "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


def test_full_run_blocked_expired(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _past(), "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


def test_full_run_blocked_all_zero_caps(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _future(),
        "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


# ── frozen ────────────────────────────────────────────────────────────────────

def test_frozen_ok(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", eval_frozen=True)
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 0


def test_frozen_blocked_when_unfrozen(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", eval_frozen=False)
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 1


def test_frozen_blocked_when_block_missing(hub, monkeypatch):
    import yaml
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    # control.yaml with eval_frozen but no budgets/seeds/gate2_envelope
    (proj / "control.yaml").write_text(yaml.safe_dump({"eval_frozen": True}), encoding="utf-8")
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 1


# ── state transitions ─────────────────────────────────────────────────────────

def _ns(slug, frm, to):
    return types.SimpleNamespace(slug=slug, frm=frm, to=to)


def test_state_legal_forward(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_state(_ns("demo", "proposal", "active")) == 0


def test_state_documented_back_edge(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    assert m.c_state(_ns("demo", "writing", "active")) == 0


def test_state_blocked_wrong_from_state(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    # row says active, but we claim from=proposal
    assert m.c_state(_ns("demo", "proposal", "active")) == 1


def test_state_blocked_illegal_edge(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="seed", project="-")
    assert m.c_state(_ns("demo", "seed", "final")) == 1


def test_state_park_kill_from_anywhere(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    assert m.c_state(_ns("demo", "active", "parked")) == 0
    hub.add_registry_row("demo2", state="seed", project="-")
    assert m.c_state(_ns("demo2", "seed", "killed")) == 0


# ── append-only ───────────────────────────────────────────────────────────────

def _ledger_project(hub, slug, lines):
    proj = hub.make_project(slug)
    (proj / "EXPERIMENT_LOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hub.add_registry_row(slug, state="active", project=str(proj))
    return proj


def test_append_only_baseline_then_append_ok(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0  # records baseline
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1\nentry 2\nentry 3\n", encoding="utf-8")
    assert m.c_append_only(a) == 0  # pure append -> OK


def test_append_only_rewrite_violation(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0
    # rewrite an earlier line -> violation
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1 TAMPERED\nentry 2\n", encoding="utf-8")
    assert m.c_append_only(a) == 1


def test_append_only_removed_line_violation(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2", "entry 3"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1\nentry 2\n", encoding="utf-8")  # shrank
    assert m.c_append_only(a) == 1


# ── writeback ─────────────────────────────────────────────────────────────────

def test_writeback_ok_with_dated_notebook_naming_slug(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    today = time.strftime("%Y-%m-%d")
    hub.notebook_entry(f"{today}-demo.md", "# Notebook — demo\nworked on demo today\n")
    assert m.c_writeback(types.SimpleNamespace(slug="demo")) == 0


def test_writeback_warn_when_nothing(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    assert m.c_writeback(types.SimpleNamespace(slug="demo")) == 2
