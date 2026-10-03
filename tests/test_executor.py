"""Unit tests for tools/executor — the pieces the end-to-end tests build on.

Spec validation + the skill allowlist, argv per backend, stream parsing, the supervisor liveness
lock, reconcile, scheduler caps / brake / priorities (with an injected spawn — no processes), the
attention queue, and the stdin/stdout contracts of the AskUserQuestion hook and MCP permission host.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import RunSpec, SpecError, backends, manifest, procs, scheduler, spec  # noqa: E402

FAKE = REPO / "tests" / "fake_claude.py"


def setup(hub, *, enabled=True, extra: str = ""):
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\n'
        "agents:\n  programmatic:\n"
        f"    enabled: {str(bool(enabled)).lower()}\n    backend: claude\n    max_depth: 1\n"
        f"{extra}"
        "    backends:\n      claude:\n"
        f"        command: {json.dumps([sys.executable, str(FAKE)])}\n",
        encoding="utf-8")
    return executor.Lab(hub.root)


class Spawns:
    """An injected spawn(): records what the scheduler would start, starts nothing."""

    def __init__(self):
        self.calls = []

    def __call__(self, lab, where, run_id, log):
        self.calls.append((where, run_id))
        return 4242


# ── spec: allowlist, arguments, refusals ─────────────────────────────────────

def test_registry_never_contains_finalize():
    assert "finalize" not in executor.SKILL_REGISTRY and "finalize" in executor.NEVER
    for name, cfg in executor.SKILL_REGISTRY.items():
        assert cfg["level"] in ("hub", "project") and cfg["mode"] in ("headless", "interactive"), name


@pytest.mark.parametrize("bad", ["a\nb", "x" * 401, "--dangerously-skip-permissions", "rm -rf / ; ls", "$(whoami)"])
def test_sanitize_rejects(bad):
    with pytest.raises(SpecError):
        spec.sanitize_text(bad)


def test_sanitize_allows_in_project_only_for_ideate():
    assert spec.sanitize_text("--in-project demo", allow_in_project=True) == "--in-project demo"
    with pytest.raises(SpecError):
        spec.sanitize_text("--in-project demo")
    with pytest.raises(SpecError):
        spec.sanitize_text("--in-project ../x", allow_in_project=True)


def test_validate_levels_and_targets(hub):
    lab = setup(hub)
    with pytest.raises(SpecError, match="Gate 3"):
        spec.validate(lab, RunSpec(skill="finalize", target="x"))
    with pytest.raises(SpecError, match="unknown"):
        spec.validate(lab, RunSpec(skill="rm"))
    with pytest.raises(SpecError, match="needs an idea"):
        spec.validate(lab, RunSpec(skill="propose"))
    with pytest.raises(SpecError, match="inside a project"):
        spec.validate(lab, RunSpec(skill="experiment"))
    with pytest.raises(SpecError, match="no project repo"):
        spec.validate(lab, RunSpec(skill="experiment", target="ghost"))
    with pytest.raises(SpecError, match="invalid target"):
        spec.validate(lab, RunSpec(skill="propose", target="../etc"))
    with pytest.raises(SpecError, match="takes no arguments"):
        spec.validate(lab, RunSpec(skill="lab-status", args="x"))
    v = spec.validate(lab, RunSpec(skill="propose", target="idea-a"))
    assert v["workdir"] == lab.hub and v["subject"] == "idea-a"
    assert spec.slash_command(v) == "/propose idea-a"
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    v = spec.validate(lab, RunSpec(skill="experiment", target="demo", args="exp-003"))
    assert v["workdir"] == proj and spec.slash_command(v) == "/experiment demo exp-003"


def test_autopilot_brief_must_live_in_campaigns(hub):
    lab = setup(hub)
    with pytest.raises(SpecError, match="needs a signed campaign"):
        spec.validate(lab, RunSpec(skill="autopilot"))
    (hub.root / "evil.md").write_text("x", encoding="utf-8")
    with pytest.raises(SpecError):
        spec.validate(lab, RunSpec(skill="autopilot", args="evil.md"))
    (hub.lab / "campaigns").mkdir()
    (hub.lab / "campaigns" / "c1.md").write_text("brief", encoding="utf-8")
    v = spec.validate(lab, RunSpec(skill="autopilot", args="c1.md"))
    assert spec.slash_command(v) == "/autopilot continue lab/campaigns/c1.md"


def test_prompt_forms(hub):
    lab = setup(hub)
    v = spec.validate(lab, RunSpec(skill="propose", target="idea-a"))
    assert spec.render_prompt(lab, v, "claude") == "/propose idea-a"          # native slash command
    p = spec.render_prompt(lab, v, "codex")
    assert "SKILL.md" in p and "/propose idea-a" in p                        # other agents read the file
    pre = spec.preamble(lab, "rid-1", v, "claude")
    assert "run_report --run-id rid-1" in pre and "Gate 3" in pre and "AskUserQuestion" in pre
    assert "(question)" in spec.preamble(lab, "rid-1", v, "opencode") and "(request_user_input)" in spec.preamble(lab, "rid-1", v, "codex")


# ── backends: argv, resolution, parsing ──────────────────────────────────────

def test_run_command_claude_first_attempt_and_resume(hub):
    cli = ["claude.exe"]
    rc = backends.build_run_command("claude", prompt="/lab-status", workdir=hub.root, prog={}, cli=cli,
                                    session_id="S1", settings_path=Path("s.json"),
                                    system_prompt_file=Path("p.md"), add_dirs=[Path("/hub")], cli_ver=(2, 1, 300))
    a = rc.argv
    assert a[:2] == ["claude.exe", "-p"] and rc.stdin_text == "/lab-status"   # one-shot: prompt via stdin
    assert a[a.index("--session-id") + 1] == "S1" and "--resume" not in a
    assert a[a.index("--permission-mode") + 1] == "auto" and "--forward-subagent-text" in a
    assert "--permission-prompt-tool" not in a and "--input-format" not in a
    lv = backends.build_run_command("claude", prompt="/lab-status", workdir=hub.root, prog={}, cli=cli,
                                    session_id="S1", live=True, cli_ver=(2, 1, 300)).argv
    assert lv[lv.index("--input-format") + 1] == "stream-json" and "--replay-user-messages" in lv
    assert lv[lv.index("--permission-prompt-tool") + 1] == "stdio"
    rc2 = backends.build_run_command("claude", prompt=None, workdir=hub.root, prog={}, cli=cli,
                                     resume_sid="S1", cli_ver=(2, 1, 100))
    assert rc2.argv[rc2.argv.index("--resume") + 1] == "S1" and rc2.stdin_text is None
    assert "--forward-subagent-text" not in rc2.argv            # version-gated flag skipped on old CLIs
    assert "--permission-mode" in rc2.argv                      # re-passed: a -p resume doesn't restore it


def test_run_command_argv_mode_keeps_prompt_before_variadic_flags(hub):
    rc = backends.build_run_command("claude", prompt="hello", workdir=hub.root,
                                    prog={"backends": {"claude": {"prompt_via": "argv"}}}, cli=["c"],
                                    add_dirs=[Path("/hub")])
    assert rc.argv[2] == "hello" and rc.stdin_text is None


@pytest.mark.parametrize("flag", ["--settings x", "--resume y", "--add-dir /", "--mcp-config z", "--input-format text",
                                  "--permission-mode bypassPermissions", "--dangerously-skip-permissions"])
def test_executor_owned_flags_refused_in_extra_args(hub, flag):
    with pytest.raises(SystemExit):
        backends.build_run_command("claude", prompt="x", workdir=hub.root, cli=["c"],
                                   prog={"backends": {"claude": {"extra_args": flag}}})


def test_run_command_other_backends(hub):
    rc = backends.build_run_command("opencode", prompt="do it", workdir=hub.root, prog={}, cli=["oc"],
                                    resume_sid="ses_1", preamble="RULES")
    assert rc.argv[:3] == ["oc", "run", "do it\n\n---\nRULES"] and rc.argv[rc.argv.index("-s") + 1] == "ses_1"
    assert rc.stdin_text is None and rc.fires_hooks is False
    rc = backends.build_run_command("codex", prompt="go", workdir=hub.root, prog={}, cli=["cx"])
    assert rc.argv[:2] == ["cx", "exec"] and rc.argv[-1] == "-" and rc.stdin_text == "go"
    assert "--json" in rc.argv and "-a" not in rc.argv and "resume" not in rc.argv
    assert rc.fires_hooks is False                       # no tracer hooks passed → synthesized worker log
    # resume (codex ≥0.35): exec-level options BEFORE the subcommand, then `resume <thread> -`
    rc = backends.build_run_command("codex", prompt="more", workdir=hub.root, prog={}, cli=["cx"], resume_sid="t-1")
    assert rc.argv[-3:] == ["resume", "t-1", "-"] and rc.stdin_text == "more"
    assert rc.argv.index("-C") < rc.argv.index("resume") and rc.argv.index("--sandbox") < rc.argv.index("resume")
    with pytest.raises(SystemExit, match="resume"):
        backends.build_run_command("codex", prompt="go", workdir=hub.root, cli=["cx"],
                                   prog={"backends": {"codex": {"extra_args": "resume --last"}}})


def test_resolve_cli(tmp_path, monkeypatch):
    exe = tmp_path / ("claude.exe" if os.name == "nt" else "claude")
    exe.write_text("", encoding="utf-8")
    assert backends.resolve_cli("claude", {"command": str(exe)}) == [str(exe)]
    assert backends.resolve_cli("claude", {"command": ["py", "fake.py"]}) == ["py", "fake.py"]
    assert backends.resolve_cli("claude", {"command": str(tmp_path / "nope")}) is None
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(backends, "_candidates", lambda name: [exe])
    assert backends.resolve_cli("claude") == [str(exe)]          # falls back to install locations
    assert backends.resolve_cli("not-a-backend") is None


def test_cli_version_parses_fake():
    assert backends.cli_version([sys.executable, str(FAKE)]) == (9, 9, 9)


def test_parse_events_claude_tree_and_defer():
    evs = backends.parse_events("claude", {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
        {"type": "text", "text": "hi"},
        {"type": "tool_use", "id": "t1", "name": "Agent", "input": {"subagent_type": "overseer", "description": "check"}},
        {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls"}}]}})
    assert [e["event"] for e in evs] == ["text", "action", "action"]           # every block, not just the first
    assert evs[1]["spawn"] == {"subagent_type": "overseer", "description": "check", "background": False}
    sub = backends.parse_events("claude", {"type": "assistant", "parent_tool_use_id": "t1", "message": {
        "content": [{"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "a.md"}}]}})
    assert sub[0]["parent"] == "t1" and sub[0]["summary"] == "a.md"
    tr = backends.parse_events("claude", {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "PACKET"}]}]}})
    assert tr[0]["event"] == "tool_result" and tr[0]["text"] == "PACKET"
    r = backends.parse_events("claude", {"type": "result", "stop_reason": "end_turn", "session_id": "s",
                                         "total_cost_usd": 0.5})[0]
    assert r["stop_reason"] == "end_turn" and r["cost_usd"] == 0.5


def test_parse_events_codex_singular_types_and_no_double_count():
    started = backends.parse_events("codex", {"type": "item.started", "item": {"type": "file_change"}})
    done = backends.parse_events("codex", {"type": "item.completed", "item": {"type": "file_change"}})
    assert started[0]["event"] == "begin" and done[0]["event"] == "action"


# ── locks ────────────────────────────────────────────────────────────────────

def test_runlock_exclusive_and_freed_when_holder_dies(tmp_path):
    lockf = tmp_path / "r.d" / "lock"
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sys, time; sys.path.insert(0, sys.argv[1]);"
                               "from executor.procs import RunLock; l = RunLock(sys.argv[2]);"
                               "assert l.try_acquire(); print('held', flush=True); time.sleep(60)",
                               str(REPO / "tools"), str(lockf)], stdout=subprocess.PIPE, text=True,
                              **procs.NEW_GROUP)
    try:
        assert holder.stdout.readline().strip() == "held"
        assert procs.is_locked(lockf)
        assert not procs.RunLock(lockf).try_acquire()
        procs.kill_tree(holder.pid)
        holder.wait(timeout=15)
        deadline = time.time() + 5
        while procs.is_locked(lockf) and time.time() < deadline:
            time.sleep(0.1)
        assert not procs.is_locked(lockf)          # the kernel released it on death
    finally:
        if holder.poll() is None:
            holder.kill()


def test_excl_lock_reclaims_stale(tmp_path):
    f = tmp_path / ".x.lock"
    f.write_text("dead", encoding="utf-8")
    old = time.time() - 600
    os.utime(f, (old, old))
    with procs.excl_lock(f, wait=1):
        assert f.exists()
    assert not f.exists()


# ── scheduler: caps, priorities, brake, reconcile (injected spawn) ───────────

def _queue(lab, n, **kw):
    return [executor.enqueue(lab, RunSpec(skill="advance", target=f"idea-{i}", **kw))["run_id"] for i in range(n)]


def test_hub_cap_serializes_lab_wide_hub_sessions_but_not_per_study_ones(hub):
    """hub_max_concurrent caps hub sessions that aren't about a study; a hub run about a study (e.g.
    /analyze idea-x) counts against that study, so one long hub procedure doesn't block the others."""
    lab = setup(hub, extra="    hub_max_concurrent: 1\n    max_concurrent: 1\n    max_concurrent_total: 5\n")
    lab_wide = [executor.enqueue(lab, RunSpec(skill="lab-status"))["run_id"] for _ in range(2)]
    per_study = _queue(lab, 2)
    again = executor.enqueue(lab, RunSpec(skill="advance", target="idea-0"))["run_id"]
    sp = Spawns()
    rep = executor.tick(lab, spawn=sp)
    started = set(rep["started"])
    assert len(started & set(lab_wide)) == 1                                 # one lab-wide hub session
    assert len(started & {per_study[0], again}) == 1 and per_study[1] in started   # one per study
    assert len(started) == 3


