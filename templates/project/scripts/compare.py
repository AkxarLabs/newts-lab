"""Query runs/registry.jsonl — the committed run record. stdlib only.

    python scripts/compare.py list [--last 20]
    python scripts/compare.py best --metric toy_abs_error --minimize [--experiment exp-004] [--stage PILOT]
    python scripts/compare.py seeds --metric toy_abs_error [exp-004 ...]
    python scripts/compare.py experiments exp-003 exp-004 --metric toy_abs_error

Output is markdown, pasteable into EXPERIMENT_LOG.md / analysis files. Non-completed
runs are excluded everywhere except `list`.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REGISTRY = Path(__file__).resolve().parents[1] / "runs" / "registry.jsonl"


def load(completed_only: bool = True) -> list[dict]:
    if not REGISTRY.exists():
        return []
    rows = []
    for l in REGISTRY.read_text(encoding="utf-8-sig").strip().splitlines():
        if not l.strip():
            continue
        try:
            rows.append(json.loads(l))
        except json.JSONDecodeError:
            print(f"[compare] skipping unreadable registry line: {l[:80]}", file=sys.stderr)
    return [r for r in rows if r.get("status") == "completed"] if completed_only else rows


def metric_of(row: dict, name: str):
    value = (row.get("metrics") or {}).get(name)
    return value if isinstance(value, (int, float)) else None


def agg(rows: list[dict], name: str) -> str:
    vals = [v for r in rows if (v := metric_of(r, name)) is not None]
    if not vals:
        return "—"
    if len(vals) == 1:
        return f"{vals[0]:.6g}"
    return f"{statistics.mean(vals):.6g} ± {statistics.stdev(vals):.2g} (n={len(vals)})"


def cmd_list(args) -> None:
    rows = load(completed_only=False)[-args.last:]
    print("| run_id | experiment | stage | seed | status | wall_s |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r.get('run_id', '?')} | {r.get('experiment_name', '?')} | {r.get('stage')} | {r.get('seed')} "
              f"| {r.get('status', '?')} | {r.get('wall_seconds')} |")


def cmd_best(args) -> None:
    rows = load()
    if args.experiment:
        rows = [r for r in rows if r.get("experiment_name") == args.experiment]
    if args.stage:
        rows = [r for r in rows if r.get("stage") == args.stage]
    scored = [(metric_of(r, args.metric), r) for r in rows]
    scored = [(v, r) for v, r in scored if v is not None]
    if not scored:
        print(f"no completed runs with metric '{args.metric}'")
        return
    value, row = (min if args.minimize else max)(scored, key=lambda x: x[0])
    print(f"**Best {args.metric}** ({'min' if args.minimize else 'max'}): `{value:.6g}` — "
          f"run `{row['run_id']}` (experiment {row['experiment_name']}, seed {row.get('seed')}, "
          f"commit {row.get('commit')})")


def cmd_seeds(args) -> None:
    rows = load()
    names = args.experiments or sorted({n for r in rows if (n := r.get("experiment_name"))})
    print(f"| experiment | {args.metric} (mean ± std) | seeds |")
    print("|---|---|---|")
    for name in names:
        group = [r for r in rows if r.get("experiment_name") == name]
        seeds = sorted({r.get("seed") for r in group})
        print(f"| {name} | {agg(group, args.metric)} | {seeds} |")


def cmd_experiments(args) -> None:
    rows = load()
    groups = {name: [r for r in rows if r.get("experiment_name") == name] for name in args.experiments}
    baseline_vals = [v for r in groups[args.experiments[0]] if (v := metric_of(r, args.metric)) is not None]
    baseline = statistics.mean(baseline_vals) if baseline_vals else None
    print(f"| experiment | {args.metric} | delta vs {args.experiments[0]} | n |")
    print("|---|---|---|---|")
    for name, group in groups.items():
        vals = [v for r in group if (v := metric_of(r, args.metric)) is not None]
        mean = statistics.mean(vals) if vals else None
        delta = "—" if (mean is None or baseline is None or name == args.experiments[0]) \
            else f"{mean - baseline:+.6g}"
        print(f"| {name} | {agg(group, args.metric)} | {delta} | {len(vals)} |")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list"); p.add_argument("--last", type=int, default=20); p.set_defaults(fn=cmd_list)

    p = sub.add_parser("best")
    p.add_argument("--metric", required=True); p.add_argument("--minimize", action="store_true")
    p.add_argument("--experiment"); p.add_argument("--stage"); p.set_defaults(fn=cmd_best)

    p = sub.add_parser("seeds")
    p.add_argument("experiments", nargs="*"); p.add_argument("--metric", required=True)
    p.set_defaults(fn=cmd_seeds)

    p = sub.add_parser("experiments")
    p.add_argument("experiments", nargs="+"); p.add_argument("--metric", required=True)
    p.set_defaults(fn=cmd_experiments)

    args = parser.parse_args()
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
