"""Tests for tools/trace_hook.py — the fail-safe activity tracer (a Claude Code hook).

These functions take their inputs directly (tool_input dicts, a cwd string) — no module globals
to override — so the tests are pure and hermetic. _resolve_bus walks the real filesystem from the
given cwd, so we build fixture hub/project/worktree dirs under tmp_path.
"""

from __future__ import annotations

from conftest import load


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

def test_template_trace_hook_in_lockstep_with_hub():
    hub = load("trace_hook")
    tpl = load("templates/project/scripts/trace_hook")
    assert tpl.IDEA_RE.pattern == hub.IDEA_RE.pattern
    assert tpl.PROJ_RE.pattern == hub.PROJ_RE.pattern


def test_template_idea_of_resolves_studies_paths():
    # the bug: the template copy returned "" for studies/<slug>/... (stale ideas|papers regex).
    tpl = load("templates/project/scripts/trace_hook")
    assert tpl._idea_of({"file_path": "studies/demo/proposal.md"}) == "demo"
    assert tpl._idea_of({"file_path": "studies/demo/paper/main.tex"}) == "demo"
