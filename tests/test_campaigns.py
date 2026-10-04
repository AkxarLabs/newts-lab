"""The campaign keeper (tools/executor/campaigns.py): a signed campaign keeps going whatever happens to a
single run — re-entry by how the last cycle ended, dispatch validation, per-study waits, child retries,
stop conditions with a final report cycle — and Gate 3 by delegation (tools/gate3.py), which only the
keeper records, only when the brief delegates it and the audits are clean, and which the PI can revoke."""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import campaigns, manifest, scheduler  # noqa: E402
import gate3  # noqa: E402

from test_executor import Spawns, setup  # noqa: E402

BRIEF = """# Campaign Brief — test

## Direction & targets

- **Research direction(s):** sparse routing
- **Parallelism:** ≤ {par} ideas in flight (compute slots still cap training runs)

## Papers may finalize without me (Gate 3)

- [{g3}] Papers may finalize without me (Gate 3 delegated under the checks below)

## PI authorization

- [x] Authorized as scoped above · **PI:** signed in the dashboard (signed_via: dashboard:2026-09-27T10:00:00)

## Campaign Log (append-only)

| time | idea | lifecycle step | outcome / route | progress? | note |
|---|---|---|---|---|---|
| 10:00 | idea-a | ideate | filed | yes | |
"""


@pytest.fixture
def camp(hub):
    lab = setup(hub, extra="    max_concurrent_total: 6\n    hub_max_concurrent: 2\n")
    for slug, state in (("idea-a", "proposal"), ("idea-b", "triaged")):
        hub.add_registry_row(slug, state=state, next="/propose")
        (hub.root / "studies" / slug).mkdir(parents=True, exist_ok=True)
    (hub.lab / "campaigns").mkdir(exist_ok=True)

    def make(par=2, g3=" ", **kw):
        (hub.lab / "campaigns" / "2026-09-27-test.md").write_text(BRIEF.format(par=par, g3=g3), encoding="utf-8")
        return campaigns.create(lab, "lab/campaigns/2026-09-27-test.md", **kw)
    return lab, make


def _runs(lab, **match):
    return [m for *_x, m in executor.all_runs(lab) if all(m.get(k) == v for k, v in match.items())]


def _cycles(lab):
    return sorted(_runs(lab, skill="autopilot"), key=lambda m: (int(m.get("campaign_cycle") or 0), m.get("created") or ""))


def _finish(lab, run_id, status, **fields):
    _t, workdir, path, m = executor.find_run(lab, run_id)
    manifest.transition(lab, path, m, status, by="test", finished=manifest.now(), **fields)
    return workdir


def _footer(lab, workdir, run_id, **data):
    bus = lab.bus_of(workdir)
    bus.mkdir(parents=True, exist_ok=True)
    with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": manifest.now(), "kind": "run_report", "run_id": run_id, "data": data}) + "\n")


def _dispatch(lab, cycle_id, **data):
    with (lab.lab / ".bus" / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": manifest.now() + f".{time.time_ns()}", "kind": "campaign_dispatch",
                            "run_id": cycle_id, "data": data}) + "\n")


def _stopped(lab, run_id):
    """Killed, or (a run whose supervisor is still coming up) carrying the stop marker it will obey."""
    _t, _w, path, m = executor.find_run(lab, run_id)
    return m["status"] == "killed" or (manifest.run_dir(path.parent, run_id) / "stop").exists()


def _nb(m):
    return manifest.parse_ts(m.get("not_before")) or 0


# ── re-entry ─────────────────────────────────────────────────────────────────────────────────────
def test_first_tick_starts_a_cycle_and_only_one(camp):
    lab, make = camp
    make()
    sp = Spawns()
    rep = executor.tick(lab, spawn=sp)
    cyc = _cycles(lab)
    assert len(cyc) == 1 and rep["started"] == [cyc[0]["run_id"]] and cyc[0]["campaign_cycle"] == 1
    assert "CAMPAIGN CYCLE 1" in (executor.manifest.run_dir(executor.find_run(lab, cyc[0]["run_id"])[2].parent,
                                                             cyc[0]["run_id"]) / "preamble.md").read_text(encoding="utf-8")
    executor.tick(lab, spawn=sp)
    assert len(_cycles(lab)) == 1              # idempotent: never two live cycles


