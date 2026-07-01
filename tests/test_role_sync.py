"""Tests for tools/role_sync.py — rendering backend-native subagent role files from agent-roles/.

Hermetic machinery tests use a tmp HUB with a fake role; two real-repo guards assert the committed
generated files are in sync and that the role constraints survived the round-trip (the fresh-context
invariant, parent-only ledgers, verify-only overseer).
"""

from __future__ import annotations

import tomllib

from conftest import load


def _fresh(monkeypatch, root):
    m = load("role_sync")
    monkeypatch.setattr(m, "HUB", root)
    return m


def _seed_role(root, *, model="inherit"):
    roles = root / "agent-roles"
    roles.mkdir(parents=True, exist_ok=True)
    (roles / "demo-role.yaml").write_text(
        'name: demo-role\n'
        'description: "A demo role — one lens."\n'
        'model_key: reviewer_model\n'
        'tools_claude: "Read, Grep"\n'
        'codex:\n'
        '  sandbox_mode: read-only\n'
        '  model_reasoning_effort: high\n', encoding="utf-8")
    (roles / "demo-role.md").write_text("Do the thing.\nCarefully.\n", encoding="utf-8")
    (root / "lab").mkdir(exist_ok=True)
    (root / "lab" / "config.yaml").write_text(f"agents:\n  reviewer_model: {model}\n", encoding="utf-8")


def test_render_then_check_roundtrips(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path)
    assert m.render() == 0
    assert (tmp_path / ".claude" / "agents" / "demo-role.md").exists()
    assert (tmp_path / ".codex" / "agents" / "demo-role.toml").exists()
    assert (tmp_path / "templates" / "project" / ".codex" / "agents" / "demo-role.toml").exists()
    assert m.check() == 0


def test_check_detects_stale(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path)
    m.render()
    (tmp_path / ".claude" / "agents" / "demo-role.md").write_text("edited\n", encoding="utf-8")
    assert m.check() == 1


def test_check_detects_missing(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path)
    m.render()
    (tmp_path / ".codex" / "agents" / "demo-role.toml").unlink()
    assert m.check() == 1


def test_claude_frontmatter_and_model_from_config(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path, model="opus")
    m.render()
    md = (tmp_path / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert md.startswith("---\nname: demo-role\n")
    assert "tools: Read, Grep\n" in md
    assert "model: opus\n" in md            # resolved from lab/config.yaml agents.reviewer_model
    assert md.rstrip().endswith("Carefully.")


def test_codex_toml_parses_and_has_fields(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path)
    m.render()
    data = tomllib.loads((tmp_path / ".codex" / "agents" / "demo-role.toml").read_text(encoding="utf-8"))
    assert data["name"] == "demo-role"
    assert data["sandbox_mode"] == "read-only"
    assert data["model_reasoning_effort"] == "high"
    assert "Do the thing." in data["developer_instructions"]


# ── real-repo guards ──────────────────────────────────────────────────────────

def test_real_repo_roles_in_sync():
    m = load("role_sync")  # HUB = the real repo
    assert m.check() == 0  # committed .claude/agents + .codex/agents match agent-roles/


def test_real_repo_preserves_role_constraints():
    m = load("role_sync")
    rv = (m.HUB / ".claude" / "agents" / "fresh-context-reviewer.md").read_text(encoding="utf-8")
    er = (m.HUB / ".claude" / "agents" / "experiment-runner.md").read_text(encoding="utf-8")
    ov = (m.HUB / ".claude" / "agents" / "overseer.md").read_text(encoding="utf-8")
    assert "independence" in rv                                   # fresh-context invariant
    assert "parent session owns those" in er and "worktree" in er  # parent-only ledgers + confinement
    assert "you never fix" in ov                                  # verify-only
    for name in ("fresh-context-reviewer", "experiment-runner", "overseer"):
        assert tomllib.loads((m.HUB / ".codex" / "agents" / f"{name}.toml")
                             .read_text(encoding="utf-8"))["name"] == name
