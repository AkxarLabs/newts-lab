"""Multi-seed / grid sweep launcher with hard per-run timeout enforcement.

    uv run python scripts/sweep.py --config configs/experiments/exp-004.yaml --seeds 0,1,2
    uv run python scripts/sweep.py --config ... --seeds 0,1,2 --grid toy.n_samples=50,200 --parallel 2

Each (grid-combo x seed) job is one scripts/run.py subprocess; run.py appends its own
registry row (sweep adds nothing — one row per run, always). The subprocess timeout
(config budget.max_minutes + grace) is the outer safety net behind run.py's watchdog.
Ends with a mean +/- std markdown table per grid combo, suitable for pasting into
EXPERIMENT_LOG.md or an analysis file.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import signal
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for the sibling lab_bus
sys.path.insert(0, str(REPO / "src"))


def _resolve_pkg() -> str:
    """Match scripts/run.py: the package under src/ to import. `project_pkg` for spawned
    projects; an adopted repo's own name via control.yaml `package:` (or $PROJECT_PKG)."""
    src = REPO / "src"
    override = os.environ.get("PROJECT_PKG")
    if override:
        return override
    ctl = REPO / "control.yaml"
    if ctl.exists():
        try:
            import yaml
            name = (yaml.safe_load(ctl.read_text(encoding="utf-8-sig")) or {}).get("package")
            if name:
                return str(name)
        except Exception:  # noqa: BLE001 — best-effort; fall through to autodetect
            pass
    if (src / "project_pkg" / "__init__.py").exists():
        return "project_pkg"
    pkgs = [p.name for p in src.iterdir() if (p / "__init__.py").exists()] if src.exists() else []
    if len(pkgs) == 1:
        return pkgs[0]
    raise SystemExit("[sweep] cannot resolve the project package under src/ — set `package:` "
                     "in control.yaml (or $PROJECT_PKG)")


import importlib  # noqa: E402

load_config = importlib.import_module(f"{_resolve_pkg()}.config").load_config
_locked_append = importlib.import_module(f"{_resolve_pkg()}.tracking")._locked_append

try:
    import lab_bus  # dashboard event bus (optional, best-effort)
except Exception:  # noqa: BLE001
    lab_bus = None

RUN_ID_RE = re.compile(r"^\[run\] (\S+) ->", re.MULTILINE)
_NEW_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
    else {"start_new_session": True}


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the run.py process AND its children (a SIGKILL/TerminateProcess on the parent
    leaves grandchild training procs — e.g. torchrun — running and the GPU busy)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        proc.kill()


def _finalize_orphan(run_id: str | None, status: str) -> None:
    """A killed run.py never ran ctx.finish, so its meta.json is stuck 'running' with no
    registry row. Reconcile the mechanical record so it matches reality (append-only)."""
    if not run_id:
        return
    run_dir = REPO / "runs" / run_id
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return
    if meta.get("status") != "running":
        return  # it finalized after all — leave it
    meta["status"] = status
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    row = {"run_id": run_id, "experiment_name": meta.get("experiment_name"),
           "stage": meta.get("stage"), "seed": meta.get("seed"),
           "commit": meta.get("commit"), "dirty": meta.get("dirty"),
           "status": status, "wall_seconds": None, "metrics": {}}
    # Use the SAME sidecar lock + fsync as RunContext.finish, so a timeout-orphan write can't
    # interleave with a sibling job finalizing at the same instant during a --parallel sweep.
    with _locked_append(REPO / "runs" / "registry.jsonl") as f:
        f.write(json.dumps(row) + "\n")


def parse_grid(items: list[str]) -> list[list[tuple[str, str]]]:
    """["a.b=1,2", "c=x,y"] -> cartesian product as lists of (key, value) pairs."""
    axes = []
    for item in items:
        key, _, raw = item.partition("=")
        axes.append([(key.strip(), v.strip()) for v in raw.split(",")])
    return [list(combo) for combo in itertools.product(*axes)] if axes else [[]]


