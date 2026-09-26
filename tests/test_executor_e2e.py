"""End-to-end executor tests: real detached supervisor processes driving tests/fake_claude.py.

These exercise the whole path a dashboard click takes — enqueue → tick → detached supervisor →
agent CLI (fake) → stream capture → manifest/bus/ledger — including the AskUserQuestion defer hook,
the MCP permission host, stop, crash + resume, reply, subagent tracking, and the run_report footer.
No real model, no network, no ports.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec, SpecError  # noqa: E402

FAKE = REPO / "tests" / "fake_claude.py"
LIVE = {"queued", "starting", "resuming", "running"}


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
    assert c["stdin"] == "/lab-status"
    assert "--session-id" in c["argv"] and c["argv"][c["argv"].index("--session-id") + 1] == m["session_id"]
    assert c["argv"][c["argv"].index("--permission-mode") + 1] == "auto"
    assert "--append-system-prompt-file" in c["argv"] and "--settings" in c["argv"]
    assert c["argv"][c["argv"].index("--permission-prompt-tool") + 1] == "mcp__newts__permission"
    assert c["env"]["AUTOSCIENTIST_NO_GATE3"] == "1" and c["env"]["AUTOSCIENTIST_AGENT_DEPTH"] == "1"
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

def test_defer_answer_resume_round_trip(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub)
    m = executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-x", created_by="test"))
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "waiting_input", m
    pq = m["pending_question"]
    assert pq["tool_use_id"] == "toolu_q1"
    assert pq["input"]["questions"][0]["question"] == "Which project type?"
    assert (run_dir(lab, m) / "question.json").exists()          # written by the real hook
    events = [json.loads(x) for x in (lab.bus / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["kind"] == "agent_waiting" and e["data"]["run_id"] == m["run_id"] for e in events)
    # answering queues the resume; the resumed attempt continues the same session
    executor.answer(lab, m["run_id"], {"Which project type?": "empirical"})
    m2 = executor.find_run(lab, m["run_id"])[3]
    assert m2["status"] == "queued" and m2["resume"]["mode"] == "answer" and m2["pending_question"] is None
    m2 = wait_for(lab, m["run_id"])
    assert m2["status"] == "completed", m2
    assert 'answers={"Which project type?": "empirical"}' in m2["last_message"]
    assert m2["attempt"] == 2 and [a["resume"] for a in m2["attempts"]] == [None, "answer"]
    assert m2["qa"][0]["answers"] == {"Which project type?": "empirical"}
    c = calls(lab, m2)
    assert c[1]["argv"][c[1]["argv"].index("--resume") + 1] == m["session_id"]   # same session
    assert "--session-id" not in c[1]["argv"]
    assert c[1]["argv"][c[1]["argv"].index("--permission-mode") + 1] == "auto"    # re-passed on resume
    assert c[1]["stdin"] == ""                                                    # no new user turn
    assert (run_dir(lab, m) / "answer.used.json").exists()


def test_free_text_reply_to_a_question(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "defer")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="spawn-project", target="idea-y"))["run_id"])
    assert m["status"] == "waiting_input"
    executor.reply(lab, m["run_id"], "neither — it's a theory project")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed"
    assert "response=neither — it's a theory project" in m["last_message"]


def test_prose_question_then_reply_resumes_with_text(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "prose")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="discuss", args="direction"))["run_id"])
    assert m["status"] == "completed" and "A or B" in m["last_message"]
    executor.reply(lab, m["run_id"], "Use dataset B")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed" and "Use dataset B" in m["last_message"]
    c = calls(lab, m)
    assert c[1]["stdin"] == "Use dataset B" and "--resume" in c[1]["argv"]


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

def test_permission_host_denies_and_logs(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "mcp")
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    assert m["status"] == "completed" and "permission=deny" in m["last_message"]
    log = (run_dir(lab, m) / "permissions.jsonl").read_text(encoding="utf-8")
    assert '"decision": "deny"' in log and "rm -rf" in log
    items = executor.attention.collect(lab)
    assert any(it["kind"] == "denied" and it["run_id"] == m["run_id"] for it in items)


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
