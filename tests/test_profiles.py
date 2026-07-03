"""Tests for tools/profiles.py — config profiles (budget tiers + engine presets).

Pure tests for the comment-preserving stamp + rigor-floor validator, then integration tests for
apply/save against a hand-built fake hub (config text with the budget namespaces, lab/profiles/,
and .claude/agents/*.md). Hermetic — no network, no real lab.
"""

from __future__ import annotations

import textwrap

import yaml

from conftest import REPO, load

_CFG = textwrap.dedent(
    """\
    ideation:
      candidates: 8                 # initial candidates
      enable_combination: true      # crossovers
    experiment:
      num_drafts: 3
      max_parallel_subagents: 3
      multi_seed_n: 3
    oversight:
      level: standard
    agents:
      tiers:
        strong: inherit
        standard: inherit
        fast: inherit
      reviewer_model: strong
      runner_model: standard
      overseer_model: standard
      reviewer_effort: ""
      runner_effort: ""
      overseer_effort: ""
      programmatic:
        backend: claude
        max_concurrent: 3
        backends:
          claude:
            model: claude-opus-4-8
            effort: high
    """
)


def _m():
    return load("profiles")


# ── pure: stamp preserves comments + handles nesting ───────────────────────────

def test_stamp_replaces_value_and_keeps_comment():
    m = _m()
    out, ok = m.stamp(_CFG, ["ideation", "candidates"], 4)
    assert ok
    line = next(ln for ln in out.splitlines() if ln.strip().startswith("candidates:"))
    assert line.strip().startswith("candidates: 4")
    assert "# initial candidates" in line                       # inline comment survives
    # every other line is byte-identical
    a, b = _CFG.splitlines(), out.splitlines()
    assert [i for i in range(len(a)) if a[i] != b[i]] == [a.index("  candidates: 8                 # initial candidates")]


def test_stamp_bool_and_deep_nesting():
    m = _m()
    out, ok = m.stamp(_CFG, ["ideation", "enable_combination"], False)
    assert ok and "enable_combination: false" in out
    out, ok = m.stamp(out, ["agents", "programmatic", "backends", "claude", "model"], "claude-haiku-4-5-20251001")
    assert ok and "model: claude-haiku-4-5-20251001" in out
    out, ok = m.stamp(out, ["agents", "programmatic", "max_concurrent"], 1)
    assert ok
    assert yaml.safe_load(out)["agents"]["programmatic"]["max_concurrent"] == 1


def test_stamp_missing_key_is_noop():
    m = _m()
    out, ok = m.stamp(_CFG, ["ideation", "does_not_exist"], 5)
    assert not ok and out == _CFG


def test_flatten():
    m = _m()
    flat = m._flatten({"a": {"b": 1, "c": {"d": 2}}, "e": 3})
    assert flat == {("a", "b"): 1, ("a", "c", "d"): 2, ("e",): 3}


# ── pure: rigor floors ─────────────────────────────────────────────────────────

def test_rigor_violations_catches_floor_breaks():
    m = _m()
    assert m.rigor_violations({("experiment", "multi_seed_n"): 2})
    assert m.rigor_violations({("oversight", "level"): "off"})
    assert m.rigor_violations({("eval_frozen",): False})
    assert m.rigor_violations({("gate2_envelope", "pi_signed"): True})
    # a clean budget profile passes
    assert m.rigor_violations({("experiment", "multi_seed_n"): 5,
                               ("oversight", "level"): "strict",
                               ("ideation", "candidates"): 4}) == []


def test_every_builtin_profile_passes_validate():
    m = _m()
    for f in sorted((REPO / "lab" / "profiles").glob("*.yaml")):
        flat = m._flatten(yaml.safe_load(f.read_text(encoding="utf-8")))
        assert m.rigor_violations(flat) == [], f"{f.name} breaks an integrity floor"


# ── integration: apply / save against a fake hub ───────────────────────────────

def _seed_agent_roles(hub):
    """Minimal agent-roles/ so role_sync.render() (invoked by apply after an agents.* change) has
    real specs to render — the canonical sync path P1.3 makes apply use."""
    roles = hub / "agent-roles"
    roles.mkdir(parents=True, exist_ok=True)
    for name, key in (("fresh-context-reviewer", "reviewer_model"),
                      ("experiment-runner", "runner_model"),
                      ("overseer", "overseer_model")):
        (roles / f"{name}.yaml").write_text(
            f'name: {name}\n'
            f'description: "role {name}"\n'
            f'model_key: {key}\n'
            'tools_claude: "Read, Grep"\n'
            'codex:\n'
            '  sandbox_mode: read-only\n'
            '  model_reasoning_effort: high\n', encoding="utf-8")
        (roles / f"{name}.md").write_text(f"Body of {name}.\n", encoding="utf-8")