def test_total_cap_and_priority_and_not_before(hub):
    lab = setup(hub, extra="    hub_max_concurrent: 5\n    max_concurrent_total: 2\n")
    low = _queue(lab, 2)
    hi = executor.enqueue(lab, RunSpec(skill="advance", target="idea-hi", priority=5))["run_id"]
    later = executor.enqueue(lab, RunSpec(skill="advance", target="idea-later", priority=9,
                                          extra={"not_before": "2999-01-01T00:00:00"}))["run_id"]
    rep = executor.tick(lab, spawn=Spawns())
    assert rep["started"] == [hi, low[0]]           # priority first; the future run waits; cap 2
    assert executor.find_run(lab, later)[3]["status"] == "queued"


def test_disabled_tick_starts_nothing(hub):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    setup(hub, enabled=False)
    rep = executor.tick(lab, spawn=Spawns())
    assert rep["started"] == [] and rep["enabled"] is False
    assert executor.find_run(lab, rid)[3]["status"] == "queued"


def test_daily_brake(hub):
    lab = setup(hub, extra="    daily_max_runs: 1\n    hub_max_concurrent: 5\n")
    a, b = _queue(lab, 2)
    path = executor.find_run(lab, a)[2]
    m = manifest.read_manifest(path)
    m["attempts"] = [{"n": 1, "started": manifest.now(), "wall_seconds": 5}]
    manifest.write_manifest(path, m)
    rep = executor.tick(lab, spawn=Spawns())
    assert rep["brake"] and "daily run cap" in rep["brake"] and rep["started"] == []
    items = executor.attention.collect(lab, brake_reason=rep["brake"])
    assert any(it["kind"] == "brake" for it in items)


