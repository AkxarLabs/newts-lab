"""Zero-token run monitor: one line of status, no log dumps, no judgment calls.

    python scripts/status.py            # latest run
    python scripts/status.py <run_id>  [--log-interval 60]

This is the ONLY check an unattended loop makes while a run is in flight (see
/research-loop): it costs no reasoning about partial curves and keeps the agent
from babysitting. Liveness = meta status "running" + recent metrics.jsonl mtime
(stalled if silent for > 2x the expected log interval). stdlib only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "runs"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", help="defaults to the most recent run dir")
    parser.add_argument("--log-interval", type=float, default=60.0,
                        help="expected seconds between ctx.log() calls")
    args = parser.parse_args()

    if args.run_id:
        run_dir = RUNS / args.run_id
    else:
        dirs = sorted([d for d in RUNS.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime)
        if not dirs:
            print("status=none (no runs)")
            return 1
        run_dir = dirs[-1]

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
    state = "alive" if (age is None or age <= 2 * args.log_interval) else "stalled"
    print(f"{run_dir.name} status={state} · elapsed={elapsed:.0f}s/budget={budget_str}{last}")
    return 0 if state == "alive" else 3


if __name__ == "__main__":
    raise SystemExit(main())
