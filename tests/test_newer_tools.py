"""Tests for the newer hub trust tools:
  sync_figures.py      — copy project figures into the hub + a verifiable manifest, --check drift
  lock_artifacts.py    — archive cited metrics.json into papers/<slug>/artifacts/ + record sha256
  hub_writeback.py     — atomic project->hub write-back (notebook + knowledge + registry state)
  process_writebacks.py— reconcile deferred HUB-WRITEBACK-PENDING blocks, idempotently

These drive main() via sys.argv where the tool only exposes a CLI; globals (HUB/LAB) are
overridden onto the fake hub. lock + audit are chained to prove the "auditable from the hub
alone" property.
"""

from __future__ import annotations

import json
import sys
import time

import yaml
from conftest import load


# ── sync_figures ──────────────────────────────────────────────────────────────

def _sync_mod(hub, monkeypatch):
    m = load("sync_figures")
    monkeypatch.setattr(m, "HUB", hub.root)
    return m


def _run_main(m, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["tool.py", *argv])
    return m.main()


def test_sync_figures_writes_manifest_then_check_clean(hub, monkeypatch):
    m = _sync_mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    figs = proj / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    (figs / "fig1.png").write_bytes(b"PNGDATA")
    # sync
    assert _run_main(m, monkeypatch, "demo") == 0
    manifest = hub.root / "papers" / "demo" / "figures" / ".manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert "fig1.png" in data
    # --check: clean
    assert _run_main(m, monkeypatch, "demo", "--check") == 0


def test_sync_figures_check_flags_hand_edited_hub_copy(hub, monkeypatch):
    m = _sync_mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    figs = proj / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    (figs / "fig1.png").write_bytes(b"PNGDATA")
    _run_main(m, monkeypatch, "demo")
    # hand-edit the HUB copy -> diverged
    (hub.root / "papers" / "demo" / "figures" / "fig1.png").write_bytes(b"TAMPERED")
    assert _run_main(m, monkeypatch, "demo", "--check") == 1


def test_sync_figures_check_flags_stale_project_source(hub, monkeypatch):
    m = _sync_mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    figs = proj / "figures"
    figs.mkdir(parents=True, exist_ok=True)
    (figs / "fig1.png").write_bytes(b"PNGDATA")
    _run_main(m, monkeypatch, "demo")
    # regenerate the PROJECT source without re-syncing -> stale
    (figs / "fig1.png").write_bytes(b"REGENERATED")
    assert _run_main(m, monkeypatch, "demo", "--check") == 1


# ── lock_artifacts (+ audit chained) ──────────────────────────────────────────

def _paper_with_claim(hub, slug, claim):
    pdir = hub.root / "papers" / slug
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "claims.yaml").write_text(yaml.safe_dump({"claims": [claim]}), encoding="utf-8")
    return pdir


def test_lock_archives_and_records_sha256(hub, monkeypatch):
    m = load("lock_artifacts")
    monkeypatch.setattr(m, "HUB", hub.root)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.913})
    _paper_with_claim(hub, "demo", {
        "id": "C001", "project": "demo", "numbers": ["0.913"], "metric": "val_acc",
        "artifacts": ["runs/r0/metrics.json"]})
    assert _run_main(m, monkeypatch, "demo") == 0
    archived = hub.root / "papers" / "demo" / "artifacts" / "runs" / "r0" / "metrics.json"
    assert archived.exists()
    doc = yaml.safe_load((hub.root / "papers" / "demo" / "claims.yaml").read_text(encoding="utf-8"))
    sha = doc["claims"][0]["artifact_sha256"]["runs/r0/metrics.json"]
    assert len(sha) == 64


