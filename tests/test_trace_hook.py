"""Tests for tools/trace_hook.py — the fail-safe activity tracer (a Claude Code hook).

These functions take their inputs directly (tool_input dicts, a cwd string) — no module globals
to override — so the tests are pure and hermetic. _resolve_bus walks the real filesystem from the
given cwd, so we build fixture hub/project/worktree dirs under tmp_path.
"""

from __future__ import annotations

import ast

from conftest import REPO, load


def _mod():
    return load("trace_hook")


# ── _idea_of ──────────────────────────────────────────────────────────────────

def test_idea_of_ideas_path():
    m = _mod()
    assert m._idea_of({"file_path": "studies/my-slug/proposal.md"}) == "my-slug"


def test_idea_of_papers_path():
    m = _mod()
    # the paper lives at studies/<slug>/paper/ — still attributed to the slug, not "paper"
    assert m._idea_of({"file_path": "studies/cool-paper/paper/main.tex"}) == "cool-paper"


def test_idea_of_project_artifact_attribution():
    m = _mod()
    # a hub session touching a project's runs/ / PLAN.md / EXPERIMENT_LOG.md attributes to it
    assert m._idea_of({"command": "cat foo-proj/runs/r0/metrics.json"}) == "foo-proj"
    assert m._idea_of({"file_path": "bar-proj/PLAN.md"}) == "bar-proj"
    assert m._idea_of({"file_path": "baz-proj/EXPERIMENT_LOG.md"}) == "baz-proj"


def test_idea_of_unrelated_returns_empty():
    m = _mod()
    assert m._idea_of({"file_path": "src/utils.py"}) == ""
    assert m._idea_of({"command": "ls -la"}) == ""
    assert m._idea_of("not-a-dict") == ""


def test_idea_of_handles_windows_separators():
    m = _mod()
    assert m._idea_of({"file_path": r"studies\win-slug\IDEA.md"}) == "win-slug"


# ── _resolve_bus ──────────────────────────────────────────────────────────────

def test_resolve_bus_finds_hub(tmp_path):
    m = _mod()
    hub = tmp_path / "hub"
    (hub / "lab").mkdir(parents=True)
    (hub / "lab" / "REGISTRY.md").write_text("reg", encoding="utf-8")
    sub = hub / "studies" / "x"
    sub.mkdir(parents=True)
    assert m._resolve_bus(str(sub)) == hub / "lab" / ".bus"


def test_resolve_bus_finds_project(tmp_path):
    m = _mod()
    proj = tmp_path / "projects" / "demo"
    proj.mkdir(parents=True)
    (proj / "control.yaml").write_text("eval_frozen: true\n", encoding="utf-8")
    inner = proj / "runs"
    inner.mkdir()
    assert m._resolve_bus(str(inner)) == proj / ".bus"


def test_resolve_bus_worktree_maps_to_base_project(tmp_path):
    m = _mod()
    base = tmp_path / "projects" / "demo"
    base.mkdir(parents=True)
    (base / "control.yaml").write_text("eval_frozen: true\n", encoding="utf-8")
    wt = tmp_path / "projects" / "demo-wt-v1"
    wt.mkdir(parents=True)
    (wt / "control.yaml").write_text("eval_frozen: true\n", encoding="utf-8")
    # a worktree resolves to the BASE project's .bus
    assert m._resolve_bus(str(wt)) == base / ".bus"


# ── _summary / _kind ──────────────────────────────────────────────────────────

def test_summary_for_bash_and_read():
    m = _mod()
    assert m._summary("Bash", {"command": "python run.py"}) == "Bash: python run.py"
    assert m._summary("Read", {"file_path": "/a/b/main.tex"}) == "Read: main.tex"


def test_kind_classifies_tools():
    m = _mod()
    assert m._kind("Task", {}) == "spawn"
    assert m._kind("Edit", {}) == "edit"
    assert m._kind("Read", {}) == "read"
    assert m._kind("Bash", {"command": "python run.py --x"}) == "run"
    assert m._kind("Bash", {"command": "git commit -m x"}) == "git"
    assert m._kind("Bash", {"command": "ls"}) == "bash"
    assert m._kind("Skill", {}) == "skill"


# ── drift guard: the project-template copy must stay in lockstep with the hub ──────
# (Its docstring claims "verbatim copy of the hub's tools/trace_hook.py"; the studies/ refactor
#  once let IDEA_RE drift to the stale (?:ideas|papers)/ form — this test pins them together.)

def _src_after_module_docstring(rel: str) -> str:
    """The file's source below its module docstring. The docstring is the ONLY intended
    difference between the hub copy and the project-template copy, so everything after it must
    be byte-identical — this pins the whole code body (regexes, _kind/_summary, main dispatch),
    not just a few constants."""
    path = REPO.joinpath(*rel.split("/"))
    src = path.read_text(encoding="utf-8")
    doc = ast.parse(src).body[0]
    assert isinstance(doc, ast.Expr) and isinstance(doc.value, ast.Constant), f"{rel}: no module docstring"
    return "\n".join(src.splitlines()[doc.end_lineno:])


def test_template_trace_hook_in_lockstep_with_hub():
    hub = load("trace_hook")
    tpl = load("templates/project/scripts/trace_hook")
    # explicit named canaries (good failure messages for the constants that actually drifted before)
    assert tpl.IDEA_RE.pattern == hub.IDEA_RE.pattern
    assert tpl.PROJ_RE.pattern == hub.PROJ_RE.pattern
    assert tpl.WORKER_RETENTION_S == hub.WORKER_RETENTION_S
    # strong guard: the entire body below the docstring must match, so NO logic can drift undetected
    assert _src_after_module_docstring("templates/project/scripts/trace_hook.py") == \
        _src_after_module_docstring("tools/trace_hook.py")


