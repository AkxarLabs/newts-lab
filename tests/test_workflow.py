"""The research workflow (workflow/stages.yaml + tools/workflow.py): one definition that the guard, the
executor and the dashboard read, and the PI's per-stage instructions layered onto each procedure."""

from __future__ import annotations

import re
import shutil

import pytest

from conftest import REPO, load

OLD_LIFECYCLE = ["seed", "triaged", "lit-review", "scoping", "proposal", "active",
                 "analysis", "writing", "internal-review", "final"]
OLD_BACK = {("analysis", "active"), ("writing", "active"), ("internal-review", "active"),
            ("writing", "analysis"), ("internal-review", "writing"), ("analysis", "writing")}


@pytest.fixture
def wf():
    return load("workflow")


@pytest.fixture
def lab(tmp_path, wf):
    """A throwaway hub: this repo's manifest and skills, two of them with a small default method."""
    root = tmp_path / "hub"
    (root / "workflow").mkdir(parents=True)
    shutil.copy(REPO / "workflow" / "stages.yaml", root / "workflow" / "stages.yaml")
    shutil.copytree(REPO / ".claude" / "skills", root / ".claude" / "skills")   # a lab ships its skills
    for proc in ("experiment", "propose"):
        (root / ".claude" / "skills" / proc / "METHOD.md").write_text(f"Default method for {proc}.\n", encoding="utf-8")
    (root / "studies" / "alpha").mkdir(parents=True)
    (root / "studies" / "alpha" / "IDEA.md").write_text("---\nstate: active\n---\n# Alpha\n", encoding="utf-8")
    (root / "lab").mkdir()
    return root


# ── the definition ───────────────────────────────────────────────────────────────────────────────
def test_the_manifest_is_consistent(wf):
    assert wf.check() == [] or all("METHOD.md" in p or "brief" in p for p in wf.check()), wf.check()


def test_lifecycle_and_transitions_are_unchanged(wf):
    assert wf.lifecycle() == OLD_LIFECYCLE
    assert wf.back_edges() == OLD_BACK
    assert set(wf.side_states()) == {"parked", "killed"}
    assert wf.terminal_states() == {"final", "parked", "killed"}
    guard = load("guard")
    for a in OLD_LIFECYCLE + ["parked", "killed"]:
        for b in OLD_LIFECYCLE + ["parked", "killed"]:
            legacy = b in ("parked", "killed") or a == b or (
                a in OLD_LIFECYCLE and b in OLD_LIFECYCLE
                and (OLD_LIFECYCLE.index(b) == OLD_LIFECYCLE.index(a) + 1 or (a, b) in OLD_BACK))
            assert guard.legal_transition(a, b) == legacy, (a, b)


def test_the_launch_allowlist_comes_from_the_manifest_and_never_holds_finalize(wf):
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    import executor
    reg = wf.launch_registry()
    assert executor.SKILL_REGISTRY == reg
    assert "finalize" not in reg and "finalize" in executor.NEVER
    for name, cfg in reg.items():
        assert cfg["level"] in ("hub", "project") and cfg["mode"] in ("headless", "interactive"), name


def test_a_manifest_that_makes_finalize_launchable_is_rejected(lab, wf):
    p = lab / ".claude" / "skills" / "finalize" / "SKILL.md"     # the skill defines itself
    txt = p.read_text(encoding="utf-8")
    assert "  launchable: false\n" in txt
    p.write_text(txt.replace("  launchable: false\n", "  launchable: true\n", 1), encoding="utf-8")
    assert any("finalize must never be launchable" in x for x in wf.check(lab))
    assert "finalize" not in wf.launch_registry(lab)


def test_a_new_skill_folder_is_a_procedure_with_no_other_edit(lab, wf):
    """Adding a procedure is adding a skill folder: no manifest entry, no code."""
    d = lab / ".claude" / "skills" / "survey"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: survey\ndescription: Survey the field: a quick look. Argument; a topic.\n---\n\n"
                                "# Survey\n", encoding="utf-8")
    assert "survey" in wf.launch_registry(lab)                 # a plain skill is a launchable utility
    p = wf.procedure("survey", lab)
    assert p["kind"] == "utility" and p["mode"] == "headless" and p["does"].startswith("Survey the field")
    (d / "SKILL.md").write_text("---\nname: survey\ndescription: Survey.\nnewts:\n  kind: stage\n  level: hub\n"
                                "  mode: interactive\n  args: slug\n  title: Survey the field\n---\n# Survey\n", encoding="utf-8")
    p = wf.procedure("survey", lab)                           # its newts: block defines it
    assert p["title"] == "Survey the field" and p["mode"] == "interactive" and p["args"] == "slug"
    assert not [x for x in wf.check(lab) if "survey" in x]


