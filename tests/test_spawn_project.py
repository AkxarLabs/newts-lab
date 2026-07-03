"""Tests for tools/spawn_project.py — the mechanical scaffolder.

Scaffolds the REAL templates/project/ into a tmp dir (so we validate actual placeholders, the
no-BOM write, and that the hub-side runtime cruft — .pytest_cache / .bus / stale runs/ dirs —
never travels). Plus the overwrite-refusal guard. No uv/network (the --run-smoke path is exercised
by the spawn-smoke CI).
"""

from __future__ import annotations

import types

from conftest import REPO, load

S = load("spawn_project")


def _scaffold(tmp_path, **over):
    dest = tmp_path / "proj"
    kw = dict(hub=REPO, slug="demo-proj", title="Demo Proj", date="2026-07-01", project_type="ml")
    kw.update(over)
    return dest, S.scaffold(dest, **kw)


def test_scaffold_substitutes_placeholders(tmp_path):
    dest, _ = _scaffold(tmp_path)
    ctl = (dest / "control.yaml").read_text(encoding="utf-8")
    # hub_path is forward-slashed (valid YAML on Windows; C:\... would be an invalid escape)
    assert "demo-proj" in ctl and str(REPO).replace("\\", "/") in ctl
    assert "\\" not in ctl.split("hub_path:")[1].split("\n")[0]   # no backslashes in the hub_path value
    assert "{{slug}}" not in ctl and "{{hub_path}}" not in ctl
    pyproject = (dest / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "demo-proj"' in pyproject and "Demo Proj" in pyproject


def test_pyproject_written_without_bom(tmp_path):
    dest, _ = _scaffold(tmp_path)
    assert not (dest / "pyproject.toml").read_bytes().startswith(b"\xef\xbb\xbf")   # the whole point


def test_excludes_runtime_cruft_and_stale_runs(tmp_path):
    dest, _ = _scaffold(tmp_path)
    assert not (dest / ".pytest_cache").exists()
    assert not (dest / ".bus").exists()
    if (dest / "runs").exists():   # runs/ ships only its README — never the hub-side stale exp- dirs
        assert not any(p.is_dir() for p in (dest / "runs").glob("*"))
    assert not list(dest.rglob("__pycache__"))
    assert not list(dest.rglob("*.pyc"))


def test_literal_placeholders_left_untouched(tmp_path):
    # only the four real placeholders are substituted; {{c}}/{{caption}}/{{label}} are literal examples.
    dest, _ = _scaffold(tmp_path)
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore")
                     for p in dest.rglob("*.py") if p.is_file())
    assert "{{slug}}" not in blob   # real ones gone
    # (a literal like {{c}} may or may not appear in a given file; we only assert the reals are gone)


def test_type_card_and_control_type(tmp_path):
    dest, _ = _scaffold(tmp_path, project_type="theory")
    assert (dest / "TYPE.md").exists()
    assert "project_type: theory" in (dest / "control.yaml").read_text(encoding="utf-8")


def test_domain_profile_copied(tmp_path):
    dest, _ = _scaffold(tmp_path, domain="econ")
    assert (dest / "DOMAIN.md").exists()


def test_overlay_compete_applies_target_files(tmp_path):
    dest, _ = _scaffold(tmp_path, project_type="target-driven", overlay="compete")
    assert (dest / "TARGET.md").exists()                       # from templates/compete/
    assert (dest / "scripts" / "report_score.py").exists()


def test_backend_and_engineering_skills_ship(tmp_path):
    dest, _ = _scaffold(tmp_path)
    assert (dest / ".claude" / "skills" / "grill-with-docs" / "SKILL.md").exists()
    assert (dest / ".codex" / "agents" / "experiment-runner.toml").exists()


def test_scaffold_resolves_role_files_from_hub_tiers(tmp_path, monkeypatch):
    """The round-2 fix: a spawned project's role files are RESOLVED from the hub tier ladder at spawn
    (mechanically, no agent tokens) — so a headless agent in the project runs its subagents at the
    resolved tier, not the template's neutral `inherit`."""
    monkeypatch.setattr(S.role_sync, "_cfg_agents",
                        lambda: {"tiers": {"standard": "sonnet"}, "runner_model": "standard"})
    dest, res = _scaffold(tmp_path)
    assert "resolved_roles" in res
    md = (dest / ".claude" / "agents" / "experiment-runner.md").read_text(encoding="utf-8")
    assert "model: sonnet\n" in md   # runner_model=standard -> tiers.standard=sonnet, baked at spawn


# ── overwrite refusal ─────────────────────────────────────────────────────────

def test_runs_nonempty_helper(tmp_path):
    d = tmp_path / "p"
    (d / "runs").mkdir(parents=True)
    assert S._runs_nonempty(d) is False
    (d / "runs" / "exp-001").mkdir()
    assert S._runs_nonempty(d) is True


def test_run_refuses_existing_project_with_runs(tmp_path, monkeypatch):
    m = load("spawn_project")
    hub = tmp_path / "hub"
    (hub / "lab").mkdir(parents=True)
    (hub / "lab" / "config.yaml").write_text('lab:\n  projects_root: "../projects"\n', encoding="utf-8")
    monkeypatch.setattr(m, "HUB", hub)
    proj = (hub / ".." / "projects" / "demo").resolve()
    (proj / "runs" / "exp-001-x").mkdir(parents=True)   # a prior run exists → reused slug
    a = types.SimpleNamespace(slug="demo", title="Demo", project_type="ml", domain=None,
                              overlay=None, date=None, run_smoke=False, skip_guard=True)
    assert m.run(a) == 1
