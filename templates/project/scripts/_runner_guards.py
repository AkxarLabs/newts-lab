"""Runner-boundary guards — mechanical enforcement of Gate 2 (hard rule 2) and compute slots
(hard rule 13), called by scripts/run.py and scripts/sweep.py so a FULL run cannot bypass the
signed Gate-2 envelope and a PILOT/FULL campaign cannot bypass the cross-project compute-slot
ledger, EVEN when the runner is invoked directly (not through a lab skill).

The skills still preflight and diagnose with the hub guard; this makes the runner itself the hard
stop. Stdlib-only + subprocess to the hub tools (resolved via control.yaml `hub_path`), so these
functions import and unit-test without the project package. `runner=` is injected in tests.

Environment handshakes (set by sweep.py on its child run.py processes):
  AUTOSCIENTIST_GATE2_OK=1   the parent sweep already cleared Gate 2 for the whole campaign.
  AUTOSCIENTIST_SLOT_HELD=1  the parent sweep holds the one campaign compute slot.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _hub(control: dict) -> str:
    return str((control or {}).get("hub_path") or "").strip()


def _slug(control: dict) -> str:
    return str((control or {}).get("project") or "").strip()


def _guard_cmd(hub: str) -> list[str]:
    return [sys.executable, str(Path(hub) / "tools" / "guard.py")]


def _slots_cmd(hub: str) -> list[str]:
    return [sys.executable, str(Path(hub) / "tools" / "run_slots.py")]


def _echo(res) -> None:
    try:
        if getattr(res, "stdout", None):
            sys.stdout.write(res.stdout)
        if getattr(res, "stderr", None):
            sys.stderr.write(res.stderr)
    except Exception:  # noqa: BLE001 — echoing guard output must never mask the real verdict
        pass


def stage_of(cfg: dict) -> str:
    return str((cfg or {}).get("stage") or "SMOKE").upper()


# ── Gate 2 (hard rule 2) ──────────────────────────────────────────────────────

def gate2_preflight(control: dict, config_path, cfg: dict, *, runner=subprocess.run) -> None:
    """Block a direct FULL run that doesn't fit the signed Gate-2 envelope. No-op for SMOKE/PILOT, or
    when a parent sweep already cleared it (AUTOSCIENTIST_GATE2_OK). Raises SystemExit on a block —
    called BEFORE any run dir is created."""
    if stage_of(cfg) != "FULL" or os.environ.get("AUTOSCIENTIST_GATE2_OK"):
        return
    hub, slug = _hub(control), _slug(control)
    if not hub or not Path(hub).exists():
        raise SystemExit("[run] BLOCKED: FULL run but control.yaml hub_path is missing/unreachable — "
                         "cannot verify the Gate-2 envelope (hard rule 2). Run via the hub or set hub_path.")
    minutes = (cfg.get("budget") or {}).get("max_minutes")
    cmd = _guard_cmd(hub) + ["full-run", slug, "--config", str(config_path), "--planned-runs", "1"]
    if minutes:
        cmd += ["--planned-minutes", str(minutes)]
    res = runner(cmd, capture_output=True, text=True)
    _echo(res)
    if res.returncode != 0:
        raise SystemExit("[run] BLOCKED: FULL run is outside the signed Gate-2 envelope. See guard output above.")


def reserve_full_sweep(control: dict, config_path, planned_runs: int, planned_minutes, label,
                       *, runner=subprocess.run) -> str | None:
    """Gate the whole FULL sweep once and reserve its capacity so a concurrent sweep can't double-book.
    Returns a reservation id (or None if the guard reserved nothing). Raises SystemExit on a block."""
    hub, slug = _hub(control), _slug(control)
    if not hub or not Path(hub).exists():
        raise SystemExit("[sweep] BLOCKED: FULL sweep but control.yaml hub_path is missing — cannot verify Gate 2.")
    cmd = _guard_cmd(hub) + ["full-run", slug, "--config", str(config_path),
                             "--planned-runs", str(planned_runs), "--reserve", "--reservation-label", str(label)]
    if planned_minutes:
        cmd += ["--planned-minutes", str(planned_minutes)]
    res = runner(cmd, capture_output=True, text=True)
    _echo(res)
    if res.returncode != 0:
        raise SystemExit("[sweep] BLOCKED: FULL sweep is outside the signed Gate-2 envelope. See guard output above.")
    for line in (res.stdout or "").splitlines():
        if "reserved FULL capacity:" in line:
            return line.split(":", 1)[1].strip()
    return None


def release_reservation(control: dict, reservation_id, *, runner=subprocess.run) -> None:
    if not reservation_id:
        return
    hub, slug = _hub(control), _slug(control)
    if not hub:
        return
    runner(_guard_cmd(hub) + ["release-full-run", slug, str(reservation_id)], capture_output=True, text=True)


# ── compute slots (hard rule 13) ──────────────────────────────────────────────

def acquire_slot(control: dict, label, *, runner=subprocess.run) -> str | None:
    """Acquire a cross-project compute slot for a direct PILOT/FULL run. Returns a slot id.
    Raises SystemExit if denied (before any run dir is created) or if the hub is unreachable."""
    hub, slug = _hub(control), _slug(control)
    if not hub or not Path(hub).exists():
        raise SystemExit("[run] BLOCKED: PILOT/FULL run but hub_path missing — cannot acquire a compute slot (hard rule 13).")
    res = runner(_slots_cmd(hub) + ["acquire", slug, str(label)], capture_output=True, text=True)
    if res.returncode != 0:
        _echo(res)
        raise SystemExit("[run] BLOCKED: no compute slot available (hard rule 13). Wait, or free a slot.")
    out = (res.stdout or "").strip()
    return out.splitlines()[-1].strip() if out else None


def release_slot(control: dict, slot_id, *, runner=subprocess.run) -> None:
    if not slot_id:
        return
    hub = _hub(control)
    if not hub:
        return
    runner(_slots_cmd(hub) + ["release", str(slot_id)], capture_output=True, text=True)
