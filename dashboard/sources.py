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
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ctx  # noqa: E402 — the lab being shown (ctx.HUB / ctx.LAB): one place, re-pointed live

# The executor (tools/executor) is optional for the dashboard: import it from THIS repo's tools/
# (never from a monkeypatched HUB), and degrade to observe-and-sign if it's missing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import executor  # noqa: E402
except Exception:  # noqa: BLE001 — a broken/missing executor must never blank the dashboard
    executor = None
import workflow  # noqa: E402 — the lab's stages/states/procedures (workflow/stages.yaml)
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)
import workers  # noqa: E402 — who is working: runs + the traced agents
import attention  # noqa: E402 — what needs the PI; the executor's status

TERMINAL_STATES = workflow.terminal_states()


# ── registry ──────────────────────────────────────────────────────────────────

def parse_registry() -> list[dict]:
    return labfiles.registry_rows(ctx.HUB)


def projects_root() -> Path:
    return labfiles.projects_root(ctx.HUB)


def _project_path(row: dict) -> Path | None:
    """A registry row's project dir, preferring its explicit Project column."""
    return labfiles.project_dir(ctx.HUB, row["id"], row)


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
            meta = json.loads(labfiles.read_text(meta_path))
        except json.JSONDecodeError:
            continue
        if meta.get("status") == "queued":   # waiting in the machine's job scheduler
            sch = meta.get("scheduler") or {}
            out.append({"run_id": meta.get("run_id", run_dir.name), "stage": meta.get("stage"), "elapsed_s": 0,
                        "budget_min": (meta.get("budget") or {}).get("max_minutes"), "state": "queued",
                        "last": {}, "job": sch.get("job"), "scheduler": sch.get("kind"), "queued": meta.get("queued")})
            continue
        if meta.get("status") != "running":
            continue
        stream = run_dir / "metrics.jsonl"
        elapsed = time.time() - meta_path.stat().st_ctime
        last, stalled = {}, False
        if stream.exists() and stream.stat().st_size:
            age = time.time() - stream.stat().st_mtime
            stalled = age > 2 * log_interval
            tail = labfiles.read_text(stream).strip().splitlines()
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

def _stale_slot_minutes() -> float:
    return labfiles.to_float((ctx.config().get("compute") or {}).get("stale_slot_minutes"), 360.0)


def slots() -> list[dict]:
    sdir = ctx.LAB / ".slots"
    if not sdir.exists():
        return []
    now = time.time()
    stale_min = _stale_slot_minutes()
    out = []
    for f in sorted(sdir.glob("*.json")):
        try:
            data = json.loads(labfiles.read_text(f))
        except json.JSONDecodeError:
            continue
        data["slot_id"] = f.stem
        # mtime is the heartbeat (run_slots.py touches it); a slot past stale_slot_minutes is presumed
        # crashed and would be reclaimed on the next tool invocation. Surface it read-only so the PI
        # sees a held-but-dead slot instead of it silently reading as "occupied forever" (no reclaim
        # happens until an agent runs a tool). We never delete here — reclaim is run_slots.py's job.
        try:
            age = now - f.stat().st_mtime
            data["age_min"] = round(age / 60)
            data["stale"] = age > stale_min * 60
        except OSError:
            data["age_min"], data["stale"] = None, False
        out.append(data)
    return out


def slot_cap() -> int:
    return labfiles.to_int((ctx.config().get("compute") or {}).get("max_concurrent_runs"), 1)


# ── Gate-2 envelope accounting (ONE source of truth, mirrors tools/guard.py c_full_run) ───────────
#
# The capacity math lives here, in the read-only world model, so BOTH the serve.py gate-2 review
# bundle AND the project-card burn-down chips report the same numbers (and the same numbers guard.py
# enforces). Returns structured fields; serve.py formats them into text, the frontend into a chip.

