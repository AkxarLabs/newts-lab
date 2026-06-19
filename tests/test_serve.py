"""Tests for dashboard/serve.py — the local control surface (NO server bind).

serve.py does `import sources` at module load (it inserts dashboard/ on sys.path). We call the
pure functions directly. serve resolves project/control paths through `sources`, so we override
BOTH serve.HUB/serve.LAB AND the sources module object serve actually imported
(serve.sources.HUB / .LAB). No socket is ever bound.
"""

from __future__ import annotations

from conftest import REPO, load


def _mod(hub, monkeypatch):
    # Ensure `import sources` inside serve.py resolves to the real dashboard/sources.py.
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    # serve holds a reference to the sources module — patch its globals too.
    monkeypatch.setattr(m.sources, "HUB", hub.root)
    monkeypatch.setattr(m.sources, "LAB", hub.lab)
    return m


# ── run_tool whitelist ────────────────────────────────────────────────────────

def test_run_tool_rejects_non_whitelisted(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    res = m.run_tool("rm_rf")
    assert "error" in res
    assert "whitelist" in res["error"]


def test_safe_tools_set_is_read_only(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert "check_lab" in m.SAFE_TOOLS
    # nothing that trains/writes
    assert "run" not in m.SAFE_TOOLS and "sweep" not in m.SAFE_TOOLS


# ── gate approval ─────────────────────────────────────────────────────────────

def test_gate3_never_signable(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    res = m.approve_gate("demo", 3)
    assert "error" in res
    assert "Gate 3" in res["error"]


def test_gate2_expired_envelope_errors(hub, monkeypatch):
    import time
    m = _mod(hub, monkeypatch)
    past = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 30))
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": past,
        "full_runs": 4, "per_run_max_minutes": 30, "total_max_minutes": 120})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert "error" in res
    assert "expired" in res["error"]


def test_gate2_all_zero_envelope_returns_warning(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": None,
        "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert res.get("ok") is True
    assert res.get("warnings")  # non-empty warnings list
    assert any("authorizes nothing" in w for w in res["warnings"])


def test_gate2_successful_sign_writes_signed_and_signed_via(hub, monkeypatch):
    import yaml
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": None,
        "full_runs": 4, "per_run_max_minutes": 30, "total_max_minutes": 120})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert res.get("ok") is True
    doc = yaml.safe_load((proj / "control.yaml").read_text(encoding="utf-8"))
    env = doc["gate2_envelope"]
    assert env["pi_signed"] is True
    assert str(env["signed_via"]).startswith("dashboard:")


def test_gate1_signs_proposal_and_leaves_command(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    prop = hub.root / "ideas" / "demo" / "proposal.md"
    prop.parent.mkdir(parents=True, exist_ok=True)
    prop.write_text("# Proposal\n", encoding="utf-8")
    res = m.approve_gate("demo", 1)
    assert res.get("ok") is True
    assert "Gate 1 approved" in prop.read_text(encoding="utf-8")