def test_a_question_left_on_the_card_is_answered_into_the_next_pass(camp):
    lab, make = camp
    make(repeat_minutes=0)
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    st = campaigns.load(lab, campaigns.all_states(lab)[0]["name"])
    st["questions"] = [{"ts": manifest.now(), "run_id": c1["run_id"], "question": "Which baseline?"}]
    campaigns.save(lab, st)
    card = campaigns.summary(lab)[0]["questions"][0]
    assert card["index"] == 0 and "answer" not in card
    with pytest.raises(ValueError):
        campaigns.control(lab, st["name"], "answer", index=3, text="x")
    campaigns.control(lab, st["name"], "answer", index=0, text="the 2024 one")
    w = _finish(lab, c1["run_id"], "completed")
    _footer(lab, w, c1["run_id"], campaign="continue", summary="pass 1")
    executor.tick(lab, spawn=Spawns())
    c2 = _cycles(lab)[-1]
    pre = (manifest.run_dir(executor.find_run(lab, c2["run_id"])[2].parent, c2["run_id"]) / "preamble.md").read_text(encoding="utf-8")
    assert "The PI answered questions from earlier passes" in pre and "Which baseline?" in pre and "the 2024 one" in pre
    assert "recommendation FIRST" in pre and "Never ask the PI" not in pre
    assert campaigns.load(lab, st["name"])["questions"][0]["delivered"] is True   # delivered once


def test_completed_cycle_repeats_after_the_interval(camp):
    lab, make = camp
    make(repeat_minutes=20)
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    w = _finish(lab, c1["run_id"], "completed")
    _footer(lab, w, c1["run_id"], campaign="continue", summary="pass 1")
    executor.tick(lab, spawn=Spawns())
    c2 = _cycles(lab)[-1]
    assert c2["run_id"] != c1["run_id"] and c2["parent"] == c1["run_id"] and c2["status"] == "queued"
    assert 19 * 60 < _nb(c2) - time.time() < 21 * 60


def test_a_usage_limit_waits_until_it_lifts_and_holds_the_backend(camp):
    lab, make = camp
    make()
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    reset = time.time() + 3600
    _finish(lab, c1["run_id"], "failed", failure_kind="usage_limit", limit_reset=reset, reason="usage limit reached")
    executor.tick(lab, spawn=Spawns())
    c2 = _cycles(lab)[-1]
    assert abs(_nb(c2) - (reset + 120)) < 5
    assert scheduler.limits(lab).get("claude")
    other = executor.enqueue(lab, executor.RunSpec(skill="lab-status"))["run_id"]
    executor.tick(lab, spawn=Spawns())
    assert executor.find_run(lab, other)[3]["status"] == "queued"   # the backend is held until the reset
    st = campaigns.load(lab, "2026-09-27-test")
    assert st["consecutive_failures"] == 0 and st["status"] == "active"


def test_transient_failures_back_off_then_stall(camp):
    lab, make = camp
    make(max_failures=2)
    for i in range(2):
        executor.tick(lab, spawn=Spawns())
        c = _cycles(lab)[-1]
        # let a queued (backed-off) cycle "run" and fail
        _t, _w, path, m = executor.find_run(lab, c["run_id"])
        if m["status"] == "queued":
            manifest.transition(lab, path, m, "running", by="test")
        _finish(lab, c["run_id"], "failed", failure_kind="transient", reason="overloaded")
    executor.tick(lab, spawn=Spawns())
    st = campaigns.load(lab, "2026-09-27-test")
    assert st["status"] == "stalled" and "in a row" in st["paused_reason"]
    assert [c["kind"] for c in st["cycles"]] == ["transient", "transient"]


