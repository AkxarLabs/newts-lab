"""Who is working: the agent runs launched from here and every agent/subagent the tracer saw, joined into
one roster (run → session → subagents). Read-only and best-effort, like the rest of the snapshot.

    agents_in(dir) / launched_agents(project)   run manifests (<bus>/agents/*.json), compacted for the UI
    compact_run(manifest)                       the fields the dashboard renders
    workers(bus, project, project_ids)          the trace files (<bus>/workers/*.jsonl) folded into a roster
    join_runs(workers, runs) / link_workers()   nest each worker under its run and its spawning parent
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import ctx
from ctx import labfiles

# ── workers (per-agent activity from .bus/workers/*.jsonl — the traceability feed) ──
#
# tools/trace_hook.py (a Claude Code hook) writes ONE file per agent/subagent. We fold each file into
# a roster entry: who it is (role + a readable label), what it's doing (status, the tool it is inside
# right now, recent actions), where (project / idea / worktree variant), who spawned it (parent) and
# what it handed back (result). Best-effort and non-canonical, like the rest of the bus.
#
# Tree: a subagent's lines carry the PARENT session's id in `session_id`; its parent's file holds a
# `spawn` line (tool_use_id, subagent type, description) and later a `return` line (the result
# packet). `link_workers` matches each child to its spawn, so the UI can draw
# run → session → subagents with every subagent's label, status and result.


RUN_KEYS = ("agent_id", "run_id", "backend", "role", "status", "started", "finished", "wall_seconds",
             "exit_code", "prompt_summary", "session_id", "skill", "command", "target", "subject", "level",
             "attempt", "reason", "status_ts", "pending_question", "report", "usage", "chain", "chain_child",
             "parent", "created_by", "created", "max_minutes", "n_actions", "denials", "mode", "label",
             "cli_version", "model_used", "repeat_minutes", "not_before", "answers_given", "schema",
             "kind", "gate3_signed", "args", "model", "effort", "max_repeats", "repeat_index", "campaign",
             "repeat_child", "campaign_cycle", "campaign_final", "failure_kind", "limit_reset", "campaign_retries",
             "brief_sha", "chain_step", "transport", "pending_permissions", "assumed", "limits", "pid")


def _r10(x) -> int | None:
    return None if x is None else int(x // 10 * 10)


def compact_run(m: dict) -> dict:
    """A run manifest → the fields the dashboard renders. Time-varying numbers are rounded to 10 s
    so the SSE signature (which ignores `now`) doesn't change every tick."""
    out = {k: m.get(k) for k in RUN_KEYS}
    out["run_id"] = out["run_id"] or out["agent_id"]
    out["last_message"] = (m.get("last_message") or "")[:1200] or None
    out["last_text"] = (m.get("last_text") or "")[:400] or None
    la = m.get("last_action")
    out["last_action"] = {"tool": la.get("tool"), "summary": (la.get("summary") or "")[:200], "ts": la.get("ts")}\
        if isinstance(la, dict) else None
    now = time.time()
    st = m.get("status")
    started = labfiles.parse_ts(m.get("started"))
    if st in ("starting", "running", "resuming") and started:
        prior = sum(float(a.get("wall_seconds") or 0) for a in (m.get("attempts") or [])[:-1])
        cur = labfiles.parse_ts(((m.get("attempts") or [{}])[-1] or {}).get("started")) or started
        out["elapsed_s"] = _r10(prior + max(0.0, now - cur))
    else:   # a finished run's wall time never changes → exact (only LIVE numbers are rounded for SSE)
        out["elapsed_s"] = round(float(m.get("wall_seconds") or 0)) if m.get("wall_seconds") is not None else None
    hb = labfiles.parse_ts(m.get("heartbeat"))
    out["heartbeat_age_s"] = _r10(now - hb) if (hb and st in ("starting", "running", "resuming")) else None
    subs = m.get("subagents") or {}
    out["subagents"] = [{"id": k, "type": v.get("type"), "description": v.get("description"),
                         "status": v.get("status"), "n_actions": v.get("n_actions"),
                         "last_action": (v.get("last_action") or {}).get("summary"),
                         "result": (v.get("result") or "")[:600] or None,
                         "started": v.get("started"), "finished": v.get("finished"),
                         "parent": v.get("parent"), "session": v.get("session"), "background": v.get("background")}
                        for k, v in list(subs.items())[-40:]]
    out["n_qa"] = len(m.get("qa") or [])
    return out


def launched_agents(project_dir: Path) -> list[dict]:
    """Headless agents launched into this project (tools/executor runs, or older launcher
    launches) — each is a <project>/.bus/agents/<id>.json manifest; the full transcript lives next to
    it as <id>.stream.jsonl. Best-effort, absent dir => []."""
    return agents_in(project_dir / ".bus" / "agents")


def agents_in(adir: Path) -> list[dict]:
    if not adir.exists():
        return []
    out = []
    for f in sorted(adir.glob("*.json")):
        try:
            m = json.loads(labfiles.read_text(f))
        except json.JSONDecodeError:
            continue
        if isinstance(m, dict):
            out.append(compact_run(m))
    return out


_WORKER_DONE_KEEP_S = 1800   # a finished worker stays on the roster (greyed, with its result) this long


_WORKER_DEAD_S = 7200        # a file with no 'stop' untouched this long = a session that died uncleanly


_WORKER_STALE_S = 150        # no activity, no open tool, no stop -> idle (not "working")


SUBAGENT_STUCK_S = 1200     # an idle, unfinished subagent this long is surfaced as needing a look


_MAX_RECENT = 40




_WORKER_CACHE: dict[str, tuple] = {}