def test_depth_guard_blocks_enqueue_and_tick(hub, monkeypatch):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    monkeypatch.setenv("AUTOSCIENTIST_AGENT_DEPTH", "1")
    with pytest.raises(SpecError, match="depth"):
        _queue(lab, 1)
    assert executor.tick(lab, spawn=Spawns())["started"] == []
    assert executor.find_run(lab, rid)[3]["status"] == "queued"


def test_reconcile_marks_dead_supervisor_failed_but_respects_grace(hub):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    _t, workdir, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, "running", by="test", pid=None)
    assert executor.reconcile(lab) == 1                          # no lock holder → orphan
    m = executor.find_run(lab, rid)[3]
    assert m["status"] == "failed" and "supervisor gone" in m["reason"]
    rid2 = _queue(lab, 1)[0]
    _t, _w, path2, m2 = executor.find_run(lab, rid2)
    manifest.transition(lab, path2, m2, "starting", by="test")
    assert executor.reconcile(lab) == 0                          # starting within its grace window
    assert executor.find_run(lab, rid2)[3]["status"] == "starting"


def test_queue_ops_state_checks(hub):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    with pytest.raises(SpecError, match="not waiting"):
        executor.answer(lab, rid, {"q": "a"})
    with pytest.raises(SpecError, match="only a finished"):
        executor.resume(lab, rid)
    with pytest.raises(SpecError, match="no run"):
        executor.stop(lab, "nope")
    executor.stop(lab, rid)                                      # a queued run → cancelled
    assert executor.find_run(lab, rid)[3]["reason"] == "cancelled"