# ── _prune_workers: SessionStart retention bounds the workers dir ─────────────────

def test_prune_workers_drops_old_keeps_recent(tmp_path):
    import os
    import time
    m = _mod()
    wdir = tmp_path / "workers"
    wdir.mkdir()
    old = wdir / "dead-session.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    fresh = wdir / "live-session.jsonl"
    fresh.write_text("{}\n", encoding="utf-8")
    stale = time.time() - (m.WORKER_RETENTION_S + 3600)
    os.utime(old, (stale, stale))
    m._prune_workers(wdir)
    assert not old.exists()      # untouched past retention -> pruned
    assert fresh.exists()        # recent -> kept


def test_prune_workers_never_raises_on_missing_dir(tmp_path):
    m = _mod()
    m._prune_workers(tmp_path / "does-not-exist")   # fail-safe: no dir, no raise


def test_template_idea_of_resolves_studies_paths():
    # the bug: the template copy returned "" for studies/<slug>/... (stale ideas|papers regex).
    tpl = load("templates/project/scripts/trace_hook")
    assert tpl._idea_of({"file_path": "studies/demo/proposal.md"}) == "demo"
    assert tpl._idea_of({"file_path": "studies/demo/paper/main.tex"}) == "demo"


# ── subagent visibility: birth, in-flight tools, result packets, worktree attribution ──

def _run_hook(tmp_path, payload: dict) -> list[dict]:
    """Run the real hook as Claude Code does (JSON on stdin) against a fake hub; return its log lines."""
    import json
    import subprocess
    import sys
    hubdir = tmp_path / "hub"
    (hubdir / "lab").mkdir(parents=True, exist_ok=True)
    (hubdir / "lab" / "REGISTRY.md").write_text("# r\n", encoding="utf-8")
    payload = {"cwd": str(hubdir), **payload}
    r = subprocess.run([sys.executable, str(REPO / "tools" / "trace_hook.py")], input=json.dumps(payload),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and r.stdout == ""          # never speaks, never blocks
    wdir = hubdir / "lab" / ".bus" / "workers"
    out = []
    for f in sorted(wdir.glob("*.jsonl")) if wdir.exists() else []:
        out += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return out


def test_subagent_start_records_birth_with_parent_session(tmp_path):
    lines = _run_hook(tmp_path, {"hook_event_name": "SubagentStart", "session_id": "PARENT",
                                 "agent_id": "agent-7", "agent_type": "fresh-context-reviewer"})
    assert lines == [{**lines[0], "worker_id": "agent-7", "role": "fresh-context-reviewer",
                      "event": "start", "status": "working", "session_id": "PARENT"}]


def test_pretooluse_any_tool_is_an_in_flight_begin(tmp_path):
    lines = _run_hook(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "S", "agent_id": "a1",
                                 "agent_type": "experiment-runner", "tool_name": "Bash", "tool_use_id": "tu9",
                                 "tool_input": {"command": "uv run scripts/run.py --config configs/exp-004.yaml"}})
    rec = lines[0]
    assert rec["event"] == "begin" and rec["kind"] == "run" and rec["tool_use_id"] == "tu9"
    assert "exp-004.yaml" in rec["summary"]


def test_spawn_and_return_carry_tool_use_id_and_result_packet(tmp_path):
    spawn = _run_hook(tmp_path, {"hook_event_name": "PreToolUse", "session_id": "S", "tool_name": "Agent",
                                 "tool_use_id": "tuA", "tool_input": {"subagent_type": "overseer",
                                                                      "description": "check the claim"}})
    assert spawn[0]["event"] == "spawn" and spawn[0]["spawns"] == "overseer" and spawn[0]["tool_use_id"] == "tuA"
    ret = _run_hook(tmp_path, {"hook_event_name": "PostToolUse", "session_id": "S", "tool_name": "Agent",
                               "tool_use_id": "tuA", "tool_input": {"subagent_type": "overseer"},
                               "tool_response": {"content": [{"type": "text", "text": "SUPPORTED — evidence at runs/x"}]}})
    last = ret[-1]
    assert last["event"] == "return" and last["result"].startswith("SUPPORTED")


def test_subagent_stop_keeps_final_message(tmp_path):
    lines = _run_hook(tmp_path, {"hook_event_name": "SubagentStop", "session_id": "S", "agent_id": "a2",
                                 "agent_type": "experiment-runner", "last_assistant_message": "packet: metric=0.91"})
    assert lines[0]["event"] == "stop" and lines[0]["result"] == "packet: metric=0.91"


def test_worktree_attribution():
    m = _mod()
    assert m._worktree_of({"command": "cd ../newts-lab-projects/demo-wt-exp-004 && uv run x"}, "") == ("demo", "exp-004")
    assert m._worktree_of({}, r"C:\p\my-proj-wt-v2\sub") == ("my-proj", "v2")
    assert m._worktree_of({"command": "ls"}, "/hub") == ("", "")
    assert m.MAX_SUMMARY == 400


def test_hub_and_template_settings_register_subagent_hooks():
    import json
    for rel in (".claude/settings.json", "templates/project/.claude/settings.json"):
        hooks = json.loads((REPO / rel).read_text(encoding="utf-8"))["hooks"]
        assert "SubagentStart" in hooks and "SubagentStop" in hooks, rel
        assert hooks["PreToolUse"][0]["matcher"] == "*", rel   # every tool: in-flight 'begin' lines
