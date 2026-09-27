"""Where a run executes — on this machine, or through the machine's job scheduler.

A lab lives on one machine, and that machine decides how training runs are executed. It is DESCRIBED, not
assumed: `compute.scheduler` in the hub's lab/config.yaml (set in the dashboard → Settings → System, which
detects what the machine offers), optionally overridden per project in control.yaml `compute.scheduler`:

    compute:
      scheduler:
        kind: local            # local | slurm | custom
        stages: [PILOT, FULL]  # stages that go through the scheduler; SMOKE always runs where it's launched
        poll_seconds: 30
        max_queue_hours: 48    # give up (cancel) on a job that never started
        slurm: {partition, account, qos, gpus_per_run, gres, cpus_per_task, mem, constraint,
                time_grace_minutes, extra_args: [...], setup: [shell lines: module load …, source …]}
        custom: {submit: "qsub {script}", state: "qstat {job}", cancel: "qdel {job}"}   # any other system

With a scheduler, run.py SUBMITS the run and WAITS for it (so agents, sweep.py and status.py see the same
synchronous run as before): the run dir is created up front with status "queued"; job.sh runs
`run.py … --in-job --run-dir <dir>` on the compute node, which then behaves exactly like a local run (its
watchdog, artifacts, registry line). The submitter keeps the compute slot alive, cancels the job if it is
stopped, and records a job that vanished without finishing as failed. Queue time never counts against the
budget. Anything site-specific that isn't a setting belongs in SYSTEM.md.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _yaml(p: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def config(control: dict) -> dict:
    """The effective scheduler block: the hub's lab/config.yaml, then this project's control.yaml."""
    hub = control.get("hub_path")
    base = {}
    if hub:
        base = ((_yaml(Path(hub) / "lab" / "config.yaml").get("compute") or {}).get("scheduler") or {})
    proj = ((control.get("compute") or {}).get("scheduler") or {})
    sc = _merge(base, proj)
    if os.environ.get("NEWTS_SCHEDULER"):          # a one-off override: NEWTS_SCHEDULER=local
        sc["kind"] = os.environ["NEWTS_SCHEDULER"]
    sc.setdefault("kind", "local")
    sc.setdefault("stages", ["PILOT", "FULL"])
    return sc


def wants(sc: dict, stage: str) -> bool:
    return str(sc.get("kind") or "local") != "local" and str(stage).upper() in [str(s).upper() for s in sc.get("stages") or []]


def _sh(cmd, timeout: float = 120) -> subprocess.CompletedProcess:
    argv = cmd if isinstance(cmd, list) else shlex.split(cmd)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


class Slurm:
    kind = "slurm"

    def __init__(self, sc: dict):
        self.sc = sc
        self.s = sc.get("slurm") or {}

    def directives(self, run_id: str, run_dir: Path, minutes: float) -> list[str]:
        s = self.s
        grace = float(s.get("time_grace_minutes") or 10)
        d = [f"--job-name=nl-{run_id}"[:120], f"--output={run_dir.as_posix()}/job-%j.out",
             f"--time={max(1, int(round(float(minutes or 60) + grace)))}"]
        for key, flag in (("partition", "--partition"), ("account", "--account"), ("qos", "--qos"),
                          ("cpus_per_task", "--cpus-per-task"), ("mem", "--mem"), ("constraint", "--constraint")):
            if s.get(key) not in (None, ""):
                d.append(f"{flag}={s[key]}")
        if s.get("gres"):
            d.append(f"--gres={s['gres']}")
        elif s.get("gpus_per_run"):
            d.append(f"--gres=gpu:{int(s['gpus_per_run'])}")
        d += [str(x) for x in (s.get("extra_args") or [])]
        return ["#SBATCH " + x for x in d]

    def setup(self) -> list[str]:
        return [str(x) for x in (self.s.get("setup") or [])]

    def submit(self, script: Path) -> str:
        r = _sh(["sbatch", "--parsable", str(script)])
        if r.returncode != 0:
            raise RuntimeError(f"sbatch failed: {(r.stderr or r.stdout).strip()[-400:]}")
        return r.stdout.strip().split(";", 1)[0].strip()

    def state(self, job: str) -> str:
        r = _sh(["squeue", "-h", "-j", str(job), "-o", "%T"], timeout=60)
        st = (r.stdout or "").strip().upper()
        if r.returncode != 0 and not st:
            return "gone"
        if not st:
            return "gone"
        if any(x in st for x in ("PENDING", "CONFIGURING", "REQUEUED", "SUSPENDED")):
            return "queued"
        return "running"

    def reason(self, job: str) -> str:
        r = _sh(["sacct", "-j", str(job), "-n", "-X", "-o", "State,ExitCode,Reason%40"], timeout=60)
        return " ".join((r.stdout or "").split()) or "unknown"

    def cancel(self, job: str) -> None:
        _sh(["scancel", str(job)], timeout=60)


class Custom(Slurm):
    """Any other system, described by three command templates ({script} / {job}). `state` output is
    read loosely: PEND/QUEUE/WAIT/Q → queued, RUN/R → running, empty or a failure → gone."""
    kind = "custom"

    def __init__(self, sc: dict):
        super().__init__(sc)
        self.c = sc.get("custom") or {}

    def directives(self, run_id: str, run_dir: Path, minutes: float) -> list[str]:
        return [str(x) for x in (self.c.get("header") or [])]

    def setup(self) -> list[str]:
        return [str(x) for x in (self.c.get("setup") or [])]

    def submit(self, script: Path) -> str:
        if not self.c.get("submit"):
            raise RuntimeError("compute.scheduler.custom.submit is not set")
        r = _sh(self.c["submit"].format(script=str(script)))
        if r.returncode != 0:
            raise RuntimeError(f"submit failed: {(r.stderr or r.stdout).strip()[-400:]}")
        m = re.search(r"[\w.\[\]-]+", r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")
        if not m:
            raise RuntimeError("submit printed no job id")
        return m.group(0)

    def state(self, job: str) -> str:
        if not self.c.get("state"):
            return "running"
        r = _sh(self.c["state"].format(job=job), timeout=60)
        out = (r.stdout or "").upper()
        if r.returncode != 0 or not out.strip():
            return "gone"
        if re.search(r"PEND|QUEU|WAIT|\bQ\b|HOLD", out):
            return "queued"
        if re.search(r"RUN|\bR\b|ACTIVE|START", out):
            return "running"
        return "gone"

    def reason(self, job: str) -> str:
        return "the job left the queue without finishing"

    def cancel(self, job: str) -> None:
        if self.c.get("cancel"):
            _sh(self.c["cancel"].format(job=job), timeout=60)


ADAPTERS = {"slurm": Slurm, "custom": Custom}


def adapter(sc: dict):
    kind = str(sc.get("kind") or "local")
    if kind not in ADAPTERS:
        raise SystemExit(f"[run] unknown compute.scheduler.kind {kind!r} — local | slurm | custom")
    return ADAPTERS[kind](sc)


def _write_meta(run_dir: Path, meta: dict) -> None:
    tmp = run_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, run_dir / "meta.json")


def _read_meta(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


TERMINAL = {"completed", "failed", "timeout", "killed"}
EXIT = {"completed": 0, "timeout": 2}


def _finalize(run_dir: Path, status: str, why: str) -> None:
    """A job that ended without its run finishing: record it like sweep.py records an orphan."""
    meta = _read_meta(run_dir)
    if meta.get("status") in TERMINAL:
        return
    (run_dir / "error.txt").write_text(why + "\n", encoding="utf-8")
    meta.update(status=status, finished=time.strftime("%Y-%m-%dT%H:%M:%S"), wall_seconds=meta.get("wall_seconds"))
    _write_meta(run_dir, meta)
    sys.path.insert(0, str(REPO / "src"))
    try:
        import importlib
        pkg = os.environ.get("PROJECT_PKG") or "project_pkg"
        tracking = importlib.import_module(f"{pkg}.tracking")
        line = {"run_id": meta.get("run_id", run_dir.name), "experiment_name": meta.get("experiment_name"),
                "stage": meta.get("stage"), "seed": meta.get("seed"), "commit": meta.get("commit"),
                "dirty": meta.get("dirty"), "patch": meta.get("patch"), "status": status,
                "wall_seconds": meta.get("wall_seconds"), "metrics": {}}
        with tracking._locked_append(REPO / "runs" / "registry.jsonl") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:  # noqa: BLE001 — the meta + error.txt already tell the story
        pass


def submit_and_wait(cfg: dict, argv: list[str], sc: dict, control: dict, guards, slot_id, allocate, bus_emit) -> int:
    """run.py's scheduler path: reserve the run dir (queued), submit job.sh, wait, report the job's result."""
    ad = adapter(sc)
    run_id, run_dir = allocate(REPO / "runs", cfg)
    minutes = (cfg.get("budget") or {}).get("max_minutes") or 60
    meta = {"run_id": run_id, "experiment_name": cfg.get("experiment_name"), "stage": cfg.get("stage"),
            "seed": cfg.get("seed"), "config_path": cfg.get("_config_path"), "status": "queued",
            "queued": time.strftime("%Y-%m-%dT%H:%M:%S"), "budget": {"max_minutes": minutes, "breached": False},
            "scheduler": {"kind": ad.kind, "job": None, "gate2": "checked" if str(cfg.get("stage")).upper() == "FULL" else "n/a"}}
    _write_meta(run_dir, meta)
    py = sys.executable
    inner = [py, str(REPO / "scripts" / "run.py"), *argv, "--in-job", "--run-dir", str(run_dir)]
    lines = ["#!/bin/bash", *ad.directives(run_id, run_dir, float(minutes)), "set -e", *ad.setup(),
             f"cd {shlex.quote(str(REPO))}", "export NEWTS_IN_JOB=1",
             " ".join(shlex.quote(a) for a in inner)]
    script = run_dir / "job.sh"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"[run] {run_id} -> {run_dir}", flush=True)
    try:
        job = ad.submit(script)
    except Exception as e:  # noqa: BLE001
        _finalize(run_dir, "failed", f"could not submit to {ad.kind}: {e}")
        print(f"[run] FAILED to submit — {e}", flush=True)
        return 1
    meta = _read_meta(run_dir)
    meta.setdefault("scheduler", {})["job"] = job
    _write_meta(run_dir, meta)
    print(f"[run] submitted to {ad.kind} as job {job} — waiting (queue time doesn't count against the budget)", flush=True)
    bus_emit(REPO, "run_queued", run_id=run_id, stage=cfg.get("stage"), status="queued",
             detail=f"{ad.kind} job {job}")

    stopping = {"sig": None}

    def _stop(signum, _frame):
        stopping["sig"] = signum
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass
    poll = float(os.environ.get("NEWTS_SCHED_POLL") or sc.get("poll_seconds") or 30)
    max_queue = float(sc.get("max_queue_hours") or 48) * 3600
    t0, last_touch, started = time.time(), 0.0, False
    hb = run_dir / "submitter.heartbeat"
    while True:
        hb.write_text(str(os.getpid()), encoding="utf-8")
        if time.time() - last_touch > 60:
            guards.touch_slot(control, slot_id)
            last_touch = time.time()
        if stopping["sig"] is not None:
            ad.cancel(job)
            _finalize(run_dir, "killed", f"stopped (signal {stopping['sig']}); {ad.kind} job {job} cancelled")
            print(f"[run] stopped — cancelled job {job}", flush=True)
            return 1
        meta = _read_meta(run_dir)
        if meta.get("status") in TERMINAL:
            break
        st = ad.state(job)
        if st == "running":
            started = True
        if st == "gone":
            time.sleep(min(poll, 5))           # the job may have JUST written its final meta
            meta = _read_meta(run_dir)
            if meta.get("status") in TERMINAL:
                break
            why = ad.reason(job)
            _finalize(run_dir, "failed", f"{ad.kind} job {job} ended without finishing the run ({why}) — "
                                         f"see {run_dir.name}/job-{job}.out")
            break
        if not started and time.time() - t0 > max_queue:
            ad.cancel(job)
            _finalize(run_dir, "failed", f"{ad.kind} job {job} never started within {max_queue / 3600:.0f} h — cancelled")
            break
        time.sleep(poll)
    meta = _read_meta(run_dir)
    status = meta.get("status") or "failed"
    print(f"[run] {status}: job {job}" + (f" — see {run_dir / 'error.txt'}" if status != "completed" else ""), flush=True)
    return EXIT.get(status, 1)