def test_a_timeout_goes_straight_on_and_auth_pauses(camp):
    lab, make = camp
    make()
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    _finish(lab, c1["run_id"], "timeout")
    executor.tick(lab, spawn=Spawns())
    c2 = _cycles(lab)[-1]
    assert c2["run_id"] != c1["run_id"] and _nb(c2) - time.time() < 120
    _t, _w, path, m = executor.find_run(lab, c2["run_id"])
    manifest.transition(lab, path, m, "running", by="test")
    _finish(lab, c2["run_id"], "failed", failure_kind="auth", reason="the claude CLI is not logged in")
    executor.tick(lab, spawn=Spawns())
    st = campaigns.load(lab, "2026-09-27-test")
    assert st["status"] == "paused" and "logged in" in st["paused_reason"] and len(_cycles(lab)) == 2
    campaigns.control(lab, st["name"], "resume")
    executor.tick(lab, spawn=Spawns())
    assert len(_cycles(lab)) == 3


# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────
def test_dispatch_is_validated_and_runs_as_children(camp):
    lab, make = camp
    make(par=1)
    executor.tick(lab, spawn=Spawns())
    cid = _cycles(lab)[0]["run_id"]
    _dispatch(lab, cid, skill="propose", target="idea-a")          # a member (Campaign Log)
    _dispatch(lab, cid, skill="propose", target="idea-a")          # duplicate
    _dispatch(lab, cid, skill="lit-review", target="idea-b")       # not in the campaign
    _dispatch(lab, cid, skill="finalize", target="idea-a")         # never
    _dispatch(lab, cid, skill="autopilot", target="hub")           # never another campaign
    executor.tick(lab, spawn=Spawns())
    kids = _runs(lab, campaign="2026-09-27-test", skill="propose")
    assert len(kids) == 1 and kids[0]["parent"] == cid and kids[0]["created_by"] == "campaign"
    log = {(d["skill"], d["target"]): d["result"] for d in campaigns.load(lab, "2026-09-27-test")["dispatch_log"]}
    assert log[("propose", "idea-a")] in ("started", "refused: already queued or running")
    assert "not in this campaign" in log[("lit-review", "idea-b")]
    assert "can't be dispatched" in log[("finalize", "idea-a")] and "can't be dispatched" in log[("autopilot", "hub")]
    assert "CAMPAIGN RUN" in (manifest.run_dir(executor.find_run(lab, kids[0]["run_id"])[2].parent,
                                               kids[0]["run_id"]) / "preamble.md").read_text(encoding="utf-8")
    executor.tick(lab, spawn=Spawns())
    assert len(_runs(lab, campaign="2026-09-27-test", skill="propose")) == 1   # an event is handled once


def test_a_study_waiting_for_the_pi_waits_alone(camp, hub):
    lab, make = camp
    make(par=3)
    executor.tick(lab, spawn=Spawns())
    cid = _cycles(lab)[0]["run_id"]
    _dispatch(lab, cid, skill="propose", target="idea-a")
    executor.tick(lab, spawn=Spawns())
    kid = _runs(lab, skill="propose")[0]
    w = _finish(lab, kid["run_id"], "completed")
    _footer(lab, w, kid["run_id"], needs_pi="gate1", study="idea-a")
    executor.tick(lab, spawn=Spawns())
    st = campaigns.load(lab, "2026-09-27-test")
    assert st["studies"]["idea-a"]["waiting"] == "gate1" and st["status"] == "active"
    _dispatch(lab, cid, skill="propose", target="idea-a")
    executor.tick(lab, spawn=Spawns())
    assert "waiting for the PI" in campaigns.load(lab, "2026-09-27-test")["dispatch_log"][-1]["result"]
    # the PI signs Gate 1 → the study is picked up again
    (hub.root / "studies" / "idea-a" / "proposal.md").write_text("<!-- PI Gate 1 approved via Vivarium dashboard x -->\n",
                                                                 encoding="utf-8")
    executor.tick(lab, spawn=Spawns())
    assert not campaigns.load(lab, "2026-09-27-test")["studies"]["idea-a"]["waiting"]