def envelope_accounting(pdir: "Path | None", env: dict | None) -> dict:
    env = env or {}
    signed = bool(env.get("pi_signed"))
    exp = str(env.get("expires") or "").strip()
    expired = bool(exp and exp.lower() not in ("null", "none") and exp < time.strftime("%Y-%m-%d"))
    full_cap = labfiles.to_int(env.get("full_runs"))
    per_cap = labfiles.to_float(env.get("per_run_max_minutes"))
    total_cap = labfiles.to_float(env.get("total_max_minutes"))
    done_count, done_min = 0, 0.0
    if pdir:
        reg = pdir / "runs" / "registry.jsonl"
        for r in labfiles.read_jsonl(reg):
            if str(r.get("stage", "")).upper() == "FULL":
                done_count += 1
                ws = r.get("wall_seconds")
                if isinstance(ws, (int, float)):
                    done_min += ws / 60.0
    resv_runs, resv_min = 0, 0.0
    if pdir:
        rf = pdir / ".guard" / "full-run-reservations.jsonl"
        now = time.time()
        for r in labfiles.read_jsonl(rf):
            if str(r.get("status", "active")).lower() != "active":
                continue
            ts = r.get("ts")
            if isinstance(ts, (int, float)) and (now - ts) > 24 * 3600:
                continue
            pr, pm = labfiles.to_int(r.get("planned_runs")), labfiles.to_float(r.get("planned_minutes"))
            resv_runs += pr
            resv_min += pr * pm
    # a zero/unset cap is "unbounded" for THAT dimension (guard.py:202); but an envelope whose caps are
    # ALL zero authorizes nothing (guard.py refuses every FULL run) — surface that, never "active ∞".
    authorizes = any((full_cap, per_cap, total_cap))
    status = ("no signed envelope" if not signed
              else "EXPIRED" if expired
              else "authorizes nothing" if not authorizes
              else "active")
    return {
        "signed": signed, "expires": exp, "expired": expired, "authorizes": authorizes, "status": status,
        "signed_via": env.get("signed_via"),
        "full_cap": full_cap, "per_cap": per_cap, "total_cap": total_cap,
        "full_done": done_count, "min_done": round(done_min),
        "full_resv": resv_runs, "min_resv": round(resv_min),
        "full_rem": (full_cap - done_count - resv_runs) if full_cap else None,
        "min_rem": round(total_cap - done_min - resv_min) if total_cap else None,
    }


_NB_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _notebook_status() -> dict:
    """Latest lab/notebook entry + its age — makes hard-rule-11 write-back cadence visible ('last
    write-back 2 d ago') so a PI can see a lab that's stopped recording. Best-effort; {} if absent.
    Age is derived from the entry's DATED FILENAME, not st_mtime: a `git clone`/`checkout`/`pull`
    resets mtimes, which would make a lab that stopped recording weeks ago read as fresh. Selecting by
    the filename string also means no stat() in the hot path (no glob→stat TOCTOU race)."""
    nb = ctx.LAB / "notebook"
    if not nb.exists():
        return {}
    dated = [f for f in nb.glob("*.md") if f.name.lower() != "readme.md"]
    if not dated:
        return {}
    latest = max(dated, key=lambda f: f.name)   # ISO-dated names sort chronologically as strings
    m = _NB_DATE.match(latest.name)
    if not m:
        return {"latest": latest.name}          # undated name → surface it, but no age we can trust
    try:
        entry_epoch = time.mktime((int(m.group(1)), int(m.group(2)), int(m.group(3)), 0, 0, 0, 0, 0, -1))
    except (ValueError, OverflowError):
        return {"latest": latest.name}
    return {"latest": latest.name, "age_hours": round(max(0.0, (time.time() - entry_epoch) / 3600.0), 1)}


def editor_scheme() -> str:
    """URI scheme for the 'open in editor' deep-links (vscode|cursor|…|none). The dashboard is
    local-only, so a `<scheme>://file/<abs-path>` opens the PI's own editor. Default vscode."""
    return str((ctx.config().get("dashboard") or {}).get("editor", "vscode")).strip().lower()


# ── paper artifacts (the compiled PDF a back-half session produced) ────────────
#
# A paper lives in the HUB at studies/<slug>/paper/ (main.tex → main.pdf via /write-paper's blocking
# latexmk gate; figures synced into figures/). We only report whether the PDF exists + its mtime, so
# the viewer's button shows and the snapshot diff (hence the SSE push) auto-refreshes it on recompile.

