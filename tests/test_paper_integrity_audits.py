"""Tests for the paper-integrity audits — multi-seed, ablation coverage, eval discipline — plus the
audit_claims --scan-integers opt-in. Exit convention: 0 clean · 2 needs human review · 1 violation.
"""

from __future__ import annotations

import json

import yaml as _yaml

from conftest import load


def _mod(hub, monkeypatch, name):
    m = load(name)
    monkeypatch.setattr(m, "HUB", hub.root)
    return m


def _paper(hub, slug, claims):
    d = hub.root / "studies" / slug / "paper"
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("claims.yaml").write_text(_yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return d


def _proj_with_runs(hub, slug, seed_rows):
    proj = hub.make_project(slug)
    reg = proj / "runs" / "registry.jsonl"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text("\n".join(json.dumps(r) for r in seed_rows), encoding="utf-8")
    hub.add_registry_row(slug, state="writing", project=str(proj))
    return proj


# ── multi-seed (hard rule 6) ──────────────────────────────────────────────────

def test_multiseed_pass_three_seeds(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_multiseed")
    _proj_with_runs(hub, "demo", [{"run_id": f"r{i}", "seed": i} for i in range(3)])
    paper = _paper(hub, "demo", [{"id": "C1", "headline": True, "project": "demo",
                                  "artifacts": [f"runs/r{i}/metrics.json" for i in range(3)]}])
    assert m.audit(paper) == 0


def test_multiseed_fail_two_seeds(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_multiseed")
    _proj_with_runs(hub, "demo", [{"run_id": "r0", "seed": 0}, {"run_id": "r1", "seed": 1}])
    paper = _paper(hub, "demo", [{"id": "C1", "headline": True, "project": "demo",
                                  "artifacts": ["runs/r0/metrics.json", "runs/r1/metrics.json"]}])
    assert m.audit(paper) == 1


def test_multiseed_waiver_is_manual(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_multiseed")
    _proj_with_runs(hub, "demo", [{"run_id": "r0", "seed": 0}])
    paper = _paper(hub, "demo", [{"id": "C1", "headline": True, "project": "demo",
                                  "multi_seed_waiver": "single expensive run; PI aware",
                                  "artifacts": ["runs/r0/metrics.json"]}])
    assert m.audit(paper) == 2


def test_multiseed_no_headline_is_clean(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_multiseed")
    _proj_with_runs(hub, "demo", [{"run_id": "r0", "seed": 0}])
    paper = _paper(hub, "demo", [{"id": "C1", "project": "demo", "artifacts": ["runs/r0/metrics.json"]}])
    assert m.audit(paper) == 0


# ── ablation coverage ─────────────────────────────────────────────────────────

def _proposal_ablations(hub, slug, body):
    d = hub.root / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("proposal.md").write_text(
        "# Proposal\n\n## 4. Experimental design\n\n### Planned ablations\n" + body + "\n\n## 5. Budget\n",
        encoding="utf-8")


def test_ablation_accounted(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_ablation_coverage")
    proj = hub.make_project("demo")
    (proj / "PLAN.md").write_text("| exp-005 | remove curriculum module | PILOT | done | | |\n", encoding="utf-8")
    hub.add_registry_row("demo", state="writing", project=str(proj))
    _proposal_ablations(hub, "demo", "- remove the curriculum module\n")
    assert m.audit(_paper(hub, "demo", [])) == 0


def test_ablation_unaccounted_fails(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_ablation_coverage")
    proj = hub.make_project("demo")
    (proj / "PLAN.md").write_text("| exp-002 | baseline | PILOT | done | | |\n", encoding="utf-8")
    hub.add_registry_row("demo", state="writing", project=str(proj))
    _proposal_ablations(hub, "demo", "- ablate the gizmo widget entirely\n")
    assert m.audit(_paper(hub, "demo", [])) == 1


def test_ablation_unparseable_is_manual(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_ablation_coverage")
    hub.make_project("demo")
    hub.add_registry_row("demo", state="writing", project="-")
    _proposal_ablations(hub, "demo", "<!-- Every component gets a removal test. -->")
    assert m.audit(_paper(hub, "demo", [])) == 2


def test_ablation_waived_is_accounted(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_ablation_coverage")
    proj = hub.make_project("demo")
    (proj / "PLAN.md").write_text("baseline only\n", encoding="utf-8")
    hub.add_registry_row("demo", state="writing", project=str(proj))
    _proposal_ablations(hub, "demo", "- ablate the widget (waived: out of scope this round)\n")
    assert m.audit(_paper(hub, "demo", [])) == 0


# ── eval discipline (hard rule 5) ─────────────────────────────────────────────

def _proposal_eval(hub, slug, val, test):
    d = hub.root / "studies" / slug
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("proposal.md").write_text(
        "# Proposal\n\n## 4. Experimental design\n\n"
        "### Metrics & evaluation protocol (FROZEN once approved)\n"
        "- **Primary metric:** accuracy\n"
        f"- **Validation set** (selection signal): {val}\n"
        f"- **Held-out test set** (reporting only): {test}\n\n## 5. Budget\n",
        encoding="utf-8")


def test_eval_protocol_and_test_claims_pass(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_eval_discipline")
    _proposal_eval(hub, "demo", "20% held-out val split", "final 20% test split")
    assert m.audit(_paper(hub, "demo", [{"id": "C1", "headline": True, "split": "test"}])) == 0


def test_eval_protocol_underspecified_fails(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_eval_discipline")
    _proposal_eval(hub, "demo", "", "")   # unfilled — only the label+hint remain
    assert m.audit(_paper(hub, "demo", [{"id": "C1", "headline": True, "split": "test"}])) == 1


def test_eval_headline_reports_validation_fails(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_eval_discipline")
    _proposal_eval(hub, "demo", "val split", "test split")
    assert m.audit(_paper(hub, "demo", [{"id": "C1", "headline": True, "split": "validation"}])) == 1


def test_eval_no_split_declared_is_manual(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_eval_discipline")
    _proposal_eval(hub, "demo", "val split", "test split")
    assert m.audit(_paper(hub, "demo", [{"id": "C1", "headline": True}])) == 2


# ── audit_claims --scan-integers ──────────────────────────────────────────────

def test_scan_integers_flags_metric_int_not_year(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_claims")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\begin{document}\n"
        "We train on 5000 samples.\n"          # 5000 near "samples" -> flag
        "We ran 2024 trials this cycle.\n"     # only int is a year -> NOT flagged even near "trials"
        "The model uses 12 layers.\n",         # "layers" is not a result word -> NOT flagged
        encoding="utf-8")
    assert m.coverage_scan(paper) == []                          # no decimals -> clean without the flag
    found = m.coverage_scan(paper, scan_integers=True)
    assert len(found) == 1 and "5000" in found[0] and "[int]" in found[0]
    assert not any("trials" in f for f in found)                 # a year-only line is excluded
    assert not any("layers" in f for f in found)                 # "layers" is not a result word


def test_scan_integers_respects_annotation(hub, monkeypatch):
    m = _mod(hub, monkeypatch, "audit_claims")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "main.tex").write_text(
        "\\begin{document}\nWe train on 5000 samples.  % C007\n", encoding="utf-8")
    assert m.coverage_scan(paper, scan_integers=True) == []  # annotated -> not flagged
