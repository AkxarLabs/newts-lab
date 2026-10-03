"""Tests for checks/audit_claims.py — the mechanical claims auditor (hard rule 1)."""

from __future__ import annotations

import hashlib

import yaml
from conftest import load


def _mod(hub, monkeypatch):
    m = load("audit_claims")
    monkeypatch.setattr(m, "HUB", hub.root)
    return m


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_tolerance_half_ulp_of_printed_precision(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # "71.30" -> 2 decimals -> half-ULP 0.005; bare 71.3 -> 1 decimal -> 0.05 (10x looser).
    assert m.tolerance(71.30, "71.30", 1e-9) == 0.005
    assert m.tolerance(71.3, "71.3", 1e-9) == 0.05
    # integer printed -> half-ULP 0.5
    assert m.tolerance(5, "5", 1e-9) == 0.5
    # rel_tol wins when looser
    assert m.tolerance(1000.0, "1000", 1e-2) == 10.0


def test_numeric_leaves_skips_bools_and_walks_nesting(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    leaves = dict(m.numeric_leaves({"a": 1, "b": {"c": 2.5}, "flag": True, "xs": [10, 20]}))
    assert leaves["a"] == 1.0
    assert leaves["b.c"] == 2.5
    assert leaves["xs[0]"] == 10.0 and leaves["xs[1]"] == 20.0
    assert all("flag" not in k for k in leaves)  # bools are not numbers


def test_extract_numbers_json_and_text(hub, monkeypatch, tmp_path):
    m = _mod(hub, monkeypatch)
    j = tmp_path / "m.json"
    j.write_text('{"val_acc": 0.91, "loss": 1.2}', encoding="utf-8")
    vals = dict(m.extract_numbers(j))
    assert vals["val_acc"] == 0.91
    t = tmp_path / "log.txt"
    t.write_text("acc was 0.91 and 0.42", encoding="utf-8")
    nums = [v for _, v in m.extract_numbers(t)]
    assert 0.91 in nums and 0.42 in nums


# ── audit_claim verdicts ──────────────────────────────────────────────────────

def _paper(hub, slug, claims):
    pdir = hub.root / "studies" / slug / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "claims.yaml").write_text(yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return pdir


def test_audit_pass_direct_match(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.913})
    hub.add_registry_row("demo", project=str(proj))
    claim = {"id": "C001", "project": "demo", "numbers": ["0.913"],
             "metric": "val_acc", "artifacts": ["runs/r0/metrics.json"]}
    paper = _paper(hub, "demo", [claim])
    status, _ = m.audit_claim(claim, paper, 1e-3, False, False)
    assert status == "PASS"


def test_audit_pass_derived_mean_over_seeds(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.90})
    hub.write_metrics(proj, "runs/r1/metrics.json", {"val_acc": 0.92})
    hub.add_registry_row("demo", project=str(proj))
    # mean(0.90, 0.92) = 0.91 — present in neither artifact directly.
    claim = {"id": "C001", "project": "demo", "numbers": ["0.91"], "metric": "val_acc",
             "artifacts": ["runs/r0/metrics.json", "runs/r1/metrics.json"]}
    paper = _paper(hub, "demo", [claim])
    status, _ = m.audit_claim(claim, paper, 1e-3, False, False)
    assert status == "PASS-derived"


def test_audit_manual_when_derivation_present_but_unmatched(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.90})
    hub.add_registry_row("demo", project=str(proj))
    claim = {"id": "C001", "project": "demo", "numbers": ["42.0"], "metric": "val_acc",
             "artifacts": ["runs/r0/metrics.json"], "derivation": "hand-computed delta"}
    paper = _paper(hub, "demo", [claim])
    status, detail = m.audit_claim(claim, paper, 1e-3, False, False)
    assert status == "MANUAL"
    assert "derivation" in detail


def test_audit_fail_artifact_missing(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.add_registry_row("demo", project=str(proj))
    claim = {"id": "C001", "project": "demo", "numbers": ["0.9"],
             "artifacts": ["runs/nope/metrics.json"]}
    paper = _paper(hub, "demo", [claim])
    status, detail = m.audit_claim(claim, paper, 1e-3, False, False)
    assert status == "FAIL"
    assert "artifact missing" in detail


def test_audit_fail_unmatched_no_derivation(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.90})
    hub.add_registry_row("demo", project=str(proj))
    claim = {"id": "C001", "project": "demo", "numbers": ["0.5"], "metric": "val_acc",
             "artifacts": ["runs/r0/metrics.json"]}
    paper = _paper(hub, "demo", [claim])
    status, _ = m.audit_claim(claim, paper, 1e-3, False, False)
    assert status == "FAIL"


# ── resolve_project_dir precedence ────────────────────────────────────────────

def test_resolve_project_dir_explicit_path_wins(hub, monkeypatch, tmp_path):
    m = _mod(hub, monkeypatch)
    explicit = tmp_path / "explicit-proj"
    explicit.mkdir()
    hub.add_registry_row("demo", project="../projects/demo")
    claim = {"project": "demo", "project_path": str(explicit)}
    assert m.resolve_project_dir(claim) == explicit.resolve()