def test_answer_validation(hub):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    _t, _w, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, "waiting_input", by="test",
                        pending_question={"tool_use_id": "t", "input": {"questions": []}})
    for bad in ({"q": 5}, {"": "x"}, {"q": ["a", 3]}, {"q": "x" * 5000}):
        with pytest.raises(SpecError):
            executor.answer(lab, rid, bad)
    m = executor.answer(lab, rid, {"Which?": ["a", "b"]})   # parked (no live session): the answer resumes it
    assert m["status"] == "queued" and m["resume"]["mode"] == "reply" and "- Which?: a, b" in m["resume"]["text"]
    assert m["qa"][-1]["answers"] == {"Which?": ["a", "b"]} and m["pending_question"] is None


def test_parse_next():
    s = scheduler.parse_next("/spawn-project idea-q")
    assert (s.skill, s.target) == ("spawn-project", "idea-q")
    assert scheduler.parse_next("/finalize idea-q") is None      # Gate 3 never chains
    assert scheduler.parse_next("/discuss direction") is None    # interactive skills never auto-chain
    assert scheduler.parse_next("run the tests") is None
    assert scheduler.parse_next("/advance").target == "hub"
    s = scheduler.parse_next("/experiment demo exp-004")
    assert (s.target, s.args) == ("demo", "exp-004")