def test_children_are_retried_after_a_timeout(camp):
    lab, make = camp
    make(par=2)
    executor.tick(lab, spawn=Spawns())
    _dispatch(lab, _cycles(lab)[0]["run_id"], skill="propose", target="idea-a")
    executor.tick(lab, spawn=Spawns())
    kid = _runs(lab, skill="propose")[0]
    _t, _w, path, m = executor.find_run(lab, kid["run_id"])
    manifest.transition(lab, path, m, "running", by="test", session_id="s-1")
    _finish(lab, kid["run_id"], "timeout")
    executor.tick(lab, spawn=Spawns())
    m = executor.find_run(lab, kid["run_id"])[3]
    assert m["campaign_retries"] == 1 and (m.get("resume") or {}).get("mode") == "continue" or m["status"] != "timeout"


# ── stopping ─────────────────────────────────────────────────────────────────────────────────────
def test_the_deadline_ends_with_a_final_report_cycle(camp):
    lab, make = camp
    make(hours=0.0001)
    time.sleep(0.5)
    executor.tick(lab, spawn=Spawns())
    c = _cycles(lab)[0]
    assert c["campaign_final"] is True
    pre = (manifest.run_dir(executor.find_run(lab, c["run_id"])[2].parent, c["run_id"]) / "preamble.md").read_text(encoding="utf-8")
    assert "FINAL CYCLE" in pre
    _finish(lab, c["run_id"], "completed")
    executor.tick(lab, spawn=Spawns())
    assert campaigns.load(lab, "2026-09-27-test")["status"] == "done" and len(_cycles(lab)) == 1


def test_the_pi_stops_a_campaign(camp):
    lab, make = camp
    make()
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    campaigns.control(lab, "2026-09-27-test", "stop")
    assert _stopped(lab, c1["run_id"])
    _finish(lab, c1["run_id"], "killed", reason="stopped by the PI")   # what its supervisor records
    executor.tick(lab, spawn=Spawns())
    c2 = _cycles(lab)[-1]
    assert c2["campaign_final"] is True                      # one last cycle writes the report


# ── Gate 3 by delegation ─────────────────────────────────────────────────────────────────────────
def _paper_ready(hub, slug="idea-a"):
    hub._rows = [dict(r, state="internal-review") if r["id"] == slug else r for r in hub._rows]
    hub._write_registry()
    p = hub.root / "studies" / slug / "paper"
    (p / "reviews" / "r1").mkdir(parents=True, exist_ok=True)
    (p / "main.pdf").write_bytes(b"%PDF-1.4 test")
    (p / "claims.yaml").write_text("claims: []\n", encoding="utf-8")
    (p / "reviews" / "r1" / "meta-review.md").write_text("# Meta\n\n## Decision\n\naccept\n", encoding="utf-8")


def _reviewed(lab, cid, slug="idea-a"):
    _dispatch(lab, cid, skill="review-paper", target=slug)
    executor.tick(lab, spawn=Spawns())
    kid = _runs(lab, skill="review-paper")[0]
    w = _finish(lab, kid["run_id"], "completed")
    _footer(lab, w, kid["run_id"], needs_pi="gate3", study=slug)
    return kid