def test_lock_then_audit_passes_with_project_removed(hub, monkeypatch):
    """End-to-end integrity property: lock the artifact, delete the project, audit --verify-hashes
    still PASSES from the hub archive alone."""
    import shutil

    lock = load("lock_artifacts")
    monkeypatch.setattr(lock, "HUB", hub.root)
    proj = hub.make_project("demo", control=False)
    hub.write_metrics(proj, "runs/r0/metrics.json", {"val_acc": 0.913})
    paper = _paper_with_claim(hub, "demo", {
        "id": "C001", "project": "demo", "numbers": ["0.913"], "metric": "val_acc",
        "artifacts": ["runs/r0/metrics.json"]})
    assert _run_main(lock, monkeypatch, "demo") == 0

    # remove the project entirely
    shutil.rmtree(proj)

    audit = load("audit_claims")
    monkeypatch.setattr(audit, "HUB", hub.root)
    claim = yaml.safe_load((paper / "claims.yaml").read_text(encoding="utf-8"))["claims"][0]
    status, _ = audit.audit_claim(claim, paper, 1e-3, False, True)  # --verify-hashes
    assert status == "PASS"


# ── hub_writeback ─────────────────────────────────────────────────────────────

def _wb_mod(hub, monkeypatch):
    m = load("hub_writeback")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def test_hub_writeback_notebook_finding_and_state(hub, monkeypatch):
    m = _wb_mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    rc = _run_main(m, monkeypatch, "--slug", "demo",
                   "--notebook", "ran the pilot for demo",
                   "--finding", "method X beats baseline by 2pts",
                   "--state", "analysis")
    assert rc == 0
    # notebook entry exists, dated, names the slug
    today = time.strftime("%Y-%m-%d")
    nb = hub.lab / "notebook" / f"{today}-demo.md"
    assert nb.exists() and "ran the pilot for demo" in nb.read_text(encoding="utf-8")
    # finding promoted
    findings = (hub.lab / "knowledge" / "FINDINGS.md").read_text(encoding="utf-8")
    assert "method X beats baseline" in findings
    # registry state updated
    reg = (hub.lab / "REGISTRY.md").read_text(encoding="utf-8")
    assert "| demo |" in reg and "analysis" in reg


def test_hub_writeback_nothing_to_do_returns_1(hub, monkeypatch):
    m = _wb_mod(hub, monkeypatch)
    assert _run_main(m, monkeypatch, "--slug", "demo") == 1


# ── process_writebacks ────────────────────────────────────────────────────────

def _pw_mod(hub, monkeypatch):
    m = load("process_writebacks")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def test_process_writebacks_apply_is_idempotent(hub, monkeypatch):
    m = _pw_mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    log = proj / "EXPERIMENT_LOG.md"
    log.write_text(
        "# log\n\n"
        "HUB-WRITEBACK-PENDING: wb-1\n"
        "notebook: deferred note for demo\n"
        "finding: deferred finding\n",
        encoding="utf-8")

    # first --apply: reconciles the block
    assert _run_main(m, monkeypatch, "--apply") == 0
    today = time.strftime("%Y-%m-%d")
    nb = hub.lab / "notebook" / f"{today}-demo.md"
    assert nb.exists() and "deferred note for demo" in nb.read_text(encoding="utf-8")
    findings = (hub.lab / "knowledge" / "FINDINGS.md").read_text(encoding="utf-8")
    assert findings.count("deferred finding") == 1
    # a DONE marker was appended (append-only)
    assert "HUB-WRITEBACK-DONE: wb-1" in log.read_text(encoding="utf-8")

    # second --apply: no-op (no new notebook/knowledge writes for the same block)
    assert _run_main(m, monkeypatch, "--apply") == 0
    findings2 = (hub.lab / "knowledge" / "FINDINGS.md").read_text(encoding="utf-8")
    assert findings2.count("deferred finding") == 1  # still exactly once


def test_process_writebacks_list_mode_finds_pending(hub, monkeypatch, capsys):
    m = _pw_mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    (proj / "EXPERIMENT_LOG.md").write_text(
        "HUB-WRITEBACK-PENDING: wb-9\nnotebook: a note\n", encoding="utf-8")
    assert _run_main(m, monkeypatch) == 0  # list mode (no --apply)
    out = capsys.readouterr().out
    assert "wb-9" in out and "pending" in out
