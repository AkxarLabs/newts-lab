"""End-to-end executor tests: real detached supervisor processes driving tests/fake_claude.py.

These exercise the whole path a dashboard click takes — enqueue → tick → detached supervisor →
agent CLI (fake) → stream capture → manifest/bus/ledger — including the live session (questions,
permissions, messages and interrupts delivered while the agent runs, parking, the one-shot fallback),
the one-shot AskUserQuestion defer hook and MCP permission host, stop, crash + resume, reply, subagent
tracking, and the run_report footer.
No real model, no network, no ports.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from conftest import REPO, load

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec, SpecError  # noqa: E402

FAKE = REPO / "tests" / "fake_claude.py"
LIVE = {"queued", "starting", "resuming", "running"}
DONE = {"completed", "failed", "timeout", "killed"}


def setup(hub, *, enabled=True, extra_prog: str = "", backend_cmd=None, max_minutes=5):
    cmd = backend_cmd or [sys.executable, str(FAKE)]
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\n'
        "compute:\n  max_concurrent_runs: 1\n"
        "agents:\n  programmatic:\n"
        f"    enabled: {str(bool(enabled)).lower()}\n"
        "    backend: claude\n"
        f"    max_minutes: {max_minutes}\n"
        "    max_concurrent: 2\n    max_concurrent_total: 3\n    hub_max_concurrent: 2\n    max_depth: 1\n"
        f"{extra_prog}"
        "    backends:\n      claude:\n"
        f"        command: {json.dumps(cmd)}\n",
        encoding="utf-8")
    return executor.Lab(hub.root)


def wait_for(lab, run_id, statuses=None, timeout=45.0):
    """Tick until the run leaves the live states (or reaches one of `statuses`)."""
    deadline = time.time() + timeout
    m = {}
    while time.time() < deadline:
        executor.tick(lab, wait=2)
        hit = executor.find_run(lab, run_id)
        m = hit[3] if hit else {}
        st = m.get("status")
        if (statuses and st in statuses) or (not statuses and st not in LIVE):
            return m
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} still {m.get('status')} after {timeout}s: {m}")


def run_dir(lab, m) -> Path:
    workdir = lab.target_dir(m["target"]) if m["level"] == "project" else lab.hub
    return lab.agents_dir(workdir) / f"{m['run_id']}.d"


def calls(lab, m) -> list[dict]:
    f = run_dir(lab, m) / "fake_calls.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── happy path ────────────────────────────────────────────────────────────────

def test_hub_run_completes_and_records_everything(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_REPORT", json.dumps({"next": "", "needs_pi": "none", "summary": "orientation done"}))
    lab = setup(hub)
    m = executor.enqueue(lab, RunSpec(skill="lab-status", created_by="test"))
    assert m["status"] == "queued" and m["position"] == 1
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed", m
    assert m["session_id"] and m["attempt"] == 1 and m["attempts"][0]["exit_code"] == 0
    assert "smoke green" in m["last_message"]
    assert m["usage"]["cost_usd"] == pytest.approx(0.0123)
    assert m["last_action"]["tool"] == "Bash" and "run.py" in m["last_action"]["summary"]
    # the transcript holds the attempt separator + every stream line
    stream = (lab.bus / "agents" / m["stream"]).read_text(encoding="utf-8")
    assert '"_attempt": 1' in stream and '"type": "result"' in stream
    # hub run → hub bus events; ledger has the full transition history
    kinds = [json.loads(x)["kind"] for x in (lab.bus / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "agent_launched" in kinds and "agent_finished" in kinds
    trans = [(r["from"], r["to"]) for r in executor.ledger(lab) if r["run_id"] == m["run_id"]]
    assert trans[:3] == [(None, "queued"), ("queued", "starting"), ("starting", "running")]
    assert trans[-1][1] == "completed"
    # the CLI was invoked as designed: slash command on stdin, session pre-assigned, gates env set
    c = calls(lab, m)[0]
    assert c["stdin"] == "/lab-status" and m["transport"] == "live"
    assert "--session-id" in c["argv"] and c["argv"][c["argv"].index("--session-id") + 1] == m["session_id"]
    assert c["argv"][c["argv"].index("--permission-mode") + 1] == "auto"
    assert "--append-system-prompt-file" in c["argv"] and "--settings" in c["argv"]
    assert c["argv"][c["argv"].index("--input-format") + 1] == "stream-json"
    assert c["argv"][c["argv"].index("--permission-prompt-tool") + 1] == "stdio" and "--mcp-config" not in c["argv"]
    assert c["env"]["AUTOSCIENTIST_NO_GATE3"] == "1" and c["env"]["AUTOSCIENTIST_AGENT_DEPTH"] == "1"
    # the run's own settings pre-approve exactly the lab's bus commands (footer, dispatch) — nothing else
    st = json.loads((run_dir(lab, m) / "settings.json").read_text(encoding="utf-8"))
    allow = st["permissions"]["allow"]
    assert allow and all("lab_bus.py" in a and (" emit:*)" in a or " escalate:*)" in a) for a in allow)
    assert c["env"]["NEWTS_RUN_ID"] == m["run_id"]
    assert Path(c["cwd"]).resolve() == hub.root.resolve()
    # the next tick post-processes: the footer becomes the report
    executor.tick(lab)
    m = executor.find_run(lab, m["run_id"])[3]
    assert m["post_processed"] and m["report"]["summary"] == "orientation done"
    assert m["report"]["needs_pi"] is None and m["report"]["source"] == "footer"


def test_project_run_uses_project_cwd_and_hub_add_dir(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    lab = setup(hub)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    m = executor.enqueue(lab, RunSpec(skill="experiment", target="demo", args="exp-002", created_by="test"))
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed"
    assert (proj / ".bus" / "agents" / f"{m['run_id']}.json").exists()   # project runs live on the project bus
    c = calls(lab, m)[0]
    assert Path(c["cwd"]).resolve() == proj.resolve()
    assert c["argv"][c["argv"].index("--add-dir") + 1] == str(hub.root)
    assert "/experiment demo exp-002" in c["stdin"] and "SKILL.md" in c["stdin"]


# ── the question round-trip ───────────────────────────────────────────────────

def test_oneshot_prose_question_then_reply_resumes_with_text(hub, monkeypatch):
    # the fallback: a one-shot run asks in prose and ends its turn; the PI's reply resumes the session
    monkeypatch.setenv("FAKE_MODE", "prose")
    lab = setup(hub, extra_prog="    live: false\n")
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="discuss", args="direction"))["run_id"])
    assert m["status"] == "completed" and "A or B" in m["last_message"]
    executor.reply(lab, m["run_id"], "Use dataset B")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed" and "Use dataset B" in m["last_message"]
    c = calls(lab, m)
    assert c[1]["stdin"] == "Use dataset B" and "--resume" in c[1]["argv"] and m["transport"] == "oneshot"
    assert "--permission-prompt-tool" not in c[0]["argv"] and "--mcp-config" not in c[0]["argv"]


# ── live sessions: the agent keeps running while you answer ───────────────────

def _live_cfg(**kw):
    return "    live:\n" + "".join(f"      {k}: {v}\n" for k, v in kw.items())


def test_live_question_is_answered_in_place(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-x"))["run_id"]
    m = wait_for(lab, rid, statuses={"waiting_input", "completed", "failed"})
    assert m["status"] == "waiting_input" and m["pending_question"]["live"] and m["pid"], m
    items = executor.attention.collect(lab)
    assert any(it["kind"] == "question" and it["run_id"] == rid for it in items)
    executor.answer(lab, rid, {"Which project type?": "empirical"})
    m = wait_for(lab, rid, statuses=DONE)
    assert m["status"] == "completed", m
    assert 'answers={"Which project type?": "empirical"}' in m["last_message"]
    assert m["attempt"] == 1 and len(calls(lab, m)) == 1          # no resume: the same process
    assert m["qa"][0]["answers"] == {"Which project type?": "empirical"} and m["qa"][0]["by"] == "PI"


def test_live_free_text_answer(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-y"))["run_id"]
    wait_for(lab, rid, statuses={"waiting_input"})
    executor.reply(lab, rid, "neither — it's a theory project")
    m = wait_for(lab, rid, statuses=DONE)
    assert m["status"] == "completed" and "response=neither — it's a theory project" in m["last_message"]


def test_live_question_parks_then_the_answer_resumes(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub, extra_prog=_live_cfg(park_minutes=0.03))
    rid = executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-z"))["run_id"]
    m = wait_for(lab, rid, statuses={"waiting_input"})
    deadline = time.time() + 30
    while m.get("pid") and time.time() < deadline:   # parked: the process ends, the question stays
        time.sleep(0.5)
        m = executor.find_run(lab, rid)[3]
    assert m["status"] == "waiting_input" and not m.get("pid") and m["pending_question"]["live"], m
    monkeypatch.setenv("FAKE_MODE", "complete")
    executor.answer(lab, rid, {"Which project type?": "ml"})
    m = executor.find_run(lab, rid)[3]
    assert m["status"] == "queued" and m["resume"]["mode"] == "reply"
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and m["attempt"] == 2
    c = calls(lab, m)[1]
    assert "--resume" in c["argv"] and "The PI answered your question" in c["stdin"] and "ml" in c["stdin"]


def test_live_permission_waits_for_the_pi(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "mcp")
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"]
    deadline = time.time() + 30
    m = {}
    while time.time() < deadline and not m.get("pending_permissions"):
        executor.tick(lab, wait=1)
        m = executor.find_run(lab, rid)[3]
        time.sleep(0.2)
    req = m["pending_permissions"][0]
    assert m["status"] == "running" and req["tool"] == "Bash" and "rm -rf" in req["input"]["command"]
    items = [it for it in executor.attention.collect(lab) if it["kind"] == "permission" and it["run_id"] == rid]
    assert items and items[0]["detail"]["n"] == req["id"]
    executor.permission_decision(lab, rid, req["id"], True)
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and "permission=allow" in m["last_message"]
    assert not m.get("pending_permissions")
    log = (run_dir(lab, m) / "permissions.jsonl").read_text(encoding="utf-8")
    assert '"decision": "allow"' in log and '"by": "PI"' in log


def test_live_permission_is_denied_at_its_deadline(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "mcp")
    lab = setup(hub, extra_prog=_live_cfg(permission_minutes=0.02))
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    assert m["status"] == "completed" and "permission=deny" in m["last_message"]
    assert any(it["kind"] == "denied" and it["run_id"] == m["run_id"] for it in executor.attention.collect(lab))


def test_live_message_and_interrupt_reach_a_working_session(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_STEER", "20")
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    time.sleep(1.5)
    executor.reply(lab, rid, "use dataset B")      # while it works: no resume, the same turn reads it
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and "steered: use dataset B" in m["last_message"], m
    assert m["attempt"] == 1
    rid = executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    time.sleep(1.5)
    executor.interrupt(lab, rid)
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and "interrupted" in m["last_message"], m


def test_a_campaign_run_assumes_the_recommended_answer_and_says_so(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub, extra_prog=_live_cfg(campaign_question_minutes=0.02))
    rid = executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-c", campaign="c1"))["run_id"]
    m = wait_for(lab, rid, statuses=DONE, timeout=60)
    assert m["status"] == "completed" and 'answers={"Which project type?": "ml"}' in m["last_message"], m
    assert m["assumed"][0]["answers"] == {"Which project type?": "ml"}
    items = [it for it in executor.attention.collect(lab) if it["run_id"] == rid and it["kind"] == "assumed"]
    assert items and "ml" in items[0]["title"] and items[0]["actions"][0]["id"] == "reply"


def test_live_start_failure_falls_back_to_one_shot(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_LIVE_FAIL", "1")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    assert m["status"] == "completed" and m["transport"] == "oneshot" and m["no_live"], m
    assert m["attempt"] == 1 and len(m["attempts"]) == 1
    c = calls(lab, m)   # (the failing live start exits before the fake logs its call)
    assert len(c) == 1 and "--input-format" not in c[0]["argv"]
    assert c[0]["stdin"] == "/lab-status"                              # one-shot: the prompt on stdin
    assert "retrying one-shot" in (lab.bus / "agents" / m["stream"]).read_text(encoding="utf-8")


# ── stop, crash, resume, timeout ──────────────────────────────────────────────

def test_stop_kills_a_live_run(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    monkeypatch.setenv("FAKE_SLEEP", "60")
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    executor.stop(lab, rid)
    m = wait_for(lab, rid, timeout=40)
    assert m["status"] == "killed" and m["reason"] == "stopped by the PI"
    assert m["attempts"][-1]["exit_code"] not in (0, None)


def test_crash_then_resume_continues_session(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    assert m["status"] == "failed" and m["reason"] == "exit 3"
    monkeypatch.setenv("FAKE_MODE", "complete")
    executor.resume(lab, m["run_id"])
    m2 = wait_for(lab, m["run_id"])
    assert m2["status"] == "completed" and m2["attempt"] == 2
    c = calls(lab, m2)[1]
    assert c["argv"][c["argv"].index("--resume") + 1] == m["session_id"]
    assert "interrupted" in c["stdin"]


def test_watchdog_times_out(hub):
    """The wall-clock watchdog in the shared drain loop kills an overrunning child → 'timeout'."""
    import os
    import executor.supervise as sup
    res = sup.run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=hub.root,
                          env=dict(os.environ), stream_path=hub.root / "s.jsonl", backend="claude",
                          max_seconds=2)
    assert res.breached and res.rc not in (0, None) and sup.classify(res) == "timeout"


def test_cancel_queued_run(hub, monkeypatch):
    lab = setup(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"]
    executor.cancel(lab, rid)
    m = executor.find_run(lab, rid)[3]
    assert m["status"] == "killed" and m["reason"] == "cancelled"
    assert executor.tick(lab)["started"] == []


# ── permission host + subagents ───────────────────────────────────────────────

def test_subagents_tracked_from_stream(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "subagents")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    sa = m["subagents"]["tu_agent"]
    assert sa["type"] == "experiment-runner" and sa["description"] == "variant exp-004"
    assert sa["status"] == "done" and "RESULT PACKET" in sa["result"]
    assert sa["n_actions"] == 1 and sa["last_action"]["tool"] == "Bash"
    assert m["last_action"]["tool"] == "Agent"   # the parent's own last action, not the subagent's


# ── chaining ──────────────────────────────────────────────────────────────────

def test_chain_next_launches_the_reported_next_step(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_REPORT", json.dumps({"next": "/lit-review idea-z", "needs_pi": "none", "summary": "ok"}))
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="ideate", args="small LMs", chain="next"))["run_id"])
    executor.tick(lab)
    m = executor.find_run(lab, m["run_id"])[3]
    child = executor.find_run(lab, m["chain_child"])[3]
    assert child["skill"] == "lit-review" and child["subject"] == "idea-z" and child["parent"] == m["run_id"]
    assert child["chain"] == "off"   # `next` follows exactly once


def test_chain_stops_at_a_gate(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_REPORT", json.dumps({"next": "/spawn-project idea-z", "needs_pi": "gate1", "summary": "proposal ready"}))
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="propose", target="idea-z", chain="loop"))["run_id"])
    executor.tick(lab)
    m = executor.find_run(lab, m["run_id"])[3]
    assert not m.get("chain_child")                      # never crosses a gate
    items = executor.attention.collect(lab)
    it = next(i for i in items if i["run_id"] == m["run_id"])
    assert it["kind"] == "needs_pi" and it["sev"] == "block" and "Gate 1" in it["title"]
    assert any(a["id"] == "next" and a["command"] == "/spawn-project idea-z" for a in it["actions"])


# ── refusals ──────────────────────────────────────────────────────────────────

def test_disabled_refuses_and_tick_starts_nothing(hub, monkeypatch):
    lab = setup(hub, enabled=False)
    with pytest.raises(SpecError, match="off"):
        executor.enqueue(lab, RunSpec(skill="lab-status"))


def test_missing_cli_refused_at_enqueue(hub):
    lab = setup(hub, backend_cmd=str(hub.root / "no-such-claude.exe"))   # a string = one executable path
    with pytest.raises(SpecError, match="CLI was not found"):
        executor.enqueue(lab, RunSpec(skill="lab-status"))


def test_expired_login_gets_an_actionable_reason(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "authfail")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    assert m["status"] == "failed" and "not logged in" in m["reason"] and "/login" in m["reason"]
    it = next(i for i in executor.attention.collect(lab) if i["run_id"] == m["run_id"])
    assert it["kind"] == "crashed" and "/login" in it["body"]


# ── tracing end to end: the executor's hooks + the repo's own, a nested subagent, joined to the run ──

def _traced(hub, monkeypatch, bg=False):
    import shutil as _sh
    monkeypatch.setenv("FAKE_MODE", "traced")
    monkeypatch.setenv("FAKE_BG", "1" if bg else "0")
    # the repo's own settings + tracer, as in a real lab: they must stand down (one line per event)
    (hub.root / ".claude").mkdir(exist_ok=True)
    _sh.copy(REPO / ".claude" / "settings.json", hub.root / ".claude" / "settings.json")
    (hub.root / "tools").mkdir(exist_ok=True)
    _sh.copy(REPO / "tools" / "trace_hook.py", hub.root / "tools" / "trace_hook.py")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"], timeout=90)
    assert m["status"] == "completed", m
    return lab, m


def _worker_lines(hub, wid):
    f = hub.lab / ".bus" / "workers" / f"{wid}.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_the_trace_is_recorded_once_joined_to_its_run_and_nested(hub, monkeypatch):
    lab, m = _traced(hub, monkeypatch)
    root = _worker_lines(hub, m["session_id"])
    assert root[0]["event"] == "start" and root[-1]["event"] == "stop"
    assert all(ln.get("run_id") == m["run_id"] for ln in root)
    assert len([ln for ln in root if ln["event"] == "start"]) == 1          # the repo's hooks stood down
    sub1, sub2 = _worker_lines(hub, "sub-1"), _worker_lines(hub, "sub-2")
    assert sub1[0]["session_id"] == m["session_id"] and sub2[0]["role"] == "overseer"
    sources = load("dashboard/sources")
    monkeypatch.setattr(sources.ctx, "HUB", hub.root)
    monkeypatch.setattr(sources.ctx, "LAB", hub.lab)
    snap = sources.snapshot()
    ws = {w["worker_id"]: w for w in snap["workers"]}
    assert ws[m["session_id"]]["run_id"] == m["run_id"]
    assert ws["sub-1"]["parent"] == m["session_id"] and ws["sub-1"]["run_id"] == m["run_id"]
    assert ws["sub-2"]["parent"] == "sub-1" and ws["sub-2"]["depth_in_session"] == 2   # nested, not flattened
    assert "sub-2" in ws["sub-1"]["children"] and ws["sub-2"]["result"] == "SUPPORTED"
    run = next(r for r in snap["runs"] if r["run_id"] == m["run_id"])
    assert run["subagents"] and run["subagents"][0]["type"] == "experiment-runner"


def test_a_background_subagent_is_not_done_at_launch(hub, monkeypatch):
    lab, m = _traced(hub, monkeypatch, bg=True)
    sa = m["subagents"]["tu_agent"]
    assert sa["background"] and sa["status"] == "done" and sa.get("launched")   # waited for, then finished
    root = _worker_lines(hub, m["session_id"])
    post = [ln for ln in root if ln.get("tool_use_id") == "tu_agent" and ln["event"] != "spawn"]
    assert post and post[0]["event"] == "action" and "background" in post[0]["summary"]


def test_a_backend_without_hooks_still_joins_its_run(hub, monkeypatch):
    """The supervisor's fallback log (no hooks fired) names its run, so the roster joins it."""
    sources = load("dashboard/sources")
    wdir = hub.lab / ".bus" / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    (wdir / "hub-x-1.jsonl").write_text(json.dumps({"ts": "2026-09-27T10:00:00", "worker_id": "hub-x-1", "event": "start",
                                                     "run_id": "hub-x-1", "session_id": "hub-x-1"}) + "\n", encoding="utf-8")
    ws = sources.workers.scan(hub.lab / ".bus")
    sources.workers.join_runs(ws, [{"run_id": "hub-x-1", "session_id": None, "status": "running", "command": "/lab-status"}])
    assert ws[0]["run_id"] == "hub-x-1" and ws[0]["label"] == "/lab-status" and not ws[0].get("interactive")
