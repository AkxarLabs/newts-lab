"""The scheduler: one stateless `tick()` that any client may run (the dashboard's background thread,
`executor_cli.py serve`, or a one-off `executor_cli.py tick`).

  tick = reconcile orphans → post-process finished runs (read the run_report footer; chain the next
         step; schedule repeats) → apply caps + daily brake → start queued runs, each in its own
         detached supervisor process.

Runs are owned by their supervisors, never by the ticker: killing the dashboard mid-run changes
nothing; queued runs simply wait for the next tick from any client.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import threading
import time
from pathlib import Path

from .lab import HUB_TARGET, Lab, pos_float, pos_int, read_jsonl
from .manifest import (ACTIVE, TERMINAL, all_runs, emit, now, parse_ts, read_manifest, run_dir,
                       scheduler_lock, transition, write_manifest)
from .procs import DETACHED, is_locked, kill_tree, pid_alive, python_exe
from .spec import RunSpec, SpecError, SKILL_REGISTRY

CLI = Path(__file__).resolve().parents[1] / "executor_cli.py"
STARTING_GRACE_S = 60
_LAST_TICK: dict = {}


# ── reconcile ────────────────────────────────────────────────────────────────

def reconcile_manifest(lab: Lab, workdir: Path, path: Path, m: dict) -> bool:
    """Mark one orphaned run failed. Schema-2 runs: the supervisor's OS lock is the liveness signal.
    Legacy (agent_runner v1) manifests: pid liveness, as before. Returns True if it changed."""
    st = m.get("status")
    if m.get("schema") == 2 and st in ACTIVE:
        rd = run_dir(Path(path).parent, m.get("run_id") or m.get("agent_id"))
        age = time.time() - (parse_ts(m.get("status_ts")) or 0)
        if st in ("starting", "resuming") and age < STARTING_GRACE_S:
            return False   # the supervisor may not have taken its lock yet — and never probe it then
        if is_locked(rd / "lock"):
            return False
        if m.get("pid") and pid_alive(m["pid"]):
            kill_tree(m["pid"])   # an undrained orphan can't be observed — stop it
        transition(lab, path, m, "failed", by="reconcile", reason="reconciled: supervisor gone",
                   finished=now(), pid=None,
                   last_message=((m.get("last_message") or "") + " [reconciled: process gone]").strip())
        emit(lab, workdir, "agent_finished", detail=m.get("run_id"), status="failed",
             data={"reconciled": True, "run_id": m.get("run_id")})
        return True
    if m.get("schema") != 2 and st == "running":
        if pid_alive(m.get("pid")):
            return False
        m.update(status="failed", finished=now(),
                 last_message=(m.get("last_message") or "") + " [reconciled: process gone]")
        write_manifest(path, m)
        emit(lab, workdir, "agent_finished", detail=m.get("agent_id"), status="failed", data={"reconciled": True})
        return True
    return False


def reconcile(lab: Lab) -> int:
    n = 0
    for _target, workdir, path, m in all_runs(lab):
        try:
            n += int(reconcile_manifest(lab, workdir, path, m))
        except OSError:
            continue
    # leftover stop markers on runs that already ended
    for _target, _workdir, path, m in all_runs(lab):
        if m.get("status") in TERMINAL:
            stop = run_dir(Path(path).parent, m.get("run_id") or m.get("agent_id") or "") / "stop"
            with contextlib.suppress(OSError):
                if stop.exists():
                    stop.unlink()
    return n


# ── post-processing: report footer, chaining, repeats ────────────────────────

def read_report(lab: Lab, workdir: Path, run_id: str) -> dict | None:
    """The last `run_report` event this run emitted on its bus (the machine-readable footer)."""
    rep = None
    for e in read_jsonl(lab.bus_of(workdir) / "events.jsonl", tail=4000):
        if e.get("kind") == "run_report" and e.get("run_id") == run_id:
            rep = e
    if not rep:
        return None
    d = rep.get("data") or {}
    needs = str(d.get("needs_pi") or "").strip().lower() or None
    return {"next": (str(d.get("next") or "").strip() or None), "needs_pi": None if needs in (None, "none", "") else needs,
            "summary": str(d.get("summary") or rep.get("detail") or "")[:600] or None, "ts": rep.get("ts"),
            "source": "footer"}


def parse_next(cmd: str | None, default_target: str = HUB_TARGET) -> RunSpec | None:
    """'/spawn-project my-idea' → RunSpec(skill='spawn-project', target='my-idea'). Only commands for
    whitelisted skills parse; anything else (prose, Gate-3 skills) returns None."""
    if not cmd or not cmd.strip().startswith("/"):
        return None
    toks = cmd.strip().split()
    skill = toks[0].lstrip("/")
    cfg = SKILL_REGISTRY.get(skill)
    if not cfg or cfg.get("mode") != "headless":
        return None
    rest = toks[1:]
    schema = cfg["args"]
    if skill == "autopilot":
        if len(rest) >= 2 and rest[0] == "continue":
            return RunSpec(skill=skill, target=HUB_TARGET, args=rest[1])
        return None
    if schema.startswith("slug"):
        if rest:
            return RunSpec(skill=skill, target=rest[0], args=" ".join(rest[1:]))
        if schema.startswith("slug?"):
            return RunSpec(skill=skill, target=HUB_TARGET)
        return None
    return RunSpec(skill=skill, target=default_target if cfg["level"] == "project" else HUB_TARGET,
                   args=" ".join(rest))


def post_process(lab: Lab, workdir: Path, path: Path, m: dict) -> None:
    from .runs import enqueue   # local: runs imports scheduler-free modules only
    if m.get("post_processed") or m.get("status") not in TERMINAL:
        return
    run_id = m.get("run_id")
    rep = read_report(lab, workdir, run_id)
    if not rep:
        text = (m.get("last_message") or m.get("last_text") or "").strip()
        rep = {"next": None, "needs_pi": None, "summary": text[:600] or None, "ts": m.get("finished"),
               "source": "last_message"}
    m["report"] = rep
    prog = lab.prog()
    clean = m.get("status") == "completed" and not rep.get("needs_pi")
    # chain: follow the run's own `next` command (once, or in a loop until a gate / cap)
    if clean and m.get("chain") in ("next", "loop") and not m.get("chain_child"):
        spec = parse_next(rep.get("next"), m.get("subject") or HUB_TARGET)
        step = int(m.get("chain_step") or 0) + 1
        cap = pos_int(prog.get("chain_max_steps", 6), 6, 1)
        if spec and (m.get("chain") == "next" or step <= cap):
            spec.backend, spec.model, spec.effort = m.get("backend"), m.get("model"), m.get("effort")
            spec.parent, spec.created_by = run_id, "chain"
            spec.chain = "loop" if m.get("chain") == "loop" else "off"
            spec.extra = {"chain_step": step}
            try:
                child = enqueue(lab, spec)
                m["chain_child"] = child["run_id"]
            except SpecError as e:
                m["chain_error"] = str(e)
        elif rep.get("next"):
            m["chain_error"] = ("chain cap reached" if spec else f"next step not launchable: {rep.get('next')}")
    # repeat (e.g. /autopilot continue every 30 min): a fresh session per cycle
    rmin = pos_float(m.get("repeat_minutes"), 0.0)
    idx = int(m.get("repeat_index") or 0)
    mx = m.get("max_repeats")
    if clean and rmin > 0 and not m.get("repeat_child") and (mx is None or idx + 1 < int(mx)):
        spec = RunSpec(skill=m.get("skill"), target=m.get("target") or HUB_TARGET, args=m.get("args") or "",
                       backend=m.get("backend"), model=m.get("model"), effort=m.get("effort"),
                       max_minutes=m.get("max_minutes"), parent=run_id, created_by="repeat",
                       repeat_minutes=rmin, max_repeats=mx, campaign=m.get("campaign"),
                       extra={"repeat_index": idx + 1,
                              "not_before": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + rmin * 60))})
        try:
            child = enqueue(lab, spec)
            m["repeat_child"] = child["run_id"]
        except SpecError as e:
            m["repeat_error"] = str(e)
    m["post_processed"] = True
    write_manifest(path, m)


# ── caps / brake ─────────────────────────────────────────────────────────────

def _today() -> str:
    return time.strftime("%Y-%m-%d")


def daily_usage(runs: list[dict]) -> dict:
    today, n, secs = _today(), 0, 0.0
    for m in runs:
        for a in m.get("attempts") or []:
            if not str(a.get("started") or "").startswith(today):
                continue
            n += 1
            if a.get("wall_seconds") is not None:
                secs += pos_float(a["wall_seconds"], 0.0)
            elif m.get("status") in ACTIVE:
                secs += max(0.0, time.time() - (parse_ts(a.get("started")) or time.time()))
    return {"attempts": n, "minutes": round(secs / 60, 1)}


def caps(lab: Lab) -> dict:
    prog = lab.prog()
    return {"total": pos_int(prog.get("max_concurrent_total", 3), 3, 0),
            "per_project": pos_int(prog.get("max_concurrent", 3), 3, 0),
            "hub": pos_int(prog.get("hub_max_concurrent", 1), 1, 0),
            "daily_runs": pos_int(prog.get("daily_max_runs", 0), 0, 0),
            "daily_minutes": pos_float(prog.get("daily_max_minutes", 0), 0.0)}


def brake(lab: Lab, runs: list[dict]) -> str | None:
    c, u = caps(lab), daily_usage(runs)
    if c["daily_runs"] and u["attempts"] >= c["daily_runs"]:
        return f"daily run cap reached ({u['attempts']}/{c['daily_runs']} attempts today)"
    if c["daily_minutes"] and u["minutes"] >= c["daily_minutes"]:
        return f"daily agent-minutes cap reached ({u['minutes']:g}/{c['daily_minutes']:g} min today)"
    return None


# ── spawning ─────────────────────────────────────────────────────────────────

def spawn_supervisor(lab: Lab, target: str, run_id: str, log_path: Path) -> int:
    """Start `executor_cli.py supervise` fully detached (its own session / no console); it outlives
    whoever called tick(). Returns its pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "ab") as log:
        p = subprocess.Popen([python_exe(), str(CLI), "--hub", str(lab.hub), "supervise",
                              "--run", run_id, "--target", target],
                             cwd=str(lab.hub), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             close_fds=True, **DETACHED)
    return p.pid


