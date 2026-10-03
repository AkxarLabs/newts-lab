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
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .lab import HUB_TARGET, Lab, pos_float, pos_int, read_jsonl
from .manifest import (ACTIVE, TERMINAL, all_runs, emit, now, parse_ts, read_manifest, run_dir,
                       scheduler_lock, transition, write_manifest)
from .procs import DETACHED, is_locked, kill_tree, pid_alive, python_exe
from .spec import RunSpec, SpecError, SKILL_REGISTRY
from . import campaigns, notify

CLI = Path(__file__).resolve().parents[1] / "executor_cli.py"
STARTING_GRACE_S = 60
_LAST_TICK: dict = {}


# ── reconcile ────────────────────────────────────────────────────────────────

def _still(path: Path, status: str) -> dict | None:
    """The manifest re-read from disk, if it is STILL in `status` — else None (someone moved it on)."""
    fresh = read_manifest(path)
    return fresh if (fresh is not None and fresh.get("status") == status) else None


def reconcile_manifest(lab: Lab, workdir: Path, path: Path, m: dict) -> bool:
    """Mark one orphaned run failed. Schema-2 runs: the supervisor's OS lock is the liveness signal.
    Legacy (agent_runner v1) manifests: pid liveness, as before. Returns True if it changed."""
    st = m.get("status")
    if m.get("schema") == 2 and st in ACTIVE:
        rd = run_dir(Path(path).parent, m.get("run_id") or m.get("agent_id"))
        age = time.time() - (parse_ts(m.get("status_ts")) or 0)
        if st in ("starting", "resuming"):
            spawn = {}
            try:
                spawn = json.loads((rd / "spawn.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            booting = spawn.get("pid") and pid_alive(spawn["pid"])
            if booting or (age < STARTING_GRACE_S and not spawn.get("pid")):
                return False   # still coming up — and never probe its lock then
            if spawn.get("pid") and not (rd / "lock").exists():
                # its supervisor died before it ever took the run: no agent was started, so it is
                # safe to put the run back in the queue (bounded) instead of failing it
                m = _still(path, st)
                if m is None:
                    return False
                tries = int(m.get("spawn_retries") or 0)
                if tries < 3:
                    with contextlib.suppress(OSError):
                        (rd / "spawn.json").unlink()
                    transition(lab, path, m, "queued", by="reconcile", spawn_retries=tries + 1,
                               reason="supervisor exited before starting the run — re-queued")
                    return True
        if is_locked(rd / "lock"):
            return False
        # The supervisor writes its final status BEFORE it releases the lock — so, having seen the lock
        # free, re-read: if it just finished, the terminal record is already on disk and must win over
        # the stale copy we were handed (a lost race here would turn "completed" into "failed").
        m = _still(path, st)
        if m is None:
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
        m = _still(path, st)
        if m is None:
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
            "study": (str(d.get("study") or "").strip() or None),
            "campaign": (str(d.get("campaign") or "").strip().lower() or None),
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
    if m.get("failure_kind") == "usage_limit":   # hold this backend's queue until the limit lifts
        _note_limit(lab, m.get("backend") or "claude", pos_float(m.get("limit_reset"), 0.0) or time.time() + 1800)
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
        if m.get("kind") == "ask":   # the same free-form instruction again
            try:
                spec.prompt = (run_dir(path.parent, run_id) / "prompt.md").read_text(encoding="utf-8")
            except OSError:
                spec.prompt = ""
        try:
            child = enqueue(lab, spec)
            m["repeat_child"] = child["run_id"]
        except SpecError as e:
            m["repeat_error"] = str(e)
    m["post_processed"] = True
    write_manifest(path, m)


# ── usage limits: a backend that hit its limit starts nothing until it lifts ─────────────────────

def _limits_path(lab: Lab) -> Path:
    return lab.lab / ".bus" / "limits.json"


def limits(lab: Lab) -> dict:
    try:
        d = json.loads(_limits_path(lab).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    t = time.time()
    return {k: v for k, v in d.items() if isinstance(v, (int, float)) and v > t}


def _note_limit(lab: Lab, backend: str, until: float) -> None:
    d = limits(lab)
    d[backend] = max(float(until), d.get(backend, 0.0))
    p = _limits_path(lab)
    with contextlib.suppress(OSError):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d), encoding="utf-8")


def cap_key(m: dict, target: str) -> str:
    """What a run counts against: a campaign's cycles (1 at a time), a study (hub runs about a study count
    as that study's, so a long hub procedure on one study doesn't block every other), or the hub itself."""
    if m.get("skill") == "autopilot" and m.get("campaign"):
        return "campaign:" + str(m["campaign"])
    if m.get("level") == "hub":
        return ("hub:" + str(m["subject"])) if m.get("subject") else HUB_TARGET
    return m.get("target") or target


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
    # Carry our import path: under `uv run --with pyyaml` the overlay that provides pyyaml may not
    # be visible to a bare child of sys.executable — the supervisor must import exactly what we can.
    env = dict(os.environ)
    if python_exe() == sys.executable:   # the same interpreter: carry exactly what we can import
        paths = [p for p in sys.path if p and os.path.isdir(p)]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(paths))
    else:                                # a durable interpreter with its own pyyaml — never another's paths
        env.pop("PYTHONPATH", None)
    with open(log_path, "ab") as log:
        p = subprocess.Popen([python_exe(), str(CLI), "--hub", str(lab.hub), "supervise",
                              "--run", run_id, "--target", target],
                             cwd=str(lab.hub), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                             env=env, close_fds=True, **DETACHED)
    try:   # a sidecar, NOT the manifest (the supervisor owns the manifest from here on)
        (log_path.parent / "spawn.json").write_text(json.dumps({"pid": p.pid, "ts": now()}), encoding="utf-8")
    except OSError:
        pass
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
        try:
            notify.check_in_background(lab)   # what needs the PI → their phone (works with the dashboard closed)
        except Exception:  # noqa: BLE001
            pass
        prog = lab.prog()
        report["enabled"] = bool(prog.get("enabled"))
        depth = pos_int(os.environ.get("AUTOSCIENTIST_AGENT_DEPTH", "0") or 0, 0, 0)
        if not prog.get("enabled") or depth >= pos_int(prog.get("max_depth", 1), 1, 0):
            return report
        try:
            report["campaigns"] = campaigns.keep(lab)
        except Exception as e:  # noqa: BLE001 — the keeper must never stop scheduling
            report["campaigns"] = {"error": str(e)}
        runs = all_runs(lab)   # post-processing and the keeper may have queued runs
        manifests = [m for *_x, m in runs]
        report["brake"] = brake(lab, manifests)
        if report["brake"]:
            return report
        c = caps(lab)
        active = [(t, m) for t, _w, _p, m in runs if m.get("status") in ACTIVE]
        n_total = len(active)
        per: dict[str, int] = {}
        for t, m in active:
            key = cap_key(m, t)
            per[key] = per.get(key, 0) + 1
        held = limits(lab)
        queued = [(t, w, p, m) for t, w, p, m in runs if m.get("status") == "queued" and m.get("schema") == 2]
        queued.sort(key=lambda x: (-int(x[3].get("priority") or 0), 0 if x[3].get("resume") else 1,
                                   x[3].get("created") or ""))
        tnow = time.time()
        for _t, workdir, path, m in queued:
            nb = parse_ts(m.get("not_before"))
            if nb and nb > tnow:
                continue
            if held.get(m.get("backend") or "claude"):
                continue   # that backend's usage limit hasn't lifted yet
            key = cap_key(m, _t)
            cap = 1 if key.startswith("campaign:") else c["hub"] if key == HUB_TARGET else c["per_project"]
            if n_total >= c["total"] or per.get(key, 0) >= cap:
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
        if not report["skipped"]:
            write_lease(lab, os.environ.get("NEWTS_TICKER") or "tick")


