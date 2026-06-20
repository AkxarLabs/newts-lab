"""Read-only world model for the Vivarium dashboard.

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
    return (HUB / (lab_cfg.get("projects_root") or "../kartr-lab-projects")).resolve()


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


def _launched_agents(project_dir: Path) -> list[dict]:
    """Headless top-level agents launched into this project by tools/agent_runner.py — each is a
    <project>/.bus/agents/<id>.json manifest. Surfaces who/what/status; the full transcript lives
    next to it as <id>.stream.jsonl. Best-effort, absent dir => []."""
    adir = project_dir / ".bus" / "agents"
    if not adir.exists():
        return []
    out = []
    for f in sorted(adir.glob("*.json")):
        try:
            m = json.loads(_read_text(f))
        except json.JSONDecodeError:
            continue
        out.append({k: m.get(k) for k in
                    ("agent_id", "backend", "role", "status", "started", "finished",
                     "wall_seconds", "exit_code", "prompt_summary")})
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
                        "state": state, "ack": ack,
                        "kind": d.get("kind", "note"), "action": d.get("action"),
                        "args": d.get("args")})
    return threads


_GATE_RE = re.compile(r"gate ?([123])", re.I)


def _gate_of(next_action: str) -> int | None:
    m = _GATE_RE.search(next_action or "")
    return int(m.group(1)) if m else None


# ── workers (per-agent activity from .bus/workers/*.jsonl — the traceability feed) ──
#
# tools/trace_hook.py (a Claude Code hook) writes ONE file per agent/subagent. We fold
# each file into a roster entry: who it is (role), what it's doing (status + recent
# actions), and where (project / idea). Best-effort and non-canonical, like the rest of
# the bus — absent dir => []. The dashboard renders one sprite per entry.

_WORKER_LINGER_S = 300   # keep a finished worker on the roster this long (for its despawn anim)
_WORKER_STALE_S = 150    # no activity & no stop -> treat as idle, not "working"
_MAX_RECENT = 40
_KNOWN_ROLES = {"orchestrator", "experiment-runner", "fresh-context-reviewer",
                "overseer", "ideation-critic", "scoping-advocate"}


def _workers(bus_dir: Path, project: str | None = None) -> list[dict]:
    wdir = bus_dir / "workers"
    if not wdir.exists():
        return []
    now = time.time()
    out = []
    for f in sorted(wdir.glob("*.jsonl")):
        lines = _read_jsonl(f)
        if not lines:
            continue
        role, idea, done, spawns, actions = "orchestrator", None, False, None, []
        for ln in lines:
            if ln.get("role"):
                role = ln["role"]
            if ln.get("idea"):
                idea = ln["idea"]
            if ln.get("spawns"):
                spawns = ln["spawns"]
            ev = ln.get("event")
            if ev == "stop":
                done = True
            if ev in ("action", "spawn"):
                actions.append({"ts": ln.get("ts"),
                                "text": ln.get("summary") or ln.get("tool") or ev,
                                "kind": ln.get("kind") or ev})
        try:
            age = now - f.stat().st_mtime
        except OSError:
            age = 0
        if done:
            if age > _WORKER_LINGER_S:
                continue                       # finished a while ago -> off the roster
            status = "done"
        elif age > _WORKER_STALE_S:
            status = "idle"
        else:
            status = "working"
        out.append({
            "worker_id": f.stem,
            "role": role,
            "role_known": role in _KNOWN_ROLES,
            "status": status,
            "project": project,
            "idea": idea,
            "spawns": spawns,
            "started": lines[0].get("ts"),
            "last_ts": lines[-1].get("ts"),
            "n_actions": sum(1 for ln in lines if ln.get("event") in ("action", "spawn")),
            "recent_actions": actions[-_MAX_RECENT:],
        })
    return out


# ── campaigns (/autopilot) — first-class grouping of delegated projects ─────────
#
# A campaign is a PI-signed /autopilot brief that delegates work across projects. We read it from two
# tolerant sources and merge: (1) campaign logs in lab/campaigns/*.md (optional YAML frontmatter),
# and (2) the truth on the ground — each project's control.yaml gate2_envelope.signed_via, which is
# `autopilot:<campaign>` (or `campaign:<name>`) when a FULL-run envelope was signed under a campaign.

def _first_heading(text: str) -> str | None:
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()
    return None


def _excerpt(text: str, n: int = 240) -> str:
    body = text
    if body.lstrip().startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            body = parts[2]
    body = "\n".join(ln for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("#"))
    return (body[:n] + "…") if len(body) > n else body


def campaigns(rows: list[dict] | None = None) -> list[dict]:
    rows = rows if rows is not None else parse_registry()
    cmap: dict[str, dict] = {}
    cdir = LAB / "campaigns"
    for f in (sorted(cdir.glob("*.md")) if cdir.exists() else []):
        text = _read_text(f)
        meta = {}
        if text.lstrip().startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                try:
                    meta = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    meta = {}
        name = str(meta.get("name") or f.stem)
        projects = meta.get("projects") or meta.get("ideas") or []
        if isinstance(projects, str):
            projects = [projects]
        cmap[name] = {
            "name": name, "title": meta.get("title") or _first_heading(text) or name,
            "status": str(meta.get("status") or "active"),
            "signed": meta.get("signed_by") or meta.get("signed"),
            "started": meta.get("started"), "budget": meta.get("budget") or meta.get("envelope"),
            "projects": [str(p).strip() for p in projects], "file": f"campaigns/{f.name}",
            "detail": _excerpt(text),
        }
    # membership from each project's signed envelope (the ground truth)
    for row in rows:
        pdir = _project_path(row)
        ctrl = (pdir / "control.yaml") if pdir else None
        if not ctrl or not ctrl.exists():
            continue
        env = (_load_yaml(ctrl).get("gate2_envelope") or {})
        sv = str(env.get("signed_via") or "").strip()
        if ":" in sv:
            kind, ref = sv.split(":", 1)
            if kind.strip().lower() in ("autopilot", "campaign") and ref.strip():
                ref = ref.strip()
                c = cmap.setdefault(ref, {"name": ref, "title": ref, "status": "active", "signed": None,
                                          "started": None, "budget": env, "projects": [], "file": None, "detail": ""})
                if row["id"] not in c["projects"]:
                    c["projects"].append(row["id"])
    return list(cmap.values())


# ── the snapshot ──────────────────────────────────────────────────────────────

def snapshot() -> dict:
    rows = parse_registry()
    hub_bus = LAB / ".bus"
    items, all_events = [], []
    workers = _workers(hub_bus, None)

    for e in _read_jsonl(hub_bus / "events.jsonl", limit=400):
        all_events.append(e)

    for row in rows:
        pdir = _project_path(row)
        item = {
            "id": row["id"], "title": row["title"], "state": row["state"],
            "updated": row["updated"], "next": row["next"],
            "has_project": pdir is not None, "has_paper": bool((row.get("paper") or "").strip(" -—`")),
            "project_dir": str(pdir) if pdir else None, "gate": _gate_of(row["next"]),
            "inflight": [], "best": None, "loop_active": False, "events": [],
        }
        item["directives"] = []
        item["agents"] = []
        item["n_workers"] = 0
        if pdir is not None:
            registry = _read_jsonl(pdir / "runs" / "registry.jsonl")
            item["n_runs"] = sum(1 for r in registry if r.get("run_id"))
            item["best"] = _best_metric(registry)
            item["inflight"] = _inflight_runs(pdir)
            item["loop_active"] = (pdir / ".bus" / ".loop-active").exists()
            item["agents"] = _launched_agents(pdir)
            item["directives"] = _directive_threads(pdir / ".bus")
            pevents = _read_jsonl(pdir / ".bus" / "events.jsonl", limit=80)
            item["events"] = pevents[-12:]
            all_events.extend(pevents)
            pworkers = _workers(pdir / ".bus", row["id"])
            item["n_workers"] = sum(1 for w in pworkers if w["status"] != "done")
            workers.extend(pworkers)
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
        "workers": workers[-200:],
        "campaigns": campaigns(rows),
        "gates_waiting": len(gates),
        "cold": len(rows) == 0,
    }
