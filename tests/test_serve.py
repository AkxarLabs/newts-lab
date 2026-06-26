"""Tests for dashboard/serve.py — the local control surface (NO server bind).

serve.py does `import sources` at module load (it inserts dashboard/ on sys.path). We call the
pure functions directly. serve resolves project/control paths through `sources`, so we override
BOTH serve.HUB/serve.LAB AND the sources module object serve actually imported
(serve.sources.HUB / .LAB). No socket is ever bound.
"""

from __future__ import annotations

from conftest import REPO, load


def _mod(hub, monkeypatch):
    # Ensure `import sources` inside serve.py resolves to the real dashboard/sources.py.
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    # serve holds a reference to the sources module — patch its globals too.
    monkeypatch.setattr(m.sources, "HUB", hub.root)
    monkeypatch.setattr(m.sources, "LAB", hub.lab)
    return m


# ── run_tool whitelist ────────────────────────────────────────────────────────

def test_run_tool_rejects_non_whitelisted(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    res = m.run_tool("rm_rf")
    assert "error" in res
    assert "whitelist" in res["error"]


def test_safe_tools_set_is_read_only(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert "check_lab" in m.SAFE_TOOLS
    # nothing that trains/writes
    assert "run" not in m.SAFE_TOOLS and "sweep" not in m.SAFE_TOOLS


# ── gate approval ─────────────────────────────────────────────────────────────

def test_gate3_never_signable(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    res = m.approve_gate("demo", 3)
    assert "error" in res
    assert "Gate 3" in res["error"]


def test_gate2_expired_envelope_errors(hub, monkeypatch):
    import time
    m = _mod(hub, monkeypatch)
    past = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 30))
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": past,
        "full_runs": 4, "per_run_max_minutes": 30, "total_max_minutes": 120})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert "error" in res
    assert "expired" in res["error"]


def test_gate2_all_zero_envelope_returns_warning(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": None,
        "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert res.get("ok") is True
    assert res.get("warnings")  # non-empty warnings list
    assert any("authorizes nothing" in w for w in res["warnings"])


def test_gate2_successful_sign_writes_signed_and_signed_via(hub, monkeypatch):
    import yaml
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": None,
        "full_runs": 4, "per_run_max_minutes": 30, "total_max_minutes": 120})
    hub.add_registry_row("demo", state="active", project=str(proj))
    res = m.approve_gate("demo", 2)
    assert res.get("ok") is True
    doc = yaml.safe_load((proj / "control.yaml").read_text(encoding="utf-8"))
    env = doc["gate2_envelope"]
    assert env["pi_signed"] is True
    assert str(env["signed_via"]).startswith("dashboard:")


def test_gate1_signs_proposal_and_leaves_command(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    prop = hub.root / "studies" / "demo" / "proposal.md"
    prop.parent.mkdir(parents=True, exist_ok=True)
    prop.write_text("# Proposal\n", encoding="utf-8")
    res = m.approve_gate("demo", 1)
    assert res.get("ok") is True
    assert "Gate 1 approved" in prop.read_text(encoding="utf-8")


# ── paper artifacts (compiled PDF + figures) — read-only binary views ──────────

def _make_paper(hub, slug="demo", figures=None):
    pdir = hub.root / "studies" / slug / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "main.pdf").write_bytes(b"%PDF-1.5\nbody\n")
    (pdir / "main.tex").write_text("\\documentclass{article}\n", encoding="utf-8")
    if figures:
        fdir = pdir / "figures"
        fdir.mkdir(exist_ok=True)
        for name, data in figures.items():
            (fdir / name).write_bytes(data)
    return pdir