def test_gate3_is_recorded_only_when_delegated_and_the_audits_are_clean(camp, hub, monkeypatch):
    lab, make = camp
    make(g3="x", gate3_auto=True)
    _paper_ready(hub)
    audits = {"claims": 0, "multiseed": 2, "ablations": 0, "eval": 0}
    monkeypatch.setattr(gate3, "run_audits", lambda h, s: dict(audits))
    executor.tick(lab, spawn=Spawns())
    _reviewed(lab, _cycles(lab)[0]["run_id"])
    executor.tick(lab, spawn=Spawns())
    assert not gate3.note_path(hub.root, "idea-a").exists()          # a MANUAL audit (exit 2) blocks
    assert "multiseed audit exit 2" in campaigns.load(lab, "2026-09-27-test")["gate3_log"][-1]["result"]
    audits["multiseed"] = 0
    (hub.root / "studies" / "idea-a" / "paper" / "claims.yaml").write_text("claims: [1]\n", encoding="utf-8")
    time.sleep(1.1)
    (hub.root / "studies" / "idea-a" / "paper" / "claims.yaml").touch()
    executor.tick(lab, spawn=Spawns())
    note = gate3.note_path(hub.root, "idea-a").read_text(encoding="utf-8")
    assert "signed_via: campaign:lab/campaigns/2026-09-27-test.md" in note and "brief_sha256:" in note
    fin = _runs(lab, skill="finalize")
    assert len(fin) == 1 and fin[0]["gate3_signed"] and fin[0]["created_by"] == "campaign-gate3"
    assert gate3.delegation_valid(hub.root, "idea-a")[0]
    # the PI revokes: the note stops counting everywhere, and the finalize run is stopped
    campaigns.control(lab, "2026-09-27-test", "revoke_gate3")
    ok, why = gate3.delegation_valid(hub.root, "idea-a")
    assert not ok and "revoked" in why
    assert _stopped(lab, _runs(lab, skill="finalize")[0]["run_id"])
    with pytest.raises(executor.SpecError):
        executor.enqueue(lab, executor.RunSpec(skill="finalize", target="idea-a", gate3=True))


def test_no_gate3_without_the_box_or_with_a_hold(camp, hub, monkeypatch):
    lab, make = camp
    make(g3=" ", gate3_auto=True)                         # the brief does not delegate Gate 3
    _paper_ready(hub)
    monkeypatch.setattr(gate3, "run_audits", lambda h, s: {"claims": 0})
    executor.tick(lab, spawn=Spawns())
    _reviewed(lab, _cycles(lab)[0]["run_id"])
    executor.tick(lab, spawn=Spawns())
    assert not gate3.note_path(hub.root, "idea-a").exists()
    # a delegating brief, but the PI holds this study
    (hub.lab / "campaigns" / "2026-09-27-test.md").write_text(BRIEF.format(par=2, g3="x"), encoding="utf-8")
    campaigns.control(lab, "2026-09-27-test", "hold", study="idea-a")
    executor.tick(lab, spawn=Spawns())
    assert not gate3.note_path(hub.root, "idea-a").exists()


def test_an_edited_brief_invalidates_a_delegated_note(camp, hub, monkeypatch):
    lab, make = camp
    make(g3="x", gate3_auto=True)
    _paper_ready(hub)
    monkeypatch.setattr(gate3, "run_audits", lambda h, s: {"claims": 0})
    executor.tick(lab, spawn=Spawns())
    _reviewed(lab, _cycles(lab)[0]["run_id"])
    executor.tick(lab, spawn=Spawns())
    assert gate3.delegation_valid(hub.root, "idea-a")[0]
    b = hub.lab / "campaigns" / "2026-09-27-test.md"
    b.write_text(b.read_text(encoding="utf-8").replace("sparse routing", "anything at all"), encoding="utf-8")
    ok, why = gate3.delegation_valid(hub.root, "idea-a")
    assert not ok and "changed" in why


