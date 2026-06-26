"""Tests for tools/agent_runner.py — the programmatic headless-agent launcher.

These never invoke a real `claude`/`codex` CLI. A `_dummy` backend points at a tiny portable
Python emitter that prints codex-style JSONL to stdout, so we can verify the launcher's
PERSISTENCE + safety contract hermetically: manifest lifecycle, full stream capture, the
worker-log schema the dashboard reads, the agent_launched/agent_finished bus events, crash
reconcile, the depth guard, and the master-enable refusal.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
import types
from pathlib import Path

from conftest import REPO, load

# A portable emitter that mimics `codex exec --json` output, then exits 0.
_EMITTER = textwrap.dedent(
    """\
    import json, sys
    for obj in [
        {"type": "thread.started", "thread_id": "t-test"},
        {"type": "item.completed", "item": {"type": "command_execution",
                                            "command": "python scripts/run.py", "status": "completed"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "smoke green; cv=0.91"}},
    ]:
        sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()
    """
)

# A backend that never emits and just sleeps — used to trip the wall-clock watchdog.
_SLOW_EMITTER = "import time\ntime.sleep(30)\n"

_CONFIG = """\
lab:
  projects_root: "../projects"
compute:
  max_concurrent_runs: 1
agents:
  programmatic:
    enabled: {enabled}
    backend: _dummy
    model: inherit
    max_minutes: {max_minutes}
    max_concurrent: 2
    max_depth: 1
    backends:
      _dummy:
        command: {command}