def test_paper_pdf_found_and_missing(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m.paper_pdf("demo") is None        # nothing compiled yet
    _make_paper(hub)
    f = m.paper_pdf("demo")
    assert f is not None and f.name == "main.pdf"


def test_figure_list_filters_by_extension(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _make_paper(hub, figures={"loss.png": b"\x89PNG", "tab.tex": b"x", "diagram.pdf": b"%PDF"})
    figs = m.figure_list("demo")
    assert "loss.png" in figs and "diagram.pdf" in figs
    assert "tab.tex" not in figs              # .tex is not a servable figure


def test_figure_file_blocks_path_traversal(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _make_paper(hub, figures={"loss.png": b"\x89PNG"})
    assert m.figure_file("demo", "loss.png") is not None
    # any traversal attempt is reduced to a basename that doesn't exist in figures/ -> None
    assert m.figure_file("demo", "../../../etc/passwd") is None
    assert m.figure_file("demo", "../control.yaml") is None


def test_read_doc_section_carries_editor_path(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    prop = hub.root / "studies" / "demo" / "proposal.md"
    prop.parent.mkdir(parents=True, exist_ok=True)
    prop.write_text("# Proposal\n", encoding="utf-8")
    sec = m.read_doc("gate", "demo", 1)["sections"][0]
    assert sec.get("path", "").endswith("proposal.md")


# ── markdown section extraction (the gate-bundle parser) ──────────────────────

def test_md_section_numbered_and_suffixed_headings(hub, monkeypatch):
    import re
    m = _mod(hub, monkeypatch)
    text = (
        "# T\n\n## 5. Budget\n\n- compute: 10h\n\n"
        "### Gate 2 envelope (optional)\n- none\n\n"
        "## 6. Kill criteria (checked after every pilot)\n\n- effect < 0.1\n\n"
        "## 7. Success criteria & deliverable\n\n- a paper\n"
    )
    budget = m._md_section(text, re.compile(r"\bBudget\b", re.I))
    assert "compute: 10h" in budget and "Gate 2 envelope" in budget   # ### nested stays inside the ## section
    assert "Kill criteria" not in budget                              # stops at the next ## heading
    assert "effect < 0.1" in m._md_section(text, re.compile(r"Kill criteria", re.I))
    assert m._md_section(text, re.compile(r"nonexistent", re.I)) == ""


# ── Gate 1 bundle: novelty verdict + decision-critical sections + full proposal ──

def test_gate1_bundle_composes_novelty_and_critical_sections(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    sdir = hub.root / "studies" / "demo"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "lit-review.md").write_text(
        "# Lit\n\n## Novelty verdict\n\n**Verdict:** novel\n**Closest prior work:** [foo]\n\n"
        "## Positioning & implications for the proposal\n\nstuff\n", encoding="utf-8")
    (sdir / "proposal.md").write_text(
        "# Proposal\n\n## 1. Hypothesis\n\nH\n\n## 5. Budget\n\n- 10 GPU-h\n\n"
        "## 6. Kill criteria (checked after every pilot)\n\n- kill if X\n\n"
        "## 7. Success criteria & deliverable\n\n- a paper\n", encoding="utf-8")
    res = m.read_doc("gate", "demo", 1)
    titles = [s["title"] for s in res["sections"]]
    assert any("Novelty verdict" in t for t in titles)
    crit = next(s for s in res["sections"] if "Decision-critical" in s["title"])
    assert "10 GPU-h" in crit["text"] and "kill if X" in crit["text"] and "a paper" in crit["text"]
    nov = next(s for s in res["sections"] if "Novelty" in s["title"])
    assert nov["path"].endswith("lit-review.md")              # editor link to the lit-review
    assert any(t.endswith("proposal.md") for t in titles)     # full proposal still present


# ── Gate 2 bundle: the completed PILOT runs that justify scaling ──────────────

def test_gate2_bundle_surfaces_completed_pilot_runs(hub, monkeypatch):
    import json
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": False, "signed_via": None, "expires": None,
        "full_runs": 2, "per_run_max_minutes": 30, "total_max_minutes": 60})
    hub.add_registry_row("demo", state="active", project=str(proj))
    reg = proj / "runs" / "registry.jsonl"
    reg.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"run_id": "exp-002-pilot-s0", "stage": "PILOT", "status": "completed", "seed": 0, "metrics": {"val_acc": 0.83}},
        {"run_id": "exp-001-smoke-s0", "stage": "SMOKE", "status": "completed", "seed": 0, "metrics": {"val_acc": 0.5}},
        {"run_id": "exp-003-pilot-s1", "stage": "PILOT", "status": "running", "seed": 1, "metrics": {}},
    ]
    reg.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    pilot = next(s for s in m.read_doc("gate", "demo", 2)["sections"] if "Pilot evidence" in s["title"])
    assert "exp-002-pilot-s0" in pilot["text"] and "val_acc=0.83" in pilot["text"]
    assert "exp-001-smoke" not in pilot["text"]    # SMOKE excluded
    assert "exp-003-pilot" not in pilot["text"]    # still-running excluded
    assert "1 completed PILOT" in pilot["title"]


# ── Gate 3 bundle: reviews found RECURSIVELY (the old glob missed them) + meta verdict ──