# ── attention ────────────────────────────────────────────────────────────────

def test_attention_kinds_ids_and_acks(hub):
    lab = setup(hub)
    ids = _queue(lab, 3)
    rows = []
    for rid, st, extra in ((ids[0], "waiting_input", {"pending_question": {"input": {"questions": [{"question": "Q?"}]}}}),
                           (ids[1], "failed", {"session_id": "s", "reason": "exit 1"}),
                           (ids[2], "completed", {"report": {"needs_pi": None, "next": "/lit-review x", "summary": "done"}})):
        _t, _w, path, m = executor.find_run(lab, rid)
        manifest.transition(lab, path, m, st, by="test", **extra)
        rows.append(rid)
    items = executor.attention.collect(lab)
    kinds = {it["kind"]: it for it in items}
    assert kinds["question"]["sev"] == "block" and kinds["question"]["title"] == "Q?"
    assert any(a["id"] == "resume" for a in kinds["crashed"]["actions"])
    assert kinds["report"]["sev"] == "info" and kinds["report"]["detail"]["next"] == "/lit-review x"
    assert items[0]["kind"] == "question"                        # most urgent first
    executor.attention.ack(lab, kinds["report"]["id"], "dismiss")
    assert "report" not in {it["kind"] for it in executor.attention.collect(lab)}
    with pytest.raises(ValueError):
        executor.attention.ack(lab, "x", "explode")


