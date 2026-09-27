"""Codex / opencode backends and subagent tracing everywhere.

Unit tests pin the stream parsers, the codex hook flags, the login probes and the tracer's tool-name
folding to the shapes read from the CLIs' sources (codex-rs rust-v0.157, opencode 1.18.23). The
end-to-end tests run real detached supervisors against tests/fake_codex.py (executes the `-c` hooks
through the platform shell, like codex) and tests/fake_opencode.mjs (loads the REAL tracer plugin
under node), then assert on the manifests AND the per-worker logs the dashboard reads.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import REPO, load

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec, backends, spec  # noqa: E402
from test_executor_e2e import calls, wait_for  # noqa: E402

FAKE_CODEX = REPO / "tests" / "fake_codex.py"
FAKE_OPENCODE = REPO / "tests" / "fake_opencode.mjs"
NODE = shutil.which("node")
needs_toml = pytest.mark.skipif(sys.version_info < (3, 11), reason="fake codex parses -c hooks with tomllib")


def _events(backend, obj):
    return backends.parse_events(backend, obj)


# ── codex: argv, stream, hooks ────────────────────────────────────────────────

def test_codex_collab_spawn_and_wait_become_subagent_events():
    started = _events("codex", {"type": "item.started", "item": {"type": "collab_tool_call", "tool": "spawn_agent",
                                                                 "receiver_thread_ids": [], "prompt": "exp-4"}})
    assert started[0]["event"] == "begin"
    done = _events("codex", {"type": "item.completed", "item": {
        "type": "collab_tool_call", "tool": "spawn_agent", "receiver_thread_ids": ["thr-1"], "prompt": "exp-4",
        "agents_states": {"thr-1": {"status": "pending_init", "message": None}}}})
    spawn = [e for e in done if e.get("spawn")][0]
    assert spawn["tool_use_id"] == "thr-1" and spawn["spawn"]["child_session"] == "thr-1"
    assert not [e for e in done if e["event"] == "tool_result"]        # still running
    waited = _events("codex", {"type": "item.completed", "item": {
        "type": "collab_tool_call", "tool": "wait", "receiver_thread_ids": ["thr-1"],
        "agents_states": {"thr-1": {"status": "completed", "message": "RESULT ok"}}}})
    res = [e for e in waited if e["event"] == "tool_result"][0]
    assert res["tool_use_id"] == "thr-1" and res["text"] == "RESULT ok" and res["is_error"] is False
    errored = _events("codex", {"type": "item.completed", "item": {
        "type": "collab_tool_call", "tool": "wait", "agents_states": {"thr-2": {"status": "errored", "message": "boom"}}}})
    assert [e for e in errored if e["event"] == "tool_result"][0]["is_error"] is True


def test_codex_turn_failed_declined_and_mcp_names():
    assert _events("codex", {"type": "turn.failed", "error": {"message": "quota"}})[0]["last_message"] == "[error] quota"
    ev = _events("codex", {"type": "item.completed", "item": {"id": "i1", "type": "command_execution",
                                                              "command": "rm -rf x", "status": "declined"}})
    assert [e["event"] for e in ev] == ["action", "denied"]
    mcp = _events("codex", {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "s2", "tool": "search"}})
    assert mcp[0]["tool"] == "mcp__s2__search"


def test_codex_hook_overrides_are_valid_toml_and_bypass_trust(tmp_path):
    tomllib = pytest.importorskip("tomllib")
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "trace_hook.py").write_text("", encoding="utf-8")
    flags = backends.codex_hook_overrides(tmp_path, {}, python=r"C:\Py 3\python.exe")
    assert flags[0] == "--dangerously-bypass-hook-trust"
    kv = dict(f.split("=", 1) for f in flags[2::2])
    assert set(kv) == {f"hooks.{e}" for e in backends.TRACE_EVENTS}
    for key, val in kv.items():
        groups = tomllib.loads("v = " + val)["v"]
        h = groups[0]["hooks"][0]
        assert h["type"] == "command" and h["command"].startswith('"C:\\Py 3\\python.exe" "')
        assert h["command"].endswith('trace_hook.py"')
        assert groups[0].get("matcher") == ("*" if key in ("hooks.PreToolUse", "hooks.PostToolUse") else None)
    assert backends.codex_hook_overrides(tmp_path, {"trace_hooks": False}) is None
    assert backends.codex_hook_overrides(tmp_path / "nowhere", {}) is None


def test_codex_argv_carries_hooks_and_resume_order(tmp_path):
    hooks = ["--dangerously-bypass-hook-trust", "-c", 'hooks.SessionStart=[{hooks=[{command="py trace_hook.py"}]}]']
    rc = backends.build_run_command("codex", prompt="p", workdir=tmp_path, prog={}, cli=["cx"],
                                    resume_sid="thr-9", codex_hooks=hooks)
    assert rc.fires_hooks is True
    assert rc.argv.index("--dangerously-bypass-hook-trust") < rc.argv.index("resume")
    assert rc.argv[-3:] == ["resume", "thr-9", "-"]


def test_auth_probes_parse_each_cli():
    cp = lambda rc, out="", err="": subprocess.CompletedProcess([], rc, out, err)  # noqa: E731
    assert backends._auth_from("claude", cp(0, '{"loggedIn": false, "authMethod": "none"}'))["logged_in"] is False
    assert backends._auth_from("codex", cp(0, "", "Logged in using ChatGPT\n")) == {"logged_in": True, "method": "ChatGPT"}
    assert backends._auth_from("codex", cp(1, "", "Not logged in\n"))["logged_in"] is False
    oc = "\x1b[90m┌\x1b[39m  Credentials\n└  0 credentials\n\n┌  Environment\n●  OpenAI OPENAI_API_KEY\n└  1 environment variable\n"
    assert backends._auth_from("opencode", cp(0, oc))["logged_in"] is True
    assert backends._auth_from("opencode", cp(0, "└  0 credentials\n"))["logged_in"] is False
    assert backends._auth_from("opencode", cp(0, "garbage")) is None


# ── opencode: stream ──────────────────────────────────────────────────────────

def test_opencode_task_is_a_subagent_with_its_result_and_step_finish_is_cost():
    part = {"callID": "call_t", "tool": "task", "state": {
        "status": "completed", "input": {"description": "variant 4", "subagent_type": "experiment-runner"},
        "output": '<task id="ses_c" state="completed"><task_result>RESULT ok</task_result></task>',
        "metadata": {"sessionId": "ses_c"}}}
    ev = _events("opencode", {"type": "tool_use", "sessionID": "ses_r", "part": part})
    assert ev[0]["spawn"] == {"subagent_type": "experiment-runner", "description": "variant 4", "child_session": "ses_c"}
    assert ev[1] == {"event": "tool_result", "tool_use_id": "call_t", "is_error": False, "text": "RESULT ok"}
    fin = _events("opencode", {"type": "step_finish", "sessionID": "ses_r", "part": {
        "cost": 0.01, "tokens": {"input": 5, "output": 2, "reasoning": 0, "cache": {"read": 1, "write": 0}}}})
    assert fin[0]["event"] == "usage" and fin[0]["cost_delta"] == 0.01 and fin[0]["usage"]["cache_read"] == 1
    assert fin[1]["session_id"] == "ses_r"


def test_opencode_traced_walks_up_to_git_root(tmp_path):
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert backends.opencode_traced(sub) is False
    (tmp_path / ".opencode" / "plugins").mkdir(parents=True)
    (tmp_path / ".opencode" / "plugins" / "newts-trace.js").write_text("", encoding="utf-8")
    assert backends.opencode_traced(sub) is True


# ── the tracer: codex + opencode payloads fold onto one vocabulary ─────────────

def _trace(tmp_path, payload, argv=(), env=None):
    hub = tmp_path / "hub"
    (hub / "lab").mkdir(parents=True, exist_ok=True)
    (hub / "lab" / "REGISTRY.md").write_text("# r\n", encoding="utf-8")
    subprocess.run([sys.executable, str(REPO / "tools" / "trace_hook.py"), *argv],
                   input=json.dumps({"cwd": str(hub), **payload}), text=True, check=True,
                   env={**os.environ, **(env or {})})
    wdir = hub / "lab" / ".bus" / "workers"
    return {f.stem: [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] for f in wdir.glob("*.jsonl")} \
        if wdir.exists() else {}


def test_tracer_folds_codex_payloads(tmp_path):
    base = {"session_id": "thr-root"}
    _trace(tmp_path, {**base, "hook_event_name": "PreToolUse", "tool_name": "apply_patch", "tool_use_id": "c1",
                      "tool_input": {"command": "*** Begin Patch\n*** Update File: src/model.py\n@@\n"}})
    _trace(tmp_path, {**base, "hook_event_name": "PreToolUse", "tool_name": "spawn_agent", "tool_use_id": "c2",
                      "tool_input": {"message": "run exp-4", "agent_type": "experiment-runner"}})
    logs = _trace(tmp_path, {**base, "hook_event_name": "PostToolUse", "tool_name": "spawn_agent", "tool_use_id": "c2",
                             "tool_input": {"message": "run exp-4", "agent_type": "experiment-runner"},
                             "tool_response": {"agent_id": "thr-kid", "nickname": "Ada"}})
    root = logs["thr-root"]
    assert root[0]["event"] == "begin" and root[0]["kind"] == "edit" and "model.py" in root[0]["summary"]
    assert root[1]["event"] == "spawn" and root[1]["spawns"] == "experiment-runner"
    assert root[2]["event"] == "action" and root[2]["child"] == "thr-kid" and "result" not in root[2]


def test_tracer_folds_opencode_task_and_camelcase(tmp_path):
    base = {"session_id": "ses_r"}
    _trace(tmp_path, {**base, "agent_id": "ses_c", "agent_type": "experiment-runner", "hook_event_name": "PostToolUse",
                      "tool_name": "read", "tool_input": {"filePath": "/x/configs/exp-4.yaml"}, "tool_use_id": "r1"})
    logs = _trace(tmp_path, {**base, "hook_event_name": "PostToolUse", "tool_name": "task", "tool_use_id": "t1",
                             "tool_input": {"description": "variant 4", "subagent_type": "experiment-runner"},
                             "tool_response": {"output": "<task id=\"ses_c\"><task_result>RESULT ok</task_result></task>",
                                               "child_session": "ses_c"}})
    kid = logs["ses_c"][0]
    assert kid["role"] == "experiment-runner" and kid["kind"] == "read" and "exp-4.yaml" in kid["summary"]
    ret = logs["ses_r"][0]
    assert ret["event"] == "return" and ret["result"] == "RESULT ok" and ret["child"] == "ses_c"


def test_repo_codex_hooks_stand_down_when_executor_passed_flags(tmp_path):
    p = {"session_id": "s", "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert _trace(tmp_path, p, argv=["--from-repo"], env={"NEWTS_TRACE_FLAGS": "1"}) == {}
    assert _trace(tmp_path, p, argv=["--from-repo"], env={"NEWTS_TRACE_FLAGS": ""})["s"]


def test_dashboard_links_spawn_to_exact_child(tmp_path):
    src = load("dashboard/sources")
    parent = src._fold_worker([
        {"ts": "2026-09-26T10:00:00", "worker_id": "r", "event": "spawn", "tool_use_id": "c1", "spawns": "default",
         "summary": "Agent: default: first"},
        {"ts": "2026-09-26T10:00:01", "worker_id": "r", "event": "spawn", "tool_use_id": "c2", "spawns": "default",
         "summary": "Agent: default: second"},
        {"ts": "2026-09-26T10:00:02", "worker_id": "r", "event": "action", "tool_use_id": "c2", "child": "kid-B"},
        {"ts": "2026-09-26T10:00:03", "worker_id": "r", "event": "action", "tool_use_id": "c1", "child": "kid-A"}])
    workers = [{"worker_id": "r", "is_subagent": False, "spawned": parent["spawns"], "_returns": {}},
               {"worker_id": "kid-B", "is_subagent": True, "parent": "r", "role": "default", "started": "1"},
               {"worker_id": "kid-A", "is_subagent": True, "parent": "r", "role": "default", "started": "2"}]
    src._link_workers(workers)
    labels = {w["worker_id"]: w.get("label") for w in workers}
    assert labels == {"r": None, "kid-B": "second", "kid-A": "first"}   # by id, not by start order


# ── claude-side hardening ─────────────────────────────────────────────────────

def test_ask_hook_refuses_questions_from_inside_a_subagent(tmp_path):
    payload = {"tool_name": "AskUserQuestion", "agent_id": "a1", "tool_use_id": "t", "tool_input": {"questions": []}}
    r = subprocess.run([sys.executable, str(REPO / "tools" / "executor" / "ask_hook.py")], input=json.dumps(payload),
                       text=True, capture_output=True, env={**os.environ, "NEWTS_RUN_DIR": str(tmp_path)})
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "result" in out["permissionDecisionReason"]
    assert not (tmp_path / "question.json").exists()          # the run does NOT pause


def test_preamble_warns_background_work_dies_with_the_session(hub):
    lab = executor.Lab(hub.root)
    v = spec.validate(lab, RunSpec(skill="lab-status"))
    text = spec.preamble(lab, "r1", v, "claude")
    assert "background shell job is killed" in text and "Subagents cannot ask the PI" in text


def test_spec_validates_model_effort_and_repeat(hub):
    lab = executor.Lab(hub.root)
    for bad in (dict(model="--dangerously-skip-permissions"), dict(model="a b"), dict(effort="ultra"),
                dict(repeat_minutes=1)):
        with pytest.raises(executor.SpecError):
            spec.validate(lab, RunSpec(skill="lab-status", **bad))
    spec.validate(lab, RunSpec(skill="lab-status", model="openai/gpt-5.5", effort="high", repeat_minutes=30))


# ── end to end: codex ─────────────────────────────────────────────────────────

def _setup_backend(hub, backend, cmd, extra=""):
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\n'
        "agents:\n  programmatic:\n    enabled: true\n"
        f"    backend: {backend}\n    max_minutes: 5\n    max_concurrent: 2\n    max_concurrent_total: 3\n"
        "    hub_max_concurrent: 2\n    max_depth: 1\n    backends:\n"
        f"      {backend}:\n        command: {json.dumps(cmd)}\n{extra}",
        encoding="utf-8")
    (hub.root / "tools").mkdir(exist_ok=True)
    shutil.copy(REPO / "tools" / "trace_hook.py", hub.root / "tools" / "trace_hook.py")
    return executor.Lab(hub.root)


def _workers(hub) -> dict:
    wdir = hub.lab / ".bus" / "workers"
    return {f.stem: [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
            for f in wdir.glob("*.jsonl")} if wdir.exists() else {}


def _wait_logs(hub, pred, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = _workers(hub)
        if pred(w):
            return w
        time.sleep(0.2)
    return _workers(hub)


@needs_toml
def test_codex_run_traces_subagents_through_real_hooks_and_resumes(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "subagents")
    lab = _setup_backend(hub, "codex", [sys.executable, str(FAKE_CODEX)])
    m = executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex", created_by="test"))
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed", m
    c = calls(lab, m)[0]
    assert "-a" not in c["argv"] and "--dangerously-bypass-hook-trust" in c["argv"] and c["argv"][-1] == "-"
    assert c["env"].get("NEWTS_TRACE_FLAGS") == "1"
    tid = m["session_id"]
    sa = m["subagents"]["thr-child-1"]                        # from the stream (collab_tool_call)
    assert sa["status"] == "done" and "metric=0.91" in sa["result"] and sa["session"] == "thr-child-1"
    assert m["usage"]["tokens"]["input_tokens"] == 120
    # the hooks ran through the shell and fed the same worker logs claude's do
    w = _wait_logs(hub, lambda w: "thr-child-1" in w and tid in w)
    assert m["run_id"] not in w                                # hooks fire → no synthesized run log
    kid = w["thr-child-1"]
    assert kid[0]["event"] == "start" and kid[0]["role"] == "experiment-runner" and kid[0]["session_id"] == tid
    assert any(ln.get("kind") == "run" for ln in kid)
    assert kid[-1]["event"] == "stop" and "metric=0.91" in kid[-1]["result"]
    root = w[tid]
    assert any(ln["event"] == "spawn" and ln.get("spawns") == "experiment-runner" for ln in root)
    assert any(ln.get("child") == "thr-child-1" for ln in root)
    # resume: reply → `codex exec … resume <thread> -`
    executor.reply(lab, m["run_id"], "now run exp-005")
    m = wait_for(lab, m["run_id"])
    assert m["status"] == "completed" and m["attempt"] == 2
    c2 = calls(lab, m)[1]
    assert c2["argv"][-3:] == ["resume", tid, "-"] and "now run exp-005" in c2["stdin"]


def test_codex_without_hook_script_falls_back_to_synthesized_log(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "complete")
    lab = _setup_backend(hub, "codex", [sys.executable, str(FAKE_CODEX)])
    (hub.root / "tools" / "trace_hook.py").unlink()
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status", backend="codex"))["run_id"])
    assert m["status"] == "completed"
    argv = calls(lab, m)[0]["argv"]
    assert not any("trace_hook" in a for a in argv)              # no tracer registered…
    assert any("signature_guard" in a for a in argv)             # …but the signature guard still is
    assert m["run_id"] in _workers(hub)                        # the supervisor's own worker log


# ── end to end: opencode (the real plugin, under node) ─────────────────────────

@pytest.mark.skipif(not NODE, reason="node is needed to load the opencode plugin")
def test_opencode_run_traces_subagents_through_the_real_plugin(hub, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "subagents")
    lab = _setup_backend(hub, "opencode", [NODE, str(FAKE_OPENCODE)])
    (hub.root / ".opencode" / "plugins").mkdir(parents=True)
    shutil.copy(REPO / ".opencode" / "plugins" / "newts-trace.js", hub.root / ".opencode" / "plugins")
    monkeypatch.setenv("NEWTS_PYTHON", sys.executable)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status", backend="opencode"))["run_id"])
    assert m["status"] == "completed", m
    assert m["session_id"] == "ses_root1" and m["last_message"] == "all done"
    assert m["usage"]["cost_usd"] == pytest.approx(0.0042) and m["usage"]["tokens"]["input"] == 150
    sa = m["subagents"]["call_task"]
    assert sa["status"] == "done" and sa["result"].startswith("RESULT PACKET") and sa["session"] == "ses_child1"
    w = _wait_logs(hub, lambda w: "ses_child1" in w and any(ln["event"] == "stop" for ln in w["ses_child1"]))
    assert m["run_id"] not in w                                # the plugin traces → no synthesized log
    kid = w["ses_child1"]
    assert kid[0]["event"] == "start" and kid[0]["role"] == "experiment-runner" and kid[0]["session_id"] == "ses_root1"
    assert {ln.get("kind") for ln in kid} >= {"read", "run"}
    assert kid[-1]["event"] == "stop" and kid[-1]["result"].startswith("RESULT PACKET")
    root = w["ses_root1"]
    assert any(ln["event"] == "spawn" and ln.get("spawns") == "experiment-runner" for ln in root)
    assert any(ln["event"] == "return" and ln.get("child") == "ses_child1" for ln in root)
    # reply resumes the same opencode session
    executor.reply(lab, m["run_id"], "and exp-005")
    m = wait_for(lab, m["run_id"])
    c2 = calls(lab, m)[1]
    assert m["status"] == "completed" and c2["argv"][c2["argv"].index("-s") + 1] == "ses_root1"


# ── claude env, legacy stop, campaigns over the executor ───────────────────────

def test_claude_runs_get_unbounded_background_subagent_wait(hub, monkeypatch):
    from test_executor_e2e import setup
    monkeypatch.setenv("FAKE_MODE", "complete")
    monkeypatch.delenv("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", raising=False)
    lab = setup(hub)
    m = wait_for(lab, executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"])
    env = calls(lab, m)[0]["env"]
    assert env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] == "0" and env["NEWTS_PYTHON"]


def test_legacy_launch_honours_the_dashboard_stop(hub, monkeypatch):
    ar = load("agent_runner")
    emitter = hub.root / "slow.py"
    emitter.write_text("import json,sys,time\nprint(json.dumps({'type':'thread.started','thread_id':'t'}),flush=True)\n"
                       "time.sleep(30)\n", encoding="utf-8")
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\nagents:\n  programmatic:\n    enabled: true\n    backend: _dummy\n'
        f"    max_minutes: 5\n    max_concurrent: 2\n    max_depth: 1\n    backends:\n      _dummy:\n"
        f"        command: {json.dumps([sys.executable, str(emitter)])}\n", encoding="utf-8")
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    monkeypatch.setattr(ar, "HUB", hub.root)
    monkeypatch.setattr(ar, "LAB", hub.lab)
    import types
    args = types.SimpleNamespace(project="demo", prompt="go", prompt_file=None, role="orchestrator", label=None,
                                 backend=None, model=None)
    t = threading.Thread(target=ar.cmd_launch, args=(args,), daemon=True)
    t.start()
    adir = proj / ".bus" / "agents"
    deadline = time.time() + 20
    man = None
    while time.time() < deadline:
        ms = list(adir.glob("*.json"))
        if ms:
            man = json.loads(ms[0].read_text(encoding="utf-8"))
            if man.get("status") == "running" and man.get("session_id"):
                break
        time.sleep(0.2)
    assert man and man["status"] == "running"
    lab = executor.Lab(hub.root)
    executor.stop(lab, man["run_id"])                          # what the dashboard's stop button calls
    t.join(timeout=30)
    man = json.loads((adir / f"{man['run_id']}.json").read_text(encoding="utf-8"))
    assert man["status"] == "killed" and man["reason"] == "stopped by the PI"


def test_campaign_workers_are_executor_runs(hub, monkeypatch):
    from test_executor_e2e import setup
    monkeypatch.setenv("FAKE_MODE", "complete")
    setup(hub)
    for slug in ("p1", "p2"):
        hub.add_registry_row(slug, state="active", project=str(hub.make_project(slug)))
    ar = load("agent_runner")
    monkeypatch.setattr(ar, "HUB", hub.root)
    monkeypatch.setattr(ar, "LAB", hub.lab)
    monkeypatch.setattr(ar, "CAMPAIGN_POLL_S", 0.3)
    man = ar.run_campaign(["p1", "p2"], "advance {{slug}} under {{campaign}}", campaign="camp.md")
    assert {r["status"] for r in man["results"].values()} == {"completed"}, man
    lab = executor.Lab(hub.root)
    for slug, r in man["results"].items():
        hit = executor.find_run(lab, r["agent_id"])
        assert hit, r
        run = hit[3]
        assert run["parent"] == man["campaign_id"] and run["created_by"] == "campaign" and run["target"] == slug
        stdin = calls(lab, run)[0]["stdin"]
        assert f"advance {slug} under {man['campaign_id']}" in stdin


# ── dashboard settings endpoint ───────────────────────────────────────────────

def test_executor_config_endpoint_whitelists_validates_and_stamps(hub, monkeypatch):
    serve = load("dashboard/serve")
    monkeypatch.setattr(serve, "LAB", hub.lab)
    monkeypatch.setattr(serve, "HUB", hub.root)
    monkeypatch.setattr(serve, "_pi_log", lambda rec: None)
    cfg = hub.lab / "config.yaml"
    cfg.write_text("agents:\n  programmatic:\n    enabled: false   # master\n    backend: claude   # which CLI\n"
                   "    max_minutes: 240\n    daily_max_runs: 0\ndashboard:\n  auto_spawn_on_gate1: false\n", encoding="utf-8")
    out, code = serve.set_executor_config({"changes": {"backend": "codex"}})
    assert code == 400                                          # needs confirm
    for bad in ({"enabled": True}, {"permission_mode": "bypassPermissions"}, {"max_minutes": 1},
                {"model": "--x"}, {"backend": "gemini"}):
        out, code = serve.set_executor_config({"changes": bad, "confirm": True})
        assert code == 400, bad
    out, code = serve.set_executor_config({"changes": {"backend": "opencode", "max_minutes": "90",
                                                       "daily_max_runs": 12, "auto_spawn_on_gate1": True},
                                           "confirm": True})
    assert code == 200, out
    text = cfg.read_text(encoding="utf-8")
    assert "backend: opencode" in text and "# which CLI" in text and "max_minutes: 90\n" in text  # comments kept
    assert "daily_max_runs: 12" in text and "auto_spawn_on_gate1: true" in text and "enabled: false" in text


def test_launch_passes_repeat_and_rejects_bad_model(hub, monkeypatch):
    from test_executor_e2e import setup
    serve = load("dashboard/serve")
    setup(hub)
    monkeypatch.setattr(serve, "HUB", hub.root)
    monkeypatch.setattr(serve, "_pi_log", lambda rec: None)
    out, code = serve.launch_run({"skill": "lab-status", "model": "-p", "confirm": True})
    assert code == 400 and "model" in out["error"]
    out, code = serve.launch_run({"skill": "lab-status", "repeat_minutes": "30", "max_repeats": "4",
                                  "effort": "high", "confirm": True})
    assert code == 200, out
    run = executor.find_run(executor.Lab(hub.root), out["run_id"])[3]
    assert run["repeat_minutes"] == 30 and run["max_repeats"] == 4 and run["effort"] == "high"


# ── shipped files: opencode roles + plugin, codex hooks, project upgrades ───────

def test_opencode_roles_and_plugin_ship_in_hub_and_template():
    for root in (REPO, REPO / "templates" / "project"):
        crit = (root / ".opencode" / "agents" / "ideation-critic.md").read_text(encoding="utf-8")
        assert "mode: subagent" in crit and "edit: deny" in crit and "task: deny" in crit
        runner = (root / ".opencode" / "agents" / "experiment-runner.md").read_text(encoding="utf-8")
        assert "bash: allow" in runner and "edit: allow" in runner
        hooks = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        assert set(hooks) == set(backends.TRACE_EVENTS)
        assert all("--from-repo" in g["hooks"][0]["command"] for gs in hooks.values() for g in gs)
    assert (REPO / ".opencode/plugins/newts-trace.js").read_bytes() == \
        (REPO / "templates/project/.opencode/plugins/newts-trace.js").read_bytes()


@pytest.mark.skipif(not NODE, reason="node is needed to syntax-check the opencode plugin")
def test_opencode_plugin_exports_only_plugin_functions():
    code = ("import(process.argv[1]).then(m => { const v = Object.values(m); "
            "if (!v.length || v.some(x => typeof x !== 'function')) process.exit(3) })")
    url = (REPO / ".opencode" / "plugins" / "newts-trace.js").as_uri()
    assert subprocess.run([NODE, "-e", code, url], timeout=30).returncode == 0


def test_upgrade_project_syncs_tracing_files(hub, monkeypatch):
    up = load("upgrade_project")
    proj = hub.make_project("old")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "trace_hook.py").write_text("# old\n", encoding="utf-8")
    (proj / ".claude").mkdir(exist_ok=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Read"]}, "hooks": {}}),
                                                    encoding="utf-8")
    assert up.upgrade(proj, check=True) > 0
    assert (proj / "scripts" / "trace_hook.py").read_text(encoding="utf-8") == "# old\n"   # check changes nothing
    up.upgrade(proj)
    st = json.loads((proj / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert st["permissions"] == {"allow": ["Read"]} and "SubagentStart" in st["hooks"]
    assert (proj / ".opencode" / "plugins" / "newts-trace.js").exists()
    assert (proj / "scripts" / "trace_hook.py").read_bytes().replace(b"\r\n", b"\n") == \
        (REPO / "templates/project/scripts/trace_hook.py").read_bytes().replace(b"\r\n", b"\n")
    assert up.upgrade(proj, check=True) == 0


def test_check_lab_flags_projects_with_stale_tracing(hub, monkeypatch):
    m = load("check_lab")
    monkeypatch.setattr(m, "HUB", hub.root)
    tmpl = hub.root / "templates" / "project" / "scripts"
    tmpl.mkdir(parents=True)
    (tmpl / "trace_hook.py").write_text("# current\n", encoding="utf-8")
    proj = hub.make_project("old")
    (proj / "scripts").mkdir(exist_ok=True)
    (proj / "scripts" / "trace_hook.py").write_text("# old\n", encoding="utf-8")
    rows = {"old": {"project": str(proj)}}
    assert any("upgrade_project.py old" in w for w in m.executor_checks({}, rows, hub.projects_root))
    (proj / "scripts" / "trace_hook.py").write_text("# current\n", encoding="utf-8")
    assert not any("upgrade_project" in w for w in m.executor_checks({}, rows, hub.projects_root))


def test_executor_config_inserts_keys_missing_from_an_older_config(hub, monkeypatch):
    serve = load("dashboard/serve")
    monkeypatch.setattr(serve, "LAB", hub.lab)
    monkeypatch.setattr(serve, "_pi_log", lambda rec: None)
    cfg = hub.lab / "config.yaml"
    cfg.write_text("agents:\n  programmatic:\n    enabled: true   # master\n    backends:\n      claude:\n"
                   "        model: opus\n\n# ── next section ──\nautopilot:\n  max_concurrent_projects: 1\n",
                   encoding="utf-8")
    out, code = serve.set_executor_config({"changes": {"daily_max_runs": 20, "hub_max_concurrent": 2},
                                           "confirm": True})
    assert code == 200, out
    import yaml
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    prog = doc["agents"]["programmatic"]
    assert prog["daily_max_runs"] == 20 and prog["hub_max_concurrent"] == 2
    assert prog["backends"]["claude"]["model"] == "opus" and doc["autopilot"]["max_concurrent_projects"] == 1
    assert "# ── next section ──" in cfg.read_text(encoding="utf-8")
    out, code = serve.set_executor_config({"changes": {"auto_spawn_on_gate1": True}, "confirm": True})
    assert code == 400 and "dashboard" in out["error"]      # no such section: refused, file untouched