def test_gate3_bundle_finds_reviews_recursively_and_lifts_verdict(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = hub.root / "studies" / "demo" / "paper"
    (paper / "reviews" / "critique-2026-06-27").mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("claims: []\n", encoding="utf-8")
    (paper / "reviews" / "review-1.md").write_text("# review wrapper\n", encoding="utf-8")
    (paper / "reviews" / "critique-2026-06-27" / "meta-review.md").write_text(
        "# Meta\n\n## Score aggregation\n\n| Dimension | Median | Range |\n|---|---|---|\n"
        "| **Overall** | 7 | 6-8 |\n\n## Decision\n\n**accept**\n\n## Action items\n\n- none\n", encoding="utf-8")
    res = m.read_doc("gate", "demo", 3)
    titles = [s["title"] for s in res["sections"]]
    verdict = next(s for s in res["sections"] if "Meta-review verdict" in s["title"])
    assert "accept" in verdict["text"] and "Overall" in verdict["text"]
    assert any("review-1.md" in t for t in titles)            # was missed by the non-recursive glob
    assert any("meta-review.md" in t for t in titles)


# ── claims ↔ artifact map ─────────────────────────────────────────────────────

def test_claims_map_resolves_and_marks_linkage(hub, monkeypatch):
    import json
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="writing", project=str(proj))
    art = proj / "runs" / "r0" / "metrics.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps({"val_acc": 0.91}), encoding="utf-8")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text(
        "claims:\n"
        "  - id: C001\n    claim: ours hits 0.91\n    numbers: ['0.91']\n    metric: val_acc\n"
        "    location: Table 2\n    project: demo\n    artifacts:\n      - runs/r0/metrics.json\n"
        "  - id: C002\n    claim: missing one\n    numbers: ['1.0']\n    project: demo\n"
        "    artifacts:\n      - runs/ghost/metrics.json\n", encoding="utf-8")
    res = m.claims_map("demo")
    assert res["n"] == 2
    c1 = res["claims"][0]
    assert c1["id"] == "C001" and c1["linked"] is True
    a = c1["artifacts"][0]
    assert a["exists"] is True and a["run_id"] == "r0" and a["project"] == "demo" and a["abs"].endswith("metrics.json")
    c2 = res["claims"][1]
    assert c2["linked"] is False and c2["artifacts"][0]["exists"] is False


def test_claims_map_missing_file_errors(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    res = m.claims_map("demo")
    assert "error" in res and "claims.yaml" in res["error"]


def test_run_tool_audit_claims_whitelisted_needs_slug(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert "audit_claims" in m.SAFE_TOOLS          # read-only audit is allowed
    res = m.run_tool("audit_claims", "")
    assert "error" in res and "slug" in res["error"]


# ── claims_map hardening (from the adversarial review) ────────────────────────

def test_claims_map_coerces_scalar_artifacts_and_numbers(hub, monkeypatch):
    import json
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    art = proj / "runs" / "r0" / "metrics.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text(json.dumps({"val_acc": 0.91}), encoding="utf-8")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text(
        "claims:\n  - just a bare string\n"            # non-dict list item → skipped
        "  - id: C001\n    numbers: '0.91'\n    artifacts: runs/r0/metrics.json\n    project: demo\n",
        encoding="utf-8")
    res = m.claims_map("demo")
    assert res["n"] == 1                               # the bare string is not a claim
    c = res["claims"][0]
    assert c["numbers"] == ["0.91"]                    # scalar coerced — NOT split into characters
    assert len(c["artifacts"]) == 1                    # scalar coerced — NOT 20 single-char rels
    a = c["artifacts"][0]
    assert a["rel"] == "runs/r0/metrics.json" and a["exists"] is True and a["run_id"] == "r0"


def test_claims_map_tolerates_non_dict_toplevel(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("just a bare scalar\n", encoding="utf-8")
    res = m.claims_map("demo")                          # must not raise AttributeError
    assert res["ok"] is True and res["n"] == 0


def test_claims_map_blocks_artifact_traversal(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    (proj.parent / "secret.json").write_text("{}", encoding="utf-8")   # a real file OUTSIDE the project
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text(
        "claims:\n  - id: C001\n    project: demo\n    artifacts:\n      - ../secret.json\n", encoding="utf-8")
    a = m.claims_map("demo")["claims"][0]["artifacts"][0]
    assert a["exists"] is False and "abs" not in a     # escapes the project → never surfaced
