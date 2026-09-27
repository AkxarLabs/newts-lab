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

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"

# The executor (tools/executor) is optional for the dashboard: import it from THIS repo's tools/
# (never from a monkeypatched HUB), and degrade to observe-and-sign if it's missing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    import executor  # noqa: E402
except Exception:  # noqa: BLE001 — a broken/missing executor must never blank the dashboard
    executor = None
import workflow  # noqa: E402 — the lab's stages/states/procedures (workflow/stages.yaml)

TERMINAL_STATES = workflow.terminal_states()
_REGISTRY_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]


def _read_text(path: Path) -> str:
    # errors="replace" so ONE non-UTF-8 byte written by a training script into any tailed file
    # (metrics.jsonl, events.jsonl, a worker log) can't raise UnicodeDecodeError and 500 the whole
    # snapshot — the module's "never a crash" contract must hold for exactly that dirty input.
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


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
    # Always return a dict: a valid-YAML but non-mapping file (a bare scalar `42`, a top-level list)
    # would otherwise make every `_load_yaml(...).get(...)` call site raise AttributeError and blank
    # the whole snapshot — the same "never a crash on dirty input" contract _read_text upholds.
    try:
        data = yaml.safe_load(_read_text(path))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


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
    return (HUB / (lab_cfg.get("projects_root") or "../newts-lab-projects")).resolve()


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


_RUN_KEYS = ("agent_id", "run_id", "backend", "role", "status", "started", "finished", "wall_seconds",
             "exit_code", "prompt_summary", "session_id", "skill", "command", "target", "subject", "level",
             "attempt", "reason", "status_ts", "pending_question", "report", "usage", "chain", "chain_child",
             "parent", "created_by", "created", "max_minutes", "n_actions", "denials", "mode", "label",
             "cli_version", "model_used", "repeat_minutes", "not_before", "answers_given", "schema",
             "kind", "gate3_signed", "args", "model", "effort", "max_repeats", "repeat_index", "campaign")


