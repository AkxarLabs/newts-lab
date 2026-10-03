"""The campaign keeper: keeps a PI-signed campaign going until it is done, whatever happens to single runs.

A campaign (lab/campaigns/<name>.md, signed by the PI) is carried by repeated `/autopilot continue <brief>`
**cycles**. Each cycle is one portfolio pass: it reads the state of every idea, decides the next step for
each, and DISPATCHES that step (`lab_bus.py emit campaign_dispatch --data skill=… --data target=…`) instead
of running it inline. The keeper — this module, called from `scheduler.tick()` under the tick lock, i.e.
executor code, never an agent — does the rest:

  * starts the next cycle after each one ends, depending on HOW it ended (not only on a clean finish):
      completed → after `repeat_minutes` · usage limit → when the limit lifts · timeout → right away ·
      transient error → backoff 2/5/15/30/60 min · sign-in problem → pause and ask the PI ·
      stopped by the PI → pause
  * validates every dispatch (a launchable procedure, never finalize or another campaign; a study that
    belongs to this campaign and isn't waiting for the PI; no duplicate; the brief's parallelism) and
    enqueues it as a normal executor run (parent = the cycle), so it is capped, traced, retried and shown
  * retries a dispatched run that hit a timeout / usage limit / transient error (up to 3 times)
  * marks a study as waiting when its run reports `needs_pi` — only that study waits; the campaign goes on
  * records Gate 3 itself — only if the brief delegates it — once a paper passed review AND the keeper's
    own run of the paper audits is clean, then launches /finalize (tools/gate3.py)
  * stops on the deadline, the agent-minutes budget, the cycle cap, the PI's Stop, a cycle reporting
    `campaign=done`, or N failures in a row (→ "stalled", which asks the PI) — ending with one final
    report cycle (the morning report)

State: lab/.bus/campaigns/<name>.json — written only here and by the dashboard (the PI's pause/stop/
revoke/hold), both under the scheduler lock; the signature guard denies agents.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from .lab import HUB_TARGET, Lab, pos_float, pos_int, read_jsonl
from .manifest import ACTIVE, TERMINAL, all_runs, now, parse_ts, read_manifest, run_dir, transition
from .procs import is_locked
from .spec import NEVER, RunSpec, SpecError, SKILL_REGISTRY

BACKOFF_MIN = [2, 5, 15, 30, 60]
LIVE = ACTIVE | {"queued", "waiting_input"}


def _session_up(path, m: dict) -> bool:
    """A live session is still open for this run (its supervisor holds the run's lock)."""
    return m.get("transport") == "live" and is_locked(run_dir(Path(path).parent, m["run_id"]) / "lock")
RETRYABLE = {"timeout", "usage_limit", "transient"}
MAX_CHILD_RETRIES = 3
DISPATCHABLE_NOT = {"autopilot", "setup-lab", "configure", "discuss", "compete"} | set(NEVER)
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def state_dir(lab: Lab) -> Path:
    return lab.lab / ".bus" / "campaigns"


def state_path(lab: Lab, name: str) -> Path:
    if not _NAME_RE.match(name or ""):
        raise ValueError(f"bad campaign name {name!r}")
    return state_dir(lab) / f"{name}.json"


def load(lab: Lab, name: str) -> dict | None:
    try:
        return json.loads(state_path(lab, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(lab: Lab, st: dict) -> None:
    p = state_path(lab, st["name"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def all_states(lab: Lab) -> list[dict]:
    d = state_dir(lab)
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def create(lab: Lab, brief_rel: str, *, hours: float = 12, agent_minutes: float = 0, cycle_minutes: float = 90,
           repeat_minutes: float = 20, max_cycles: int = 0, gate3_auto: bool = False, backend: str | None = None,
           model: str | None = None, child_minutes: float | None = None, max_failures: int = 4) -> dict:
    """Start keeping a signed campaign (the dashboard calls this right after the PI signs the brief)."""
    name = Path(brief_rel).stem
    if load(lab, name):
        raise ValueError(f"campaign {name} is already being kept")
    t = time.time()
    st = {"schema": 1, "name": name, "file": brief_rel, "status": "active", "created": now(),
          "deadline": _iso(t + hours * 3600) if hours else None,
          "budget": {"agent_minutes": pos_float(agent_minutes, 0.0), "max_cycles": pos_int(max_cycles, 0, 0)},
          "cycle_minutes": pos_float(cycle_minutes, 90.0) or 90.0, "repeat_minutes": pos_float(repeat_minutes, 20.0),
          "child_minutes": pos_float(child_minutes, 0.0) or None, "max_failures": pos_int(max_failures, 4, 1),
          "backend": backend, "model": model, "gate3_auto": bool(gate3_auto),
          "cycles": [], "consecutive_failures": 0, "timeouts_in_a_row": 0, "next_cycle_at": None,
          "used_minutes": 0.0, "studies": {}, "dispatch_log": [], "seen_dispatch": [], "questions": [],
          "gate3_log": [], "events": [{"ts": now(), "what": "started"}]}
    save(lab, st)
    return st


def _event(st: dict, what: str) -> None:
    st.setdefault("events", []).append({"ts": now(), "what": what})
    st["events"] = st["events"][-60:]


# ── the PI's controls (the dashboard, under the scheduler lock) ──────────────────────────────────
def control(lab: Lab, name: str, action: str, study: str | None = None, text: str | None = None,
            index: int | None = None) -> dict:
    """pause | resume | stop | revoke_gate3 | hold | unhold (hold/unhold take a study) | answer (a
    question a pass left on the card: `index` into its questions, `text` = the answer — the next pass
    gets it)."""
    from .manifest import scheduler_lock   # noqa: PLC0415
    from .runs import stop as stop_run       # noqa: PLC0415
    with scheduler_lock(lab):
        st = load(lab, name)
        if not st:
            raise ValueError(f"no campaign {name}")
        if action == "pause":
            st["status"] = "paused"
            _event(st, "paused by the PI")
        elif action == "resume":
            if st["status"] in ("done", "stopped"):
                raise ValueError(f"the campaign is {st['status']}")
            st.update(status="active", consecutive_failures=0, paused_reason=None, next_cycle_at=None)
            _event(st, "resumed by the PI")
        elif action == "stop":
            st["status"] = "stopping"
            _event(st, "stopped by the PI")
        elif action == "revoke_gate3":
            st["gate3_auto"] = False
            _event(st, "Gate-3 delegation revoked by the PI")
        elif action == "answer":
            qs = st.get("questions") or []
            if index is None or not 0 <= int(index) < len(qs) or not (text or "").strip():
                raise ValueError("which question, and what's the answer?")
            qs[int(index)].update(answer=str(text).strip()[:2000], answered_at=now(), delivered=False)
            _event(st, "the PI answered a question — the next pass gets it")
        elif action in ("hold", "unhold"):
            if not study or not _NAME_RE.match(study):
                raise ValueError("which study?")
            st.setdefault("studies", {}).setdefault(study, {})["hold"] = action == "hold"
            _event(st, f"{study}: {'held from' if action == 'hold' else 'released for'} auto-finalizing")
        else:
            raise ValueError(f"unknown action {action!r}")
        save(lab, st)
    if action == "stop":   # outside the lock: stopping takes it itself
        for _t, _w, _p, m in all_runs(lab):
            if m.get("campaign") == name and m.get("status") in LIVE:
                try:
                    stop_run(lab, m["run_id"], by="campaign-stop")
                except (SpecError, OSError):
                    pass
    if action == "revoke_gate3":
        for _t, _w, _p, m in all_runs(lab):
            if m.get("campaign") == name and m.get("skill") == "finalize" and m.get("status") in LIVE:
                try:
                    stop_run(lab, m["run_id"], by="gate3-revoked")
                except (SpecError, OSError):
                    pass
    return load(lab, name) or {}


# ── the keeper ───────────────────────────────────────────────────────────────────────────────────
def keep(lab: Lab, enqueue=None) -> dict:
    """One pass over every kept campaign. Runs inside tick() (which holds the scheduler lock)."""
    if enqueue is None:
        from .runs import enqueue   # noqa: PLC0415 — runs imports spec/manifest only
    out = {"cycles": [], "dispatched": [], "retried": [], "gate3": []}
    states = all_states(lab)
    if not states:
        return out
    runs = all_runs(lab)
    for st in states:
        if st.get("status") not in ("active", "finishing", "stopping"):
            continue
        try:
            _keep_one(lab, st, runs, out, enqueue)
        except Exception as e:  # noqa: BLE001 — one bad campaign never stops the others or the tick
            st["last_error"] = f"{type(e).__name__}: {e}"[:400]
        save(lab, st)
    return out


def _wall_min(m: dict) -> float:
    secs = sum(pos_float(a.get("wall_seconds"), 0.0) for a in (m.get("attempts") or []))
    if m.get("status") in ACTIVE:
        a = (m.get("attempts") or [{}])[-1]
        if a.get("wall_seconds") is None:
            secs += max(0.0, time.time() - (parse_ts(a.get("started")) or time.time()))
    return secs / 60


def _brief(lab: Lab, st: dict) -> str:
    try:
        return (lab.hub / st["file"]).read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def _parallel(brief: str) -> int:
    m = re.search(r"≤\s*(\d+)\s*ideas in flight", brief)
    return max(1, int(m.group(1))) if m else 1


def _members(lab: Lab, st: dict, brief: str) -> None:
    """Studies in this campaign: named in its Campaign Log, or projects whose envelope it signed."""
    studies = st.setdefault("studies", {})
    log = brief.split("## Campaign Log", 1)[1] if "## Campaign Log" in brief else ""
    found = set()
    for line in log.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and _NAME_RE.match(cells[1] or "") and cells[1] not in ("idea", "---"):
            found.add(cells[1])
    rows = {r.get("id"): r for r in lab.registry_rows()}
    for slug in rows:
        pdir = lab.project_dir(slug)
        if pdir and st["file"] in ((pdir / "control.yaml").read_text(encoding="utf-8", errors="replace")
                                   if (pdir / "control.yaml").is_file() else ""):
            found.add(slug)
    for slug in found:
        if slug in rows:
            studies.setdefault(slug, {})["member"] = True


def _row_sig(lab: Lab, slug: str) -> str:
    r = lab.row(slug) or {}
    return f"{r.get('state')}|{r.get('next')}"


def _signed_since(lab: Lab, slug: str, kind: str) -> bool:
    """Has the PI resolved what this study was waiting for?"""
    hub = lab.hub
    if kind == "gate1":
        t = (hub / "studies" / slug / "proposal.md")
        return t.is_file() and "PI Gate 1 approved" in t.read_text(encoding="utf-8", errors="replace")
    if kind == "gate2":
        pdir = lab.project_dir(slug)
        c = (pdir / "control.yaml") if pdir else None
        return bool(c and c.is_file() and re.search(r"pi_signed:\s*true", c.read_text(encoding="utf-8", errors="replace")))
    if kind == "gate3":
        return (hub / "studies" / slug / "paper" / "gate3-approval.md").is_file()
    return False


def _update_waits(lab: Lab, st: dict, mine: list) -> None:
    studies = st.setdefault("studies", {})
    for _t, _w, _p, m in mine:
        subj, rep = m.get("subject"), m.get("report") or {}
        if m.get("status") not in TERMINAL or not subj or not rep.get("needs_pi"):
            continue
        s = studies.setdefault(subj, {})
        if s.get("waiting_run") == m["run_id"] or s.get("cleared_run") == m["run_id"]:
            continue
        s.update(waiting=rep["needs_pi"], waiting_run=m["run_id"], waiting_since=_row_sig(lab, subj),
                 waiting_ts=m.get("finished"))
        _event(st, f"{subj} waits for the PI ({rep['needs_pi']})")
    for slug, s in studies.items():
        if not s.get("waiting"):
            continue
        if _row_sig(lab, slug) != s.get("waiting_since") or _signed_since(lab, slug, s["waiting"]):
            s["cleared_run"] = s.get("waiting_run")
            s.update(waiting=None, waiting_run=None)
            _event(st, f"{slug} no longer waits — the campaign picks it up again")


def _requeue(lab: Lab, path: Path, m: dict, not_before: float, why: str, extra_minutes: float) -> None:
    used = _wall_min(m)
    transition(lab, path, m, "queued", by="campaign", reason=why, resume={"mode": "continue"},
               post_processed=False, not_before=_iso(not_before),
               campaign_retries=int(m.get("campaign_retries") or 0) + 1,
               max_minutes=round(used + extra_minutes, 1))


def _retry_children(lab: Lab, st: dict, children: list, out: dict) -> None:
    prog = lab.prog()
    for _t, _w, path, m in children:
        if m.get("status") not in ("failed", "timeout") or m.get("campaign_retry_done"):
            continue
        kind = "timeout" if m.get("status") == "timeout" else (m.get("failure_kind") or "logic")
        n = int(m.get("campaign_retries") or 0)
        if kind not in RETRYABLE or n >= MAX_CHILD_RETRIES or not m.get("session_id"):
            continue
        fin = parse_ts(m.get("finished")) or time.time()
        if kind == "usage_limit":
            nb = (pos_float(m.get("limit_reset"), 0.0) or fin + 30 * 60) + 120
        elif kind == "transient":
            nb = fin + BACKOFF_MIN[min(n, len(BACKOFF_MIN) - 1)] * 60
        else:
            nb = fin + 30
        fresh = read_manifest(path) or m
        if fresh.get("status") != m.get("status"):
            continue
        minutes = st.get("child_minutes") or pos_float(prog.get("max_minutes"), 240.0) or 240.0
        _requeue(lab, path, fresh, nb, f"campaign retry {n + 1}/{MAX_CHILD_RETRIES} after {kind}", minutes)
        out["retried"].append(m["run_id"])
        _event(st, f"retrying {m.get('skill')} {m.get('subject') or ''} after {kind}".strip())


def _dispatch(lab: Lab, st: dict, cycles: list, children: list, brief: str, out: dict, enqueue) -> None:
    cycle_ids = {m["run_id"] for *_x, m in cycles}
    if not cycle_ids:
        return
    seen = set(st.get("seen_dispatch") or [])
    events = [e for e in read_jsonl(lab.lab / ".bus" / "events.jsonl", tail=6000)
              if e.get("kind") == "campaign_dispatch" and e.get("run_id") in cycle_ids]
    live = [m for *_x, m in children if m.get("status") in LIVE]
    cap = _parallel(brief)
    for e in events:
        key = f"{e.get('ts')}|{e.get('run_id')}|{json.dumps(e.get('data') or {}, sort_keys=True)}"
        if key in seen:
            continue
        seen.add(key)
        d = e.get("data") or {}
        skill = str(d.get("skill") or "").strip().lstrip("/")
        target = str(d.get("target") or HUB_TARGET).strip() or HUB_TARGET
        args = str(d.get("args") or "").strip()
        rec = {"ts": now(), "cycle": e.get("run_id"), "skill": skill, "target": target}
        why = None
        s = (st.get("studies") or {}).get(target) or {}
        if skill in DISPATCHABLE_NOT or skill not in SKILL_REGISTRY:
            why = f"/{skill} can't be dispatched by a campaign"
        elif SKILL_REGISTRY[skill].get("mode") != "headless":
            why = f"/{skill} is interactive"
        elif target != HUB_TARGET and not s.get("member"):
            why = f"{target} is not in this campaign (add it to the Campaign Log first)"
        elif s.get("waiting"):
            why = f"{target} is waiting for the PI ({s['waiting']})"
        elif any(m.get("skill") == skill and (m.get("target") or HUB_TARGET) == target for m in live):
            why = "already queued or running"
        elif len({(m.get("target") or HUB_TARGET) for m in live} | {target}) > cap:
            why = f"the brief allows {cap} idea(s) in flight"
        if why is None:
            spec = RunSpec(skill=skill, target=target, args=args, backend=st.get("backend"), model=st.get("model"),
                           max_minutes=st.get("child_minutes"), parent=e.get("run_id"), campaign=st["name"],
                           created_by="campaign")
            try:
                child = enqueue(lab, spec)
                rec["run_id"] = child["run_id"]
                live.append(child)
                out["dispatched"].append(child["run_id"])
            except SpecError as ex:
                why = str(ex)
        rec["result"] = "started" if why is None else f"refused: {why}"
        st.setdefault("dispatch_log", []).append(rec)
        st["dispatch_log"] = st["dispatch_log"][-80:]
    st["seen_dispatch"] = list(seen)[-600:]


def _open_escalation(lab: Lab, slug: str) -> bool:
    open_ = set()
    for e in read_jsonl(lab.lab / ".bus" / "events.jsonl", tail=6000):
        if e.get("idea") != slug:
            continue
        if e.get("kind") == "escalation":
            open_.add(e.get("ts"))
        elif e.get("kind") == "escalation_resolved":
            open_.clear()
    return bool(open_)


def _try_gate3(lab: Lab, st: dict, children: list, out: dict, enqueue) -> None:
    if not st.get("gate3_auto"):
        return
    import sys   # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import gate3  # noqa: PLC0415
    ok, why = gate3.campaign_delegates(lab.hub, st["file"])
    if not ok:
        return
    for slug, s in (st.get("studies") or {}).items():
        if not s.get("member") or s.get("hold") or s.get("gate3_done") or s.get("waiting") not in (None, "gate3"):
            continue
        if gate3.registry_state(lab.hub, slug) != "internal-review" or gate3.note_path(lab.hub, slug).exists():
            continue
        pdir = lab.project_dir(slug)
        if pdir and re.search(r"^target:\s*\n(?:[ \t].*\n)*?[ \t]+active:\s*true",
                              (pdir / "control.yaml").read_text(encoding="utf-8", errors="replace")
                              if (pdir / "control.yaml").is_file() else "", re.M):
            continue   # a target-driven project: the PI picks the final output
        review = [m for *_x, m in children if m.get("skill") == "review-paper" and m.get("subject") == slug
                  and m.get("status") == "completed" and (m.get("report") or {}).get("needs_pi") == "gate3"]
        if not review:
            continue
        paper = gate3.paper_dir(lab.hub, slug)
        stamp = "|".join(str(int(p.stat().st_mtime)) for p in (paper / "main.pdf", paper / "claims.yaml") if p.exists())
        if s.get("gate3_checked") == stamp:
            continue   # same paper already failed the checks — wait for a revision
        s["gate3_checked"] = stamp
        ready = gate3.readiness(lab.hub, slug)
        fails = [c["label"] for c in ready["checks"] if not c["ok"]]
        if _open_escalation(lab, slug):
            fails.append("an escalation is still open")
        audits = {} if fails else gate3.run_audits(lab.hub, slug)
        bad = [f"{k} audit exit {v}" for k, v in audits.items() if v != 0]
        entry = {"ts": now(), "study": slug, "audits": audits}
        if fails or bad:
            entry["result"] = "not yet: " + "; ".join(fails + bad)
            st.setdefault("gate3_log", []).append(entry)
            _event(st, f"{slug}: Gate 3 not recorded — {entry['result'][9:]}")
            continue
        save(lab, st)   # gate3.delegation_valid reads the saved state (membership, hold)
        gate3.sign_delegated(lab.hub, slug, st["file"], audits, by=f"campaign keeper pid {os.getpid()}")
        spec = RunSpec(skill="finalize", target=slug, gate3=True, backend=st.get("backend"), model=st.get("model"),
                       campaign=st["name"], parent=review[-1]["run_id"], created_by="campaign-gate3")
        try:
            child = enqueue(lab, spec)
            entry.update(result="recorded Gate 3 by delegation; /finalize started", run_id=child["run_id"])
            s["gate3_done"] = True
            out["gate3"].append(slug)
        except SpecError as ex:
            entry["result"] = f"recorded, but /finalize could not start: {ex}"
        st.setdefault("gate3_log", []).append(entry)
        st["gate3_log"] = st["gate3_log"][-40:]
        _event(st, f"{slug}: Gate 3 recorded by delegation")


def _account(lab: Lab, st: dict, last: dict) -> None:
    """Fold the outcome of a finished cycle into the counters (once per cycle)."""
    if st.get("accounted") == last["run_id"]:
        return
    st["accounted"] = last["run_id"]
    status, fin = last.get("status"), parse_ts(last.get("finished")) or time.time()
    kind = "timeout" if status == "timeout" else (last.get("failure_kind") or "logic")
    rep = last.get("report") or {}
    rec = {"run_id": last["run_id"], "n": last.get("campaign_cycle"), "status": status, "kind": None,
           "finished": last.get("finished"), "summary": (rep.get("summary") or "")[:300],
           "campaign": rep.get("campaign")}
    rm = st.get("repeat_minutes") or 20
    if status == "completed":
        st["consecutive_failures"] = 0
        st["timeouts_in_a_row"] = 0
        nb = fin + rm * 60
        if (rep.get("campaign") or "") == "done" and st["status"] == "active":
            st["status"] = "finishing"
            _event(st, "the campaign reports it is done")
    elif status == "killed":
        if "campaign moved on" in str(last.get("reason") or "") or st["status"] == "stopping":
            nb = fin
        else:
            st["status"], st["paused_reason"] = "paused", "a cycle was stopped by the PI"
            nb = None
    elif kind == "timeout":
        st["timeouts_in_a_row"] = int(st.get("timeouts_in_a_row") or 0) + 1
        if st["timeouts_in_a_row"] >= 3:
            st["consecutive_failures"] = int(st.get("consecutive_failures") or 0) + 1
            st["timeouts_in_a_row"] = 0
        nb = fin + 60
    elif kind == "usage_limit":
        nb = (pos_float(last.get("limit_reset"), 0.0) or fin + 30 * 60) + 120
        _event(st, f"usage limit — the next cycle waits until {_iso(nb)[11:16]}")
    elif kind in ("auth", "cli_missing"):
        st["status"] = "paused"
        st["paused_reason"] = str(last.get("reason") or "the agent CLI needs you (sign in / install)")
        nb = None
    elif kind == "transient":
        n = int(st.get("consecutive_failures") or 0)
        st["consecutive_failures"] = n + 1
        nb = fin + BACKOFF_MIN[min(n, len(BACKOFF_MIN) - 1)] * 60
    else:
        st["consecutive_failures"] = int(st.get("consecutive_failures") or 0) + 1
        nb = fin + 5 * 60
    rec["kind"] = None if status == "completed" else kind
    st.setdefault("cycles", []).append(rec)
    st["cycles"] = st["cycles"][-200:]
    st["next_cycle_at"] = _iso(nb) if nb else None
    if st["status"] == "paused":
        _event(st, f"paused: {st.get('paused_reason')}")


def _stop_reason(st: dict) -> str | None:
    if st.get("deadline") and time.time() >= (parse_ts(st["deadline"]) or 0):
        return "the wall-clock deadline passed"
    b = st.get("budget") or {}
    if b.get("agent_minutes") and st.get("used_minutes", 0) >= b["agent_minutes"]:
        return f"the agent-time budget is used ({st['used_minutes']:.0f}/{b['agent_minutes']:.0f} min)"
    if b.get("max_cycles") and len(st.get("cycles") or []) >= b["max_cycles"]:
        return f"the cycle cap ({b['max_cycles']}) is reached"
    return None


def _keep_one(lab: Lab, st: dict, runs: list, out: dict, enqueue) -> None:
    name = st["name"]
    mine = [x for x in runs if x[3].get("campaign") == name]
    cycles = sorted([x for x in mine if x[3].get("skill") == "autopilot"],
                    key=lambda x: (int(x[3].get("campaign_cycle") or 0), x[3].get("created") or ""))
    children = [x for x in mine if x[3].get("skill") != "autopilot"]
    st["used_minutes"] = round(sum(_wall_min(m) for *_x, m in mine), 1)
    brief = _brief(lab, st)
    _members(lab, st, brief)
    _update_waits(lab, st, mine)
    _dispatch(lab, st, cycles, children, brief, out, enqueue)
    if st["status"] == "active":
        _retry_children(lab, st, children, out)
        _try_gate3(lab, st, children, out, enqueue)
    # the cycle itself
    live = [m for *_x, m in cycles if m.get("status") in LIVE]
    if live:
        c = live[0]
        if (c.get("status") == "waiting_input" and time.time() - (parse_ts(c.get("status_ts")) or time.time()) > 300
                and not _session_up(next(p for *_y, p, m in cycles if m is c), c)):
            # (a live session still asking is left to its own deadline: it takes the recommended answer)
            q = ((c.get("pending_question") or {}).get("input") or {}).get("questions") or []
            text = q[0].get("question") if q and isinstance(q[0], dict) else "a question"
            st.setdefault("questions", []).append({"ts": now(), "run_id": c["run_id"], "question": text})
            st["questions"] = st["questions"][-30:]
            fresh = read_manifest(next(p for *_y, p, m in cycles if m is c)) or c
            if fresh.get("status") == "waiting_input":
                transition(lab, next(p for *_y, p, m in cycles if m is c), fresh, "killed", by="campaign",
                           reason="campaign moved on (its question is on the campaign card)", finished=now(),
                           pending_question=None)
            _event(st, "a cycle asked a question — recorded on the campaign card; the campaign moves on")
        return
    last = cycles[-1][3] if cycles else None
    if last is not None and last.get("status") in TERMINAL:
        _account(lab, st, last)
        if last.get("campaign_final"):
            st["status"] = "done" if st["status"] in ("finishing", "stopping", "active") else st["status"]
            _event(st, "finished — the final report is written")
            return
    if st["status"] == "paused":
        return
    if int(st.get("consecutive_failures") or 0) >= int(st.get("max_failures") or 4):
        st["status"], st["paused_reason"] = "stalled", f"{st['consecutive_failures']} cycles in a row failed"
        _event(st, f"stalled: {st['paused_reason']}")
        return
    reason = _stop_reason(st)
    final = st["status"] in ("finishing", "stopping") or reason is not None
    if reason and st["status"] == "active":
        st["status"] = "finishing"
        _event(st, f"wrapping up: {reason}")
    nb = parse_ts(st.get("next_cycle_at")) or 0
    if final:
        nb = min(nb, time.time())   # the report cycle goes right away
    n = len(cycles) + 1
    answers = [q for q in st.get("questions") or [] if q.get("answer") and not q.get("delivered")]
    spec = RunSpec(skill="autopilot", target=HUB_TARGET, args=st["file"], backend=st.get("backend"),
                   model=st.get("model"), max_minutes=st.get("cycle_minutes"), campaign=name,
                   parent=last["run_id"] if last else None, created_by="campaign",
                   extra={"campaign_cycle": n, "campaign_final": final, "not_before": _iso(max(nb, time.time())),
                          "pi_answers": [{"question": q.get("question"), "answer": q["answer"]} for q in answers]})
    try:
        child = enqueue(lab, spec)
    except SpecError as e:
        st["last_error"] = str(e)[:400]
        return
    st["last_error"] = None
    for q in answers:
        q["delivered"] = True
    out["cycles"].append(child["run_id"])
    _event(st, f"cycle {n}{' (final report)' if final else ''} queued")


def summary(lab: Lab) -> list[dict]:
    """What the dashboard shows per campaign (cheap: no audits, no enqueues)."""
    out = []
    for st in all_states(lab):
        studies = st.get("studies") or {}
        out.append({k: st.get(k) for k in ("name", "file", "status", "created", "deadline", "budget", "used_minutes",
                                             "cycle_minutes", "repeat_minutes", "gate3_auto", "consecutive_failures",
                                             "max_failures", "next_cycle_at", "paused_reason", "last_error")}
                   | {"cycles": len(st.get("cycles") or []), "last_cycles": (st.get("cycles") or [])[-5:],
                      "studies": {k: {x: v.get(x) for x in ("member", "waiting", "hold", "gate3_done")}
                                  for k, v in studies.items()},
                      "dispatch_log": (st.get("dispatch_log") or [])[-12:], "questions": [{**q, "index": i} for i, q in enumerate(st.get("questions") or [])][-5:],
                      "gate3_log": (st.get("gate3_log") or [])[-6:], "events": (st.get("events") or [])[-12:]})
    return out
