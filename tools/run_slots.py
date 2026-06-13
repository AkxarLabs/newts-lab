"""Cross-project compute slot ledger — coordination when several projects run at once.

Within one project, the experiment loop controls its own runs. The hub-level risk is
CROSS-project: two projects (or a loop plus an interactive session) each launching a
training run on the same GPU. Slots serialize that: a training campaign (one run.py
run, or one sweep) holds one slot; the cap is `compute.max_concurrent_runs` in
lab/config.yaml.

    uv run --with pyyaml python tools/run_slots.py acquire <project> <label>
    uv run --with pyyaml python tools/run_slots.py touch <slot-id>
    uv run --with pyyaml python tools/run_slots.py release <slot-id>
    uv run --with pyyaml python tools/run_slots.py status

State: one JSON file per active slot under lab/.slots/ (gitignored runtime state).
O_EXCL prevents identical-id collisions; the cap check is best-effort (a millisecond-wide
check-then-create race is closed by a post-create rank re-check). A slot's mtime is its
heartbeat: `touch` it on the monitoring cadence so a long-but-live campaign is not
mistaken for crashed. Slots whose mtime is older than `compute.stale_slot_minutes` are
presumed crashed and reclaimed on any invocation — set that threshold ABOVE your longest
single campaign if you don't touch. SMOKE runs don't need a slot.

Exit codes: acquire — 0 granted (slot id on stdout), 1 denied (holders listed);
touch — 0 ok, 1 unknown slot; release — 0 ok (also 0 if already reclaimed, with a
warning); status — always 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
SLOTS = HUB / "lab" / ".slots"


def config() -> dict:
    cfg = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8")) or {}
    return cfg.get("compute") or {}


def prune_stale(stale_minutes: float) -> list[str]:
    reclaimed = []
    if not SLOTS.exists():
        return reclaimed
    now = time.time()
    for f in SLOTS.glob("*.json"):
        if (now - f.stat().st_mtime) > stale_minutes * 60:
            reclaimed.append(f.stem)
            f.unlink(missing_ok=True)
    return reclaimed


def active() -> list[dict]:
    if not SLOTS.exists():
        return []
    out = []
    for f in sorted(SLOTS.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # a concurrently-writing/partial slot file — skip, not crash
        data["slot_id"] = f.stem
        out.append(data)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("acquire")
    p.add_argument("project"); p.add_argument("label")
    p = sub.add_parser("touch")
    p.add_argument("slot_id")
    p = sub.add_parser("release")
    p.add_argument("slot_id")
    sub.add_parser("status")
    args = parser.parse_args()

    cfg = config()
    max_runs = int(cfg.get("max_concurrent_runs", 1))
    stale_minutes = float(cfg.get("stale_slot_minutes", 360))
    SLOTS.mkdir(parents=True, exist_ok=True)
    reclaimed = prune_stale(stale_minutes)
    for slot in reclaimed:
        print(f"[slots] reclaimed stale slot: {slot}", file=sys.stderr)

    if args.cmd == "status":
        slots = active()
        print(f"{len(slots)}/{max_runs} slots in use")
        for s in slots:
            age = (time.time() - s["acquired"]) / 60
            print(f"- {s['slot_id']}  project={s['project']}  label={s['label']}  age={age:.0f}m")
        return 0

    if args.cmd == "acquire":
        if len(active()) >= max_runs:
            print(f"DENIED — {max_runs}/{max_runs} slots in use:")
            for s in active():
                print(f"- {s['slot_id']} ({s['project']}: {s['label']})")
            return 1
        raw = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.project}-{args.label}"
        slot_id = re.sub(r"[^A-Za-z0-9._-]", "_", raw)  # filesystem-safe on Windows too
        path = SLOTS / f"{slot_id}.json"
        try:
            with path.open("x", encoding="utf-8") as f:
                json.dump({"project": args.project, "label": args.label, "acquired": time.time()}, f)
        except FileExistsError:
            print("DENIED — slot id collision, retry")
            return 1
        # Close the check-then-create race: if a concurrent acquire pushed us over the cap,
        # the lexicographically-latest slot ids beyond max_runs yield (self-delete + DENIED).
        ids = sorted(s["slot_id"] for s in active())
        if len(ids) > max_runs and slot_id in ids[max_runs:]:
            path.unlink(missing_ok=True)
            print(f"DENIED — lost the {max_runs}-slot race, retry")
            return 1
        print(slot_id)
        return 0

    if args.cmd == "touch":
        path = SLOTS / f"{args.slot_id}.json"
        if not path.exists():
            print(f"unknown slot: {args.slot_id}")
            return 1
        os.utime(path, None)  # refresh mtime heartbeat so a live campaign isn't reclaimed
        return 0

    if args.cmd == "release":
        path = SLOTS / f"{args.slot_id}.json"
        if not path.exists():
            # Already reclaimed (stale-pruned or never existed): not an error for the
            # caller's write-back — the slot is gone either way.
            print(f"[slots] {args.slot_id} already released/reclaimed")
            return 0
        path.unlink(missing_ok=True)
        print(f"released {args.slot_id}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