def _setup(tmp_path, monkeypatch, profiles: dict):
    m = _m()
    hub = tmp_path / "hub"
    (hub / "lab" / "profiles").mkdir(parents=True)
    (hub / "lab" / "config.yaml").write_text(_CFG, encoding="utf-8")
    _seed_agent_roles(hub)
    for name, body in profiles.items():
        (hub / "lab" / "profiles" / f"{name}.yaml").write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setattr(m, "HUB", hub)
    monkeypatch.setattr(m, "LAB", hub / "lab")
    monkeypatch.setattr(m.role_sync, "HUB", hub)   # the renderer cmd_apply now invokes for agents.* changes
    return m, hub


def test_apply_stamps_config_and_rerenders_role_files(tmp_path, monkeypatch):
    import types
    m, hub = _setup(tmp_path, monkeypatch, {"thrift": """\
        ideation:
          candidates: 4
        experiment:
          max_parallel_subagents: 1
        agents:
          reviewer_model: sonnet
          programmatic:
            backend: codex
            max_concurrent: 1
        """})
    assert m.cmd_apply(types.SimpleNamespace(name="thrift")) == 0
    cfg = yaml.safe_load((hub / "lab" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["ideation"]["candidates"] == 4
    assert cfg["experiment"]["max_parallel_subagents"] == 1
    assert cfg["agents"]["reviewer_model"] == "sonnet"
    assert cfg["agents"]["programmatic"]["backend"] == "codex"
    assert cfg["agents"]["programmatic"]["max_concurrent"] == 1
    # the comment on an untouched-value line is preserved
    assert "# initial candidates" in (hub / "lab" / "config.yaml").read_text(encoding="utf-8")
    # BOTH backends' role files were (re-)rendered by role_sync — the convergence P1.3 buys
    assert "model: sonnet" in (hub / ".claude" / "agents" / "fresh-context-reviewer.md").read_text(encoding="utf-8")
    assert (hub / ".codex" / "agents" / "fresh-context-reviewer.toml").exists()
    # the unchanged roles resolve to inherit (overseer_model=standard -> tiers.standard=inherit)
    assert "model: inherit" in (hub / ".claude" / "agents" / "overseer.md").read_text(encoding="utf-8")
    # the spawned-project Claude copies ride along too (P1.5)
    assert (hub / "templates" / "project" / ".claude" / "agents" / "overseer.md").exists()


def test_apply_tier_preset_resolves_models(tmp_path, monkeypatch):
    import types
    m, hub = _setup(tmp_path, monkeypatch, {"ladder": """\
        agents:
          tiers:
            strong: opus
            standard: sonnet
            fast: haiku
          reviewer_model: strong
          runner_model: standard
        """})
    assert m.cmd_apply(types.SimpleNamespace(name="ladder")) == 0
    cfg = yaml.safe_load((hub / "lab" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["agents"]["tiers"]["strong"] == "opus"        # tier-form preset stamped cleanly
    assert cfg["agents"]["reviewer_model"] == "strong"
    # role files render the RESOLVED model: reviewer=strong->opus, runner=standard->sonnet
    assert "model: opus" in (hub / ".claude" / "agents" / "fresh-context-reviewer.md").read_text(encoding="utf-8")
    assert "model: sonnet" in (hub / ".claude" / "agents" / "experiment-runner.md").read_text(encoding="utf-8")


def test_apply_refuses_a_floor_lowering_profile(tmp_path, monkeypatch):
    import types
    m, hub = _setup(tmp_path, monkeypatch, {"reckless": """\
        experiment:
          multi_seed_n: 1
        oversight:
          level: off
        """})
    assert m.cmd_apply(types.SimpleNamespace(name="reckless")) == 1
    cfg = yaml.safe_load((hub / "lab" / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["experiment"]["multi_seed_n"] == 3            # config UNCHANGED — nothing stamped
    assert cfg["oversight"]["level"] == "standard"


def test_save_snapshots_current_budget_keys(tmp_path, monkeypatch):
    import types
    m, hub = _setup(tmp_path, monkeypatch, {})
    assert m.cmd_save(types.SimpleNamespace(name="mine")) == 0
    saved = yaml.safe_load((hub / "lab" / "profiles" / "mine.yaml").read_text(encoding="utf-8"))
    assert saved["ideation"]["candidates"] == 8             # snapshotted from current config
    assert saved["experiment"]["multi_seed_n"] == 3
    assert saved["agents"]["programmatic"]["backend"] == "claude"
    # round-trips: the saved profile validates and re-applies cleanly
    assert m.rigor_violations(m._flatten(saved)) == []


def test_save_round_trips_tiers(tmp_path, monkeypatch):
    import types
    m, hub = _setup(tmp_path, monkeypatch, {})
    assert m.cmd_save(types.SimpleNamespace(name="mine")) == 0
    saved = yaml.safe_load((hub / "lab" / "profiles" / "mine.yaml").read_text(encoding="utf-8"))
    # the model ladder + tier-named role keys are snapshotted (PROFILE_KEYS additions)
    assert saved["agents"]["tiers"] == {"strong": "inherit", "standard": "inherit", "fast": "inherit"}
    assert saved["agents"]["reviewer_model"] == "strong"
    assert saved["agents"]["runner_model"] == "standard"
    assert m.rigor_violations(m._flatten(saved)) == []      # snapshot re-applies cleanly