def last_tick(lab: Lab) -> dict | None:
    return _LAST_TICK.get(str(lab.hub))


# ── the scheduler lease: someone must keep ticking while there is work ───────────────────────────
LEASE_STALE_S = 60


def _lease_path(lab: Lab) -> Path:
    return lab.lab / ".bus" / "scheduler.lease"


def write_lease(lab: Lab, by: str) -> None:
    with contextlib.suppress(OSError):
        p = _lease_path(lab)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"pid": os.getpid(), "ts": time.time(), "by": by}), encoding="utf-8")


def lease(lab: Lab) -> dict:
    try:
        d = json.loads(_lease_path(lab).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"age": None}
    d["age"] = round(time.time() - float(d.get("ts") or 0), 1)
    return d


def has_work(lab: Lab) -> bool:
    """Queued/live runs, or a campaign still being kept."""
    if any(m.get("status") in ACTIVE | {"queued"} for *_x, m in all_runs(lab)):
        return True
    return any(c.get("status") in ("active", "finishing", "stopping") for c in campaigns.all_states(lab))


def ensure_ticker(lab: Lab) -> bool:
    """Called when a supervisor exits: if nobody has ticked for a minute (the dashboard was closed) and there
    is work left, start a detached `executor_cli serve --until-idle` so queued runs, retries, chains and
    campaigns keep moving. Returns True if it started one."""
    if os.environ.get("NEWTS_NO_AUTOTICKER"):
        return False
    age = lease(lab).get("age")
    if age is not None and age < LEASE_STALE_S:
        return False
    if not has_work(lab):
        return False
    log = lab.lab / ".bus" / "scheduler-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("AUTOSCIENTIST_AGENT_DEPTH", None)   # the ticker is the PI's scheduler, not an agent
    with open(log, "ab") as fh:
        subprocess.Popen([python_exe(), str(CLI), "--hub", str(lab.hub), "serve", "--until-idle"], cwd=str(lab.hub),
                         stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, env=env, close_fds=True,
                         **DETACHED)
    write_lease(lab, "spawned serve --until-idle")
    return True


def tick_loop(lab_factory, stop: threading.Event, interval: float = 2.0, reconcile_every: float = 30.0,
              until_idle: bool = False, idle_seconds: float = 120.0) -> None:
    """Run tick() until `stop` is set (or, with `until_idle`, until there is no work left for two minutes).
    `lab_factory()` builds a fresh Lab each pass (so a moved or monkeypatched hub root is honoured). Keeps
    the machine awake while there is work. Never raises."""
    from . import awake   # noqa: PLC0415
    idle_since = None
    try:
        while not stop.is_set():
            lab = None
            try:
                lab = lab_factory()
                tick(lab)
                awake.update(lab)
            except Exception:  # noqa: BLE001 — the loop must survive any single bad pass
                pass
            if until_idle and lab is not None:
                try:
                    busy = has_work(lab)
                except Exception:  # noqa: BLE001
                    busy = True
                idle_since = None if busy else (idle_since or time.time())
                if idle_since and time.time() - idle_since > idle_seconds:
                    break
            stop.wait(interval)
    finally:
        awake.release()
