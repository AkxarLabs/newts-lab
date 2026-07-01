"""Tests for tools/configure.py — owner-aware config view/set/profile."""

from __future__ import annotations

import textwrap
import types

from conftest import load

C = load("configure")

_LAB_CFG = textwrap.dedent("""\
    lab:
      projects_root: "../projects"
    experiment:
      num_drafts: 3
      multi_seed_n: 3
    oversight:
      level: standard
    loop:
      mode: execute
      no_progress_backoff_cycles: 3
    eval_frozen: true
    """)


def _mod(hub, monkeypatch):
    m = load("configure")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def _set_ns(assignment, *, project=None, pi_approved=False, signed_via=None):
    return types.SimpleNamespace(assignment=assignment, project=project,
                                 pi_approved=pi_approved, signed_via=signed_via)


# ── ownership map ─────────────────────────────────────────────────────────────

def test_is_pi_owned_true():
    for k in ("lab.projects_root", "compute.max_concurrent_runs", "agents.reviewer_model",
              "critique.ensemble_own_draft", "writing.page_limit", "budgets.max_minutes",
              "gate2_envelope.pi_signed", "eval_frozen", "oversight.level", "loop.mode",
              "loop.explore_max_expansion_rounds", "ideation.in_project",
              "ideation.in_project_approval", "writing.venue", "autopilot.max_concurrent_projects"):
        assert C.is_pi_owned(k) is True, k


def test_is_pi_owned_false():
    for k in ("experiment.num_drafts", "experiment.multi_seed_n", "loop.no_progress_backoff_cycles",
              "loop.monitor_poll_seconds", "ideation.candidates", "discuss.max_research_minutes",
              "scoping.options_per_decision"):
        assert C.is_pi_owned(k) is False, k


def test_parse_value():
    assert C._parse_value("true") is True and C._parse_value("false") is False
    assert C._parse_value("null") is None
    assert C._parse_value("4") == 4 and isinstance(C._parse_value("4"), int)
    assert C._parse_value("0.5") == 0.5
    assert C._parse_value("standard") == "standard"


# ── set: owner gate + comment-preserving stamp ────────────────────────────────

def test_set_agent_key_applies_to_lab(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    assert m.cmd_set(_set_ns("experiment.num_drafts=5")) == 0
    assert "num_drafts: 5" in (hub.lab / "config.yaml").read_text(encoding="utf-8")


def test_set_pi_key_blocked_without_flag(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    assert m.cmd_set(_set_ns("oversight.level=off")) == 1
    assert "level: standard" in (hub.lab / "config.yaml").read_text(encoding="utf-8")  # unchanged


def test_set_pi_key_allowed_with_flag(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    assert m.cmd_set(_set_ns("loop.mode=explore", pi_approved=True)) == 0
    assert "mode: explore" in (hub.lab / "config.yaml").read_text(encoding="utf-8")


def test_set_eval_frozen_false_needs_flag_and_warns(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    assert m.cmd_set(_set_ns("eval_frozen=false")) == 1              # blocked without flag
    assert m.cmd_set(_set_ns("eval_frozen=false", pi_approved=True)) == 0
    assert "UNFREEZES" in capsys.readouterr().out
    assert "eval_frozen: false" in (hub.lab / "config.yaml").read_text(encoding="utf-8")


def test_set_key_not_found(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    assert m.cmd_set(_set_ns("experiment.nonexistent=5")) == 1


def test_set_preserves_inline_comment(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text("experiment:\n  num_drafts: 3   # how many drafts\n", encoding="utf-8")
    m.cmd_set(_set_ns("experiment.num_drafts=7"))
    txt = (hub.lab / "config.yaml").read_text(encoding="utf-8")
    assert "num_drafts: 7" in txt and "# how many drafts" in txt


def test_set_project_control_yaml(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text(_LAB_CFG, encoding="utf-8")
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    # budgets.max_minutes is PI-owned -> needs the flag; writes to the PROJECT control.yaml
    assert m.cmd_set(_set_ns("budgets.max_minutes=20", project="demo")) == 1
    assert m.cmd_set(_set_ns("budgets.max_minutes=20", project="demo", pi_approved=True)) == 0
    assert "max_minutes: 20" in (proj / "control.yaml").read_text(encoding="utf-8")
