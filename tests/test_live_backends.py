"""Live sessions for codex (`codex app-server`) and opencode (`opencode serve`), end to end: real
detached supervisors against tests/fake_codex.py and tests/fake_opencode.mjs, which speak each
protocol (and run the real hooks / the real tracer plugin). Questions, approvals, messages and
interrupts reach the running agent; a reply after the session ended resumes the same thread."""

from __future__ import annotations

import shutil
import sys
import time

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec  # noqa: E402
from test_backend_tracing import FAKE_CODEX, FAKE_OPENCODE, NODE, _setup_backend, _wait_logs, needs_toml  # noqa: E402
from test_executor_e2e import DONE, calls, wait_for  # noqa: E402

needs_node = pytest.mark.skipif(not NODE, reason="node runs the fake opencode server")


def codex(hub):
    return _setup_backend(hub, "codex", [sys.executable, str(FAKE_CODEX)], live=True)


def opencode(hub):
    lab = _setup_backend(hub, "opencode", [NODE, str(FAKE_OPENCODE)], live=True)
    (hub.root / ".opencode" / "plugins").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / ".opencode" / "plugins" / "newts-trace.js", hub.root / ".opencode" / "plugins")
    return lab


def first_prompt(lab, m) -> str:
    return next(c["stdin"] for c in calls(lab, m) if c.get("stdin") is not None)


def wait_pending(lab, rid, key, timeout=30):
    deadline = time.time() + timeout
    m = {}
    while time.time() < deadline:
        executor.tick(lab, wait=1)
        m = executor.find_run(lab, rid)[3]
        if m.get(key):
            return m
        time.sleep(0.2)
    raise AssertionError(f"no {key} on {rid}: {m}")


# ── codex app-server ───────────────────────────────────────────────────────────

