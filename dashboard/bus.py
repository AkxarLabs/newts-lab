"""The PI's notes and commands to agents: directives on a lab's or a project's bus (d-NNN ids,
withdrawals).
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


# Structured command actions the dashboard may issue (the agent executes them in-protocol).
COMMAND_ACTIONS = {
    "start_loop", "stop_loop", "set_mode", "run_smoke", "request_run",
    "prioritize", "park", "kill", "analyze", "ideate",
}


# ── bus writers (directives, commands) ──────────────────────────────────────
# ThreadingHTTPServer serves each POST on its own thread; serialize id-compute + append so two
# concurrent directives can't read the same max id and write a duplicate d-NNN (which would mis-route
# later acks/withdraws onto the wrong directive).
_BUS_LOCK = threading.Lock()


def _next_id(directives_path: Path) -> str:
    # max(existing d-NNN) + 1 — NOT a line count: a withdrawn/edited/missing row must never
    # cause a reissued id (which would collide and mis-route acks/withdraws onto a live directive).
    hi = 0
    if directives_path.exists():
        for line in directives_path.read_text(encoding="utf-8-sig").splitlines():
            for m in re.findall(r'"id"\s*:\s*"d-(\d+)"', line):
                hi = max(hi, int(m))
    return f"d-{hi + 1:03d}"


def _bus_dir(target: str) -> Path:
    if target in ("hub", "", None):
        return ctx.LAB / ".bus"
    pdir = ctx.pdir(target)
    return (pdir / ".bus") if pdir else (ctx.LAB / ".bus")


def _append(target: str, rec: dict, bus: Path | None = None) -> dict:
    if bus is None:
        # deriving the destination FROM the target: it must be a clean slug (it becomes a path).
        if target in ("hub", "", None):
            target, bus = "hub", ctx.LAB / ".bus"
        elif ctx.safe_id(target) is None:
            raise ValueError(f"invalid target '{target}' — a bare idea/project slug or 'hub'")
        else:
            bus = _bus_dir(target)
    # else: the caller already resolved the bus (e.g. a withdraw routed to the file holding the
    # ref) — the target is only a label in the record here, so a legacy non-slug target is fine.
    target = target if (isinstance(target, str) and target) else "hub"
    bus.mkdir(parents=True, exist_ok=True)
    path = bus / "directives.jsonl"
    with _BUS_LOCK, _file_lock(bus / ".directives.lock"):
        rec.setdefault("id", _next_id(path))
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        rec.setdefault("from", "PI via dashboard")
        # record the intended target IN the line: a directive/command aimed at a pre-spawn idea (no
        # project dir yet) falls back to the hub bus, and without this the agent inbox can't tell what
        # it was aimed at (e.g. which of two proposals a gate1_approved refers to).
        rec.setdefault("target", target)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    return rec


class _file_lock:
    """Cross-process: two dashboards (or a dashboard + a CLI) on one lab never mint the same d-NNN."""

    def __init__(self, path: Path):
        self.path, self.lock = path, None

    def __enter__(self):
        if executor is None:
            return self
        self.lock = executor.procs.RunLock(self.path)
        deadline = time.time() + 5.0
        while not self.lock.try_acquire():
            if time.time() > deadline:
                self.lock = None      # best effort: never wedge a PI's click on a stuck lock
                break
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        if self.lock is not None:
            self.lock.release()


def append_directive(target: str, text: str) -> dict:
    return _append(target, {"text": text})


def append_command(target: str, action: str, args: dict, text: str) -> dict:
    return _append(target, {"kind": "command", "action": action, "args": args or {},
                            "text": text or action.replace("_", " ")})


def _find_ref_bus(target: str, ref: str, ts: str | None = None) -> Path | None:
    """The bus dir whose directives.jsonl actually CONTAINS the directive being withdrawn.
    A directive aimed at a pre-spawn idea was recorded on the hub bus (the _append fallback);
    once the project exists, the same target resolves to the project bus, so routing the
    withdraw by target alone would strand the marker in a file the record isn't in — leaving
    the directive pending forever in both the agent inbox and the ledger.

    Matches on id AND ts: d-NNN ids are per-file counters (_next_id), so the hub and a project
    bus can independently mint the same d-003 — matching id alone could withdraw the wrong one.
    The frontend sends the displayed record's ts; when present it disambiguates exactly."""
    seen: list[Path] = []
    for bus in (_bus_dir(target), ctx.LAB / ".bus"):
        if bus in seen:
            continue
        seen.append(bus)
        path = bus / "directives.jsonl"
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("id") == ref and (not ts or rec.get("ts") == ts):
                    return bus
        except OSError:
            continue
    return None   # not found (e.g. a synthesized d?xxxx id) — caller falls back to target routing


def append_withdraw(target: str, ref: str, ts: str | None = None) -> None:
    ref = str(ref or "").strip()[:120]
    bus = _find_ref_bus(target, ref, ts)
    if bus is None and ctx.safe_id(target) is None and target not in ("hub", "", None):
        bus = ctx.LAB / ".bus"   # unknown ref + a non-slug legacy target -> safe hub fallback, never a raise
    _append(target, {"kind": "withdraw", "ref": ref}, bus=bus)