def test_a_skills_frontmatter_need_not_be_strict_yaml(wf):
    meta = wf.skill_meta("---\nname: x\ndescription: With `--flag <v>`: does y: z.\nnewts:\n  kind: entry\n---\nbody")
    assert meta["description"].startswith("With `--flag") and meta["newts"] == {"kind": "entry"}


def test_a_rule_and_its_check_need_no_code(lab, wf, monkeypatch):
    """A new rule is an entry in workflow/rules.yaml (rendered into the manuals); a check is one file in
    checks/ that the guard finds by itself."""
    shutil.copy(REPO / "workflow" / "rules.yaml", lab / "workflow" / "rules.yaml")
    with (lab / "workflow" / "rules.yaml").open("a", encoding="utf-8") as f:
        f.write("")
    rules = (lab / "workflow" / "rules.yaml").read_text(encoding="utf-8")
    rules = rules.replace("\nsubagent_rules:", "  - id: no-tabs\n    checks: [no-tabs]\n    text: \"**No tabs.** Indent with spaces.\"\n\nsubagent_rules:", 1)
    (lab / "workflow" / "rules.yaml").write_text(rules, encoding="utf-8")
    begin, end = wf._span("hard-rules")
    (lab / "AGENTS.md").write_text(f"## Hard rules\n\n{begin}\n{end}\n", encoding="utf-8")
    assert any("unknown check 'no-tabs'" in x for x in wf.check_rules(lab))
    (lab / "checks").mkdir()
    (lab / "checks" / "no_tabs.py").write_text(
        'NAME = "no-tabs"\n\n\ndef add_args(p):\n    p.add_argument("slug")\n\n\n'
        'def run(a, g):\n    return g._verdict(0, f"no tabs in {a.slug}")\n', encoding="utf-8")
    assert not [x for x in wf.check_rules(lab) if "no-tabs" in x]
    wf.render_docs(lab)
    manual = (lab / "AGENTS.md").read_text(encoding="utf-8")
    assert "14. **No tabs.** Indent with spaces." in manual and "1. **Traceability.**" in manual
    guard = load("guard")
    monkeypatch.setattr(guard, "HUB", lab)
    checks = guard._load_checks()
    assert {"no-tabs", "evolve", "append-only"} <= set(checks)
    import types
    assert checks["no-tabs"].run(types.SimpleNamespace(slug="x"), guard) == 0


def test_a_lab_from_before_skills_defined_themselves_still_works(lab, wf):
    """An older lab: its stages.yaml still lists the procedures, its skills have no `newts:` block."""
    import yaml
    old = yaml.safe_load((lab / "workflow" / "stages.yaml").read_text(encoding="utf-8"))
    old["procedures"] = {"experiment": {"kind": "stage", "level": "project", "mode": "headless", "args": "slug text?",
                                        "launchable": True, "replaceable": True, "title": "Run experiments"}}
    (lab / "workflow" / "stages.yaml").write_text(yaml.safe_dump(old, sort_keys=False), encoding="utf-8")
    sk = lab / ".claude" / "skills" / "experiment" / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    head, body = text.split("\n---\n", 1)
    sk.write_text(head.split("\nnewts:", 1)[0] + "\n---\n" + body, encoding="utf-8")
    p = wf.procedure("experiment", lab)
    assert p["level"] == "project" and p["replaceable"] and p["title"] == "Run experiments"
    assert p.get("outputs") and p.get("anchors")            # the rest of its definition: this code's skill


def test_gates_are_fixed(lab, wf):
    p = lab / "workflow" / "stages.yaml"
    txt = p.read_text(encoding="utf-8")
    p.write_text(txt.replace("  - {n: 2, at: active,", "  - {n: 4, at: active,"), encoding="utf-8")
    assert any("gates must be exactly" in x for x in wf.check(lab))


def test_ui_view_and_generated_default_are_current(wf):
    view = wf.ui_view()
    assert [s["id"] for s in view["states"]] == OLD_LIFECYCLE
    assert {r["id"] for r in view["rooms"]} == {"incubator", "study", "lab", "writing", "archive", "margins"}
    assert wf.render_docs(check_only=True) == [], "run `tools/workflow.py render-docs`"


def test_no_stage_vocabulary_is_hard_coded_in_the_ui():
    core = (REPO / "dashboard" / "static" / "ui" / "core.js").read_text(encoding="utf-8")
    studies = (REPO / "dashboard" / "static" / "ui" / "studies.js").read_text(encoding="utf-8")
    assert "'internal-review': 'Internal review'" not in core and "lit-review': 'scope'" not in studies
    assert "applyWorkflow" in core


