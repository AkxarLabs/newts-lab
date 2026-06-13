"""Read-only world model for the Marginalia dashboard.

The lab's files ARE the database — this module only reads them, tolerantly:
  - lab/REGISTRY.md        -> the idea/project roster (same row logic as tools/check_lab.py)
  - lab/.bus/events.jsonl  -> hub events;  <project>/.bus/events.jsonl -> per-project events
  - lab/.bus/directives.jsonl + ack events -> the directive threads (pending/seen/acted)
  - <project>/runs/registry.jsonl          -> completed-run record
  - <project>/runs/<id>/meta.json + metrics.jsonl -> in-flight liveness (status.py semantics)
  - lab/.slots/*.json      -> compute-slot occupancy
  - lab/campaigns/*.md     -> latest campaign log (if any)

Everything is best-effort: a malformed line is skipped, a missing file is empty, a moved
project path is reported as unreachable — never a crash. Nothing here writes.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
TERMINAL_STATES = {"final", "killed", "parked"}
_REGISTRY_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in _read_text(path).splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(_read_text(path)) or {}
    except yaml.YAMLError:
        return {}


# ── registry ──────────────────────────────────────────────────────────────────

def parse_registry() -> list[dict]:
    rows = []
    for line in _read_text(LAB / "REGISTRY.md").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= {"-"} or cells[0] == "—":
            continue
        rows.append(dict(zip(_REGISTRY_COLS, cells)))
    return rows


def projects_root() -> Path:
    lab_cfg = (_load_yaml(LAB / "config.yaml").get("lab") or {})
    return (HUB / (lab_cfg.get("projects_root") or "../AutoScientist-Projects")).resolve()


def _project_path(row: dict) -> Path | None:
    """Resolve a registry row's project dir, preferring its explicit Project column."""
    raw = (row.get("project") or "").strip().strip("`")
    if raw and raw not in ("—", "-"):
        p = Path(raw)
        return p if p.is_absolute() else (HUB / p).resolve()
    cand = projects_root() / row["id"]
    return cand if cand.exists() else None


# ── run liveness (status.py semantics) ────────────────────────────────────────

def _inflight_runs(project_dir: Path, log_interval: float = 60.0) -> list[dict]:
    runs_dir = project_dir / "runs"
    if not runs_dir.exists():
        return []
    out = []
    for run_dir in runs_dir.iterdir():
        meta_path = run_dir / "meta.json"
        if not (run_dir.is_dir() and meta_path.exists()):
            continue
        try:
            meta = json.loads(_read_text(meta_path))
        except json.JSONDecodeError:
            continue
        if meta.get("status") != "running":
            continue
        stream = run_dir / "metrics.jsonl"
        elapsed = time.time() - meta_path.stat().st_ctime
        last, stalled = {}, False
        if stream.exists() and stream.stat().st_size:
            age = time.time() - stream.stat().st_mtime
            stalled = age > 2 * log_interval
            tail = _read_text(stream).strip().splitlines()
            if tail:
                try:
                    rec = json.loads(tail[-1])
                    last = {k: v for k, v in rec.items()
                            if isinstance(v, (int, float)) and k not in ("t", "step")}
                except json.JSONDecodeError:
                    pass
        budget = (meta.get("budget") or {}).get("max_minutes")
        out.append({
            "run_id": meta.get("run_id", run_dir.name), "stage": meta.get("stage"),
            "elapsed_s": round(elapsed), "budget_min": budget,
            "state": "stalled" if stalled else "alive", "last": last,
        })
    return out


def _best_metric(rows: list[dict]) -> dict | None:
    """A small sparkline-able series of the last completed runs' first numeric metric."""
    series = []
    for r in rows:
        if r.get("status") != "completed":
            continue
        m = r.get("metrics") or {}
        num = next((v for v in m.values() if isinstance(v, (int, float))), None)
        if num is not None:
            series.append({"run_id": r.get("run_id"), "value": num})
    return {"series": series[-20:]} if series else None


# ── slots & campaigns ─────────────────────────────────────────────────────────

def slots() -> list[dict]:
    sdir = LAB / ".slots"
    if not sdir.exists():
        return []
    out = []
    for f in sorted(sdir.glob("*.json")):
        try:
            data = json.loads(_read_text(f))
        except json.JSONDecodeError:
            continue
        data["slot_id"] = f.stem
        out.append(data)
    return out


def slot_cap() -> int:
    return int((_load_yaml(LAB / "config.yaml").get("compute") or {}).get("max_concurrent_runs", 1))


# ── directives (threads with pending/seen/acted state) ────────────────────────

def _directive_threads(bus_dir: Path) -> list[dict]:
    directives = _read_jsonl(bus_dir / "directives.jsonl")
    events = _read_jsonl(bus_dir / "events.jsonl")
    withdrawn = {d.get("ref") for d in directives if d.get("kind") == "withdraw"}
    acks: dict[str, dict] = {}
    for e in events:
        if str(e.get("kind", "")).startswith("directive_"):
            ref = (e.get("data") or {}).get("ref")
            if ref:
                acks[ref] = {"state": e["kind"].split("_", 1)[1], "ts": e.get("ts"),
                             "note": (e.get("data") or {}).get("note"),
                             "evidence": (e.get("data") or {}).get("evidence")}
    threads = []
    for d in directives:
        if d.get("kind") == "withdraw" or not d.get("id"):
            continue
        ack = acks.get(d["id"])
        state = "withdrawn" if d["id"] in withdrawn else (ack["state"] if ack else "pending")
        threads.append({"id": d["id"], "ts": d.get("ts"), "text": d.get("text", ""),
                        "state": state, "ack": ack})
    return threads


# ── the snapshot ──────────────────────────────────────────────────────────────

def snapshot() -> dict:
    rows = parse_registry()
    hub_bus = LAB / ".bus"
    items, all_events = [], []

    for e in _read_jsonl(hub_bus / "events.jsonl", limit=400):
        all_events.append(e)

    for row in rows:
        pdir = _project_path(row)
        item = {
            "id": row["id"], "title": row["title"], "state": row["state"],
            "updated": row["updated"], "next": row["next"],
            "has_project": pdir is not None, "has_paper": bool((row.get("paper") or "").strip(" -—`")),
            "inflight": [], "best": None, "loop_active": False, "events": [],
        }
        item["directives"] = []
        if pdir is not None:
            registry = _read_jsonl(pdir / "runs" / "registry.jsonl")
            item["n_runs"] = sum(1 for r in registry if r.get("run_id"))
            item["best"] = _best_metric(registry)
            item["inflight"] = _inflight_runs(pdir)
            item["loop_active"] = (pdir / ".bus" / ".loop-active").exists()
            item["directives"] = _directive_threads(pdir / ".bus")
            pevents = _read_jsonl(pdir / ".bus" / "events.jsonl", limit=80)
            item["events"] = pevents[-12:]
            all_events.extend(pevents)
        items.append(item)

    all_events.sort(key=lambda e: e.get("ts", ""))
    gates = [it for it in items if "gate" in (it["next"] or "").lower()
             or any("gate_waiting" in str(e.get("kind")) for e in it["events"])]

    return {
        "now": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "items": items,
        "events": all_events[-200:],
        "slots": {"in_use": len(slots()), "cap": slot_cap(), "held": slots()},
        "directives": _directive_threads(hub_bus),
        "gates_waiting": len(gates),
        "cold": len(rows) == 0,
    }
