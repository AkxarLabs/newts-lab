"""templates/project/scripts/_scheduler.py + run.py — training through the machine's job scheduler.

End to end against a fake SLURM (tests/fake_slurm.py, POSIX): a PILOT run in a real copy of the project
template is submitted, sits in the queue as "queued" (status.py never calls it stalled), runs on the "node"
via `run.py --in-job`, and the submitter exits with the job's result. Also: a job that dies on the node,
cancelling on SIGTERM, the local path untouched, the job script's #SBATCH lines, and --in-job refusing a
run that wasn't queued.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import REPO, load

posix = pytest.mark.skipif(os.name != "posix" or not shutil.which("bash"), reason="fake SLURM needs POSIX + bash")


@pytest.fixture
def proj(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    (hub / "lab").mkdir(parents=True)
    pdir = tmp_path / "proj"
    shutil.copytree(REPO / "templates" / "project", pdir, ignore=shutil.ignore_patterns("runs", "__pycache__", ".bus"))
    (pdir / "runs").mkdir(exist_ok=True)
    ctl = (pdir / "control.yaml").read_text(encoding="utf-8")
    ctl = ctl.replace('hub_path: "{{hub_path}}"', f'hub_path: "{hub.as_posix()}"').replace('project: "{{slug}}"', 'project: "demo"')
    (pdir / "control.yaml").write_text(ctl, encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    for c in ("sbatch", "squeue", "sacct", "scancel"):
        w = fake / c
        w.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{REPO / "tests" / "fake_slurm.py"}" {c} "$@"\n')
        w.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SLURM_DIR", str(tmp_path / "slurm"))
    monkeypatch.setenv("AUTOSCIENTIST_SLOT_HELD", "1")      # the slot ledger is tested elsewhere
    monkeypatch.setenv("NEWTS_SCHED_POLL", "0.3")
    monkeypatch.delenv("NEWTS_SCHEDULER", raising=False)
    return hub, pdir


def _scheduler_cfg(hub, **extra):
    block = {"kind": "slurm", "stages": ["PILOT", "FULL"],
             "slurm": {"partition": "gpu", "gpus_per_run": 1, "mem": "8G", "setup": ["echo setting up"]}}
    block.update(extra)
    import yaml
    (hub / "lab" / "config.yaml").write_text(yaml.safe_dump({"compute": {"scheduler": block}}), encoding="utf-8")


def _run(pdir, *more, wait=True):
    argv = [sys.executable, "scripts/run.py", "--config", "configs/experiments/exp-001-smoke.yaml", "-o", "stage=PILOT", *more]
    if not wait:
        return subprocess.Popen(argv, cwd=pdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return subprocess.run(argv, cwd=pdir, capture_output=True, text=True, timeout=180)


def _meta(pdir):
    d = max((pdir / "runs").glob("exp-001-smoke-*"), key=lambda p: p.stat().st_mtime)
    return d, json.loads((d / "meta.json").read_text())


@posix
def test_submitted_queued_then_completed(proj, monkeypatch, tmp_path):
    hub, pdir = proj
    _scheduler_cfg(hub)
    monkeypatch.setenv("FAKE_SLURM_PENDING", "2")
    p = _run(pdir, wait=False)
    # while pending: the run dir exists, status queued, and status.py says so (exit 0, never "stalled")
    t0 = time.time()
    meta = {}
    while time.time() - t0 < 20:
        runs = list((pdir / "runs").glob("exp-001-smoke-*"))
        if runs:
            _d, meta = _meta(pdir)
            if meta.get("scheduler", {}).get("job"):
                break
        time.sleep(0.1)
    assert meta["status"] == "queued" and meta["scheduler"]["kind"] == "slurm"
    st = subprocess.run([sys.executable, "scripts/status.py"], cwd=pdir, capture_output=True, text=True, timeout=60)
    assert st.returncode == 0 and "status=queued" in st.stdout and "slurm job" in st.stdout
    out, _ = p.communicate(timeout=120)
    assert p.returncode == 0, out
    d, meta = _meta(pdir)
    assert meta["status"] == "completed" and meta["scheduler"]["job"] and meta["queued"]
    assert (d / "metrics.json").exists()
    reg = [json.loads(x) for x in (pdir / "runs" / "registry.jsonl").read_text().splitlines()]
    assert reg[-1]["run_id"] == d.name and reg[-1]["status"] == "completed"
    job = (d / "job.sh").read_text()
    assert "#SBATCH --partition=gpu" in job and "#SBATCH --gres=gpu:1" in job and "#SBATCH --mem=8G" in job
    assert "#SBATCH --time=" in job and "echo setting up" in job and "--in-job" in job
    assert f"[run] {d.name} -> " in out                         # sweep.py's contract line is kept


@posix
def test_job_dies_on_the_node(proj, monkeypatch):
    hub, pdir = proj
    _scheduler_cfg(hub)
    monkeypatch.setenv("FAKE_SLURM_KILL_AFTER", "1.5")        # a node failure mid-run
    r = _run(pdir, "-o", "toy.sleep_seconds=20")
    d, meta = _meta(pdir)
    assert r.returncode == 1 and meta["status"] == "failed", r.stdout
    assert "ended without finishing" in (d / "error.txt").read_text()
    reg = [json.loads(x) for x in (pdir / "runs" / "registry.jsonl").read_text().splitlines()]
    assert reg[-1]["run_id"] == d.name and reg[-1]["status"] == "failed"


@posix
def test_sigterm_cancels_the_job(proj, monkeypatch, tmp_path):
    hub, pdir = proj
    _scheduler_cfg(hub)
    monkeypatch.setenv("FAKE_SLURM_PENDING", "30")
    p = _run(pdir, wait=False)
    t0 = time.time()
    while time.time() - t0 < 20 and not list((pdir / "runs").glob("exp-001-smoke-*/job.sh")):
        time.sleep(0.1)
    time.sleep(1.0)
    p.send_signal(signal.SIGTERM)
    p.communicate(timeout=60)
    d, meta = _meta(pdir)
    assert meta["status"] == "killed"
    calls = [json.loads(x)["cmd"] for x in (tmp_path / "slurm" / "calls.jsonl").read_text().splitlines()]
    assert "scancel" in calls


def test_local_stays_local_and_smoke_never_queues(proj):
    hub, pdir = proj
    _scheduler_cfg(hub, stages=["FULL"])                     # PILOT not sent to the scheduler
    r = _run(pdir)
    assert r.returncode == 0, r.stdout + r.stderr
    _d, meta = _meta(pdir)
    assert meta["status"] == "completed" and "scheduler" not in meta


def test_in_job_refuses_a_run_that_was_not_queued(proj):
    _hub, pdir = proj
    fake_dir = pdir / "runs" / "exp-001-smoke-s0-x"
    fake_dir.mkdir(parents=True)
    (fake_dir / "meta.json").write_text(json.dumps({"status": "running"}))
    r = _run(pdir, "--in-job", "--run-dir", str(fake_dir))
    assert r.returncode != 0 and "only for a queued scheduler job" in (r.stdout + r.stderr)


def test_config_merge_and_custom_state_parsing(proj, monkeypatch):
    hub, pdir = proj
    sch = load("templates/project/scripts/_scheduler")
    _scheduler_cfg(hub)
    sc = sch.config({"hub_path": str(hub), "compute": {"scheduler": {"slurm": {"gpus_per_run": 4}}}})
    assert sc["kind"] == "slurm" and sc["slurm"]["gpus_per_run"] == 4 and sc["slurm"]["partition"] == "gpu"
    assert sch.wants(sc, "PILOT") and not sch.wants(sc, "SMOKE")
    monkeypatch.setenv("NEWTS_SCHEDULER", "local")
    assert not sch.wants(sch.config({"hub_path": str(hub)}), "FULL")
    c = sch.Custom({"custom": {"state": "true"}})
    assert c.state("1") == "gone"                              # no output = left the queue
