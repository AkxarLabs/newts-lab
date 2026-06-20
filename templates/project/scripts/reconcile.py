"""Loop/run reconciler — find and (optionally) clear stale state before resuming work.

    uv run --with pyyaml python scripts/reconcile.py            # report
    uv run --with pyyaml python scripts/reconcile.py --fix      # also clear a stale loop lock

Surfaces what a crashed or interrupted loop leaves behind, so /research-loop can start with one
command instead of a reasoning checklist:
  - dead/stalled runs   (meta.status=running but metrics have gone stale — the process is gone)
  - orphan runs         (a run dir that started but never wrote a runs/registry.jsonl line)
  - a stale loop lock   (.bus/.loop-active older than ~2× the monitor cadence)
Read-only by default; `--fix` only removes a stale loop lock (the one safe auto-action — finalizing
a dead run or recording an orphan is a judgment call left to you). Exit 0 = clean; 2 = stale state
found (cleared with --fix where safe, else reported).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="clear a stale loop lock (the only safe auto-fix)")
    args = ap.parse_args()

    ctl = _load_yaml(ROOT / "control.yaml")
    log_interval = float((ctl.get("monitoring") or {}).get("log_interval_seconds", 60))
    poll = float((ctl.get("loop") or {}).get("monitor_poll_seconds", 300))
    now = time.time()

    runs = ROOT / "runs"
    registered = set()
    reg = runs / "registry.jsonl"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8-sig").splitlines():
            try:
                registered.add(json.loads(line).get("run_id"))
            except Exception:
                continue

    dead, orphan = [], []
    if runs.exists():
        for d in sorted(runs.iterdir()):
            meta = d / "meta.json"
            if not (d.is_dir() and meta.exists()):
                continue
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            if m.get("status") != "running":
                continue
            rid = m.get("run_id", d.name)
            # Liveness anchor = the most-recently-touched file in the run dir. meta.json is written
            # ONCE at start, so anchoring on it falsely flags a healthy slow-/sparse-logging run as
            # dead; a live run touches SOMETHING (metrics, a checkpoint, a log) more recently.
            try:
                anchor_mtime = max((f.stat().st_mtime for f in d.rglob("*") if f.is_file()),
                                   default=meta.stat().st_mtime)
            except OSError:
                anchor_mtime = meta.stat().st_mtime
            age = now - anchor_mtime
            if age > 2 * log_interval:
                dead.append((rid, round(age)))
            if rid not in registered:
                orphan.append(rid)

    loop_lock = ROOT / ".bus" / ".loop-active"
    lock_age = (now - loop_lock.stat().st_mtime) if loop_lock.exists() else None
    stale_lock = lock_age is not None and lock_age > max(2 * poll, 1800)

    found = bool(dead or orphan or stale_lock)
    print(f"## Reconcile — {ROOT.name}\n")
    if dead:
        print("**Dead/stalled runs** (status=running, metrics stale — the run process is gone):")
        for rid, age in dead:
            print(f"- {rid} (stale {age}s) — finalize its ledger entry or delete the dir; do not double-count it")
    if orphan:
        print("**Orphan runs** (started, never wrote a registry line):")
        for rid in orphan:
            print(f"- {rid} — record the attempt in EXPERIMENT_LOG.md + registry, or delete the dir")
    if stale_lock:
        if args.fix:
            loop_lock.unlink()
            print(f"**Stale loop lock** removed (.bus/.loop-active was {round(lock_age)}s old).")
        else:
            print(f"**Stale loop lock**: .bus/.loop-active is {round(lock_age)}s old — the loop likely died. Re-run with --fix to clear it.")
    if not found:
        print("clean — no dead runs, orphans, or stale loop lock. Safe to resume.")
    print("\nNote: cross-project compute slots self-reclaim via the hub's run_slots.py; release yours "
          "when a campaign's ledger entry is written.")
    return 2 if found else 0


if __name__ == "__main__":
    sys.exit(main())
