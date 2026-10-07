"""What needs the PI, and the executor's status — the dashboard's half of "Needs you". Run-derived items
come from the executor (tools/executor/attention.py); this adds what only the lab's files show: gates
waiting for a signature, escalations, stalled training runs, quiet subagents, agents' proposals, campaigns
that stopped, and runs whose supervisor went silent.

    collect(items, escalations, workers, runs)  every item, in the executor's normalized shape
    executor_status() / recheck_executor()      launching, the CLIs, caps and load (CLI probes cached 30 s)
"""

from __future__ import annotations

import time

import ctx
from workers import SUBAGENT_STUCK_S

try:
    import executor
except Exception:  # noqa: BLE001 — a broken/missing executor must never blank the dashboard
    executor = None
workflow = ctx.tool("workflow")


def lab_items(items: list[dict], escalations: list[dict], roster: list[dict]) -> list[dict]:
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
                        "actions": [{"id": "sign", "label": f"review & approve Gate {g}"}]
                        + [{"id": "bundle", "label": "review bundle"}]})
        for r in it.get("inflight") or []:
            if r.get("state") == "stalled":
                out.append({"id": f"stalled:{it['id']}:{r.get('run_id')}", "kind": "stalled", "sev": "warn",
                            "ts": None, "target": it["id"], "idea": it["id"], "run_id": None, "skill": None,
                            "title": f"Run {r.get('run_id')} looks stalled", "body": f"stage {r.get('stage')}. Open the run to check, or dismiss.",
                            "detail": r, "actions": [{"id": "dismiss", "label": "dismiss"}]})
    try:
        for pr in workflow.proposals(ctx.HUB):
            what = ("replace the method of /" if pr.get("kind") == "method" else "add instructions to "
                    + ("stage " if pr.get("kind") == "stage" else "role " if pr.get("kind") == "role" else "/"))
            out.append({"id": f"proposal:{pr['id']}", "kind": "proposal", "sev": "warn", "ts": pr.get("ts"),
                        "target": pr.get("study") or "hub", "idea": pr.get("study"), "run_id": None, "skill": None,
                        "title": "An agent suggests: " + what + str(pr.get("name")) + (f" ({pr['study']})" if pr.get("study") else ""),
                        "body": pr.get("why") or pr.get("text", "")[:200], "detail": {"proposal": pr["id"]},
                        "actions": [{"id": "proposal", "label": "review"}]})
    except Exception:  # noqa: BLE001 — never blank the dashboard
        pass
    for e in escalations:
        out.append({"id": f"esc:{e['id']}", "kind": "escalation", "sev": "warn" if e.get("severity") != "high" else "block",
                    "ts": e.get("ts"), "target": e.get("source"), "idea": e.get("source"), "run_id": None,
                    "skill": None, "title": "Escalation from " + str(e.get("source")), "body": e.get("detail") or "",
                    "detail": e, "actions": [{"id": "reply", "label": "reply"}, {"id": "resolve", "label": "mark handled"}]})
    for w in roster:
        if w.get("is_subagent") and w["status"] == "idle" and not w.get("in_tool") and w.get("idle_s", 0) >= SUBAGENT_STUCK_S:
            out.append({"id": f"subagent:{w['worker_id']}:{w.get('last_ts')}", "kind": "subagent", "sev": "warn",
                        "ts": w.get("last_ts"), "target": w.get("project") or "hub", "idea": w.get("idea"),
                        "run_id": w.get("run_id"), "skill": None,
                        "title": f"{w.get('role')} has been silent for {w['idle_s'] // 60} min",
                        "body": w.get("label") or "", "detail": {"worker_id": w["worker_id"]},
                        "actions": [{"id": "inspect", "label": "inspect"}, {"id": "dismiss", "label": "dismiss"}]})
    return out


_HEARTBEAT_STALE_S = 120


def collect(items, escalations, roster, runs) -> list[dict]:
    extra = lab_items(items, escalations, roster)
    import artifacts  # noqa: PLC0415 — a question an agent left with something it made
    extra += artifacts.attention_items()
    try:   # a campaign that stopped and needs the PI (stalled, paused on a sign-in problem) — one item for it
        from executor import campaigns as _camps  # noqa: PLC0415
        for c in _camps.all_states(executor.Lab(ctx.HUB)) if executor else []:
            if c.get("status") in ("stalled", "paused") and c.get("paused_reason") and c.get("paused_reason") != "paused by the PI":
                extra.append({"id": f"campaign:{c['name']}:{c.get('status')}:{len(c.get('cycles') or [])}", "kind": "campaign",
                              "sev": "block", "ts": (c.get("events") or [{}])[-1].get("ts"), "target": "hub", "idea": None,
                              "run_id": None, "skill": "autopilot", "title": f"Campaign {c['name']} stopped and needs you",
                              "body": c.get("paused_reason") or "", "detail": {"campaign": c["name"]},
                              "actions": [{"id": "campaign", "label": "open the campaign"}]})
            for q in (c.get("questions") or [])[-3:]:
                extra.append({"id": f"cq:{c['name']}:{q.get('ts')}", "kind": "question", "sev": "warn", "ts": q.get("ts"),
                              "target": "hub", "idea": None, "run_id": None, "skill": "autopilot",
                              "title": q.get("question") or "A campaign pass asked a question",
                              "body": f"left by campaign {c['name']} . It carried on without an answer. Reply with a note and the next pass reads it.",
                              "detail": {"campaign": c["name"]}, "actions": [{"id": "campaign", "label": "open the campaign"}]})
    except Exception:  # noqa: BLE001
        pass
    for r in runs or []:   # a live run whose supervisor stopped reporting (the next tick reconciles it)
        age = r.get("heartbeat_age_s")
        if r.get("schema") == 2 and age is not None and age > _HEARTBEAT_STALE_S:
            extra.append({"id": f"stale:{r['run_id']}", "kind": "stalled", "sev": "warn", "ts": r.get("status_ts"),
                          "target": r.get("subject") or "hub", "idea": r.get("subject"), "run_id": r["run_id"],
                          "skill": r.get("skill"), "title": f"{r.get('command') or r['run_id']} has gone quiet",
                          "body": f"no heartbeat from its supervisor for {int(age // 60)} min — the scheduler checks "
                                  "whether it is still alive", "detail": {"heartbeat_age_s": age},
                          "actions": [{"id": "tail", "label": "open"}, {"id": "stop", "label": "stop"}]})
    if executor is None:
        return extra
    try:
        lab = executor.Lab(ctx.HUB)
        manifests = []
        for _t, _w, path, m in executor.all_runs(lab):
            manifests.append((path, m))
        brake = executor.brake(lab, [m for _p, m in manifests])
        return executor.attention.collect(lab, runs=manifests, extra=extra, brake_reason=brake)
    except Exception:  # noqa: BLE001 — never blank the dashboard
        return extra


_EXEC_CACHE: dict = {"ts": 0.0, "key": None, "value": None}
ctx.on_change(lambda _old, _new: _EXEC_CACHE.update(ts=0))


def recheck_executor(cli: bool = False) -> None:
    """The next snapshot re-reads the executor's status; `cli` also re-probes the agent CLIs (after a
    sign-in, an install, a backend change)."""
    _EXEC_CACHE["ts"] = 0
    if cli and executor is not None:
        executor.backends.forget_checks()


def executor_status() -> dict:
    """Launching possible? Which CLIs exist? Caps and load. The CLI probe (a subprocess) is cached 30 s."""
    if executor is None:
        return {"available": False, "enabled": False, "reason": "tools/executor is missing"}
    lab = executor.Lab(ctx.HUB)
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