"""


def _setup(hub, monkeypatch, *, enabled=True, emitter_src=_EMITTER, max_minutes=5):
    """Load the tool against the fake hub, wire a project + registry row + a _dummy backend."""
    emitter = hub.root / "emitter.py"
    emitter.write_text(emitter_src, encoding="utf-8")
    command = json.dumps([sys.executable, str(emitter)])  # JSON list -> backends._dummy.command
    (hub.lab / "config.yaml").write_text(
        _CONFIG.format(enabled=str(bool(enabled)).lower(), command=command, max_minutes=max_minutes),
        encoding="utf-8")
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    m = load("agent_runner")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m, proj


def _launch_args(**over):
    base = dict(project="demo", prompt="run the smoke and report", prompt_file=None,
                role="orchestrator", label=None, backend=None, model=None)
    base.update(over)
    return types.SimpleNamespace(**base)


def _read_jsonl(path: Path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── happy path: full capture + manifest + events + worker log ─────────────────────

def test_launch_captures_everything(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    rc = m.cmd_launch(_launch_args())
    assert rc == 0  # dummy exits 0 -> completed

    adir = proj / ".bus" / "agents"
    manifests = list(adir.glob("*.json"))
    assert len(manifests) == 1
    man = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert man["status"] == "completed"
    assert man["backend"] == "_dummy"
    assert man["exit_code"] == 0
    assert man["pid"] and man["wall_seconds"] is not None
    assert "cv=0.91" in (man["last_message"] or "")        # final agent_message captured
    assert man["session_id"] == "t-test"                   # thread.started id captured

    # full transcript persisted
    stream = adir / man["stream"]
    lines = _read_jsonl(stream)
    assert any(o.get("type") == "thread.started" for o in lines)
    assert any(o.get("type") == "item.completed" for o in lines)

    # bus events on the PROJECT bus, in the canonical shape
    events = _read_jsonl(proj / ".bus" / "events.jsonl")
    kinds = [e["kind"] for e in events]
    assert "agent_launched" in kinds and "agent_finished" in kinds
    fin = next(e for e in events if e["kind"] == "agent_finished")
    assert fin["source"] == proj.name and fin.get("status") == "completed"


def test_worker_log_matches_dashboard_schema(hub, monkeypatch):
    """The synthesized worker log must be the EXACT shape dashboard/sources.py _workers() reads."""
    m, proj = _setup(hub, monkeypatch)
    m.cmd_launch(_launch_args(label="agentX"))
    wlogs = list((proj / ".bus" / "workers").glob("*.jsonl"))
    assert len(wlogs) == 1
    lines = _read_jsonl(wlogs[0])
    events = [ln.get("event") for ln in lines]
    assert events[0] == "start" and events[-1] == "stop"     # lifecycle
    assert "action" in events                                # the command_execution item
    for ln in lines:
        assert "ts" in ln and "worker_id" in ln and "role" in ln
        assert ln["event"] in ("start", "action", "stop")

    # the dashboard reader folds it into the snapshot as a worker sprite
    src = load("dashboard/sources")
    monkeypatch.setattr(src, "HUB", hub.root)
    monkeypatch.setattr(src, "LAB", hub.lab)
    workers = src._workers(proj / ".bus", "demo")
    assert any(w["worker_id"].startswith("agentX") for w in workers)


def test_dashboard_surfaces_launched_agent(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    m.cmd_launch(_launch_args())
    src = load("dashboard/sources")
    monkeypatch.setattr(src, "HUB", hub.root)
    monkeypatch.setattr(src, "LAB", hub.lab)
    snap = src.snapshot()
    demo = next(it for it in snap["items"] if it["id"] == "demo")
    assert demo["agents"] and demo["agents"][0]["status"] == "completed"
    assert demo["agents"][0]["backend"] == "_dummy"


# ── safety: master switch, depth guard, concurrency ───────────────────────────────

def test_master_switch_off_blocks(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch, enabled=False)
    rc = m.cmd_launch(_launch_args())
    assert rc == 1
    assert not (proj / ".bus" / "agents").exists()           # nothing launched


def test_depth_guard_blocks_nested_launch(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    monkeypatch.setenv(m._DEPTH_ENV, "1")                    # we're already a launched agent
    rc = m.cmd_launch(_launch_args())
    assert rc == 1


def test_missing_prompt_blocks(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    rc = m.cmd_launch(_launch_args(prompt=None, prompt_file=None))
    assert rc == 1


# ── reconcile: a crashed 'running' manifest is marked failed (append-only) ─────────

def test_reconcile_marks_orphan_failed(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    adir = proj / ".bus" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "ghost.json").write_text(json.dumps({
        "agent_id": "ghost", "backend": "claude", "status": "running",
        "pid": 999999999,  # a pid that is not alive
    }), encoding="utf-8")
    rc = m.cmd_reconcile(types.SimpleNamespace(project="demo"))
    assert rc == 0
    man = json.loads((adir / "ghost.json").read_text(encoding="utf-8"))
    assert man["status"] == "failed"
    events = _read_jsonl(proj / ".bus" / "events.jsonl")
    assert any(e["kind"] == "agent_finished" and (e.get("data") or {}).get("reconciled")
               for e in events)


# ── backend command construction (pure-ish) ───────────────────────────────────────

def test_parse_activity_claude_shape(hub, monkeypatch):
    """The claude branch must parse the real `claude -p` stream-json envelope, not deltas."""
    m, _ = _setup(hub, monkeypatch)
    a = m._parse_activity("claude", {"type": "system", "subtype": "init", "session_id": "sess-1"})
    assert a["event"] == "start" and a["session_id"] == "sess-1"
    a = m._parse_activity("claude", {"type": "assistant", "message": {"content": [
        {"type": "text", "text": "thinking"},
        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})
    assert a["event"] == "action" and a["tool"] == "Bash" and "ls" in a["summary"]
    assert m._parse_activity("claude", {"type": "assistant",
                                        "message": {"content": [{"type": "text", "text": "hi"}]}}) is None
    a = m._parse_activity("claude", {"type": "result", "result": "final", "session_id": "sess-1"})
    assert a["event"] == "result" and a["last_message"] == "final"


def test_extra_args_protected_flag_refused(hub, monkeypatch):
    """A PI-owned extra_args must NOT be able to silently negate the human-in-loop permission default."""
    import pytest
    m, proj = _setup(hub, monkeypatch)
    prog = m._prog_cfg()
    prog.setdefault("backends", {}).setdefault("claude", {})["extra_args"] = "--permission-mode bypassPermissions"
    with pytest.raises(SystemExit):
        m._build_command("claude", "hi", proj, "inherit", "acceptEdits", prog)


def test_build_command_claude_and_codex(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    prog = m._prog_cfg()
    claude_cmd, fires = m._build_command("claude", "hi", proj, "inherit", "auto", prog)
    assert claude_cmd[:2] == ["claude", "-p"] and "--output-format" in claude_cmd
    assert "stream-json" in claude_cmd and fires is True     # claude fires hooks
    assert claude_cmd[claude_cmd.index("--permission-mode") + 1] == "auto"  # launch default flows through
    codex_cmd, fires2 = m._build_command("codex", "hi", proj, "gpt-5", "auto", prog)
    assert codex_cmd[:2] == ["codex", "exec"] and "--json" in codex_cmd
    assert "-C" in codex_cmd and ["-m", "gpt-5"] == codex_cmd[codex_cmd.index("-m"):codex_cmd.index("-m") + 2]
    assert codex_cmd[codex_cmd.index("-a") + 1] == "never"    # codex approval default
    assert codex_cmd[codex_cmd.index("--sandbox") + 1] == "workspace-write"
    assert "-c" not in codex_cmd                              # network off + no reasoning override by default
    assert fires2 is False                                    # codex needs a synthesized worker log


def test_per_backend_model_and_effort_defaults():
    """A backend with no launch/global model falls back to its own model + effort/reasoning keys."""
    m = load("agent_runner")
    prog = {"backends": {
        "claude": {"model": "claude-opus-4-8", "effort": "high"},
        "codex": {"model": "gpt-5.5", "reasoning_effort": "medium"},
    }}
    from pathlib import Path
    cc, _ = m._build_command("claude", "hi", Path("."), "inherit", "auto", prog)
    assert cc[cc.index("--model") + 1] == "claude-opus-4-8"   # per-backend default used (launch=inherit)
    assert cc[cc.index("--effort") + 1] == "high"
    xc, _ = m._build_command("codex", "hi", Path("."), "inherit", "auto", prog)
    assert xc[xc.index("-m") + 1] == "gpt-5.5"
    assert "model_reasoning_effort=medium" in xc             # passed as a -c override (no --effort flag)
    # an explicit launch/global model overrides the per-backend default
    cc2, _ = m._build_command("claude", "hi", Path("."), "claude-sonnet-4-6", "auto", prog)
    assert cc2[cc2.index("--model") + 1] == "claude-sonnet-4-6"


def test_build_command_opencode(hub, monkeypatch):
    from pathlib import Path
    import pytest
    m, proj = _setup(hub, monkeypatch)
    prog = {"backends": {"opencode": {}}}
    cmd, fires = m._build_command("opencode", "do X", proj, "inherit", "auto", prog)
    assert cmd[:6] == ["opencode", "run", "do X", "--format", "json", "--dir"]
    assert cmd[6] == str(proj)
    assert fires is False                                     # opencode needs a synthesized worker log
    assert "--model" not in cmd                               # inherit + blank backend model -> no -m
    # model (provider/model form) + variant + skip_permissions all flow from the backend cfg
    prog2 = {"backends": {"opencode": {
        "model": "anthropic/claude-sonnet-4-5", "variant": "high", "skip_permissions": True}}}
    cmd2, _ = m._build_command("opencode", "hi", proj, "inherit", "auto", prog2)
    assert cmd2[cmd2.index("--model") + 1] == "anthropic/claude-sonnet-4-5"
    assert cmd2[cmd2.index("--variant") + 1] == "high"
    assert "--dangerously-skip-permissions" in cmd2
    # default (no skip_permissions) omits the version-dependent flag
    cmd3, _ = m._build_command("opencode", "hi", proj, "inherit", "auto", prog)
    assert "--dangerously-skip-permissions" not in cmd3
    # the launcher owns --format/--dir/--dangerously-skip-permissions: refused in extra_args
    for bad in ("--format text", "--dir /tmp", "--dangerously-skip-permissions"):
        progx = {"backends": {"opencode": {"extra_args": bad}}}
        with pytest.raises(SystemExit):
            m._build_command("opencode", "hi", proj, "inherit", "auto", progx)


def test_parse_activity_opencode_shape(hub, monkeypatch):
    """opencode NDJSON: sessionID on every line, tool_use -> action, text -> result (last wins on EOF)."""
    m, _ = _setup(hub, monkeypatch)
    a = m._parse_activity("opencode", {"type": "step_start", "sessionID": "ses_AB", "part": {}})
    assert a["event"] == "start" and a["session_id"] == "ses_AB"
    a = m._parse_activity("opencode", {"type": "tool_use", "sessionID": "ses_AB", "part": {
        "tool": "bash", "state": {"status": "completed", "title": "Print hi", "input": {"command": "echo hi"}}}})
    assert a["event"] == "action" and a["tool"] == "bash" and "Print hi" in a["summary"] and a["session_id"] == "ses_AB"
    a = m._parse_activity("opencode", {"type": "text", "sessionID": "ses_AB", "part": {"text": "All done."}})
    assert a["event"] == "result" and a["last_message"] == "All done." and a["session_id"] == "ses_AB"
    a = m._parse_activity("opencode", {"type": "step_finish", "sessionID": "ses_AB", "part": {"reason": "stop"}})
    assert a["session_id"] == "ses_AB" and a["event"] != "result"   # never relied on for last_message
    a = m._parse_activity("opencode", {"type": "error", "sessionID": "ses_AB",
                                       "error": {"name": "APIError", "data": {"message": "rate limit"}}})
    assert a["event"] == "result" and "rate limit" in a["last_message"]
    # defensive: a tool_use missing the nested fields must not raise
    a = m._parse_activity("opencode", {"type": "tool_use", "sessionID": "ses_AB", "part": {}})
    assert a["event"] == "action" and not a["tool"]


def test_per_backend_safety_knobs_are_configurable(hub, monkeypatch):
    """Every safety flag the guard refuses in extra_args is settable via its dedicated per-backend key."""
    m, proj = _setup(hub, monkeypatch)
    prog = m._prog_cfg()
    backends = prog.setdefault("backends", {})
    backends.setdefault("claude", {})["permission_mode"] = "plan"      # overrides the launch default
    cx = backends.setdefault("codex", {})
    cx["approval"] = "untrusted"
    cx["sandbox"] = "read-only"
    cx["network_access"] = True

    claude_cmd, _ = m._build_command("claude", "hi", proj, "inherit", "auto", prog)
    assert claude_cmd[claude_cmd.index("--permission-mode") + 1] == "plan"  # per-backend key wins

    codex_cmd, _ = m._build_command("codex", "hi", proj, "inherit", "auto", prog)
    assert codex_cmd[codex_cmd.index("-a") + 1] == "untrusted"
    assert codex_cmd[codex_cmd.index("--sandbox") + 1] == "read-only"
    assert ["-c", "sandbox_workspace_write.network_access=true"] == \
        codex_cmd[codex_cmd.index("-c"):codex_cmd.index("-c") + 2]      # opt-in network override emitted


# ── headless permission contract: the project ships an engine allowlist ────────────

def test_project_settings_ship_engine_allowlist():
    """A headless launched agent runs --permission-mode auto; the project's settings.json must
    pre-approve the routine engine commands (`uv run …`) so they never stall/accumulate blocks.
    Without this the agent can edit files but can't run experiments. Guards the regression."""
    settings = json.loads(
        (REPO / "templates" / "project" / ".claude" / "settings.json").read_text(encoding="utf-8"))
    allow = (settings.get("permissions") or {}).get("allow") or []
    assert any(r.startswith("Bash(uv run") for r in allow), f"no uv-run allow rule in {allow}"
    # the rule must be a prefix-scoped Bash rule, not a blanket Bash() that would also auto-approve
    # destructive shell ops auto-mode is meant to still block.
    assert "Bash" not in allow and "Bash()" not in allow
    # hooks must survive alongside the new permissions block (trace_hook → dashboard).
    assert settings.get("hooks", {}).get("SessionStart")


