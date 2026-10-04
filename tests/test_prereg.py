"""The pre-registration audit (checks/audit_prereg.py) and the project check's scientific-contract lint:
the analysis plan is frozen, the test split is read once, claims are labelled, criteria are pre-written."""

from __future__ import annotations

import json
import subprocess
import sys

import yaml as _yaml

from conftest import REPO, load

S = load("spawn_project")
PROPOSAL = (REPO / "templates" / "idea" / "proposal.md").read_text(encoding="utf-8")


def _mod(hub, monkeypatch):
    m = load("audit_prereg")
    monkeypatch.setattr(m, "HUB", hub.root)
    return m


def _fill(text, label, value):
    out = []
    for line in text.splitlines():
        if f"**{label}" in line:
            line = line.split("**", 2)[0] + f"**{label}:** {value}"
        out.append(line)
    return "\n".join(out)


def _study(hub, slug, *, plan_filled=True, claims=None, log_rows=(), plan_log=True):
    sdir = hub.root / "studies" / slug
    (sdir / "paper").mkdir(parents=True, exist_ok=True)
    prop = PROPOSAL
    if plan_filled:
        for lab, val in (("Primary comparison", "ours vs tuned baseline on val_bpb, test split"),
                         ("Uncertainty", "95% CI over 5 seeds"), ("Decision rule", "CI excludes 0 → supports")):
            prop = _fill(prop, lab, val)
    (sdir / "proposal.md").write_text(prop, encoding="utf-8")
    (sdir / "paper" / "claims.yaml").write_text(_yaml.safe_dump({"claims": claims or []}), encoding="utf-8")
    proj = hub.make_project(slug)
    hub.add_registry_row(slug, state="writing", project=str(proj))
    plan = "# Plan\n\n## Analysis plan (frozen)\n\n- **Primary comparison:** x\n\n"
    if plan_log:
        plan += "## Test-split access log\n\n| date | configuration | run ids | reason |\n|---|---|---|---|\n"
        plan += "".join(f"| 2026-07-01 | {cfg} | r1 | {why} |\n" for cfg, why in log_rows)
    plan += "\n## Ablation plan\n"
    (proj / "PLAN.md").write_text(plan, encoding="utf-8")
    return sdir / "paper"


def test_prereg_clean(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", log_rows=[("exp-005", "")],
                   claims=[{"id": "C1", "claim": "ours beats base", "status": "confirmatory"},
                           {"id": "C2", "claim": "an exploratory look at depth", "status": "exploratory"}])
    assert m.audit(paper) == 0
    out = capsys.readouterr().out
    assert "all defined" in out and "none re-opened" in out and "2 labelled" in out


def test_prereg_unfilled_plan_fails(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", plan_filled=False, claims=[{"id": "C1", "claim": "x", "status": "confirmatory"}])
    assert m.audit(paper) == 1
    assert "not filled: Primary comparison, Uncertainty, Decision rule" in capsys.readouterr().out


def test_prereg_test_reopened_without_reason_fails(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", log_rows=[("exp-005", ""), ("exp-005", "")],
                   claims=[{"id": "C1", "claim": "x", "status": "confirmatory"}])
    assert m.audit(paper) == 1
    assert "re-opened without a reason: exp-005" in capsys.readouterr().out


def test_prereg_test_reopened_with_reason_passes(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", log_rows=[("exp-005", ""), ("exp-005", "reviewer asked for the ablation on test")],
                   claims=[{"id": "C1", "claim": "x", "status": "confirmatory"}])
    assert m.audit(paper) == 0


def test_prereg_silent_exploratory_claim_fails_and_unlabelled_is_manual(hub, monkeypatch, capsys):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", claims=[{"id": "C1", "claim": "depth helps", "status": "exploratory"}])
    assert m.audit(paper) == 1
    assert "does not say so: C1" in capsys.readouterr().out
    paper = _study(hub, "demo2", claims=[{"id": "C1", "claim": "depth helps"}])
    assert m.audit(paper) == 2


def test_prereg_missing_log_is_manual(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = _study(hub, "demo", plan_log=False, claims=[{"id": "C1", "claim": "x", "status": "confirmatory"}])
    assert m.audit(paper) == 2


def test_prereg_is_a_gate3_audit():
    rules = _yaml.safe_load((REPO / "workflow" / "rules.yaml").read_text(encoding="utf-8"))
    assert any(a["name"] == "prereg" and a["run"][0] == "audit_prereg.py" for a in rules["gate3_audits"])
    ids = [r["id"] for r in rules["project_rules"]]
    assert ids[-5:] == ["test-once", "analysis-plan", "post-hoc-rows", "data-provenance"][:0] or \
        {"test-once", "analysis-plan", "post-hoc-rows", "data-provenance"} <= set(ids)


# ── the project check lints the contract on a real scaffold ──────────────────────────────────
def _check(dest):
    r = subprocess.run([sys.executable, str(dest / "scripts" / "check_project.py")], capture_output=True, text=True,
                       cwd=str(dest), encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def _scaffold(tmp_path):
    dest = tmp_path / "proj"
    S.scaffold(dest, hub=REPO, slug="demo-proj", title="Demo Proj", date="2026-07-01", project_type="ml")
    for rel, sub in (("PLAN.md", ("{{title}}", "Demo")), ("control.yaml", ("{{x}}", ""))):
        p = dest / rel
        p.write_text(p.read_text(encoding="utf-8").replace(*sub), encoding="utf-8")
    return dest


def test_fresh_scaffold_passes_and_warns_about_what_is_unfilled(tmp_path):
    dest = _scaffold(tmp_path)
    rc, out = _check(dest)
    assert rc == 0, out
    assert "Analysis plan is not filled" in out and "data.sha256 is empty" in out and "total_minutes is 0" in out


def test_pilot_row_without_a_criterion_fails(tmp_path):
    dest = _scaffold(tmp_path)
    plan = dest / "PLAN.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "| exp-001 | pipeline end-to-end | SMOKE | todo | runs clean, artifacts written | |",
        "| exp-001 | pipeline end-to-end | SMOKE | todo | runs clean, artifacts written | |\n"
        "| exp-002 | baseline | PILOT | todo | | |"), encoding="utf-8")
    rc, out = _check(dest)
    assert rc == 1 and "exp-002 (PILOT) has no promotion/success criterion" in out


def test_pilot_before_smoke_and_budget_exhaustion_fail(tmp_path):
    dest = _scaffold(tmp_path)
    reg = dest / "runs" / "registry.jsonl"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({"run_id": "p1", "stage": "PILOT", "status": "completed", "wall_seconds": 7200}) + "\n", encoding="utf-8")
    ctl = dest / "control.yaml"
    ctl.write_text(ctl.read_text(encoding="utf-8").replace("total_minutes: 0", "total_minutes: 60"), encoding="utf-8")
    rc, out = _check(dest)
    assert rc == 1
    assert "PILOT run recorded before any completed SMOKE" in out and "budget exhausted (120 of 60 min)" in out


def test_missing_plan_sections_fail(tmp_path):
    dest = _scaffold(tmp_path)
    plan = dest / "PLAN.md"
    plan.write_text(plan.read_text(encoding="utf-8").replace("## Test-split access log", "## Something else"), encoding="utf-8")
    rc, out = _check(dest)
    assert rc == 1 and 'no "Test-split access log" section' in out
