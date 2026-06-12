"""Single entry point for every experiment run.

    uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml [--seed N] [-o key=value ...]

Loads config, seeds, creates the run artifact dir, executes, records — success or failure.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

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
    print(f"[run] {ctx.run_id} -> {ctx.run_dir}")

    try:
        final_metrics = run_experiment(cfg, ctx)
    except Exception:
        ctx.fail(traceback.format_exc())
        print(f"[run] FAILED — see {ctx.run_dir / 'error.txt'}")
        return 1

    ctx.finish(final_metrics)
    print(f"[run] completed: {final_metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
