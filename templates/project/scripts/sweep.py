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
import re
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from project_pkg.config import load_config

RUN_ID_RE = re.compile(r"^\[run\] (\S+) ->", re.MULTILINE)


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

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=REPO)
    try:
        out, _ = proc.communicate(timeout=timeout)
        status = {0: "completed", 2: "timeout"}.get(proc.returncode, "failed")
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        status = "killed-by-sweep"

    match = RUN_ID_RE.search(out or "")
    run_id = match.group(1) if match else None
    print(f"[sweep] {label} seed={seed} -> {status} ({run_id})", flush=True)
    return {"label": label, "seed": seed, "status": status, "run_id": run_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--seeds", default="0,1,2", help="comma-separated seeds")
    parser.add_argument("--grid", action="append", default=[], help="dotted key=v1,v2 (repeatable)")
    parser.add_argument("--parallel", type=int, default=1, help="concurrent jobs")
    parser.add_argument("--grace", type=float, default=60.0, help="seconds beyond budget before hard kill")
    args = parser.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    combos = parse_grid(args.grid)
    cfg = load_config(args.config)
    max_minutes = (cfg.get("budget") or {}).get("max_minutes") or 60
    timeout = float(max_minutes) * 60 + args.grace

    jobs = [(args.config, seed, combo, timeout) for combo in combos for seed in seeds]
    print(f"[sweep] {len(jobs)} jobs ({len(combos)} combos x {len(seeds)} seeds), "
          f"timeout {timeout:.0f}s/job, parallel={args.parallel}", flush=True)

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
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
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