# A portable emitter that mimics `opencode run --format json` NDJSON — note: NO terminal step_finish
# (the documented dropped-event case), so this proves last_message is finalized on stdout EOF.
_OPENCODE_EMITTER = textwrap.dedent(
    """\
    import json, sys
    for obj in [
        {"type": "step_start", "sessionID": "ses_AB", "part": {"type": "step-start"}},
        {"type": "tool_use", "sessionID": "ses_AB", "part": {"tool": "bash",
            "state": {"status": "completed", "title": "smoke", "input": {"command": "python run.py"}}}},
        {"type": "text", "sessionID": "ses_AB", "part": {"text": "smoke green; cv=0.91"}},
    ]:
        sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()
    """
)


def test_opencode_end_to_end_via_dummy_emitter(hub, monkeypatch):
    """cmd_launch must route backend='opencode' through the opencode parser, set the env, and
    finalize last_message on EOF — captured into the manifest + the synthesized worker log."""
    m, proj = _setup(hub, monkeypatch)
    emitter = hub.root / "oc_emitter.py"
    emitter.write_text(_OPENCODE_EMITTER, encoding="utf-8")
    # Focus on the launch+parse integration (the real opencode argv is covered separately): make
    # _build_command yield a portable emitter while keeping fires_hooks=False (synthesized worker log).
    monkeypatch.setattr(m, "_build_command", lambda *a, **k: ([sys.executable, str(emitter)], False))
    rc = m.cmd_launch(_launch_args(backend="opencode"))
    assert rc == 0
    man = json.loads(next((proj / ".bus" / "agents").glob("*.json")).read_text(encoding="utf-8"))
    assert man["status"] == "completed"
    assert man["session_id"] == "ses_AB"                       # sessionID rides every line
    assert man["last_message"] == "smoke green; cv=0.91"       # final `text`, finalized on EOF
    wlog = next((proj / ".bus" / "workers").glob("*.jsonl"))
    events = [ln.get("event") for ln in _read_jsonl(wlog)]
    assert events[0] == "start" and events[-1] == "stop" and events.count("action") == 1  # one tool_use


