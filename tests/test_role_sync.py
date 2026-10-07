"""Tests for tools/role_sync.py — rendering backend-native subagent role files from agent-roles/.

Hermetic machinery tests use a tmp HUB with a fake role; two real-repo guards assert the committed
generated files are in sync and that the role constraints survived the round-trip (the fresh-context
invariant, parent-only ledgers, verify-only overseer).
"""

from __future__ import annotations

import tomllib

import pytest

from conftest import load


def _fresh(monkeypatch, root):
    m = load("role_sync")
    monkeypatch.setattr(m, "HUB", root)
    return m


def _seed_role(root, *, model="inherit"):
    _seed_role_cfg(root, f"agents:\n  reviewer_model: {model}\n")


def _seed_role_cfg(root, config_text, *, codex_model=None):
    """Seed a demo role (model_key -> reviewer_model) + a lab/config.yaml body verbatim.
    codex_model, when set, adds an optional per-role `codex.model` to the role yaml (P1.8)."""
    roles = root / "agent-roles"
    roles.mkdir(parents=True, exist_ok=True)
    yaml_body = (
        'name: demo-role\n'
        'description: "A demo role — one lens."\n'
        'model_key: reviewer_model\n'
        'tools_claude: "Read, Grep"\n'
        'codex:\n'
        '  sandbox_mode: read-only\n'
        '  model_reasoning_effort: high\n')
    if codex_model:
        yaml_body += f'  model: "{codex_model}"\n'
    (roles / "demo-role.yaml").write_text(yaml_body, encoding="utf-8")
    (roles / "demo-role.md").write_text("Do the thing.\nCarefully.\n", encoding="utf-8")
    (root / "lab").mkdir(exist_ok=True)
    (root / "lab" / "config.yaml").write_text(config_text, encoding="utf-8")


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


# ── tier resolution (P1.2) ─────────────────────────────────────────────────────

def test_resolve_model_tier_and_passthrough():
    m = load("role_sync")
    agents = {"tiers": {"strong": "opus", "standard": "sonnet", "fast": "haiku"}}
    assert m.resolve_model("strong", agents) == "opus"                 # tier name -> its model
    assert m.resolve_model("sonnet", agents) == "sonnet"              # a direct alias passes through
    assert m.resolve_model("claude-haiku-4-5-20251001", agents) == "claude-haiku-4-5-20251001"  # pinned id
    assert m.resolve_model("totally-unknown", agents) == "totally-unknown"  # unknown string, verbatim
    assert m.resolve_model("", agents) == "inherit"                   # empty -> inherit
    assert m.resolve_model(None, agents) == "inherit"                 # None -> inherit
    assert m.resolve_model("x", {}) == "x"                            # no tiers dict at all


def test_resolve_model_inherit_tier_and_cycle():
    m = load("role_sync")
    assert m.resolve_model("strong", {"tiers": {"strong": "inherit"}}) == "inherit"
    assert m.resolve_model("strong", {"tiers": {"strong": None}}) == "inherit"  # None-valued tier -> inherit
    # a cycle (strong -> standard -> strong) terminates rather than hanging
    cyc = {"tiers": {"strong": "standard", "standard": "strong"}}
    assert m.resolve_model("strong", cyc) == "strong"                 # stops at the first repeat