def test_the_guards_honour_a_valid_delegation_only(camp, hub, monkeypatch):
    from conftest import load
    lab, make = camp
    make(g3="x", gate3_auto=True)
    _paper_ready(hub)
    monkeypatch.setattr(gate3, "run_audits", lambda h, s: {"claims": 0})
    executor.tick(lab, spawn=Spawns())
    _reviewed(lab, _cycles(lab)[0]["run_id"])
    executor.tick(lab, spawn=Spawns())
    sg = load("signature_guard")
    monkeypatch.setattr(sg, "HUB", hub.root.resolve())
    reg = hub.lab / "REGISTRY.md"
    old = reg.read_text(encoding="utf-8")
    new = old.replace("| internal-review |", "| final |")
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": str(hub.root),
               "tool_input": {"file_path": str(reg), "content": new}}
    assert sg.decide(payload) is None                       # the delegated note is a valid Gate 3
    g = load("guard")
    monkeypatch.setattr(g, "HUB", hub.root)
    assert g._gate3_marker("idea-a")
    campaigns.control(lab, "2026-09-27-test", "revoke_gate3")
    assert sg.decide(payload) and not g._gate3_marker("idea-a")
    # agents never touch the keeper's state, nor write a Gate-3 note themselves
    st = hub.lab / ".bus" / "campaigns" / "2026-09-27-test.json"
    assert sg.decide({"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": str(hub.root),
                      "tool_input": {"file_path": str(st), "content": "{}"}})
    assert sg.decide({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(hub.root),
                      "tool_input": {"command": "echo '{}' > lab/.bus/campaigns/2026-09-27-test.json"}})