# ── watchdog: a backend that overruns max_minutes is KILLED and recorded 'timeout' ─

def test_watchdog_kills_on_timeout(hub, monkeypatch):
    """The sole kill for a hung headless agent: overrun max_minutes -> _kill_tree, status 'timeout'."""
    m, proj = _setup(hub, monkeypatch, emitter_src=_SLOW_EMITTER, max_minutes=0.05)  # 3s cap, child sleeps 30s
    rc = m.cmd_launch(_launch_args())
    assert rc == 2                                            # not 0 -> not 'completed'
    man = json.loads(next((proj / ".bus" / "agents").glob("*.json")).read_text(encoding="utf-8"))
    assert man["status"] == "timeout"
    assert man["exit_code"] not in (0, None)                 # the tree was actually killed
    fin = next(e for e in _read_jsonl(proj / ".bus" / "events.jsonl") if e["kind"] == "agent_finished")
    assert fin.get("status") == "timeout"


# ── cmd_list: reports every manifest with its status ──────────────────────────────

def test_cmd_list_reports_manifests(hub, monkeypatch, capsys):
    m, proj = _setup(hub, monkeypatch)
    adir = proj / ".bus" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "a1.json").write_text(json.dumps(
        {"agent_id": "a1", "backend": "claude", "status": "completed", "exit_code": 0, "started": "t"}),
        encoding="utf-8")
    (adir / "a2.json").write_text(json.dumps(
        {"agent_id": "a2", "backend": "_dummy", "status": "running", "pid": 999999999, "started": "t"}),
        encoding="utf-8")
    assert m.cmd_list(types.SimpleNamespace(project="demo")) == 0
    out = capsys.readouterr().out
    assert "Launched agents — demo (2)" in out
    assert "a1" in out and "completed" in out
    assert "a2" in out and "running" in out


