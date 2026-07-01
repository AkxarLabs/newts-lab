"""Tests for templates/project/scripts/_runner_guards.py — the runner-boundary Gate-2 + compute-slot
guards that scripts/run.py and scripts/sweep.py call so a FULL run / PILOT+FULL campaign cannot
bypass the signed envelope or the slot ledger, even when invoked directly.

We inject a fake `runner` (stand-in for subprocess.run) so no hub tools actually execute; we assert
the guard *decides* correctly (SMOKE no-op, FULL blocks on a nonzero guard, env markers short-circuit,
ids parsed from stdout). End-to-end behavior with real tools is exercised by the spawn-smoke CI.
"""

from __future__ import annotations

import types

import pytest
from conftest import REPO, load

G = load("templates/project/scripts/_runner_guards")

# hub_path must resolve to an existing dir (the guards check Path(hub).exists()); the repo root works
# because the fake runner never actually executes the tool under it.
CONTROL = {"hub_path": str(REPO), "project": "demo"}


def _fake(returncode=0, stdout="", stderr="", sink=None):
    def run(cmd, **kw):
        if sink is not None:
            sink.append(cmd)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return run


# ── stage helper ──────────────────────────────────────────────────────────────

def test_stage_of_defaults_smoke():
    assert G.stage_of({}) == "SMOKE"
    assert G.stage_of({"stage": "full"}) == "FULL"
    assert G.stage_of({"stage": "PILOT"}) == "PILOT"


# ── Gate 2 preflight ──────────────────────────────────────────────────────────

def test_gate2_smoke_is_noop():
    calls = []
    G.gate2_preflight(CONTROL, "exp.yaml", {"stage": "SMOKE"}, runner=_fake(sink=calls))
    assert calls == []  # SMOKE never calls the guard


def test_gate2_pilot_is_noop():
    calls = []
    G.gate2_preflight(CONTROL, "exp.yaml", {"stage": "PILOT"}, runner=_fake(sink=calls))
    assert calls == []


def test_gate2_full_ok_passes_and_calls_guard():
    calls = []
    G.gate2_preflight(CONTROL, "exp.yaml", {"stage": "FULL", "budget": {"max_minutes": 30}},
                      runner=_fake(returncode=0, sink=calls))
    assert calls and "full-run" in calls[0] and "--planned-minutes" in calls[0]


def test_gate2_full_blocked_raises():
    with pytest.raises(SystemExit):
        G.gate2_preflight(CONTROL, "exp.yaml", {"stage": "FULL"}, runner=_fake(returncode=1))


def test_gate2_full_skipped_when_env_marks_cleared(monkeypatch):
    monkeypatch.setenv("AUTOSCIENTIST_GATE2_OK", "1")
    calls = []
    G.gate2_preflight(CONTROL, "exp.yaml", {"stage": "FULL"}, runner=_fake(sink=calls))
    assert calls == []  # a sweep child inherits the campaign's clearance


def test_gate2_full_missing_hub_raises():
    with pytest.raises(SystemExit):
        G.gate2_preflight({"hub_path": "", "project": "demo"}, "exp.yaml",
                          {"stage": "FULL"}, runner=_fake())


# ── sweep reservation ─────────────────────────────────────────────────────────

def test_reserve_full_sweep_parses_reservation_id():
    rid = G.reserve_full_sweep(
        CONTROL, "exp.yaml", 6, 30, "exp-004",
        runner=_fake(returncode=0, stdout="[guard] reserved FULL capacity: RID-1\n[guard] OK: fits\n"))
    assert rid == "RID-1"


def test_reserve_full_sweep_blocked_raises():
    with pytest.raises(SystemExit):
        G.reserve_full_sweep(CONTROL, "exp.yaml", 6, 30, "exp-004", runner=_fake(returncode=1))


def test_reserve_full_sweep_none_when_no_marker():
    rid = G.reserve_full_sweep(CONTROL, "exp.yaml", 6, 30, "exp-004",
                               runner=_fake(returncode=0, stdout="[guard] OK: fits\n"))
    assert rid is None


# ── compute slots ─────────────────────────────────────────────────────────────

def test_acquire_slot_returns_id():
    sid = G.acquire_slot(CONTROL, "exp-004",
                         runner=_fake(returncode=0, stdout="20260101-000000-demo-exp\n"))
    assert sid == "20260101-000000-demo-exp"


def test_acquire_slot_denied_raises():
    with pytest.raises(SystemExit):
        G.acquire_slot(CONTROL, "exp-004",
                       runner=_fake(returncode=1, stdout="DENIED — 1/1 slots in use"))


def test_acquire_slot_missing_hub_raises():
    with pytest.raises(SystemExit):
        G.acquire_slot({"hub_path": "", "project": "demo"}, "exp-004", runner=_fake())


def test_release_helpers_call_runner():
    calls = []
    G.release_slot(CONTROL, "slot-1", runner=_fake(sink=calls))
    G.release_reservation(CONTROL, "resv-1", runner=_fake(sink=calls))
    assert len(calls) == 2


def test_release_noop_when_id_none():
    calls = []
    G.release_slot(CONTROL, None, runner=_fake(sink=calls))
    G.release_reservation(CONTROL, None, runner=_fake(sink=calls))
    assert calls == []
