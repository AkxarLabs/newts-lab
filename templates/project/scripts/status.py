"""Zero-token run monitor: one line of status, no log dumps, no judgment calls.

    python scripts/status.py                         # latest run, one line
    python scripts/status.py <run_id> [--log-interval 60]
    python scripts/status.py [<run_id>] --watch [--poll 300]   # block until terminal/stalled

This is the ONLY check an unattended loop makes while a run is in flight (see
/research-loop): it costs no reasoning about partial curves and keeps the agent
from babysitting. Liveness = meta status "running" + recent metrics.jsonl mtime
(stalled if silent for > 2x the expected log interval — pass --log-interval matching
the experiment's logging cadence so a healthy sparse-logging run is not killed).

--watch turns the single probe into a blocking wait primitive: it polls every --poll
seconds and returns when the run reaches a terminal status (exit 0) or reads `stalled`
twice in a row (exit 3). With no run_id it follows the most-recent run dir, so it also
covers sweeps (whose individual run_ids aren't known until each job starts). stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUNS = Path(__file__).resolve().parents[1] / "runs"


def _resolve_run_dir(run_id: str | None) -> Path | None:
    if run_id:
        return RUNS / run_id
    if not RUNS.exists():
        return None
    dirs = sorted([d for d in RUNS.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime)
    return dirs[-1] if dirs else None


def probe(run_id: str | None, log_interval: float) -> int:
    """One status line. Returns 0 terminal/alive, 1 no-run/dead, 3 stalled."""
    run_dir = _resolve_run_dir(run_id)
    if run_dir is None:
        print("status=none (no runs)")
        return 1

    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        print(f"{run_dir.name} status=dead (no meta.json)")
        return 1
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    budget = meta.get("budget") or {}
    budget_str = f"{budget['max_minutes']}m" if budget.get("max_minutes") else "none"

    if meta.get("status") != "running":
        metrics_path = run_dir / "metrics.json"
        final = ""
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            pairs = [f"{k}={v:.6g}" for k, v in metrics.items() if isinstance(v, (int, float))]
            final = " · " + " ".join(pairs[:3]) if pairs else ""
        print(f"{run_dir.name} status={meta['status']} · wall={meta.get('wall_seconds')}s"
              f" · budget={budget_str}{final}")
        return 0

    # Running: elapsed, last streamed metric, staleness check.
    stream = run_dir / "metrics.jsonl"
    elapsed = time.time() - meta_path.stat().st_ctime
    last, age = "", None
    if stream.exists() and stream.stat().st_size:
        age = time.time() - stream.stat().st_mtime
        tail = stream.read_text(encoding="utf-8").strip().splitlines()[-1]
        record = json.loads(tail)
        pairs = [f"{k}={v:.6g}" for k, v in record.items()
                 if isinstance(v, (int, float)) and k not in ("t", "step")]
        last = " · last: " + " ".join(pairs[:3]) if pairs else ""
    state = "alive" if (age is None or age <= 2 * log_interval) else "stalled"
    print(f"{run_dir.name} status={state} · elapsed={elapsed:.0f}s/budget={budget_str}{last}")
    return 0 if state == "alive" else 3


def watch(run_id: str | None, log_interval: float, poll: float) -> int:
    """Block until the run reaches a terminal status (0) or stalls twice in a row (3)."""
    consecutive_stalls = 0
    while True:
        rc = probe(run_id, log_interval)
        if rc == 1:
            return 1
        # rc 0 from a non-running meta status = terminal; from a running+alive = keep going.
        run_dir = _resolve_run_dir(run_id)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")) if run_dir else {}
        if meta.get("status") not in (None, "running"):
            return 0
        consecutive_stalls = consecutive_stalls + 1 if rc == 3 else 0
        if consecutive_stalls >= 2:
            print(f"{run_dir.name if run_dir else '?'} status=stalled x2 — treat as failed")
            return 3
        time.sleep(poll)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", help="defaults to the most recent run dir")
    parser.add_argument("--log-interval", type=float, default=60.0,
                        help="expected seconds between ctx.log() calls")
    parser.add_argument("--watch", action="store_true",
                        help="block, polling until terminal status or two consecutive stalls")
    parser.add_argument("--poll", type=float, default=300.0,
                        help="--watch poll interval in seconds")
    args = parser.parse_args()

    if args.watch:
        return watch(args.run_id, args.log_interval, args.poll)
    return probe(args.run_id, args.log_interval)


if __name__ == "__main__":
    raise SystemExit(main())
