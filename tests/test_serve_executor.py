"""Tests for the dashboard's executor surface (dashboard/serve.py) — handler functions, no socket.

Launch / answer / reply / stop / resume / cancel, the transcript tail, the master-switch toggle,
dashboard commands that also start the procedure that consumes them, the Gate-1 follow-up launch,
escalation resolution, route precedence, the SSE change signature, and the registry-row bus fix.
Launches only ENQUEUE here (nothing is spawned): the scheduler thread is never started.
"""

from __future__ import annotations

import json
import sys

from conftest import REPO, load

FAKE = REPO / "tests" / "fake_claude.py"


def _mod(hub, monkeypatch, *, enabled=True, dashboard_extra: str = ""):
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\n'
        f"dashboard:\n  port: 8787\n{dashboard_extra}"
        "agents:\n  programmatic:\n"
        f"    enabled: {str(bool(enabled)).lower()}   # master switch\n"
        "    backend: claude\n    max_depth: 1\n"
        "    backends:\n      claude:\n"
        f"        command: {json.dumps([sys.executable, str(FAKE)])}\n",
        encoding="utf-8")
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m.ctx, "HUB", hub.root)
    monkeypatch.setattr(m.ctx, "LAB", hub.lab)
    return m


def _pi_actions(hub):
    f = hub.lab / ".bus" / "pi-actions.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


# ── launch ────────────────────────────────────────────────────────────────────