def _paper_status(slug: str) -> dict | None:
    pdir = ctx.HUB / "studies" / slug / "paper"
    pdf = pdir / "main.pdf"
    try:
        if not pdf.is_file():
            return None
        out = {"pdf": True, "mtime": int(pdf.stat().st_mtime)}
        tex = pdir / "main.tex"
        if tex.is_file():
            out["tex"] = str(tex.resolve())   # absolute, for the "edit source" editor link
        return out
    except OSError:
        return None


def _claims_count(slug: str) -> int:
    """How many claims studies/<slug>/paper/claims.yaml holds (0 if absent/empty). Drives the
    'claims (N)' button — claims.yaml can exist before the PDF, so this is independent of _paper_status."""
    f = ctx.HUB / "studies" / slug / "paper" / "claims.yaml"
    if not f.is_file():
        return 0
    doc = labfiles.load_yaml(f)
    cl = doc.get("claims") if isinstance(doc, dict) else None
    # count only dict items, matching serve.claims_map's filter so "claims (N)" == rendered rows
    return sum(1 for c in cl if isinstance(c, dict)) if isinstance(cl, list) else 0


# ── directives (threads with pending/seen/acted state) ────────────────────────

def _synth_id(d: dict) -> str:
    """Stable synthesized id for a hand-written/legacy directive with no id — the same scheme
    tools/lab_bus.py uses, so the dashboard and the agent `inbox` name the same directive."""
    import hashlib
    return "d?" + hashlib.sha1(f"{d.get('ts', '')}|{d.get('text', '')}".encode()).hexdigest()[:8]


def _directive_threads(bus_dir: Path, default_target: str = "hub") -> list[dict]:
    directives = labfiles.read_jsonl(bus_dir / "directives.jsonl")
    events = labfiles.read_jsonl(bus_dir / "events.jsonl")
    withdrawn = {d.get("ref") for d in directives if d.get("kind") == "withdraw"}
    acks: dict[str, dict] = {}
    for e in events:
        if str(e.get("kind", "")).startswith("directive_"):
            ref = (e.get("data") or {}).get("ref")
            if not ref:
                continue
            state = e["kind"].split("_", 1)[1]           # seen | done | blocked
            prev = acks.get(ref)
            # terminal acks are STICKY (matches lab_bus.unresolved_directives): once done/blocked, a
            # later 'seen' can't reopen the directive — else an out-of-order ack reopens it in the
            # dashboard while the agent considers it closed.
            if prev and prev["state"] in ("done", "blocked") and state == "seen":
                continue
            acks[ref] = {"state": state, "ts": e.get("ts"),
                         "note": (e.get("data") or {}).get("note"),
                         "evidence": (e.get("data") or {}).get("evidence")}
    threads = []
    for d in directives:
        if d.get("kind") == "withdraw":
            continue
        did = d.get("id") or _synth_id(d)               # surface id-less directives, like the inbox does
        ack = acks.get(did)
        state = "withdrawn" if did in withdrawn else (ack["state"] if ack else "pending")
        threads.append({"id": did, "ts": d.get("ts"), "text": d.get("text", ""),
                        "state": state, "ack": ack,
                        "target": d.get("target") or default_target,   # the record's own target wins (M2)
                        "kind": d.get("kind", "note"), "action": d.get("action"),
                        "args": d.get("args")})
    return threads


# \bgate\s*-?\s*(N)\b — word-bounded so "investigate 3" / "delegate 2" in a next-action can't be read
# as a waiting Gate 3 / Gate 2 (which would raise a phantom one-click Approve button). Matches
# "Gate 1", "gate-2", "PI Gate 3", "gate1".
# The dashboard's Gate-1 signature marker (serve.approve_gate writes it; defined here so the
# snapshot can detect "signed, waiting for the agent" without importing the server).
GATE1_MARK = "PI Gate 1 approved via Vivarium dashboard"   # (= markers.GATE1_DASHBOARD_MARK)


