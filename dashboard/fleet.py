"""One dashboard over many labs: a small summary of every lab — this computer's and every remote one you
keep connected — so "what needs me, what is running" is answered across all of them at once.

  lab_summary(hub)   what one lab looks like right now (from its own files: runs, registry, campaigns) —
                     served by every lab's dashboard as GET /api/summary (a remote one is read through its
                     SSH tunnel with that server's session cookie)
  keeper             a thread: keeps the remote labs marked `keep_connected` connected (key auth only —
                     a machine that needs a password or a code waits for you to press Connect) and reads
                     their summaries every ~15 s
  fleet()            GET /api/fleet (local-only): every lab with its summary, the current one marked

Summaries are cheap (no snapshot, no world): counts, the top items that need you, running runs, campaigns.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import time
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402
import machines  # noqa: E402

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCAL_TTL = 10.0
POLL_S = 15.0
_GATE_RE = re.compile(r"\bgate\s*-?\s*([123])\b", re.I)
_state = {"thread": None, "stop": None, "attempts": {}}


def _gate_signed(hub: Path, lab, slug: str, gate: int) -> bool:
    return ctx.tool("markers").gate_signed(hub, slug, gate, lab.project_dir(slug))


def lab_summary(hub: Path) -> dict:
    """What one lab needs and is doing, from its files. Cached briefly."""
    hub = Path(hub)
    key = str(hub)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _LOCAL_TTL:
        return hit[1]
    ex = sources.executor
    out = {"path": str(hub), "name": None, "needs": 0, "top": [], "running": 0, "queued": 0, "waiting": 0,
           "active_runs": [], "campaigns": [], "studies": 0, "ok": True}
    try:
        from product import lab_name  # noqa: PLC0415 — dashboard/ is on sys.path
        out["name"] = lab_name(hub)
    except Exception:  # noqa: BLE001
        out["name"] = hub.name
    if ex is None:
        return out
    try:
        lab = ex.Lab(hub)
        manifests = [(p, m) for *_x, p, m in ex.all_runs(lab)]
        runs = [m for _p, m in manifests]
        out["running"] = sum(1 for m in runs if m.get("status") in ("starting", "running", "resuming"))
        out["queued"] = sum(1 for m in runs if m.get("status") == "queued")
        out["waiting"] = sum(1 for m in runs if m.get("status") == "waiting_input")
        out["active_runs"] = [{"run_id": m["run_id"], "title": m.get("command") or m.get("label") or m.get("skill"),
                               "status": m.get("status"), "subject": m.get("subject")}
                              for m in sorted(runs, key=lambda m: m.get("created") or "", reverse=True)
                              if m.get("status") in ("starting", "running", "resuming", "waiting_input")][:5]
        items = [i for i in ex.attention.collect(lab, runs=manifests) if i.get("sev") == "block"]
        rows = lab.registry_rows()
        out["studies"] = len(rows)
        for r in rows:
            m = _GATE_RE.search(r.get("next") or "")
            if m and r.get("state") not in ("final", "killed", "parked") and not _gate_signed(hub, lab, r["id"], int(m.group(1))):
                items.append({"kind": "gate", "title": f"Gate {m.group(1)} — {r.get('title') or r['id']}", "idea": r["id"],
                              "detail": {"gate": int(m.group(1))}})
        from executor import campaigns  # noqa: PLC0415
        for c in campaigns.summary(lab):
            if c["status"] in ("active", "finishing", "stopping", "paused", "stalled"):
                out["campaigns"].append({k: c.get(k) for k in ("name", "status", "cycles", "deadline", "used_minutes",
                                                               "gate3_auto", "paused_reason")}
                                        | {"waiting": sum(1 for v in (c.get("studies") or {}).values() if v.get("waiting"))})
            if c["status"] == "stalled" or (c["status"] == "paused" and c.get("paused_reason")
                                             and c["paused_reason"] != "paused by the PI"):
                items.append({"kind": "campaign", "title": f"Campaign {c['name']} stopped — it needs you",
                              "detail": {"campaign": c["name"]}})
        out["needs"] = len(items)
        out["top"] = [{"kind": i.get("kind"), "title": i.get("title"), "run_id": i.get("run_id"), "idea": i.get("idea"),
                       "detail": {k: v for k, v in (i.get("detail") or {}).items() if k in ("gate", "campaign")}}
                      for i in items[:6]]
        out["scheduler_age"] = ex.scheduler.lease(lab).get("age")
    except Exception as e:  # noqa: BLE001 — one unreadable lab never breaks the overview
        out.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
    out["sig"] = hashlib.sha1(json.dumps([out["needs"], out["running"], out["queued"], out["waiting"], out["top"],
                                          out["campaigns"]], sort_keys=True, default=str).encode()).hexdigest()[:12]
    _CACHE[key] = (time.time(), out)
    return out


# ── remote labs ──────────────────────────────────────────────────────────────────────────────────
def _fetch(conn) -> dict | None:
    if not conn.cookie:
        conn.refresh_cookie()
    try:
        c = http.client.HTTPConnection("127.0.0.1", conn.lport, timeout=8)
        c.request("GET", "/api/summary", headers={"Cookie": conn.cookie or "", "Host": f"127.0.0.1:{conn.lport}"})
        r = c.getresponse()
        body = r.read()
        if r.status == 403:
            conn.refresh_cookie()
            return None
        return json.loads(body or b"{}") if r.status == 200 else None
    except (OSError, ValueError, http.client.HTTPException):
        return None


def _keep_once() -> None:
    m = machines
    for mach in m._load():
        for lab in mach.get("labs") or []:
            if not lab.get("keep_connected"):
                continue
            conn = m.conn_for(mach["id"], lab["path"])
            if conn is None:
                continue
            if conn.state == "connected" and conn.alive():
                summ = _fetch(conn)
                if summ:
                    conn.summary, conn.summary_ts = summ, time.time()
                continue
            if conn.state in ("starting", "waiting", "reconnecting") or (mach.get("reach") or {}).get("kind") == "auth":
                continue   # coming up, or it needs an interactive sign-in the PI starts
            last = _state["attempts"].get(conn.key, 0)
            if time.time() - last < 120:
                continue
            _state["attempts"][conn.key] = time.time()
            threading.Thread(target=conn.connect, args=(False,), name=f"fleet-connect-{conn.key}", daemon=True).start()


def start_keeper() -> bool:
    if _state["thread"] and _state["thread"].is_alive():
        return False
    stop = threading.Event()

    def loop():
        while not stop.wait(POLL_S if _state.get("ran") else 3.0):
            _state["ran"] = True
            try:
                _keep_once()
            except Exception:  # noqa: BLE001 — the overview must never take the server down
                pass

    t = threading.Thread(target=loop, name="fleet-keeper", daemon=True)
    _state.update(thread=t, stop=stop)
    t.start()
    return True


def fleet() -> tuple[dict, int]:
    """Every lab: this computer's (from the lab list) and every remote one registered on a machine."""
    import product  # noqa: PLC0415
    local, _ = product.labs_list()
    remote_now = ctx.REMOTE
    out = []
    for lab in local.get("labs") or []:
        if not lab.get("exists"):
            continue
        summ = lab_summary(Path(lab["path"]))
        out.append({"kind": "local", "key": "local::" + lab["path"], "path": lab["path"], "name": lab.get("name") or summ.get("name"),
                    "machine": "This computer", "current": bool(lab.get("current")) and not remote_now,
                    "state": "here", "summary": summ})
    for mach in machines._load():
        for lab in mach.get("labs") or []:
            c = machines.CONNS.get(f"{mach['id']}::{lab['path']}")
            summ = getattr(c, "summary", None) if c else None
            age = (time.time() - c.summary_ts) if (c and getattr(c, "summary_ts", None)) else None
            out.append({"kind": "remote", "key": f"{mach['id']}::{lab['path']}", "machine_id": mach["id"], "path": lab["path"],
                        "machine": mach.get("name") or mach["id"], "host": mach.get("host"),
                        "name": (c.name if c and c.name else None) or lab.get("name") or lab["path"].rstrip("/").split("/")[-1],
                        "current": remote_now is c and c is not None, "state": c.state if c else "idle",
                        "keep_connected": bool(lab.get("keep_connected")), "summary": summ,
                        "summary_age": round(age) if age is not None else None,
                        "needs_sign_in": (mach.get("reach") or {}).get("kind") == "auth"})
    total = sum(((x.get("summary") or {}).get("needs") or 0) for x in out)
    elsewhere = sum(((x.get("summary") or {}).get("needs") or 0) for x in out if not x.get("current"))
    return {"ok": True, "labs": out, "needs_total": total, "needs_elsewhere": elsewhere,
            "running_total": sum(((x.get("summary") or {}).get("running") or 0) for x in out)}, 200


def set_keep(body: dict) -> tuple[dict, int]:
    """Keep a remote lab connected in the background (the overview reads it), or stop."""
    mid, path = str(body.get("id") or ""), str(body.get("path") or "")
    mach = machines._get(mid)
    if not mach:
        return {"error": "no such machine"}, 404
    hit = False
    for lab in mach.get("labs") or []:
        if lab.get("path") == path:
            lab["keep_connected"] = bool(body.get("keep"))
            hit = True
    if not hit:
        return {"error": "no such lab on that machine"}, 404
    machines._put(mach)
    return {"ok": True, "note": "kept connected in the background" if body.get("keep") else "no longer kept connected"}, 200