def run_job(config: str, seed: int, combo: list[tuple[str, str]], timeout: float) -> dict:
    cmd = [sys.executable, str(REPO / "scripts" / "run.py"), "--config", config, "--seed", str(seed)]
    for key, value in combo:
        cmd += ["-o", f"{key}={value}"]
    label = ", ".join(f"{k}={v}" for k, v in combo) or "(base)"

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", cwd=REPO,
                                **_NEW_GROUP)
        try:
            out, _ = proc.communicate(timeout=timeout)
            status = {0: "completed", 2: "timeout"}.get(proc.returncode, "failed")
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            try:
                out, _ = proc.communicate(timeout=30)  # bounded drain; a surviving child
            except subprocess.TimeoutExpired:           # holding the pipe can't hang us
                out = ""
            status = "killed-by-sweep"
    except Exception as e:  # one bad job must not abort the pool (pool.map propagates raises)
        print(f"[sweep] {label} seed={seed} -> sweep-error: {e}", flush=True)
        return {"label": label, "seed": seed, "status": "sweep-error", "run_id": None}

    match = RUN_ID_RE.search(out or "")
    run_id = match.group(1) if match else None
    if status in ("timeout", "killed-by-sweep"):
        _finalize_orphan(run_id, "timeout" if status == "timeout" else "killed")
    print(f"[sweep] {label} seed={seed} -> {status} ({run_id})", flush=True)
    return {"label": label, "seed": seed, "status": status, "run_id": run_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seeds", default=None,
                        help="comma-separated seeds (default: control.yaml seeds.list, else 0,1,2)")
    parser.add_argument("--grid", action="append", default=[], help="dotted key=v1,v2 (repeatable)")
    parser.add_argument("--parallel", type=int, default=None,
                        help="concurrent jobs (default: control.yaml parallelism.sweep_parallel, else 1)")
    parser.add_argument("--grace", type=float, default=60.0, help="seconds beyond budget before hard kill")
    args = parser.parse_args()

    combos = parse_grid(args.grid)
    cfg = load_config(args.config)
    # Defaults come from the merged config so a PI editing control.yaml actually takes effect.
    if args.seeds is not None:
        seeds = [int(s) for s in args.seeds.split(",")]
    else:
        seeds = [int(s) for s in ((cfg.get("seeds") or {}).get("list") or [0, 1, 2])]
    parallel = args.parallel if args.parallel is not None \
        else int((cfg.get("parallelism") or {}).get("sweep_parallel") or 1)
    max_minutes = (cfg.get("budget") or {}).get("max_minutes") or 60
    timeout = float(max_minutes) * 60 + args.grace

    jobs = [(args.config, seed, combo, timeout) for combo in combos for seed in seeds]
    print(f"[sweep] {len(jobs)} jobs ({len(combos)} combos x {len(seeds)} seeds), "
          f"timeout {timeout:.0f}s/job, parallel={parallel}", flush=True)
    if lab_bus:
        lab_bus.emit("sweep_started", detail=cfg.get("experiment_name"),
                     data={"jobs": len(jobs), "combos": len(combos), "seeds": len(seeds)})

    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        results = list(pool.map(lambda j: run_job(*j), jobs))

    # Aggregate completed runs per combo: mean +/- std for every numeric final metric.
    print(f"\n## Sweep summary — {cfg.get('experiment_name')} ({len(seeds)} seeds)\n")
    by_label: dict[str, list[dict]] = {}
    for r in results:
        if r["status"] == "completed" and r["run_id"]:
            metrics_path = REPO / "runs" / r["run_id"] / "metrics.json"
            if metrics_path.exists():
                by_label.setdefault(r["label"], []).append(
                    json.loads(metrics_path.read_text(encoding="utf-8"))
                )

    metric_names = sorted({k for runs in by_label.values() for m in runs for k, v in m.items()
                           if isinstance(v, (int, float))})
    header = "| combo | n | " + " | ".join(metric_names) + " |"
    print(header)
    print("|" + "---|" * (len(metric_names) + 2))
    for label, runs in by_label.items():
        cells = []
        for name in metric_names:
            vals = [m[name] for m in runs if isinstance(m.get(name), (int, float))]
            if not vals:
                cells.append("—")
            elif len(vals) == 1:
                cells.append(f"{vals[0]:.6g}")
            else:
                cells.append(f"{statistics.mean(vals):.6g} ± {statistics.stdev(vals):.2g}")
        print(f"| {label} | {len(runs)} | " + " | ".join(cells) + " |")

    failures = [r for r in results if r["status"] != "completed"]
    if failures:
        print(f"\n{len(failures)} job(s) did not complete:")
        for r in failures:
            print(f"- {r['label']} seed={r['seed']}: {r['status']} ({r['run_id']})")
    if lab_bus:
        lab_bus.emit("sweep_finished", detail=cfg.get("experiment_name"),
                     status="failed" if failures else "completed",
                     data={"completed": len(results) - len(failures), "failed": len(failures)})
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