_WORKER_IN_TOOL_MAX_S = 3 * 86400   # inside one tool call (a long training run, a SLURM queue wait) this long


LIVE_IDS: set = set()               # session / run ids of runs that were live at the last snapshot


def _fold_worker(lines: list[dict]) -> dict:
    """One worker file's lines → its roster facts (pure; cached by file mtime+size)."""
    role, idea, proj, variant, sid = "orchestrator", None, None, None, None
    run_id = subject = depth = None
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
        if ln.get("run_id") and not run_id:
            run_id, subject, depth = ln["run_id"], ln.get("subject") or subject, ln.get("depth", depth)
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
                               "summary": ln.get("summary"), "ts": ln.get("ts"), "background": ln.get("background")})
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
            "run_id": run_id, "subject": subject, "depth": depth,
            "done": done, "open_tool": None if done else open_tool, "result": result,
            "spawns": spawns, "returns": returns, "n_actions": n_actions,
            "recent_actions": actions[-_MAX_RECENT:], "started": lines[0].get("ts"),
            "last_ts": lines[-1].get("ts")}


def scan(bus_dir: Path, project: str | None = None, projects: set | None = None) -> list[dict]:
    known = {"orchestrator", *ctx.tool("workflow").roles(ctx.HUB)}   # the lab's roles (agent-roles/*.yaml)
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
        key = str(f)
        hit = _WORKER_CACHE.get(key)
        if age > max(_WORKER_DEAD_S, _WORKER_DONE_KEEP_S) and f.stem not in LIVE_IDS and\
                not (hit and hit[2].get("open_tool") and age < _WORKER_IN_TOOL_MAX_S):
            continue   # never parsed: roster cost stays O(recent) before trace_hook's retention sweep
        if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
            fold = hit[2]
        else:
            lines = labfiles.read_jsonl(f)
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
            "role_known": fold["role"] in known,
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
            "run_id": fold.get("run_id"),
            "subject": fold.get("subject"),
            "depth": fold.get("depth"),
            "_returns": fold["returns"],
        })
    return out


def link_workers(workers: list[dict]) -> list[dict]:
    """Match each subagent to the spawn line in its parent's log (same session, same type, in order)
    → a readable label, the spawn id, and the result packet if the child's own stop didn't carry it.
    Fills parent.children. Mutates and returns `workers`."""
    by_id = {w["worker_id"]: w for w in workers}
    kids: dict[str, list[dict]] = {}
    for w in workers:
        if w["is_subagent"]:
            kids.setdefault(w["parent"], []).append(w)
    for root_id, children in kids.items():
        root = by_id.get(root_id)
        children.sort(key=lambda c: c.get("started") or "")
        if root is None:
            continue
        # every spawn in this session — the root's and its subagents' own (a subagent of a subagent)
        owners = [root] + children
        free = [(o, s) for o in owners for s in (o.get("spawned") or [])]
        for c in children:
            before = [(o, s) for (o, s) in free if o is not c and (s.get("ts") or "") <= (c.get("started") or "~")]
            match = next(((o, s) for (o, s) in free if s.get("child") == c["worker_id"]), None) or\
                next(((o, s) for (o, s) in before if s["type"] == c["role"] and not s.get("child")), None) or\
                (next(((o, s) for (o, s) in before if s["type"] == "general-purpose"), None)
                 if c["role"] == "general-purpose" else None)
            owner = root
            if match:
                free.remove(match)
                owner, sp = match
                desc = (sp.get("summary") or "").split(": ", 2)[-1]
                c["label"] = desc[:160] or None
                c["spawn_id"] = sp.get("tool_use_id")
                c["background"] = bool(sp.get("background"))
                if not c.get("result") and sp.get("tool_use_id"):
                    c["result"] = (owner.get("_returns") or {}).get(sp["tool_use_id"])
            c["parent"] = owner["worker_id"]
            c["depth_in_session"] = 1 if owner is root else 2
            owner.setdefault("children", [])
            if c["worker_id"] not in owner["children"]:
                owner["children"].append(c["worker_id"])
            if not c.get("project") and root.get("project"):
                c["project"] = root["project"]
            if not c.get("run_id") and root.get("run_id"):
                c["run_id"] = root["run_id"]
    for w in workers:
        w.pop("_returns", None)
        w.pop("spawned", None)
    return workers


def join_runs(workers: list[dict], runs: list[dict]) -> None:
    """A headless run's orchestrator IS a worker (its session id names the trace file): tag it with
    the run so the roster nests run → session → subagents, and give it the run's role/label."""
    by_sid = {r["session_id"]: r for r in runs if r.get("session_id")}
    by_run = {r["run_id"]: r for r in runs if r.get("run_id")}
    for w in workers:
        r = by_run.get(w.get("run_id")) or by_run.get(w["worker_id"]) or by_sid.get(w["worker_id"]) or\
            (by_sid.get(w.get("session_id")) if w.get("is_subagent") else None)
        if not r:
            w["interactive"] = not w.get("is_subagent")   # a session the PI started by hand
            if w["interactive"] and not w.get("label"):
                w["label"] = "Terminal session (started outside the dashboard)"
            continue
        w["run_id"] = r["run_id"]
        if r.get("subject") and not w.get("idea") and not w.get("project"):
            w["idea"] = r["subject"]
        if not w.get("is_subagent"):
            w["label"] = r.get("command") or r.get("prompt_summary")
            if r.get("status") in ("completed", "failed", "timeout", "killed", "waiting_input") and w["status"] != "done":
                w["status"] = "done" if r["status"] != "waiting_input" else "idle"