def test_launch_queues_a_run_and_logs(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    out, code = m.launch_run({"skill": "propose", "target": "idea-a", "confirm": True})
    assert code == 200 and out["status"] == "queued" and out["command"] == "/propose idea-a"
    assert (hub.lab / ".bus" / "agents" / f"{out['run_id']}.json").exists()
    assert _pi_actions(hub)[-1]["action"] == "run.launch"
    assert m.ctx.KICK.is_set()                                     # the scheduler is woken at once


def test_launch_refusals(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m.launch_run({"skill": "propose", "target": "idea-a"})[1] == 400             # no confirm
    out, code = m.launch_run({"skill": "finalize", "target": "idea-a", "confirm": True})
    assert code == 400 and "Gate 3" in out["error"]
    out, code = m.launch_run({"skill": "lab-status", "args": "x\ny", "confirm": True})
    assert code == 400
    out, code = m.launch_run({"skill": "propose", "target": "../../etc", "confirm": True})
    assert code == 400 and "invalid target" in out["error"]
    m2 = _mod(hub, monkeypatch, enabled=False)
    out, code = m2.launch_run({"skill": "lab-status", "confirm": True})
    assert code == 400 and "off" in out["error"]


# ── answer / reply / stop / resume / cancel ──────────────────────────────────

def _waiting_run(m, hub):
    out, _ = m.launch_run({"skill": "spawn-project", "target": "idea-q", "confirm": True})
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, out["run_id"])
    m.executor.manifest.transition(lab, path, man, "waiting_input", by="test", session_id="S1",
                                   pending_question={"tool_use_id": "tq", "input": {"questions": [
                                       {"question": "Type?", "options": [{"label": "ml"}]}]}})
    return out["run_id"]


def test_answer_then_run_is_queued_to_resume(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    rid = _waiting_run(m, hub)
    out, code = m._run_op("answer", {"run_id": rid, "answers": {"Type?": "ml"}})
    assert code == 200 and out["status"] == "queued"
    run = m.run_detail(rid)[0]["run"]
    assert run["pending_question"] is None and run["qa"][0]["answers"] == {"Type?": "ml"}
    assert m._run_op("answer", {"run_id": rid, "answers": {"Type?": "ml"}})[1] == 400   # no longer waiting


def test_reply_stop_cancel_and_bad_ids(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    rid = _waiting_run(m, hub)
    assert m._run_op("reply", {"run_id": rid, "text": "use theory"})[0]["status"] == "queued"
    assert m._run_op("stop", {"run_id": rid})[1] == 400                                # needs confirm
    out, code = m._run_op("stop", {"run_id": rid, "confirm": True})                     # queued → cancelled
    assert code == 200 and out["status"] == "killed"
    assert m._run_op("resume", {"run_id": "../x"})[1] == 400
    assert m._run_op("cancel", {"run_id": "no-such-run"})[1] == 400


# ── transcript tail ──────────────────────────────────────────────────────────

def test_run_tail_offsets_whole_lines_and_subagent_labels(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    out, _ = m.launch_run({"skill": "lab-status", "confirm": True})
    rid = out["run_id"]
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, rid)
    man["subagents"] = {"tuS": {"type": "experiment-runner", "description": "exp-004"}}
    m.executor.manifest.write_manifest(path, man)
    stream = path.parent / man["stream"]
    lines = [{"_attempt": 1, "ts": "t"},
             {"type": "system", "subtype": "init", "session_id": "abcdef123"},
             {"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}},
             {"type": "assistant", "parent_tool_use_id": "tuS", "message": {"content": [
                 {"type": "tool_use", "id": "x", "name": "Bash", "input": {"command": "uv run a"}}]}},
             {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "tuS",
                                                       "content": "PACKET ok"}]}}]
    stream.write_text("".join(json.dumps(x) + "\n" for x in lines) + '{"partial": ', encoding="utf-8")
    res, code = m.run_tail(rid, 0)
    kinds = [x["k"] for x in res["lines"]]
    assert code == 200 and kinds == ["attempt", "start", "text", "tool", "sub"]
    assert res["lines"][3]["who"].startswith("experiment-runner") and res["lines"][4]["t"] == "PACKET ok"
    assert not res["eof"]                                       # the partial last line is held back
    with stream.open("a", encoding="utf-8") as f:
        f.write('"x"}\n' + json.dumps({"type": "result", "result": "done", "stop_reason": "end_turn"}) + "\n")
    res2, _ = m.run_tail(rid, res["offset"])
    assert [x["k"] for x in res2["lines"]] == ["end"] and res2["eof"]
    assert m.run_tail("nope", 0)[1] == 404


# ── master switch toggle (in-process stamp: never touches the real repo) ─────

def test_set_programmatic_flips_config_and_logs(hub, monkeypatch):
    m = _mod(hub, monkeypatch, enabled=False)
    assert m.set_programmatic({"enabled": True})[1] == 400                              # needs confirm
    out, code = m.set_programmatic({"enabled": True, "confirm": True})
    assert code == 200 and out["enabled"] is True
    text = (hub.lab / "config.yaml").read_text(encoding="utf-8")
    import re
    assert re.search(r"enabled: true\s+# master switch", text)                           # comment preserved
    assert _pi_actions(hub)[-1] == {**_pi_actions(hub)[-1], "action": "executor.enable", "enabled": True}
    (hub.lab / "config.yaml").write_text("lab: {}\n", encoding="utf-8")
    assert m.set_programmatic({"enabled": True, "confirm": True})[1] == 400             # key absent → refused


# ── commands that also launch the consumer ───────────────────────────────────

def test_command_launch_maps_actions(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    out = m.command_launch("demo", "run_smoke", {}, "")
    assert out["ok"] and out["command"] == "/experiment demo"
    out = m.command_launch("demo", "ideate", {}, "")
    assert out["command"] == "/ideate --in-project demo"
    out = m.command_launch("hub", "ideate", {"direction": "efficient small LMs"}, "")
    assert out["command"] == "/ideate efficient small LMs"
    assert m.command_launch("demo", "park", {}, "") is None                 # registry edits stay directives


def test_stop_loop_stops_live_research_loop(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    out, _ = m.launch_run({"skill": "research-loop", "target": "demo", "confirm": True})
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, out["run_id"])
    m.executor.manifest.transition(lab, path, man, "running", by="test", pid=None)
    m.executor.manifest.transition(lab, path, man, "running", by="test", status_ts="2000-01-01T00:00:00")
    stopped = m.command_stop_loop("demo")
    assert stopped == [out["run_id"]]
    assert m.executor.find_run(lab, out["run_id"])[3]["status"] == "killed"   # no supervisor → killed now


# ── Gate 1 follow-up ─────────────────────────────────────────────────────────

def test_gate1_auto_spawn_only_when_configured(hub, monkeypatch):
    for auto in (False, True):
        m = _mod(hub, monkeypatch, dashboard_extra=f"  auto_spawn_on_gate1: {str(auto).lower()}\n")
        slug = f"idea-{int(auto)}"
        hub.add_registry_row(slug, state="proposal", next="Gate 1")
        (hub.root / "studies" / slug).mkdir(parents=True)
        (hub.root / "studies" / slug / "proposal.md").write_text("# P\n", encoding="utf-8")
        res = m.approve_gate(slug, 1)
        assert res["ok"]
        if auto:
            assert res["launch"]["command"] == f"/spawn-project {slug}" and "queued" in res["note"]
        else:
            assert "launch" not in res


# ── misc ──────────────────────────────────────────────────────────────────────

def test_resolve_escalation_writes_on_the_raising_bus(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.resolve_escalation({"ref": "not-an-id"})[1] == 400
    out, code = m.resolve_escalation({"ref": "e-abcdef123456", "source": "demo"})
    assert code == 200
    ev = json.loads((proj / ".bus" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ev["kind"] == "escalation_resolved" and ev["data"]["ref"] == "e-abcdef123456"


def test_exact_routes_precede_prefix_routes(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    for r in ("/api/run", "/api/run/answer", "/api/run/stop", "/api/attention/ack", "/api/executor/enable"):
        assert r in m.Handler._EXACT_POST


def test_sse_signature_ignores_the_clock(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    a = {"now": "2026-01-01T00:00:00", "items": [1]}
    assert m._sig(a) == m._sig({**a, "now": "2026-01-01T00:00:09"})
    assert m._sig(a) != m._sig({**a, "items": [2]})


def test_bus_dir_honours_registry_project_column(hub, monkeypatch):
    """An /adopt-ed project outside projects_root must get its directives on ITS bus, not the hub's."""
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("adopted", in_root=False)
    hub.add_registry_row("adopted", state="active", project=str(proj))
    assert m._bus_dir("adopted") == proj / ".bus"
    assert m._bus_dir("pre-spawn-idea") == hub.lab / ".bus"


def test_health_and_snapshot_expose_executor(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    h, code = m.executor_health()
    assert code == 200 and h["available"] and h["enabled"] and h["clis"]["claude"]["found"]
    snap = m.sources.snapshot()
    assert snap["executor"]["enabled"] is True and "lab-status" in snap["skills"]
