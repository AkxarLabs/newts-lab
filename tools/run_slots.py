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
import contextlib
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))  # for the sibling lab_bus
try:
    import lab_bus  # hub event bus (optional, best-effort)
except Exception:  # noqa: BLE001
    lab_bus = None

HUB = Path(__file__).resolve().parents[1]
SLOTS = HUB / "lab" / ".slots"


def _bus(kind: str, **data) -> None:
    if lab_bus:
        lab_bus.emit(kind, data=data or None)


def config() -> dict:
    try:
        cfg = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}   # no/broken config (fresh checkout) -> documented defaults apply
    return cfg.get("compute") or {}


@contextlib.contextmanager
def _acquire_lock(timeout: float = 30.0):
    """Serialize the cap-check-and-create so two near-simultaneous acquires can't BOTH pass the cap.
    (A post-create rank re-check can't guarantee this — a racer that re-checks before a competitor's
    file lands wrongly survives.) A crashed holder's lock (>2 min old) is reclaimed."""
    SLOTS.mkdir(parents=True, exist_ok=True)
    lock = SLOTS / ".acquire.lock"
    deadline = time.time() + timeout
    fd = None
    while fd is None:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            with contextlib.suppress(OSError):
                if time.time() - lock.stat().st_mtime > 120:
                    lock.unlink(); continue
            if time.time() > deadline:
                raise TimeoutError("slot ledger busy")
            time.sleep(0.05)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


def prune_stale(stale_minutes: float) -> list[str]:
    reclaimed = []
    if not SLOTS.exists():
        return reclaimed
    now = time.time()
    for f in SLOTS.glob("*.json"):
        try:
            stale = (now - f.stat().st_mtime) > stale_minutes * 60
        except OSError:
            continue
        if stale:
            # A locked/held file (Windows) must never crash the ledger for every project — skip it.
            try:
                f.unlink()
                reclaimed.append(f.stem)
            except OSError:
                continue
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
        _bus("slot_reclaimed", slot_id=slot)

    if args.cmd == "status":
        slots = active()
        print(f"{len(slots)}/{max_runs} slots in use")
        for s in slots:
            acq = s.get("acquired")
            age = f"{(time.time() - acq) / 60:.0f}m" if isinstance(acq, (int, float)) else "?"
            print(f"- {s['slot_id']}  project={s.get('project', '?')}  label={s.get('label', '?')}  age={age}")
        return 0

    if args.cmd == "acquire":
        # The whole cap-check + create runs under one lock so two acquires can't both pass the cap,
        # and the slot file is published atomically so a concurrent reader never sees it half-written.
        try:
            with _acquire_lock():
                current = active()
                if len(current) >= max_runs:
                    print(f"DENIED — {max_runs}/{max_runs} slots in use:")
                    for s in current:
                        print(f"- {s['slot_id']} ({s.get('project', '?')}: {s.get('label', '?')})")
                    _bus("slot_denied", project=args.project, label=args.label)
                    return 1
                raw = f"{time.strftime('%Y%m%d-%H%M%S')}-{args.project}-{args.label}"
                slot_id = re.sub(r"[^A-Za-z0-9._-]", "_", raw)  # filesystem-safe on Windows too
                path = SLOTS / f"{slot_id}.json"
                if path.exists():
                    print("DENIED — slot id collision, retry")
                    return 1
                tmp = SLOTS / f"{slot_id}.json.tmp"
                tmp.write_text(json.dumps({"project": args.project, "label": args.label,
                                           "acquired": time.time()}), encoding="utf-8")
                tmp.replace(path)   # atomic publish
        except TimeoutError:
            print("DENIED — slot ledger busy, retry")
            return 1
        print(slot_id)
        _bus("slot_acquired", slot_id=slot_id, project=args.project, label=args.label)
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
        _bus("slot_released", slot_id=args.slot_id)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