# ── nobody has to keep a window open ─────────────────────────────────────────────────────────────
def test_a_supervisor_starts_a_scheduler_when_none_is_ticking(camp, monkeypatch):
    lab, make = camp
    started = []
    monkeypatch.setattr(scheduler.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    monkeypatch.delenv("NEWTS_NO_AUTOTICKER", raising=False)
    assert not scheduler.ensure_ticker(lab)                      # no work → nothing to start
    make()
    lease = lab.lab / ".bus" / "scheduler.lease"
    if lease.exists():
        lease.unlink()
    assert scheduler.ensure_ticker(lab) and started and started[-1][-2:] == ["serve", "--until-idle"]
    assert not scheduler.ensure_ticker(lab)                      # it just wrote a fresh lease
    executor.tick(lab, spawn=Spawns())
    assert scheduler.lease(lab)["age"] < 5                       # every tick renews it
    monkeypatch.setenv("NEWTS_NO_AUTOTICKER", "1")
    lease.write_text(json.dumps({"ts": 0}), encoding="utf-8")
    assert not scheduler.ensure_ticker(lab)


def test_keep_awake_follows_the_work(camp, monkeypatch):
    from executor import awake
    lab, make = camp
    held = []
    monkeypatch.setattr(awake, "hold", lambda reason: held.append(reason) or True)
    monkeypatch.setattr(awake, "release", lambda: held.append(None))
    awake.update(lab)
    assert held[-1] is None
    make()
    awake.update(lab)
    assert held[-1] and "campaign" in held[-1]
    (lab.lab / "config.yaml").write_text((lab.lab / "config.yaml").read_text(encoding="utf-8")
                                         .replace('lab:\n', 'lab:\n  keep_awake: off\n', 1), encoding="utf-8")
    awake.update(lab)
    assert held[-1] is None


def test_the_spawned_scheduler_takes_over_its_spawners_lease(camp):
    """ensure_ticker writes a lease as it spawns `serve --until-idle`; that process must not mistake it for
    another live ticker and exit (it did, once)."""
    import subprocess as sp
    lab, _make = camp
    scheduler.write_lease(lab, "spawned serve --until-idle")
    r = sp.run([sys.executable, str(REPO / "tools" / "executor_cli.py"), "--hub", str(lab.hub), "serve", "--until-idle",
                "--interval", "0.2", "--idle-seconds", "1"], capture_output=True, text=True, timeout=120,
               env={**__import__("os").environ, "NEWTS_NO_AUTOTICKER": "1"})
    assert "another scheduler is ticking" not in r.stdout, r.stdout
    scheduler.write_lease(lab, "dashboard")
    r = sp.run([sys.executable, str(REPO / "tools" / "executor_cli.py"), "--hub", str(lab.hub), "serve", "--until-idle"],
               capture_output=True, text=True, timeout=60)
    assert "another scheduler is ticking" in r.stdout


def test_detached_processes_get_a_durable_python(monkeypatch, tmp_path):
    """Under `uv run --with …` the interpreter lives in a throwaway env uv deletes on exit: supervisors,
    schedulers and hooks started from it must use the durable ~/.newts/py instead (found live: a campaign
    cycle died with 'No pyvenv.cfg file' after the dashboard that started its scheduler exited)."""
    from executor import procs
    tmp = "/home/u/.cache/uv/builds-v0/.tmpAbC/bin/python" if os.name != "nt" else r"C:\u\uv\cache\builds-v0\.tmpAbC\Scripts\python.exe"
    assert procs._ephemeral(tmp) and not procs._ephemeral(sys.executable if not procs._ephemeral(sys.executable) else "/usr/bin/python3")
    monkeypatch.setattr(procs.sys, "executable", tmp)
    monkeypatch.setenv("NEWTS_KEEP_PYTHON", "1")
    assert procs.python_exe() == tmp                        # the suite's own opt-out
    monkeypatch.delenv("NEWTS_KEEP_PYTHON")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path))
    procs._STABLE.clear()
    stable = tmp_path / "py" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    stable.parent.mkdir(parents=True)
    stable.write_text("", encoding="utf-8")
    monkeypatch.setattr(procs.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    assert procs.python_exe() == str(stable)
    procs._STABLE.clear()


def test_needs_you_shows_the_campaign_not_its_retried_runs(camp, monkeypatch):
    from executor import attention
    lab, make = camp
    make(max_failures=1)
    executor.tick(lab, spawn=Spawns())
    c1 = _cycles(lab)[0]
    _finish(lab, c1["run_id"], "failed", failure_kind="logic", reason="exit 1")
    runs = [(p, m) for *_x, p, m in executor.all_runs(lab)]
    assert not [i for i in attention.run_items(lab, runs) if i["kind"] == "crashed"]   # the keeper handles it
    executor.tick(lab, spawn=Spawns())
    assert campaigns.load(lab, "2026-09-27-test")["status"] == "stalled"
    from conftest import load
    sources = load("dashboard/sources")
    monkeypatch.setattr(sources.ctx, "HUB", lab.hub)
    monkeypatch.setattr(sources.ctx, "LAB", lab.lab)
    items = sources.attention.collect([], [], [], [])
    assert any(i["kind"] == "campaign" and i["sev"] == "block" for i in items)


# ── the campaign form: Gate 1 by delegation is the PI's switch ──────────────────────────────────────
@pytest.mark.parametrize("gate1", [True, False])
def test_the_form_carries_the_gate1_choice_into_the_signed_brief(hub, monkeypatch, tmp_path, gate1):
    import shutil
    from conftest import load
    (hub.root / "templates" / "loop").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "templates" / "loop" / "CAMPAIGN.md", hub.root / "templates" / "loop")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m.ctx, "HUB", hub.root)
    monkeypatch.setattr(m.ctx, "LAB", hub.lab)
    out, code = m.campaign.campaign_create({"confirm": True, "fields": {
        "direction": "sparse routing", "ideas": 2, "parallel": 1, "full_runs": 3, "full_minutes": 60, "gate1": gate1}})
    assert code == 200, out
    assert out["gate1_auto"] is gate1
    text = (hub.root / out["file"]).read_text(encoding="utf-8")
    g1 = text.split("## Gate 1 delegation", 1)[1].split("\n## ", 1)[0]
    assert "FULL runs ≤ 3 × 60 min" in g1
    if gate1:
        assert "- [x] Kill criteria" in g1 and "NOT DELEGATED" not in g1
    else:
        assert "- [x]" not in g1 and "NOT DELEGATED" in g1 and "no proposal is self-approved" in g1
    assert "- [x] Authorized as scoped above" in text     # signed either way