def test_cmd_list_no_project(hub, monkeypatch):
    m, _ = _setup(hub, monkeypatch)
    assert m.cmd_list(types.SimpleNamespace(project="nope")) == 1


# ── cmd_kill: the PI's live stop button ───────────────────────────────────────────

def test_cmd_kill_no_running_agents(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    adir = proj / ".bus" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "done.json").write_text(json.dumps(
        {"agent_id": "done", "backend": "_dummy", "status": "completed", "pid": 1}), encoding="utf-8")
    assert m.cmd_kill(types.SimpleNamespace(project="demo", agent="done", all=False)) == 1  # nothing running


def test_cmd_kill_terminates_running_agent(hub, monkeypatch):
    m, proj = _setup(hub, monkeypatch)
    adir = proj / ".bus" / "agents"
    adir.mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (adir / "live.json").write_text(json.dumps(
            {"agent_id": "live", "backend": "_dummy", "status": "running", "pid": child.pid}),
            encoding="utf-8")
        assert m.cmd_kill(types.SimpleNamespace(project="demo", agent="live", all=False)) == 0
        deadline = time.time() + 8
        while child.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        assert child.poll() is not None                       # the tree was actually killed
        m.cmd_reconcile(types.SimpleNamespace(project="demo"))  # idempotent: mark the now-dead manifest
        man = json.loads((adir / "live.json").read_text(encoding="utf-8"))
        assert man["status"] == "failed"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
