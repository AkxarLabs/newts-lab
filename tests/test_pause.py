"""Pause the lab (tools/executor/pause.py): one switch that stops every live run (resumably), holds the
queue, keeps campaigns from passing and chains/repeats from firing — and a resume that releases it all.
Also the campaign spend cap, the dashboard endpoint (POST /api/lab/pause), the snapshot field and the CLI.
Nothing is spawned: the scheduler gets an injected spawn()."""

from __future__ import annotations

import json
import sys

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec, campaigns, manifest, pause  # noqa: E402

from test_executor import Spawns, setup  # noqa: E402
from test_campaigns import camp, _cycles, _finish, _stopped  # noqa: E402,F401 — the campaign fixture

CAPS = "    max_concurrent_total: 6\n    hub_max_concurrent: 3\n"


def _q(lab, **kw):
    return executor.enqueue(lab, RunSpec(skill="lab-status", target="hub", created_by="test", **kw))["run_id"]


def _m(lab, rid):
    return executor.find_run(lab, rid)[3]


def _set(lab, rid, status, **fields):
    _t, _w, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, status, by="test", **fields)


def test_pausing_stops_live_runs_and_holds_the_queue_and_resume_releases(hub):
    lab = setup(hub, extra=CAPS)
    a = _q(lab)
    executor.tick(lab, spawn=Spawns())
    _set(lab, a, "running", pid=None)            # a working agent (its supervisor is gone: stop kills + records)
    b = _q(lab)                                   # queued behind it
    out = pause.pause(lab, by="test")
    assert out["paused"] and not out["already"] and out["stopped"] == [a]
    assert _m(lab, a)["status"] == "killed" and _m(lab, b)["status"] == "queued"
    assert pause.state(lab)["by"] == "test" and pause.state(lab)["since"]
    rep = executor.tick(lab, spawn=Spawns())
    assert rep["started"] == [] and rep["paused"] and _m(lab, b)["status"] == "queued"   # held
    again = pause.pause(lab, by="test")
    assert again["already"] and again["stopped"] == []          # idempotent
    assert not executor.scheduler.has_work(lab)                 # nobody needs to keep ticking for a held queue
    ev = [json.loads(x) for x in (lab.lab / ".bus" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [e["kind"] for e in ev].count("lab_paused") == 1
    r = pause.resume(lab, by="test")
    assert not r["paused"] and not r["already"] and r["stopped_earlier"] == [a]
    assert pause.state(lab) is None
    sp = Spawns()
    rep = executor.tick(lab, spawn=sp)
    assert rep["started"] == [b] and _m(lab, a)["status"] == "killed"   # the stopped run stays stopped
    assert pause.resume(lab)["already"] is True


def test_a_paused_lab_refuses_to_start_a_queued_run(hub):
    lab = setup(hub, extra=CAPS)
    pause.pause(lab)
    rid = _q(lab)                                 # queuing is still allowed — it waits
    sp = Spawns()
    for _ in range(3):
        assert executor.tick(lab, spawn=sp)["started"] == []
    assert sp.calls == [] and _m(lab, rid)["status"] == "queued"


def test_a_starting_run_gets_the_stop_marker(hub):
    lab = setup(hub, extra=CAPS)
    a = _q(lab)
    executor.tick(lab, spawn=Spawns())            # "starting": its supervisor is still coming up
    out = pause.pause(lab)
    assert out["stopped"] == [a]
    _t, _w, path, _m2 = executor.find_run(lab, a)
    assert (manifest.run_dir(path.parent, a) / "stop").exists()


def test_repeats_and_chains_do_not_fire_while_paused(hub):
    lab = setup(hub, extra=CAPS)
    rid = _q(lab, repeat_minutes=30)
    executor.tick(lab, spawn=Spawns())
    pause.pause(lab)
    _set(lab, rid, "completed", finished=manifest.now())   # it finished just as the lab paused
    executor.tick(lab, spawn=Spawns())
    m = _m(lab, rid)
    assert not m.get("repeat_child") and not m.get("post_processed")
    pause.resume(lab)
    executor.tick(lab, spawn=Spawns())
    assert _m(lab, rid).get("repeat_child")       # follows up once the lab runs again


def test_campaigns_do_not_pass_while_paused_and_resume_with_the_lab(camp):
    lab, make = camp
    make(repeat_minutes=20)
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    out = pause.pause(lab)
    name = campaigns.all_states(lab)[0]["name"]
    st = campaigns.load(lab, name)
    assert out["campaigns"] == [name] and st["status"] == "paused" and st["paused_by_lab"]
    assert _stopped(lab, c1["run_id"])
    _finish(lab, c1["run_id"], "killed", reason="stopped by the PI")   # what its supervisor records
    for _ in range(2):
        executor.tick(lab, spawn=Spawns())
    assert len(_cycles(lab)) == 1                 # no pass while paused
    assert campaigns.summary(lab)[0]["paused_by_lab"] is True
    r = pause.resume(lab)
    assert r["campaigns"] == [name] and campaigns.load(lab, name)["status"] == "active"
    executor.tick(lab, spawn=Spawns())
    st = campaigns.load(lab, name)
    assert st["status"] == "active"               # a cycle the pause stopped doesn't pause the campaign
    assert len(_cycles(lab)) == 2 and not _cycles(lab)[-1]["campaign_final"]


def test_a_campaign_the_pi_paused_stays_paused_after_the_lab_resumes(camp):
    lab, make = camp
    make()
    name = campaigns.all_states(lab)[0]["name"]
    campaigns.control(lab, name, "pause")
    out = pause.pause(lab)
    assert out["campaigns"] == []
    pause.resume(lab)
    assert campaigns.load(lab, name)["status"] == "paused"


# ── the campaign spend cap ───────────────────────────────────────────────────────────────────────
def _cost(lab, rid, usd):
    _t, _w, path, m = executor.find_run(lab, rid)
    m.setdefault("usage", {})["cost_usd"] = usd
    manifest.write_manifest(path, m)


def test_the_spend_cap_stops_the_campaign_with_a_final_report(camp):
    lab, make = camp
    st = make(spend_usd=2.0)
    assert st["budget"]["spend_usd"] == 2.0
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    _cost(lab, c1["run_id"], 0.5)
    executor.tick(lab, spawn=Spawns())
    assert campaigns.load(lab, st["name"])["status"] == "active"
    assert campaigns.summary(lab)[0]["spent_usd"] == 0.5 and campaigns.summary(lab)[0]["spend_cap_usd"] == 2.0
    _cost(lab, c1["run_id"], 2.4)
    executor.tick(lab, spawn=Spawns())
    s = campaigns.load(lab, st["name"])
    assert s["status"] == "stopping" and any("spend cap" in e["what"] for e in s["events"])
    assert _stopped(lab, c1["run_id"])           # stopped at once
    _finish(lab, c1["run_id"], "killed", reason="stopped by the PI")
    executor.tick(lab, spawn=Spawns())
    assert _cycles(lab)[-1]["campaign_final"] is True   # one last cycle writes the report


def test_no_spend_cap_means_no_stop(camp):
    lab, make = camp
    st = make()
    executor.tick(lab, spawn=Spawns())
    _cost(lab, _cycles(lab)[0]["run_id"], 500.0)
    executor.tick(lab, spawn=Spawns())
    assert campaigns.load(lab, st["name"])["status"] == "active"
    assert campaigns.summary(lab)[0]["spend_cap_usd"] is None


# ── the dashboard endpoint, the snapshot field, the CLI ──────────────────────────────────────────
def test_api_lab_pause_contract_and_snapshot(hub, monkeypatch):
    from test_serve_executor import _mod, _pi_actions
    m = _mod(hub, monkeypatch)
    assert "/api/lab/pause" in m.POST_ROUTES
    out, _ = m.runops.launch_run({"skill": "lab-status", "confirm": True})
    rid = out["run_id"]
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, rid)
    m.executor.manifest.transition(lab, path, man, "running", by="test", pid=None)
    assert m.runops.lab_pause({"paused": True})[1] == 400              # needs confirm
    assert m.runops.lab_pause({"confirm": True})[1] == 400             # needs paused: bool
    assert m.sources.snapshot()["lab_paused"] is None
    out, code = m.runops.lab_pause({"paused": True, "confirm": True})
    assert code == 200 and out["ok"] and out["paused"] is True and out["stopped"] == [rid] and out["note"]
    snap = m.sources.snapshot()
    assert set(snap["lab_paused"]) == {"since", "by"} and snap["lab_paused"]["since"]
    out, code = m.runops.lab_pause({"paused": False, "confirm": True})
    assert code == 200 and out["paused"] is False and out["stopped"] == []
    assert m.sources.snapshot()["lab_paused"] is None
    acts = [a["action"] for a in _pi_actions(hub)]
    assert "lab.pause" in acts and "lab.resume" in acts


def test_cli_pause_and_resume(hub, monkeypatch, capsys):
    monkeypatch.setenv("NEWTS_NO_AUTOTICKER", "1")
    lab = setup(hub, extra=CAPS)
    sys.path.insert(0, str(REPO / "tools"))
    import executor_cli
    assert executor_cli.main(["--hub", str(hub.root), "pause", "--reason", "lunch"]) == 0
    assert pause.state(lab)["reason"] == "lunch"
    assert executor_cli.main(["--hub", str(hub.root), "resume"]) == 0
    assert pause.state(lab) is None
    assert "running again" in capsys.readouterr().out


def test_the_form_sends_a_spend_cap_into_the_brief(hub, monkeypatch, tmp_path):
    import shutil
    from conftest import load
    (hub.root / "templates" / "loop").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "templates" / "loop" / "CAMPAIGN.md", hub.root / "templates" / "loop")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m.ctx, "HUB", hub.root)
    monkeypatch.setattr(m.ctx, "LAB", hub.lab)
    bad, code = m.campaign.campaign_create({"confirm": True, "fields": {"direction": "x", "spend_cap": -3}})
    assert code == 400
    out, code = m.campaign.campaign_create({"confirm": True, "fields": {
        "direction": "sparse routing", "gate1": False, "spend_cap": "25"}})
    assert code == 200 and out["spend_cap_usd"] == 25.0
    assert "spend ≤ $25.00" in (hub.root / out["file"]).read_text(encoding="utf-8")


@pytest.mark.parametrize("cap", ["", 0])
def test_blank_spend_cap_is_no_cap(hub, monkeypatch, tmp_path, cap):
    import shutil
    from conftest import load
    (hub.root / "templates" / "loop").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "templates" / "loop" / "CAMPAIGN.md", hub.root / "templates" / "loop")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m.ctx, "HUB", hub.root)
    monkeypatch.setattr(m.ctx, "LAB", hub.lab)
    out, code = m.campaign.campaign_create({"confirm": True, "fields": {"direction": "d", "spend_cap": cap}})
    assert code == 200 and out["spend_cap_usd"] is None