def test_tier_resolves_in_rendered_model(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path,
                   "agents:\n"
                   "  tiers:\n    strong: opus\n    standard: sonnet\n    fast: haiku\n"
                   "  reviewer_model: strong\n")
    m.render()
    md = (tmp_path / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert "model: opus\n" in md          # reviewer_model=strong -> tiers.strong=opus


# ── per-role effort (P1.4) + optional codex model (P1.8) ────────────────────────

def test_effort_line_claude_only_when_set(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path, "agents:\n  reviewer_model: opus\n")   # no reviewer_effort
    m.render()
    md = (tmp_path / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert "effort:" not in md                                      # '' = model default -> no line
    _seed_role_cfg(tmp_path, "agents:\n  reviewer_model: opus\n  reviewer_effort: xhigh\n")
    m.render()
    md = (tmp_path / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert "model: opus\neffort: xhigh\n" in md                     # effort line, right after model


def test_codex_effort_override_and_no_model_line(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path, "agents:\n  reviewer_model: opus\n  reviewer_effort: low\n")
    m.render()
    data = tomllib.loads((tmp_path / ".codex" / "agents" / "demo-role.toml").read_text(encoding="utf-8"))
    assert data["model_reasoning_effort"] == "low"                  # config override beats role-yaml 'high'
    assert "model" not in data                                      # no codex.model set -> no model line


def test_codex_model_line_only_when_role_sets_it(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path, "agents:\n  reviewer_model: opus\n", codex_model="gpt-5.5-codex")
    m.render()
    data = tomllib.loads((tmp_path / ".codex" / "agents" / "demo-role.toml").read_text(encoding="utf-8"))
    assert data["model"] == "gpt-5.5-codex"                         # emitted from role yaml codex.model
    assert data["model_reasoning_effort"] == "high"                 # falls back to the role-yaml default


# ── spawned-project Claude role files (P1.5) + template neutrality (round-2) ────

def test_project_template_claude_target_present_and_rendered(tmp_path, monkeypatch):
    m = _fresh(monkeypatch, tmp_path)
    _seed_role(tmp_path)
    tmpl = tmp_path / "templates" / "project" / ".claude" / "agents" / "demo-role.md"
    assert tmpl in [p for p, _ in m._plan()]    # the spawned-project Claude target is in the plan
    m.render()
    assert tmpl.exists()


def test_template_stays_neutral_when_tier_set(tmp_path, monkeypatch):
    """Bug-2 guard: setting a hub tier must NOT leak into the shipped project template — the hub file
    resolves to the tier, the template file stays `model: inherit` with no effort line."""
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path, "agents:\n  tiers:\n    strong: opus\n"
                             "  reviewer_model: strong\n  reviewer_effort: high\n")
    m.render()
    hub = (tmp_path / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    tmpl = (tmp_path / "templates" / "project" / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert "model: opus\neffort: high\n" in hub           # hub session honors the ladder
    assert "model: inherit\n" in tmpl and "effort:" not in tmpl   # template neutral — no PI-tier leak


def test_render_project_resolves_tiers_into_instance(tmp_path, monkeypatch):
    """A spawned project instance is resolved from the live hub tiers at spawn (render_project) — the
    fix that makes headless-agent subagents honor the ladder instead of running at `inherit`."""
    m = _fresh(monkeypatch, tmp_path)
    _seed_role_cfg(tmp_path, "agents:\n  tiers:\n    strong: opus\n"
                             "  reviewer_model: strong\n  reviewer_effort: high\n")
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True)   # the copied template ships these dirs
    (proj / ".codex" / "agents").mkdir(parents=True)
    assert m.render_project(proj) >= 1
    md = (proj / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")
    assert "model: opus\neffort: high\n" in md           # instance resolved, unlike the neutral template
    # self-sufficient: even a BARE dir (template dir missing) gets the role files created + resolved,
    # so spawn correctness never silently depends on the committed template being complete
    bare = tmp_path / "bare"
    bare.mkdir()
    assert m.render_project(bare) >= 1
    assert "model: opus\n" in (bare / ".claude" / "agents" / "demo-role.md").read_text(encoding="utf-8")


def test_resolve_role_named_and_inline_critic():
    """The token-free spawn helper: model resolves through the tier ladder, effort is a direct value;
    it works for the named roles AND the inline `critic` (which has no role file)."""
    m = load("role_sync")
    agents = {"tiers": {"strong": "opus", "standard": "sonnet"},
              "reviewer_model": "strong", "reviewer_effort": "high",
              "critic_model": "standard", "critic_effort": "medium"}
    assert m.resolve_role("reviewer", agents) == ("opus", "high")
    assert m.resolve_role("critic", agents) == ("sonnet", "medium")
    assert m.resolve_role("runner", {}) == ("inherit", "")   # unset -> inherit / no effort


# ── real-repo guards ──────────────────────────────────────────────────────────

def test_real_repo_roles_in_sync():
    m = load("role_sync")  # HUB = the real repo
    # Migration window: after a config/_targets change the generated tree is intentionally stale
    # until the integrator runs `role_sync.py render`. The tell-tale is the newly-added project-
    # template Claude target (P1.5) not existing yet — skip until it's rendered (the integrator's
    # explicit `role_sync.py check` step is the strict gate). Once rendered this is strict again.
    if not (m.HUB / "templates" / "project" / ".claude" / "agents" / "overseer.md").exists():
        pytest.skip("project-template Claude role files not yet rendered — run tools/role_sync.py render")
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


def test_a_new_role_is_two_files(monkeypatch, tmp_path):
    """agent-roles/<role>.yaml + .md is the whole definition: it renders for all three CLIs, the workflow
    lists it (Compose, PI add-ons, proposals), and its model key resolves — no code edit."""
    root = tmp_path / "hub"
    roles = root / "agent-roles"
    roles.mkdir(parents=True)
    (roles / "data-wrangler.yaml").write_text(
        'name: data-wrangler\nlabel: Data wrangler\ndescription: "Cleans one dataset."\n'
        'model_key: wrangler_model\ntools_claude: "Read, Edit"\ncodex:\n  sandbox_mode: workspace-write\n', encoding="utf-8")
    (roles / "data-wrangler.md").write_text("You clean exactly one dataset.\n", encoding="utf-8")
    (root / "lab").mkdir()
    (root / "lab" / "config.yaml").write_text("agents:\n  tiers: {standard: sonnet}\n  wrangler_model: standard\n", encoding="utf-8")
    m = _fresh(monkeypatch, root)
    m.render()
    for f in (".claude/agents/data-wrangler.md", ".codex/agents/data-wrangler.toml", ".opencode/agents/data-wrangler.md"):
        assert (root / f).is_file(), f
    assert m.role_keys()["data-wrangler"] == ("wrangler_model", "wrangler_effort")
    assert m.resolve_role("data-wrangler")[0] == "sonnet"
    wf = load("workflow")
    assert wf.roles(root) == ["data-wrangler"] and wf.role_labels(root)["data-wrangler"] == "Data wrangler"