def tick(lab: Lab, *, spawn=None, wait: float = 0.0) -> dict:
    """One scheduling pass. `spawn(lab, target, run_id, log)` is injectable for tests. Skips (returns
    {"skipped": True}) if another ticker holds the lock and `wait` is 0."""
    spawn = spawn or spawn_supervisor
    report = {"ts": now(), "reconciled": 0, "started": [], "post_processed": 0, "skipped": False,
              "brake": None, "enabled": False}
    try:
        cm = scheduler_lock(lab, wait=wait or 0.01)
        cm.__enter__()
    except TimeoutError:
        report["skipped"] = True
        return report
    try:
        report["reconciled"] = reconcile(lab)
        runs = all_runs(lab)
        for _t, workdir, path, m in runs:
            if m.get("status") in TERMINAL and not m.get("post_processed") and m.get("schema") == 2:
                try:
                    post_process(lab, workdir, path, m)
                    report["post_processed"] += 1
                except OSError:
                    pass
        prog = lab.prog()
        report["enabled"] = bool(prog.get("enabled"))
        depth = pos_int(os.environ.get("AUTOSCIENTIST_AGENT_DEPTH", "0") or 0, 0, 0)
        if not prog.get("enabled") or depth >= pos_int(prog.get("max_depth", 1), 1, 0):
            return report
        runs = all_runs(lab)   # post-processing may have queued children
        manifests = [m for *_x, m in runs]
        report["brake"] = brake(lab, manifests)
        if report["brake"]:
            return report
        c = caps(lab)
        active = [(t, m) for t, _w, _p, m in runs if m.get("status") in ACTIVE]
        n_total = len(active)
        per: dict[str, int] = {}
        for t, m in active:
            key = HUB_TARGET if m.get("level") == "hub" else (m.get("target") or t)
            per[key] = per.get(key, 0) + 1
        queued = [(t, w, p, m) for t, w, p, m in runs if m.get("status") == "queued" and m.get("schema") == 2]
        queued.sort(key=lambda x: (-int(x[3].get("priority") or 0), 0 if x[3].get("resume") else 1,
                                   x[3].get("created") or ""))
        tnow = time.time()
        for _t, workdir, path, m in queued:
            nb = parse_ts(m.get("not_before"))
            if nb and nb > tnow:
                continue
            key = HUB_TARGET if m.get("level") == "hub" else (m.get("target") or _t)
            cap_key = c["hub"] if key == HUB_TARGET else c["per_project"]
            if n_total >= c["total"] or per.get(key, 0) >= cap_key:
                continue
            m = read_manifest(path) or m
            if m.get("status") != "queued":
                continue
            to = "resuming" if m.get("resume") else "starting"
            transition(lab, path, m, to, by="scheduler")
            rd = run_dir(Path(path).parent, m["run_id"])
            # the supervisor finds the run where it LIVES: a hub-level run about an idea
            # (/spawn-project idea-x) executes in — and is recorded on — the hub, not a project repo
            where = HUB_TARGET if m.get("level") == "hub" else (m.get("target") or HUB_TARGET)
            try:
                # no manifest write after this point: the supervisor owns the run from here on (it
                # records its own pid) — writing our stale copy could clobber its first updates
                spawn(lab, where, m["run_id"], rd / "supervisor.log")
            except OSError as e:
                transition(lab, path, m, "failed", by="scheduler", reason=f"could not start supervisor: {e}",
                           finished=now())
                continue
            n_total += 1
            per[key] = per.get(key, 0) + 1
            report["started"].append(m["run_id"])
        return report
    finally:
        cm.__exit__(None, None, None)
        _LAST_TICK[str(lab.hub)] = {"ts": report["ts"], "started": len(report["started"]),
                                    "skipped": report["skipped"], "brake": report["brake"]}


def last_tick(lab: Lab) -> dict | None:
    return _LAST_TICK.get(str(lab.hub))


def tick_loop(lab_factory, stop: threading.Event, interval: float = 2.0, reconcile_every: float = 30.0) -> None:
    """Run tick() until `stop` is set. `lab_factory()` builds a fresh Lab each pass (so a moved or
    monkeypatched hub root is honoured). Never raises."""
    while not stop.is_set():
        try:
            tick(lab_factory())
        except Exception:  # noqa: BLE001 — the loop must survive any single bad pass
            pass
        stop.wait(interval)