def _gate_signed(idea: str, gate: int | None, pdir: Path | None) -> bool:
    """True when the PI's signature for this gate is already recorded on disk AND still valid —
    the approval is done, and what remains is the AGENT consuming it at its next checkpoint.
    Rendering this distinctly is what stops a successful approval from looking like 'nothing
    happened'. Detection rides on the on-disk signature (not the event bus), so it holds no
    matter which session/tool signed, and it clears itself the moment the agent transitions the
    registry row past the gate (the next-action text stops naming a gate, so gate -> None)."""
    # (an EXPIRED signed envelope is not "waiting for the agent": guard.py full-run and approve_gate
    # both refuse it, so the PI must re-authorize — markers.gate_signed keeps it an actionable gate)
    return bool(gate) and ctx.tool("markers").gate_signed(ctx.HUB, idea, gate, pdir)


def _escalations(events: list[dict]) -> list[dict]:
    """Unresolved escalations, paired with their escalation_resolved events by ref. An escalation
    with no matching resolver stays 'needs you'; once an agent emits escalation_resolved (data.ref =
    the escalation id) it drops off — so a handled escalation stops nagging the bell forever (its
    id defaults to a synthesized hash when the emitter didn't set one)."""
    def _eid(e: dict) -> str:
        return str((e.get("data") or {}).get("id") or "").strip() or _synth_id(
            {"ts": e.get("ts"), "text": e.get("detail", "")})
    resolved = {str((e.get("data") or {}).get("ref") or "").strip()
                for e in events if e.get("kind") == "escalation_resolved"}
    out = []
    for e in events:
        if e.get("kind") != "escalation":
            continue
        eid = _eid(e)
        if eid in resolved:
            continue
        out.append({"id": eid, "ts": e.get("ts"), "source": e.get("source"),
                    "detail": e.get("detail", ""),
                    "severity": (e.get("data") or {}).get("severity")})
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
    cdir = ctx.LAB / "campaigns"
    for f in (sorted(cdir.glob("*.md")) if cdir.exists() else []):
        text = labfiles.read_text(f)
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
        env = (labfiles.load_yaml(ctrl).get("gate2_envelope") or {})
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

def _rooms3d_sig() -> str:
    """Changes when the lab's own room looks (lab/rooms3d/*.json) do — the world fetches them again."""
    d = ctx.LAB / "rooms3d"
    fs = sorted(d.glob("*.json")) if d.is_dir() else []
    return ",".join(f"{f.stem}:{int(f.stat().st_mtime)}" for f in fs)


