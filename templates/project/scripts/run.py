"""Single entry point for every experiment run.

    uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml [--seed N] [-o key=value ...]

Loads config, seeds, creates the run artifact dir, executes, records — success or failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from project_pkg.config import load_config
from project_pkg.experiment import run as run_experiment
from project_pkg.seeding import set_seed
from project_pkg.tracking import RunContext


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="experiment yaml under configs/experiments/")
    parser.add_argument("--seed", type=int, default=None, help="override config seed")
    parser.add_argument("-o", "--override", action="append", default=[], help="dotted override, e.g. toy.n_samples=200")
    args = parser.parse_args()

    overrides = list(args.override)
    if args.seed is not None:
        overrides.append(f"seed={args.seed}")

    cfg = load_config(args.config, overrides)
    set_seed(int(cfg.get("seed", 0)))
    ctx = RunContext(cfg)
    print(f"[run] {ctx.run_id} -> {ctx.run_dir}", flush=True)

    # Budget watchdog: budget.max_minutes is ENFORCED, not advisory. Daemon thread +
    # Event (works on Windows; no SIGALRM). On breach: record timeout in the run
    # artifacts and registry, then hard-exit 2 — arbitrary experiment code cannot be
    # stopped gracefully in-process. NOTE: os._exit kills only THIS process; if your
    # experiment code spawns subprocesses (torchrun, an external trainer), launch them in
    # a killable process group so the watchdog/your harness can reap them — otherwise they
    # outlive the breach. sweep.py launches run.py in its own process group and kills the
    # whole tree on timeout, so sweep-driven runs are covered; a bare backgrounded run.py
    # is not.
    done = threading.Event()
    max_minutes = (cfg.get("budget") or {}).get("max_minutes")
    if max_minutes:

        def _watchdog() -> None:
            if not done.wait(timeout=float(max_minutes) * 60):
                ctx.breach_budget()
                print(f"[run] TIMEOUT — budget.max_minutes={max_minutes} breached", flush=True)
                os._exit(2)

        threading.Thread(target=_watchdog, daemon=True).start()

    try:
        final_metrics = run_experiment(cfg, ctx)
    except Exception:
        done.set()
        ctx.fail(traceback.format_exc())
        print(f"[run] FAILED — see {ctx.run_dir / 'error.txt'}")
        return 1

    done.set()
    ctx.finish(final_metrics)
    print(f"[run] completed: {final_metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