# ── the PI's instructions ────────────────────────────────────────────────────────────────────────
def test_brief_layers_method_lab_and_study_instructions(lab, wf):
    text, h = wf.brief("experiment", lab)
    assert "Default method for experiment." in text and "NEWTS STAGE BRIEF /experiment" in text and h
    wf.write_custom("add", "experiment", "Always log GPU hours.", lab)
    wf.write_custom("stage", "experiments", "Prefer small models first.", lab)
    wf.write_custom("add", "experiment", "Use dataset Y for this study.", lab, study="alpha")
    text2, h2 = wf.brief("experiment", lab, study="alpha")
    assert h2 != h
    i_meth, i_lab, i_study = (text2.index("Default method"), text2.index("Always log GPU hours"),
                              text2.index("Use dataset Y"))
    assert i_meth < i_lab < i_study          # reading order: method, then lab, then study
    assert "Prefer small models first." in text2
    assert "Use dataset Y" not in wf.brief("experiment", lab)[0]   # study instructions stay with the study


def test_a_replacement_method_wins_and_flags_a_changed_default(lab, wf):
    wf.write_custom("method", "experiment", "My own method.", lab)
    text, _ = wf.brief("experiment", lab)
    assert "My own method." in text and "Default method" not in text and "replaced by the PI for the lab" in text
    wf.write_custom("method", "experiment", "This study's method.", lab, study="alpha")
    assert "This study's method." in wf.brief("experiment", lab, study="alpha")[0]
    (lab / ".claude" / "skills" / "experiment" / "METHOD.md").write_text("A new default.\n", encoding="utf-8")
    assert wf.status(lab)["procedures"]["experiment"]["stale"] is True
    assert "default method has changed" in wf.brief("experiment", lab)[0]
    wf.write_custom("method", "experiment", "", lab)                  # empty = reset to the default
    assert "A new default." in wf.brief("experiment", lab)[0]


def test_only_replaceable_procedures_take_a_method_and_sizes_are_capped(lab, wf):
    with pytest.raises(ValueError):
        wf.propose("advance", "replace", "x", lab)
    with pytest.raises(ValueError):
        wf.write_custom("add", "experiment", "x" * (wf.MAX_CUSTOM + 1), lab)
    with pytest.raises(ValueError):
        wf.custom_file("add", "../etc", lab)
    with pytest.raises(ValueError):
        wf.custom_dir(lab, study="../x")


def test_agent_proposals_need_the_pi(lab, wf):
    rec = wf.propose("experiment", "add", "Also report wall-clock.", lab, study="alpha", why="it was missing")
    assert [p["id"] for p in wf.proposals(lab)] == [rec["id"]]
    assert "wall-clock" not in wf.brief("experiment", lab, study="alpha")[0]      # nothing changes until accepted
    wf.resolve_proposal(rec["id"], True, lab)
    assert "Also report wall-clock." in wf.brief("experiment", lab, study="alpha")[0]
    assert wf.proposals(lab) == []
    rec2 = wf.propose("experiment", "add", "Declined idea.", lab)
    wf.resolve_proposal(rec2["id"], False, lab)
    assert "Declined idea." not in wf.brief("experiment", lab)[0]
    with pytest.raises(ValueError):
        wf.resolve_proposal(rec2["id"], True, lab)


# ── the split: SKILL.md = contract, METHOD.md = method ───────────────────────────────────────────
def test_every_procedure_opens_with_its_generated_contract_and_no_method_carries_a_rule(wf):
    """Each SKILL.md starts from the contract head render-docs writes from its frontmatter (load the brief,
    what it must produce); a replaceable procedure's default METHOD.md carries no system rule, so replacing a
    method can never remove one."""
    for name, p in wf.load()["procedures"].items():
        skill = (REPO / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        if p.get("engineering"):
            continue
        assert "<!-- newts:contract" in skill and f"workflow.py brief {name}" in skill, name
        if p.get("replaceable"):
            method = (REPO / ".claude" / "skills" / name / "METHOD.md").read_text(encoding="utf-8")
            assert wf.system_tokens(method) == set(), (name, wf.system_tokens(method))
            assert wf.system_tokens(skill), f"{name}: a contract with no guard call, gate or footer?"
    assert wf.render_docs(check_only=True) == [], "run `tools/workflow.py render-docs`"


def test_headless_runs_carry_the_brief_and_record_its_sha(tmp_path, wf):
    import sys
    sys.path.insert(0, str(REPO / "tools"))
    from executor import spec
    from executor.lab import Lab
    lab = Lab(REPO)
    v = {"skill": "propose", "subject": None, "target": "hub", "workdir": REPO, "level": "hub",
         "cfg": {"mode": "headless", "args": "slug"}, "args": ""}
    pre = spec.preamble(lab, "r1", v, "claude")
    assert "NEWTS STAGE BRIEF /propose" in pre and "Proposal: the method" in pre
    text, h = spec.stage_brief(lab, v)
    assert h and h in text
    ask = {**v, "skill": "ask", "cfg": {"mode": "headless", "kind": "ask"}}
    assert spec.stage_brief(lab, ask) == (None, None)