def _r10(x) -> int | None:
    return None if x is None else int(x // 10 * 10)


def _compact_run(m: dict) -> dict:
    """A run manifest → the fields the dashboard renders. Time-varying numbers are rounded to 10 s
    so the SSE signature (which ignores `now`) doesn't change every tick."""
    out = {k: m.get(k) for k in _RUN_KEYS}
    out["run_id"] = out["run_id"] or out["agent_id"]
    out["last_message"] = (m.get("last_message") or "")[:1200] or None
    out["last_text"] = (m.get("last_text") or "")[:400] or None
    la = m.get("last_action")
    out["last_action"] = {"tool": la.get("tool"), "summary": (la.get("summary") or "")[:200], "ts": la.get("ts")} \
        if isinstance(la, dict) else None
    now = time.time()
    st = m.get("status")
    started = _epoch(m.get("started"))
    if st in ("starting", "running", "resuming") and started:
        prior = sum(float(a.get("wall_seconds") or 0) for a in (m.get("attempts") or [])[:-1])
        cur = _epoch(((m.get("attempts") or [{}])[-1] or {}).get("started")) or started
        out["elapsed_s"] = _r10(prior + max(0.0, now - cur))
    else:   # a finished run's wall time never changes → exact (only LIVE numbers are rounded for SSE)
        out["elapsed_s"] = round(float(m.get("wall_seconds") or 0)) if m.get("wall_seconds") is not None else None
    hb = _epoch(m.get("heartbeat"))
    out["heartbeat_age_s"] = _r10(now - hb) if (hb and st in ("starting", "running", "resuming")) else None
    subs = m.get("subagents") or {}
    out["subagents"] = [{"id": k, "type": v.get("type"), "description": v.get("description"),
                         "status": v.get("status"), "n_actions": v.get("n_actions"),
                         "last_action": (v.get("last_action") or {}).get("summary"),
                         "result": (v.get("result") or "")[:600] or None,
                         "started": v.get("started"), "finished": v.get("finished")}
                        for k, v in list(subs.items())[-40:]]
    out["n_qa"] = len(m.get("qa") or [])
    return out


def _launched_agents(project_dir: Path) -> list[dict]:
    """Headless agents launched into this project (tools/executor runs or tools/agent_runner.py
    launches) — each is a <project>/.bus/agents/<id>.json manifest; the full transcript lives next to
    it as <id>.stream.jsonl. Best-effort, absent dir => []."""
    return _agents_in(project_dir / ".bus" / "agents")


def _agents_in(adir: Path) -> list[dict]:
    if not adir.exists():
        return []
    out = []
    for f in sorted(adir.glob("*.json")):
        try:
            m = json.loads(_read_text(f))
        except json.JSONDecodeError:
            continue
        if isinstance(m, dict):
            out.append(_compact_run(m))
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
    return _to_float((_load_yaml(LAB / "config.yaml").get("compute") or {}).get("stale_slot_minutes"), 360.0)


def slots() -> list[dict]:
    sdir = LAB / ".slots"
    if not sdir.exists():
        return []
    now = time.time()
    stale_min = _stale_slot_minutes()
    out = []
    for f in sorted(sdir.glob("*.json")):
        try:
            data = json.loads(_read_text(f))
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
    return _to_int((_load_yaml(LAB / "config.yaml").get("compute") or {}).get("max_concurrent_runs"), 1)


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
    full_cap = _to_int(env.get("full_runs"))
    per_cap = _to_float(env.get("per_run_max_minutes"))
    total_cap = _to_float(env.get("total_max_minutes"))
    done_count, done_min = 0, 0.0
    if pdir:
        reg = pdir / "runs" / "registry.jsonl"
        for r in (_read_jsonl(reg) if reg.exists() else []):
            if str(r.get("stage", "")).upper() == "FULL":
                done_count += 1
                ws = r.get("wall_seconds")
                if isinstance(ws, (int, float)):
                    done_min += ws / 60.0
    resv_runs, resv_min = 0, 0.0
    if pdir:
        rf = pdir / ".guard" / "full-run-reservations.jsonl"
        now = time.time()
        for r in (_read_jsonl(rf) if rf.exists() else []):
            if str(r.get("status", "active")).lower() != "active":
                continue
            ts = r.get("ts")
            if isinstance(ts, (int, float)) and (now - ts) > 24 * 3600:
                continue
            pr, pm = _to_int(r.get("planned_runs")), _to_float(r.get("planned_minutes"))
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
    nb = LAB / "notebook"
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
    return str((_load_yaml(LAB / "config.yaml").get("dashboard") or {}).get("editor", "vscode")).strip().lower()


# ── paper artifacts (the compiled PDF a back-half session produced) ────────────
#
# A paper lives in the HUB at studies/<slug>/paper/ (main.tex → main.pdf via /write-paper's blocking
# latexmk gate; figures synced into figures/). We only report whether the PDF exists + its mtime, so
# the viewer's button shows and the snapshot diff (hence the SSE push) auto-refreshes it on recompile.

def _paper_status(slug: str) -> dict | None:
    pdir = HUB / "studies" / slug / "paper"
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
    f = HUB / "studies" / slug / "paper" / "claims.yaml"
    if not f.is_file():
        return 0
    doc = _load_yaml(f)
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
    directives = _read_jsonl(bus_dir / "directives.jsonl")
    events = _read_jsonl(bus_dir / "events.jsonl")
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
_GATE_RE = re.compile(r"\bgate\s*-?\s*([123])\b", re.I)


def _gate_of(next_action: str) -> int | None:
    m = _GATE_RE.search(next_action or "")
    return int(m.group(1)) if m else None


# The dashboard's Gate-1 signature marker (serve.approve_gate writes it; defined here so the
# snapshot can detect "signed, waiting for the agent" without importing the server).
GATE1_MARK = "PI Gate 1 approved via Vivarium dashboard"


def _gate_signed(idea: str, gate: int | None, pdir: Path | None) -> bool:
    """True when the PI's signature for this gate is already recorded on disk AND still valid —
    the approval is done, and what remains is the AGENT consuming it at its next checkpoint.
    Rendering this distinctly is what stops a successful approval from looking like 'nothing
    happened'. Detection rides on the on-disk signature (not the event bus), so it holds no
    matter which session/tool signed, and it clears itself the moment the agent transitions the
    registry row past the gate (the next-action text stops matching _GATE_RE, so gate -> None)."""
    try:
        if gate == 1:
            p = HUB / "studies" / idea / "proposal.md"
            return p.is_file() and GATE1_MARK in _read_text(p)
        if gate == 2 and pdir is not None:
            env = _load_yaml(pdir / "control.yaml").get("gate2_envelope") or {}
            if not env.get("pi_signed"):
                return False
            # an EXPIRED signed envelope is not "waiting for the agent" — guard.py full-run and
            # approve_gate both refuse it, so the PI must re-authorize; keep it an actionable gate.
            expires = str(env.get("expires") or "").strip().lower()
            if expires and expires not in ("null", "none", "~") and expires < time.strftime("%Y-%m-%d"):
                return False
            return True
        if gate == 3:   # the PI's dashboard signature (product.gate3_sign) or a session's gate3-approval.md
            p = HUB / "studies" / idea / "paper" / "gate3-approval.md"
            return p.is_file() and bool(re.search(r"gate ?3 approved", _read_text(p), re.I))
    except OSError:
        pass
    return False


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


# ── workers (per-agent activity from .bus/workers/*.jsonl — the traceability feed) ──
#
# tools/trace_hook.py (a Claude Code hook) writes ONE file per agent/subagent. We fold each file into
# a roster entry: who it is (role + a readable label), what it's doing (status, the tool it is inside
# right now, recent actions), where (project / idea / worktree variant), who spawned it (parent) and
# what it handed back (result). Best-effort and non-canonical, like the rest of the bus.
#
# Tree: a subagent's lines carry the PARENT session's id in `session_id`; its parent's file holds a
# `spawn` line (tool_use_id, subagent type, description) and later a `return` line (the result
# packet). `_link_workers` matches each child to its spawn, so the UI can draw
# run → session → subagents with every subagent's label, status and result.

_WORKER_DONE_KEEP_S = 1800   # a finished worker stays on the roster (greyed, with its result) this long
_WORKER_DEAD_S = 7200        # a file with no 'stop' untouched this long = a session that died uncleanly
_WORKER_STALE_S = 150        # no activity, no open tool, no stop -> idle (not "working")
_SUBAGENT_STUCK_S = 1200     # an idle, unfinished subagent this long is surfaced as needing a look
_MAX_RECENT = 40
_KNOWN_ROLES = {"orchestrator", "experiment-runner", "fresh-context-reviewer",
                "overseer", "ideation-critic", "scoping-advocate"}
_WORKER_CACHE: dict[str, tuple] = {}


def _epoch(ts) -> float | None:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _fold_worker(lines: list[dict]) -> dict:
    """One worker file's lines → its roster facts (pure; cached by file mtime+size)."""
    role, idea, proj, variant, sid = "orchestrator", None, None, None, None
    stop_i, start_i = -1, -1
    actions, spawns, returns = [], [], {}
    open_tool, result, n_actions = None, None, 0
    for i, ln in enumerate(lines):
        if ln.get("role"):
            role = ln["role"]
        if ln.get("idea"):
            idea = ln["idea"]
        if ln.get("project"):
            proj, variant = ln["project"], ln.get("variant") or variant
        if ln.get("session_id") and not sid:
            sid = ln["session_id"]
        ev = ln.get("event")
        if ev == "start":
            start_i = i
        elif ev == "stop":
            stop_i = i
            if ln.get("result"):
                result = ln["result"]
        elif ev == "begin":
            open_tool = {"tool": ln.get("tool"), "summary": ln.get("summary"), "since": ln.get("ts"),
                         "kind": ln.get("kind"), "tool_use_id": ln.get("tool_use_id")}
        elif ev in ("action", "spawn", "return"):
            if ev == "spawn":
                spawns.append({"tool_use_id": ln.get("tool_use_id"), "type": ln.get("spawns") or "general-purpose",
                               "summary": ln.get("summary"), "ts": ln.get("ts")})
            if ev == "return" and ln.get("tool_use_id"):
                returns[ln["tool_use_id"]] = ln.get("result")
            if ln.get("child") and ln.get("tool_use_id"):   # codex / opencode name the child exactly
                for sp in spawns:
                    if sp.get("tool_use_id") == ln["tool_use_id"]:
                        sp["child"] = ln["child"]
            if ev in ("action", "return"):
                open_tool = None          # the call that was in flight has finished
            if ev != "return":
                n_actions += 1
            actions.append({"ts": ln.get("ts"), "text": ln.get("summary") or ln.get("tool") or ev,
                            "kind": ln.get("kind") or ev, "event": ev})
    done = stop_i >= 0 and stop_i >= start_i    # a later 'start' (a resumed session) reopens it
    return {"role": role, "idea": idea, "project_hint": proj, "variant": variant, "session_id": sid,
            "done": done, "open_tool": None if done else open_tool, "result": result,
            "spawns": spawns, "returns": returns, "n_actions": n_actions,
            "recent_actions": actions[-_MAX_RECENT:], "started": lines[0].get("ts"),
            "last_ts": lines[-1].get("ts")}


def _workers(bus_dir: Path, project: str | None = None, projects: set | None = None) -> list[dict]:
    wdir = bus_dir / "workers"
    if not wdir.exists():
        return []
    now = time.time()
    out = []
    for f in sorted(wdir.glob("*.jsonl")):
        try:
            st = f.stat()
        except OSError:
            continue
        age = now - st.st_mtime
        if age > max(_WORKER_DEAD_S, _WORKER_DONE_KEEP_S):
            continue   # never parsed: roster cost stays O(recent) before trace_hook's retention sweep
        key = str(f)
        hit = _WORKER_CACHE.get(key)
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            fold = hit[2]
        else:
            lines = _read_jsonl(f)
            if not lines:
                continue
            fold = _fold_worker(lines)
            _WORKER_CACHE[key] = (st.st_mtime, st.st_size, fold)
        if fold["done"] and age > _WORKER_DONE_KEEP_S:
            continue
        if fold["done"]:
            status = "done"
        elif fold["open_tool"]:
            status = "working"            # inside a tool call — however long it takes
        elif age > _WORKER_STALE_S:
            status = "idle"
        else:
            status = "working"
        wid = f.stem
        # attribution: an explicit project bus wins; a hub-bus worker whose calls named a registered
        # project (its /improve worktree, its runs/…) is promoted to that project so the project's
        # lab view and worker count include it
        proj = project
        if not proj:
            for cand in (fold["project_hint"], fold["idea"]):
                if cand and projects and cand in projects:
                    proj = cand
                    break
        sid = fold["session_id"]
        is_sub = bool(sid and sid != wid)
        out.append({
            "worker_id": wid,
            "role": fold["role"],
            "role_known": fold["role"] in _KNOWN_ROLES,
            "status": status,
            "project": proj,
            "idea": fold["idea"] or (proj if proj != project else None),
            "variant": fold["variant"],
            "session_id": sid,
            "parent": sid if is_sub else None,
            "is_subagent": is_sub,
            "children": [],
            "label": None,
            "spawns": fold["spawns"][-1]["type"] if fold["spawns"] else None,
            "spawned": fold["spawns"][-20:],
            "started": fold["started"],
            "last_ts": fold["last_ts"],
            "idle_s": int(age // 10 * 10),
            "in_tool": fold["open_tool"],
            "result": fold["result"],
            "n_actions": fold["n_actions"],
            "recent_actions": fold["recent_actions"],
            "_returns": fold["returns"],
        })
    return out


def _link_workers(workers: list[dict]) -> list[dict]:
    """Match each subagent to the spawn line in its parent's log (same session, same type, in order)
    → a readable label, the spawn id, and the result packet if the child's own stop didn't carry it.
    Fills parent.children. Mutates and returns `workers`."""
    by_id = {w["worker_id"]: w for w in workers}
    kids: dict[str, list[dict]] = {}
    for w in workers:
        if w["is_subagent"]:
            kids.setdefault(w["parent"], []).append(w)
    for pid, children in kids.items():
        parent = by_id.get(pid)
        children.sort(key=lambda c: c.get("started") or "")
        if parent is None:
            continue
        parent["children"] = [c["worker_id"] for c in children]
        free = list(parent.get("spawned") or [])
        for c in children:
            match = next((s for s in free if s.get("child") == c["worker_id"]), None) or \
                next((s for s in free if s["type"] == c["role"] and not s.get("child")), None) or \
                (next((s for s in free if s["type"] == "general-purpose"), None) if c["role"] == "general-purpose" else None)
            if match:
                free.remove(match)
                desc = (match.get("summary") or "").split(": ", 2)[-1]
                c["label"] = desc[:160] or None
                c["spawn_id"] = match.get("tool_use_id")
                if not c.get("result") and match.get("tool_use_id"):
                    c["result"] = (parent.get("_returns") or {}).get(match["tool_use_id"])
            if not c.get("project") and parent.get("project"):
                c["project"] = parent["project"]
    for w in workers:
        w.pop("_returns", None)
        w.pop("spawned", None)
    return workers


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
    proj_ids = {r["id"] for r in rows if _project_path(r) is not None}
    workers = _workers(hub_bus, None, proj_ids)
    hub_runs = _agents_in(hub_bus / "agents")

    for e in _read_jsonl(hub_bus / "events.jsonl", limit=400):
        all_events.append(e)

    for row in rows:
        pdir = _project_path(row)
        gate = _gate_of(row["next"])   # the registry next-action text is the gate signal
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
            registry = _read_jsonl(pdir / "runs" / "registry.jsonl")
            item["n_runs"] = sum(1 for r in registry if r.get("run_id"))
            item["best"] = _best_metric(registry)
            item["inflight"] = _inflight_runs(pdir)
            item["loop_active"] = (pdir / ".bus" / ".loop-active").exists()
            item["agents"] = _launched_agents(pdir)
            item["directives"] = _directive_threads(pdir / ".bus", default_target=row["id"])
            ctrl = pdir / "control.yaml"
            env = (_load_yaml(ctrl).get("gate2_envelope") if ctrl.exists() else None)
            if env:   # only projects with an envelope block carry the burn-down chip
                item["envelope"] = envelope_accounting(pdir, env)
            pevents = _read_jsonl(pdir / ".bus" / "events.jsonl", limit=80)
            item["events"] = pevents[-12:]
            all_events.extend(pevents)
            workers.extend(_workers(pdir / ".bus", row["id"], proj_ids))
        items.append(item)

    # hub-bus workers promoted to a project (its /improve worktrees) count toward that project too
    for item in items:
        item["n_workers"] = sum(1 for w in workers if w["project"] == item["id"] and w["status"] != "done")
    runs = hub_runs + [a for it in items for a in (it.get("agents") or [])]
    _join_runs(workers, runs)
    _link_workers(workers)
    workers.sort(key=lambda w: w.get("last_ts") or "")

    all_events.sort(key=lambda e: e.get("ts", ""))
    # gates_waiting counts gates that still need the PI's SIGNATURE — a signed-but-unconsumed gate
    # renders in "Needs you" as 'signed, waiting for the agent' but no longer lights the badge/beacon
    # (you already acted; the wait is the agent's). Still a subset of the panel's cards, so the badge
    # can never light with an empty panel.
    held = slots()   # compute once (was called twice)
    return {
        "now": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "editor": editor_scheme(),
        "items": items,
        "events": all_events[-200:],
        "escalations": _escalations(all_events),
        "notebook": _notebook_status(),
        "slots": {"in_use": len(held), "cap": slot_cap(), "held": held},
        "directives": _directive_threads(hub_bus),
        "workers": workers[-200:],
        "campaigns": campaigns(rows),
        "gates_waiting": sum(1 for it in items if it["gate"] and not it["gate_signed"]),
        "cold": len(rows) == 0,
        "runs": sorted(runs, key=lambda r: r.get("created") or r.get("started") or "", reverse=True)[:100],
        "hub_agents": hub_runs,
        "attention": _attention(items, all_events, workers, runs),
        "executor": executor_status(),
        "skills": (executor.SKILL_REGISTRY if executor else {}),
        "workflow": _workflow_view(),
    }


def _workflow_view() -> dict:
    try:
        return workflow.ui_view(HUB)
    except Exception as e:  # noqa: BLE001 — a broken manifest shows as a problem, never a blank dashboard
        return {"error": str(e)}


def _join_runs(workers: list[dict], runs: list[dict]) -> None:
    """A headless run's orchestrator IS a worker (its session id names the trace file): tag it with
    the run so the roster nests run → session → subagents, and give it the run's role/label."""
    by_sid = {r["session_id"]: r for r in runs if r.get("session_id")}
    for w in workers:
        r = by_sid.get(w["worker_id"]) or (by_sid.get(w.get("session_id")) if w.get("is_subagent") else None)
        if not r:
            continue
        w["run_id"] = r["run_id"]
        if not w.get("is_subagent"):
            w["label"] = r.get("command") or r.get("prompt_summary")
            if r.get("status") in ("completed", "failed", "timeout", "killed", "waiting_input") and w["status"] != "done":
                w["status"] = "done" if r["status"] != "waiting_input" else "idle"


# ── attention: one "needs you" queue ─────────────────────────────────────────

def _lab_attention(items: list[dict], events: list[dict], workers: list[dict]) -> list[dict]:
    """Lab-derived items in the executor's normalized shape (gates, escalations, stalled runs,
    stuck subagents). Run-derived items come from executor.attention."""
    out = []
    for it in items:
        if it.get("gate") and not it.get("gate_signed") and it["gate"] in (1, 2, 3):
            g = it["gate"]
            out.append({"id": f"gate:{it['id']}:{g}", "kind": "gate", "sev": "block", "ts": it.get("updated"),
                        "target": it["id"], "idea": it["id"], "run_id": None, "skill": None,
                        "title": f"Gate {g} — {it.get('title') or it['id']}",
                        "body": it.get("next") or "", "detail": {"gate": g},
                        "actions": [{"id": "sign", "label": f"review & sign Gate {g}"}]
                        + [{"id": "bundle", "label": "review bundle"}]})
        for r in it.get("inflight") or []:
            if r.get("state") == "stalled":
                out.append({"id": f"stalled:{it['id']}:{r.get('run_id')}", "kind": "stalled", "sev": "warn",
                            "ts": None, "target": it["id"], "idea": it["id"], "run_id": None, "skill": None,
                            "title": f"Run {r.get('run_id')} looks stalled", "body": f"stage {r.get('stage')}",
                            "detail": r, "actions": [{"id": "dismiss", "label": "dismiss"}]})
    try:
        for pr in workflow.proposals(HUB):
            what = ("replace the method of /" if pr.get("kind") == "method" else "add instructions to "
                    + ("stage " if pr.get("kind") == "stage" else "role " if pr.get("kind") == "role" else "/"))
            out.append({"id": f"proposal:{pr['id']}", "kind": "proposal", "sev": "warn", "ts": pr.get("ts"),
                        "target": pr.get("study") or "hub", "idea": pr.get("study"), "run_id": None, "skill": None,
                        "title": "An agent suggests: " + what + str(pr.get("name")) + (f" ({pr['study']})" if pr.get("study") else ""),
                        "body": pr.get("why") or pr.get("text", "")[:200], "detail": {"proposal": pr["id"]},
                        "actions": [{"id": "proposal", "label": "review"}]})
    except Exception:  # noqa: BLE001 — never blank the dashboard
        pass
    for e in _escalations(events):
        out.append({"id": f"esc:{e['id']}", "kind": "escalation", "sev": "warn" if e.get("severity") != "high" else "block",
                    "ts": e.get("ts"), "target": e.get("source"), "idea": e.get("source"), "run_id": None,
                    "skill": None, "title": "Escalation from " + str(e.get("source")), "body": e.get("detail") or "",
                    "detail": e, "actions": [{"id": "reply", "label": "reply"}, {"id": "resolve", "label": "mark handled"}]})
    for w in workers:
        if w.get("is_subagent") and w["status"] == "idle" and not w.get("in_tool") and w.get("idle_s", 0) >= _SUBAGENT_STUCK_S:
            out.append({"id": f"subagent:{w['worker_id']}:{w.get('last_ts')}", "kind": "subagent", "sev": "warn",
                        "ts": w.get("last_ts"), "target": w.get("project") or "hub", "idea": w.get("idea"),
                        "run_id": w.get("run_id"), "skill": None,
                        "title": f"{w.get('role')} has been silent for {w['idle_s'] // 60} min",
                        "body": w.get("label") or "", "detail": {"worker_id": w["worker_id"]},
                        "actions": [{"id": "inspect", "label": "inspect"}, {"id": "dismiss", "label": "dismiss"}]})
    return out


def _attention(items, events, workers, runs) -> list[dict]:
    extra = _lab_attention(items, events, workers)
    if executor is None:
        return extra
    try:
        lab = executor.Lab(HUB)
        manifests = []
        for _t, _w, path, m in executor.all_runs(lab):
            manifests.append((path, m))
        brake = executor.brake(lab, [m for _p, m in manifests])
        return executor.attention.collect(lab, runs=manifests, extra=extra, brake_reason=brake)
    except Exception:  # noqa: BLE001 — never blank the dashboard
        return extra


_EXEC_CACHE: dict = {"ts": 0.0, "key": None, "value": None}


def executor_status() -> dict:
    """Launching possible? Which CLIs exist? Caps and load. The CLI probe (a subprocess) is cached 30 s."""
    if executor is None:
        return {"available": False, "enabled": False, "reason": "tools/executor is missing"}
    lab = executor.Lab(HUB)
    key = str(lab.hub)
    if _EXEC_CACHE["key"] == key and time.time() - _EXEC_CACHE["ts"] < 30 and _EXEC_CACHE["value"]:
        base = dict(_EXEC_CACHE["value"])
    else:
        try:
            base = executor.health(lab)
        except Exception as e:  # noqa: BLE001
            base = {"enabled": False, "error": str(e)}
        _EXEC_CACHE.update(ts=time.time(), key=key, value=base)
    prog = lab.prog()
    runs = [m for *_x, m in executor.all_runs(lab)]
    # settings the PI can change here: always fresh (the cached part is only the CLI probes)
    base.update(backend=prog.get("backend") or "claude", permission_mode=prog.get("permission_mode") or "auto",
                caps=executor.caps(lab), config={k: prog.get(k) for k in executor.CONFIG_KEYS if k in prog},
                auto_spawn_on_gate1=bool((lab.dashboard_cfg() or {}).get("auto_spawn_on_gate1")))
    base.update(available=True, enabled=bool(prog.get("enabled")),
                active=sum(1 for m in runs if m.get("status") in executor.ACTIVE),
                queued=sum(1 for m in runs if m.get("status") == "queued"),
                waiting=sum(1 for m in runs if m.get("status") in executor.PAUSED))
    lt = base.get("last_tick")
    if isinstance(lt, dict):
        base["last_tick"] = {k: v for k, v in lt.items() if k != "ts"}   # keep the SSE signature stable
    base.pop("daily", None)
    return base