def test_health_reports_cli_and_caps(hub):
    lab = setup(hub)
    h = executor.health(lab)
    assert h["enabled"] is True and h["clis"]["claude"]["found"] and h["clis"]["claude"]["version"] == "9.9.9"
    assert h["caps"]["hub"] == 1 and h["queued"] == 0


# ── check_lab: executor hygiene lints ────────────────────────────────────────

def test_check_lab_executor_lints(hub, monkeypatch):
    from conftest import load
    m = load("check_lab")
    monkeypatch.setattr(m, "HUB", hub.root)
    adir = hub.lab / ".bus" / "agents"
    adir.mkdir(parents=True)
    (adir / "old.json").write_text(json.dumps({"run_id": "old", "status": "running", "max_minutes": 10,
                                                "status_ts": "2020-01-01T00:00:00"}), encoding="utf-8")
    (adir / "ask.json").write_text(json.dumps({"run_id": "ask", "status": "waiting_input",
                                                "status_ts": "2020-01-01T00:00:00"}), encoding="utf-8")
    cfg = {"agents": {"programmatic": {"enabled": False, "backends": {"claude": {"command": str(hub.root / "nope.exe")}}}},
           "dashboard": {"auto_spawn_on_gate1": True}}
    out = m.executor_checks(cfg, {}, hub.projects_root)
    text = "\n".join(out)
    assert "auto_spawn_on_gate1" in text and "nope.exe" in text
    assert "run old has been 'running'" in text and "run ask has waited" in text


def test_reconcile_never_overwrites_a_run_that_just_finished(hub):
    """Race: reconcile holds a stale 'running' copy, the supervisor then writes 'completed' and frees its
    lock. Reconcile must re-read and leave the terminal record alone (not turn it into 'failed')."""
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    _t, workdir, path, m = executor.find_run(lab, rid)
    stale = dict(m, status="running")
    manifest.transition(lab, path, m, "completed", by="supervisor", finished=manifest.now())
    assert scheduler.reconcile_manifest(lab, workdir, path, stale) is False
    assert executor.find_run(lab, rid)[3]["status"] == "completed"


def test_reconcile_requeues_a_run_whose_supervisor_died_before_starting(hub):
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    _t, workdir, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, "starting", by="scheduler")
    rd = manifest.run_dir(path.parent, rid)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "spawn.json").write_text(json.dumps({"pid": 999999991, "ts": manifest.now()}), encoding="utf-8")
    assert scheduler.reconcile_manifest(lab, workdir, path, m) is True
    m = executor.find_run(lab, rid)[3]
    assert m["status"] == "queued" and m["spawn_retries"] == 1 and "re-queued" in m["reason"]


def test_health_reports_cli_login(hub, monkeypatch):
    lab = setup(hub)
    backends._AUTH_CACHE.clear()
    monkeypatch.setenv("FAKE_LOGGED_IN", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert executor.health(lab)["clis"]["claude"]["logged_in"] is False
    backends._AUTH_CACHE.clear()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")          # an API key also works without a claude.ai login
    assert executor.health(lab)["clis"]["claude"]["logged_in"] is True
    backends._AUTH_CACHE.clear()