def test_resolve_project_dir_registry_column(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False, in_root=False)  # outside projects_root
    hub.add_registry_row("demo", project=str(proj))
    claim = {"project": "demo"}
    assert m.resolve_project_dir(claim) == proj.resolve()


def test_resolve_project_dir_default_projects_root(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # no registry row -> falls back to projects_root()/<slug>
    claim = {"project": "demo"}
    assert m.resolve_project_dir(claim) == (hub.projects_root / "demo").resolve()


# ── hub-archive-first + --verify-hashes ───────────────────────────────────────

def test_archive_first_audit_passes_with_project_absent_and_hash_verified(hub, monkeypatch):
    """The canonical /finalize case: project dir is gone, but the locked artifact under
    studies/<slug>/paper/artifacts/ + the recorded sha256 keep the audit PASSING."""
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", project="../projects/demo")  # project dir does NOT exist
    paper = hub.root / "studies" / "demo" / "paper"
    art = paper / "artifacts" / "runs" / "r0"
    art.mkdir(parents=True, exist_ok=True)
    metrics_bytes = b'{"val_acc": 0.913}'
    (art / "metrics.json").write_bytes(metrics_bytes)
    sha = hashlib.sha256(metrics_bytes).hexdigest()
    claim = {"id": "C001", "project": "demo", "numbers": ["0.913"], "metric": "val_acc",
             "artifacts": ["runs/r0/metrics.json"],
             "artifact_sha256": {"runs/r0/metrics.json": sha}}
    _paper(hub, "demo", [claim])
    status, _ = m.audit_claim(claim, paper, 1e-3, False, True)  # verify_hashes=True
    assert status == "PASS"


def test_verify_hashes_fail_on_tamper(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", project="../projects/demo")
    paper = hub.root / "studies" / "demo" / "paper"
    art = paper / "artifacts" / "runs" / "r0"
    art.mkdir(parents=True, exist_ok=True)
    (art / "metrics.json").write_bytes(b'{"val_acc": 0.913}')
    claim = {"id": "C001", "project": "demo", "numbers": ["0.913"], "metric": "val_acc",
             "artifacts": ["runs/r0/metrics.json"],
             "artifact_sha256": {"runs/r0/metrics.json": "0" * 64}}  # wrong hash
    _paper(hub, "demo", [claim])
    status, detail = m.audit_claim(claim, paper, 1e-3, False, True)
    assert status == "FAIL"
    assert "hash mismatch" in detail


# ── novelty scan (--scan-novelty: the discovery-vs-rediscovery gate) ───────────

def _tex(pdir, body: str):
    (pdir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\\end{document}\n",
        encoding="utf-8")


def test_novelty_scan_flags_only_unbacked_priority_claims(hub, monkeypatch):
    """A priority/superiority claim with no \\cite or % Cnnn/Nnnn backing is flagged; the same
    claim backed by a cite or an annotation is not; a non-priority 'first row' is left alone."""
    m = _mod(hub, monkeypatch)
    pdir = _paper(hub, "demo", [])
    _tex(pdir,
         "We achieve state-of-the-art accuracy here.\n"             # L3 unbacked -> flag
         "Our method outperforms all prior work \\cite{a2024}.\n"   # L4 \cite -> ok
         "This is the first method to do X. % N001 lit-review\n"    # L5 %N -> ok
         "An unprecedented gain over baselines. % C1\n"             # L6 %C -> ok
         "The first row of the table shows the layout.\n")          # L7 not a priority phrase
    findings = m.novelty_scan(pdir)
    assert len(findings) == 1
    assert findings[0].startswith("L3") and "state-of-the-art" in findings[0]


def test_novelty_scan_clean_when_backed_or_softened(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    pdir = _paper(hub, "demo2", [])
    _tex(pdir, "We report strong accuracy \\cite{b2024} and a clear improvement.\n")
    assert m.novelty_scan(pdir) == []


def test_novelty_scan_empty_without_main_tex(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    pdir = _paper(hub, "demo3", [])
    assert m.novelty_scan(pdir) == []


def test_scan_novelty_flag_sets_exit_2_via_main(hub, monkeypatch, capsys):
    """End-to-end: a passing claim + one unbacked novelty claim -> main() returns 2 (WARN),
    and without --scan-novelty the same paper is clean (0)."""
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.913})
    hub.add_registry_row("demo", project=str(proj))
    claim = {"id": "C001", "project": "demo", "numbers": ["0.913"],
             "metric": "val_acc", "artifacts": ["runs/r0/metrics.json"]}
    pdir = _paper(hub, "demo", [claim])
    _tex(pdir, "We report state-of-the-art results. % C001\n"       # measurement/coverage clean
               "We are the first to achieve this.\n")               # unbacked priority -> WARN
    rel = "studies/demo/paper"
    monkeypatch.setattr("sys.argv", ["audit_claims.py", rel, "--no-coverage", "--scan-novelty"])
    assert m.main() == 2
    monkeypatch.setattr("sys.argv", ["audit_claims.py", rel, "--no-coverage"])
    assert m.main() == 0  # novelty not scanned unless opted in
