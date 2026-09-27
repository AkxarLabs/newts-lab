"""One "needs you" queue for everything a run can want from the PI.

Item: {id, kind, sev, ts, target, idea, run_id, title, body, detail, actions[]}
  kind ∈ question · permission · denied · crashed · report · needs_pi · brake   (run-derived, here)
       + gate · escalation · stalled · subagent        (lab-derived, merged in by dashboard/sources.py)
  sev  ∈ block (the lab is waiting on you) · warn · info
  id   is stable (derived from the underlying record), so a dismissal is durable, and a genuinely new
       occurrence (a new attempt, a new question) gets a new id and re-surfaces.

Acks: lab/.bus/attention-acks.jsonl  {ts, id, action: dismiss|seen, by}
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .lab import Lab, read_jsonl
from .manifest import append_jsonl, now, parse_ts, run_dir

SEV_ORDER = {"block": 0, "warn": 1, "info": 2}
_NEEDS_PI_TITLE = {
    "gate1": "Gate 1 — a proposal awaits your approval",
    "gate2": "Gate 2 — a FULL run needs a signed envelope",
    "gate3": "Gate 3 — a paper awaits final sign-off (in a session)",
    "kill_criteria": "Kill criteria fired — kill or park?",
    "null_result": "Null / negative result — how to proceed?",
    "spawn_type": "Confirm the project type before spawning",
    "other": "The agent needs a PI decision",
}


def _item(kind, sev, iid, m, title, body="", detail=None, actions=None, ts=None) -> dict:
    return {"id": iid, "kind": kind, "sev": sev, "ts": ts or m.get("status_ts") or now(),
            "target": m.get("target"), "idea": m.get("subject"), "run_id": m.get("run_id"),
            "skill": m.get("skill"), "title": title, "body": body, "detail": detail or {},
            "actions": actions or []}


def run_items(lab: Lab, runs: list[tuple[Path, dict]]) -> list[dict]:
    """Items derived from run manifests (+ their sidecars). `runs` = [(manifest_path, manifest)]."""
    out = []
    for path, m in runs:
        if m.get("schema") != 2:
            continue
        rid, st, att = m.get("run_id"), m.get("status"), m.get("attempt") or 0
        label = m.get("command") or f"/{m.get('skill')}"
        rd = run_dir(Path(path).parent, rid)
        if st == "waiting_input" and m.get("pending_question"):
            pq = m["pending_question"]
            qs = (pq.get("input") or {}).get("questions") or []
            first = qs[0].get("question") if qs and isinstance(qs[0], dict) else "The agent asked a question"
            out.append(_item("question", "block", f"question:{rid}:{att}", m, first,
                             body=f"{label} is paused until you answer.",
                             detail={"questions": qs, "tool_use_id": pq.get("tool_use_id")},
                             actions=[{"id": "answer", "label": "answer"}, {"id": "stop", "label": "stop run"}]))
        # pending permission requests (only when permission_wait_seconds > 0)
        for req in sorted(rd.glob("perm-*.json")) if rd.is_dir() else []:
            if req.name.endswith(".decision.json"):
                continue
            n = req.stem.split("-")[-1]
            if (rd / f"perm-{n}.decision.json").exists() or st not in ("running", "starting", "resuming"):
                continue
            try:
                r = json.loads(req.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            inp = r.get("input") or {}
            what = inp.get("command") or inp.get("file_path") or inp.get("url") or ""
            out.append(_item("permission", "block", f"perm:{rid}:{n}", m,
                             f"Allow {r.get('tool')}?", body=str(what)[:300],
                             detail={"n": int(n) if str(n).isdigit() else n, "tool": r.get("tool"), "input": inp},
                             actions=[{"id": "allow", "label": "allow once"}, {"id": "deny", "label": "deny"}],
                             ts=r.get("ts")))
        den = int(m.get("denials") or 0)
        plog = rd / "permissions.jsonl"
        denied = [r for r in read_jsonl(plog, tail=200) if r.get("decision") == "deny" and r.get("by") != "PI"] \
            if plog.exists() else []
        den = max(den, len(denied))
        if den:
            tools = sorted({str(r.get("tool")) for r in denied if r.get("tool")})
            out.append(_item("denied", "warn", f"denied:{rid}:{den}", m,
                             f"{den} action(s) were denied in {label}",
                             body=("Denied: " + ", ".join(tools)) if tools else
                             "The permission mode is PI-owned config (agents.programmatic.permission_mode).",
                             detail={"count": den, "recent": denied[-5:]},
                             actions=[{"id": "dismiss", "label": "dismiss"}]))
        kept = bool(m.get("campaign")) and str(m.get("created_by") or "").startswith("campaign")
        if st in ("failed", "timeout", "killed") and m.get("reason") != "cancelled" and not kept:
            # (a campaign's own runs are retried by its keeper; a campaign that needs you says so itself)
            can = bool(m.get("session_id"))
            out.append(_item("crashed", "warn", f"crashed:{rid}:{att}", m,
                             f"{label} {st}", body=m.get("reason") or (m.get("last_message") or "")[:300],
                             actions=([{"id": "resume", "label": "resume"}] if can else [])
                             + [{"id": "tail", "label": "transcript"}, {"id": "dismiss", "label": "dismiss"}]))
        if st == "completed":
            rep = m.get("report") or {}
            needs = rep.get("needs_pi")
            nxt = rep.get("next")
            actions = [{"id": "tail", "label": "transcript"}]
            if nxt:
                actions.append({"id": "next", "label": f"run {nxt}", "command": nxt})
            actions += [{"id": "reply", "label": "reply"}, {"id": "dismiss", "label": "dismiss"}]
            if needs:
                out.append(_item("needs_pi", "block", f"needs:{rid}:{att}", m,
                                 _NEEDS_PI_TITLE.get(needs, _NEEDS_PI_TITLE["other"]),
                                 body=rep.get("summary") or "", detail={"needs_pi": needs, "next": nxt},
                                 actions=actions))
            else:
                out.append(_item("report", "info", f"report:{rid}:{att}", m, f"{label} finished",
                                 body=rep.get("summary") or (m.get("last_message") or "")[:400],
                                 detail={"next": nxt}, actions=actions))
    return out


def brake_item(reason: str | None) -> list[dict]:
    if not reason:
        return []
    day = time.strftime("%Y-%m-%d")
    return [{"id": f"brake:{day}", "kind": "brake", "sev": "info", "ts": now(), "target": "hub",
             "idea": None, "run_id": None, "title": "Daily usage brake engaged", "body": reason,
             "detail": {}, "actions": [{"id": "dismiss", "label": "dismiss"}]}]


def load_acks(lab: Lab) -> dict[str, str]:
    acks: dict[str, str] = {}
    for a in read_jsonl(lab.acks_ledger, tail=5000):
        if a.get("id") and a.get("action"):
            acks[str(a["id"])] = str(a["action"])
    return acks


def apply_acks(lab: Lab, items: list[dict]) -> list[dict]:
    acks = load_acks(lab)
    out = []
    for it in items:
        a = acks.get(it["id"])
        if a == "dismiss":
            continue
        out.append({**it, "seen": a == "seen"})
    out.sort(key=lambda it: (SEV_ORDER.get(it.get("sev"), 3), -(parse_ts(it.get("ts")) or 0)))
    return out


def ack(lab: Lab, item_id: str, action: str = "dismiss", by: str = "PI via dashboard") -> dict:
    if action not in ("dismiss", "seen"):
        raise ValueError("action must be dismiss | seen")
    if not isinstance(item_id, str) or not item_id or len(item_id) > 200:
        raise ValueError("invalid attention id")
    rec = {"ts": now(), "id": item_id, "action": action, "by": by}
    append_jsonl(lab.acks_ledger, rec)
    return rec


def collect(lab: Lab, runs: list[tuple[Path, dict]] | None = None, extra: list[dict] | None = None,
            brake_reason: str | None = None) -> list[dict]:
    """Run-derived items + any lab-derived `extra` items, acks applied, most urgent first."""
    if runs is None:
        from .manifest import all_runs
        runs = [(p, m) for _t, _w, p, m in all_runs(lab)]
    return apply_acks(lab, run_items(lab, runs) + (extra or []) + brake_item(brake_reason))