def snapshot() -> dict:
    rows = parse_registry()
    hub_bus = ctx.LAB / ".bus"
    items, all_events = [], []
    proj_ids = {r["id"] for r in rows if _project_path(r) is not None}
    roster = workers.scan(hub_bus, None, proj_ids)
    hub_runs = workers.agents_in(hub_bus / "agents")

    for e in labfiles.read_jsonl(hub_bus / "events.jsonl", tail=400):
        all_events.append(e)

    for row in rows:
        pdir = _project_path(row)
        gate = ctx.tool("markers").gate_waiting(row["next"])   # the registry next-action text is the gate signal
        item = {
            "id": row["id"], "title": row["title"], "state": row["state"],
            "updated": row["updated"], "next": row["next"],
            "has_project": pdir is not None, "has_paper": bool((row.get("paper") or "").strip(" -—`")),
            "project_dir": str(pdir) if pdir else None, "gate": gate,
            "gate_signed": _gate_signed(row["id"], gate, pdir),
            "paper": _paper_status(row["id"]),   # the compiled PDF on disk (drives the paper viewer)
            "claims": _claims_count(row["id"]),  # number of claims in claims.yaml (drives the claims↔artifact map)
            "inflight": [], "best": None, "loop_active": False, "events": [],
        }
        item["directives"] = []
        item["agents"] = []
        item["n_workers"] = 0
        item["envelope"] = None
        if pdir is not None:
            registry = labfiles.read_jsonl(pdir / "runs" / "registry.jsonl")
            item["n_runs"] = sum(1 for r in registry if r.get("run_id"))
            item["best"] = _best_metric(registry)
            item["inflight"] = _inflight_runs(pdir)
            item["loop_active"] = (pdir / ".bus" / ".loop-active").exists()
            item["agents"] = workers.launched_agents(pdir)
            item["directives"] = _directive_threads(pdir / ".bus", default_target=row["id"])
            ctrl = pdir / "control.yaml"
            cfg = labfiles.load_yaml(ctrl) if ctrl.exists() else {}
            item["project_type"] = str(cfg.get("project_type") or "ml")   # the world draws its lab by it
            env = cfg.get("gate2_envelope")
            if env:   # only projects with an envelope block carry the burn-down chip
                item["envelope"] = envelope_accounting(pdir, env)
            pevents = labfiles.read_jsonl(pdir / ".bus" / "events.jsonl", tail=80)
            item["events"] = pevents[-12:]
            all_events.extend(pevents)
            roster.extend(workers.scan(pdir / ".bus", row["id"], proj_ids))
        items.append(item)

    # hub-bus workers promoted to a project (its /improve worktrees) count toward that project too
    for item in items:
        item["n_workers"] = sum(1 for w in roster if w["project"] == item["id"] and w["status"] != "done")
    runs = hub_runs + [a for it in items for a in (it.get("agents") or [])]
    workers.LIVE_IDS.clear()
    workers.LIVE_IDS.update(x for r in runs if r.get("status") in ("starting", "running", "resuming", "waiting_input")
                     for x in (r.get("run_id"), r.get("session_id")) if x)
    workers.join_runs(roster, runs)
    workers.link_workers(roster)
    roster.sort(key=lambda w: w.get("last_ts") or "")

    all_events.sort(key=lambda e: e.get("ts", ""))
    # gates_waiting counts gates that still need the PI's SIGNATURE — a signed-but-unconsumed gate
    # renders in "Needs you" as 'signed, waiting for the agent' but no longer lights the badge/beacon
    # (you already acted; the wait is the agent's). Still a subset of the panel's cards, so the badge
    # can never light with an empty panel.
    held = slots()   # compute once (was called twice)
    return {
        "now": ctx.ts(),
        "editor": editor_scheme(),
        "items": items,
        "events": all_events[-200:],
        "escalations": (esc := _escalations(all_events)),
        "notebook": _notebook_status(),
        "slots": {"in_use": len(held), "cap": slot_cap(), "held": held},
        "directives": _directive_threads(hub_bus),
        "workers": roster[-200:],
        "campaigns": campaigns(rows),
        "gates_waiting": sum(1 for it in items if it["gate"] and not it["gate_signed"]),
        "cold": len(rows) == 0,
        "runs": sorted(runs, key=lambda r: r.get("created") or r.get("started") or "", reverse=True)[:100],
        "hub_agents": hub_runs,
        "attention": attention.collect(items, esc, roster, runs),
        "executor": attention.executor_status(),
        "skills": (executor.registry(ctx.HUB) if executor else {}),
        "workflow": _workflow_view(),
        "rooms3d_sig": _rooms3d_sig(),
        **_autonomy_view(),
    }


def _autonomy_view() -> dict:
    """The campaigns the executor keeps, whether a scheduler is ticking, whether the machine is held awake."""
    if executor is None:
        return {"campaign_states": [], "scheduler": {}, "awake": {}}
    try:
        lab = executor.Lab(ctx.HUB)
        from executor import awake, campaigns as _camps  # noqa: PLC0415
        return {"campaign_states": _camps.summary(lab), "scheduler": executor.scheduler.lease(lab),
                "awake": awake.status()}
    except Exception as e:  # noqa: BLE001 — never blank the dashboard
        return {"campaign_states": [], "scheduler": {"error": str(e)}, "awake": {}}


def _workflow_view() -> dict:
    try:
        return workflow.ui_view(ctx.HUB)
    except Exception as e:  # noqa: BLE001 — a broken manifest shows as a problem, never a blank dashboard
        return {"error": str(e)}