@needs_toml
def test_codex_live_session_traces_and_resumes_the_same_thread(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "subagents")
    lab = codex(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"])
    assert m["status"] == "completed" and m["transport"] == "live", m
    start = calls(lab, m)[0]
    assert start["argv"][0] == "app-server" and "--dangerously-bypass-hook-trust" not in start["argv"]
    p = start["params"]
    assert p["config"]["bypass_hook_trust"] is True and p["approvalPolicy"] == "on-request"
    assert "HEADLESS" in p["developerInstructions"] and p["cwd"]          # the preamble is the thread's instructions
    prompt = first_prompt(lab, m)                                          # …so the prompt is just the task
    assert "`/lab-status`" in prompt and "HEADLESS" not in prompt
    tid = m["session_id"]
    assert m["last_message"] == "done" and m["usage"]["tokens"]["input_tokens"] == 120
    sa = m["subagents"]["thr-child-1"]
    assert sa["status"] == "done" and sa["session"] == "thr-child-1"
    w = _wait_logs(hub, lambda w: "thr-child-1" in w and tid in w)
    assert w["thr-child-1"][0]["role"] == "experiment-runner" and m["run_id"] not in w   # the real hooks ran
    executor.reply(lab, m["run_id"], "now run exp-005")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed" and m["attempt"] == 2
    resumed = [c for c in calls(lab, m) if c.get("method") == "thread/resume"]
    assert resumed and resumed[0]["params"]["threadId"] == tid
    assert any(c.get("stdin") == "now run exp-005" for c in calls(lab, m))


@needs_toml
def test_codex_question_and_approval_reach_the_running_agent(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "question")
    lab = codex(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"]
    m = wait_for(lab, rid, statuses={"waiting_input"} | DONE)
    q = m["pending_question"]["input"]["questions"][0]
    assert m["status"] == "waiting_input" and q["question"] == "Which project type?" and q["options"][1]["label"] == "empirical"
    executor.answer(lab, rid, {"Which project type?": "empirical"})
    m = wait_for(lab, rid, statuses=DONE)
    assert m["status"] == "completed" and 'answers={"ptype": {"answers": ["empirical"]}}' == m["last_message"], m

    monkeypatch.setenv("FAKE_MODE", "approval")
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"]
    m = wait_pending(lab, rid, "pending_permissions")
    req = m["pending_permissions"][0]
    assert req["tool"] == "Bash" and req["input"]["command"] == "curl https://x" and req["why"] == "network access"
    executor.permission_decision(lab, rid, req["id"], False)
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and m["last_message"] == "decision=decline"


@needs_toml
def test_codex_steer_interrupt_and_usage_limit(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_STEER", "20")
    lab = codex(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    time.sleep(2)
    executor.reply(lab, rid, "use dataset B")
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and "steered: use dataset B" in m["last_message"] and m["attempt"] == 1, m
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    time.sleep(2)
    executor.interrupt(lab, rid)
    m = wait_for(lab, rid)
    assert "interrupted" in m["last_message"], m
    monkeypatch.setenv("FAKE_MODE", "usage_limit")
    monkeypatch.delenv("FAKE_STEER")
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"])
    assert m["status"] == "failed" and m["failure_kind"] == "usage_limit", m


# ── opencode serve ─────────────────────────────────────────────────────────────

@needs_node
def test_opencode_live_session_traces_through_the_plugin_and_resumes(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "subagents")
    monkeypatch.setenv("NEWTS_PYTHON", sys.executable)
    lab = opencode(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status", backend="opencode"))["run_id"])
    assert m["status"] == "completed" and m["transport"] == "live", m
    assert m["session_id"] == "ses_root1" and m["last_message"] == "all done"
    assert m["usage"]["cost_usd"] == pytest.approx(0.0042)
    sa = m["subagents"]["call_task"]
    assert sa["status"] == "done" and sa["session"] == "ses_child1" and sa["result"].startswith("RESULT PACKET")
    c = calls(lab, m)[0]
    assert "/lab-status" in c["stdin"] and "HEADLESS" not in c["stdin"]
    assert "HEADLESS" in c["body"]["system"]                                # the preamble rides `system`
    w = _wait_logs(hub, lambda w: "ses_child1" in w and any(ln["event"] == "stop" for ln in w["ses_child1"]))
    assert w["ses_child1"][0]["role"] == "experiment-runner" and m["run_id"] not in w   # the real plugin traced it
    executor.reply(lab, m["run_id"], "and exp-005")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed" and m["attempt"] == 2
    c2 = calls(lab, m)[-1]
    assert c2["argv"][2] == "ses_root1" and c2["stdin"] == "and exp-005"


@needs_node
def test_opencode_question_approval_and_steer(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "question")
    lab = opencode(hub)
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="opencode"))["run_id"]
    m = wait_for(lab, rid, statuses={"waiting_input"} | DONE)
    assert m["status"] == "waiting_input" and m["pending_question"]["tool_use_id"] == "que_1", m
    executor.answer(lab, rid, {"Which project type?": "ml"})
    m = wait_for(lab, rid, statuses=DONE)
    assert m["status"] == "completed" and m["last_message"] == 'answers=[["ml"]]', m

    monkeypatch.setenv("FAKE_MODE", "approval")
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="opencode"))["run_id"]
    m = wait_pending(lab, rid, "pending_permissions")
    assert m["pending_permissions"][0]["input"]["command"] == "curl https://x"
    executor.permission_decision(lab, rid, "per_1", True)
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and m["last_message"] == "decision=once"

    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.setenv("FAKE_STEER", "20")
    rid = executor.enqueue(lab, RunSpec(skill="lab-status", backend="opencode"))["run_id"]
    wait_for(lab, rid, statuses={"running"})
    time.sleep(2)
    executor.reply(lab, rid, "use dataset B")
    m = wait_for(lab, rid)
    assert m["status"] == "completed" and "steered: use dataset B" in m["last_message"] and m["attempt"] == 1, m
