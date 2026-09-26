"""Launch a headless TOP-LEVEL agent into a project repo and capture everything it does.

    uv run --with pyyaml python tools/agent_runner.py launch      --project <slug|path> \
        --prompt-file <f> [--role R] [--label L] [--backend claude|codex|opencode] [--model M]
    uv run --with pyyaml python tools/agent_runner.py launch-many --projects p1,p2,p3 \
        --prompt-file <f> [--campaign <brief>] [--role R] [--backend B] [--max-concurrent N]
    uv run --with pyyaml python tools/agent_runner.py list          --project <slug|path>
    uv run --with pyyaml python tools/agent_runner.py reconcile     --project <slug|path>
    uv run --with pyyaml python tools/agent_runner.py kill          --project <slug|path> [--agent ID | --all]
    uv run --with pyyaml python tools/agent_runner.py kill-campaign --campaign <manifest|id>

The hub orchestrator (e.g. an `/autopilot` coordinator) calls `launch` to spin up ONE headless
session **per project** — a **top-level session** (`claude -p` / `codex exec` / `opencode run`), NOT a
nested subagent — so it sidesteps the no-nested-subagents rule and can itself spawn its own
experiment-runner subagents. `launch-many` runs one such `launch` per project up to a concurrency cap
(`min(autopilot.max_concurrent_projects, agents.programmatic.max_concurrent)`), with per-project
failure isolation and a campaign manifest under `lab/.bus/campaign-agents/<id>.json` — so `/autopilot`
gets platform-agnostic concurrency without shell backgrounding; `kill-campaign` stops the whole fleet. It runs in the project's cwd, so the project's `.claude/settings.json`
hooks + `run.py` already emit run/worker signals into `<project>/.bus/` (the dashboard catches them
live). On top of that, this tool persists, so **nothing is lost** even on a crash:
  - `<project>/.bus/agents/<id>.stream.jsonl` — the full captured stdout JSONL transcript
  - `<project>/.bus/agents/<id>.json`        — a manifest (status running→terminal, pid, timing)
  - `agent_launched` / `agent_finished`      — bus events on the project bus
  - a synthesized `<project>/.bus/workers/<id>.jsonl` worker log for backends that DON'T fire
    Claude Code hooks (codex, opencode), so they still render as a dashboard sprite (claude relies on hooks).

Safety (the lab is "full autonomy WITH many human-intervention points"):
  - **PI-owned opt-in:** refuses unless `agents.programmatic.enabled: true` (default OFF).
  - **Depth-capped:** a launched agent can't launch more (env `AUTOSCIENTIST_AGENT_DEPTH` vs `max_depth`).
  - **Gate 3 is never delegated** — a launched agent stops its pipeline at `internal-review` (enforced
    by the prompt the orchestrator gives it; this tool never finalizes anything).
  - **Watchdog** kills the process tree on `max_minutes` breach; **reconcile** marks crashed agents.
  - Training still serializes through `tools/run_slots.py` (`compute.max_concurrent_runs`); the PI can
    stop everything by setting that to 0, by a dashboard `kill`/`park` directive, or by flipping the
    master switch off. Exit: 0 = completed · 1 = blocked/error · 2 = non-clean agent exit.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))   # tools/ — the shared executor package
from executor import backends as _bk  # noqa: E402
from executor import manifest as _man  # noqa: E402
from executor import procs as _procs  # noqa: E402
from executor import scheduler as _sched  # noqa: E402
from executor import supervise as _sup  # noqa: E402
from executor.lab import Lab as _Lab  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
_DEPTH_ENV = "AUTOSCIENTIST_AGENT_DEPTH"
# Match sweep.py: a killable process group so we can reap the whole tree on timeout.
_NEW_GROUP = _procs.NEW_GROUP


# ── config / registry ───────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _prog_cfg() -> dict:
    return ((_load_yaml(LAB / "config.yaml").get("agents") or {}).get("programmatic")) or {}


def _pos_int(value, default: int, minimum: int) -> int:
    """Parse a numeric config knob defensively: unparseable -> default; below minimum -> clamped."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return v if v >= minimum else minimum


def _pos_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _launch_lock(adir: Path):
    """Serialize the cap-check + manifest reservation so two near-simultaneous launches can't both
    pass max_concurrent. A crashed holder's lock (>2 min old) is reclaimed."""
    return _man.launch_lock(adir)


def _registry_rows() -> list[dict]:
    reg = LAB / "REGISTRY.md"
    out = []
    if not reg.exists():
        return out
    for line in reg.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= {"-"} or cells[0] == "—":
            continue
        out.append(dict(zip(_COLS, cells)))
    return out


def _projects_root() -> Path:
    root = ((_load_yaml(LAB / "config.yaml").get("lab") or {}).get("projects_root")) \
        or "../newts-lab-projects"
    return (HUB / root).resolve()


def _resolve_project(arg: str) -> Path | None:
    p = Path(arg)
    if p.exists() and (p / "control.yaml").exists():
        return p.resolve()
    row = next((r for r in _registry_rows() if r["id"] == arg), None)
    if row:
        raw = (row.get("project") or "").strip().strip("`")
        if raw and raw not in ("—", "-"):
            pp = Path(raw)
            return pp if pp.is_absolute() else (HUB / pp).resolve()
    cand = _projects_root() / arg
    return cand if cand.exists() else None


# ── process helpers (shared with the executor: tools/executor/procs.py) ──────────

def _pid_alive(pid) -> bool:
    return _procs.pid_alive(pid)


def _kill_tree(pid) -> None:
    _procs.kill_tree(pid)


# ── persistence (mirror tracking.py shapes) ───────────────────────────────────────

def _agents_dir(pdir: Path) -> Path:
    d = pdir / ".bus" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_manifest(path: Path, manifest: dict) -> None:
    _man.write_manifest(path, manifest)


def _list_manifests(pdir: Path) -> list[dict]:
    adir = pdir / ".bus" / "agents"
    if not adir.exists():
        return []
    out = []
    for f in sorted(adir.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8-sig")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _emit(pdir: Path, kind: str, **fields) -> None:
    """One project-bus event, same shape as tracking.py._bus_emit. Best-effort."""
    try:
        bus = pdir / ".bus"
        bus.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": pdir.name, "kind": kind}
        rec.update({k: v for k, v in fields.items() if v is not None})
        with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _worker_line(wlog: Path, **fields) -> None:
    """One worker-log line in the EXACT schema tools/trace_hook.py writes + dashboard reads."""
    try:
        wlog.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
        rec.update({k: v for k, v in fields.items() if v is not None})
        with wlog.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001
        pass


# ── backends (shared with the executor: tools/executor/backends.py) ───────────────

def _build_command(backend: str, prompt: str, pdir: Path, model: str,
                   permission_mode: str, prog: dict) -> tuple[list[str], bool]:
    """Return (argv, fires_claude_hooks). The launcher only synthesizes a worker log when the
    backend does NOT fire Claude Code hooks (claude does; codex / test backends don't)."""
    return _bk.build_command(backend, prompt, pdir, model, permission_mode, prog)


def _parse_activity(backend: str, obj: dict) -> dict | None:
    """Translate one stream JSON object into a worker-activity dict, or None to ignore."""
    return _bk.parse_activity(backend, obj)


# ── commands ────────────────────────────────────────────────────────────────────

def cmd_launch(a) -> int:
    prog = _prog_cfg()
    if not prog.get("enabled"):
        print("[agent_runner] BLOCKED: agents.programmatic.enabled is false — programmatic launching is "
              "a PI-owned opt-in. Enable via /configure (or a PI-signed /autopilot campaign brief) first.")
        return 1
    depth = _pos_int(os.environ.get(_DEPTH_ENV, "0") or 0, 0, 0)
    max_depth = _pos_int(prog.get("max_depth", 1), 1, 0)   # 0 = kill switch (blocks all launches)
    if depth >= max_depth:
        print(f"[agent_runner] BLOCKED: launch depth {depth} >= max_depth {max_depth} — a launched agent "
              "may not launch further agents (mirrors the no-nested-subagents rule). Only the top-level "
              "orchestrator launches.")
        return 1
    pdir = _resolve_project(a.project)
    if not pdir or not pdir.exists():
        print(f"[agent_runner] BLOCKED: no project dir for {a.project!r}")
        return 1
    prompt = a.prompt
    if prompt is None and a.prompt_file:
        try:
            prompt = Path(a.prompt_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"[agent_runner] BLOCKED: cannot read --prompt-file {a.prompt_file}: {e}")
            return 1
    if not prompt:
        print("[agent_runner] BLOCKED: need --prompt or --prompt-file")
        return 1

    backend = a.backend or prog.get("backend") or "claude"
    model = a.model or prog.get("model") or "inherit"
    perm = prog.get("permission_mode") or "auto"
    role = a.role or "orchestrator"
    # A headless agent ALWAYS has a wall-clock cap — 0/unset is the default, never "unbounded"
    # (the watchdog is the only kill for a hung/non-terminating child, so it must always run).
    max_minutes = _pos_float(prog.get("max_minutes"), 0.0)
    if max_minutes <= 0:
        max_minutes = 240.0
    cap = _pos_int(prog.get("max_concurrent", 3), 3, 1)   # matches lab/config.yaml default
    cmd, fires_hooks = _build_command(backend, prompt, pdir, model, perm, prog)  # may SystemExit on the extra-args guard
    adir = _agents_dir(pdir)

    # Serialize the cap-check + manifest reservation so two near-simultaneous launches can't both
    # pass the cap (the reservation — a 'running' manifest — counts toward the next launcher's check).
    try:
        with _launch_lock(adir):
            running = [m for m in _list_manifests(pdir)
                       if m.get("status") == "running" and _pid_alive(m.get("pid"))]
            if len(running) >= cap:
                print(f"[agent_runner] BLOCKED: {len(running)} agent(s) already running on {pdir.name} "
                      f"(agents.programmatic.max_concurrent={cap})")
                return 1
            base = f"{a.label or role}-{time.strftime('%Y%m%d-%H%M%S')}"
            agent_id, manifest_path = base, adir / f"{base}.json"
            for i in range(1, 100):  # collision suffix (same-second launches)
                if not manifest_path.exists():
                    break
                agent_id = f"{base}-{i}"
                manifest_path = adir / f"{agent_id}.json"
            stream_path = adir / f"{agent_id}.stream.jsonl"
            wlog = None if fires_hooks else (pdir / ".bus" / "workers" / f"{agent_id}.jsonl")
            manifest = {
                "schema": 2, "run_id": agent_id, "target": pdir.name, "level": "project",
                "created_by": "agent_runner", "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "attempt": 1, "status_ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "agent_id": agent_id, "backend": backend, "model": model, "role": role,
                "label": a.label, "project": pdir.name, "cwd": str(pdir),
                "prompt_summary": prompt.strip()[:200], "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "status": "running", "pid": None, "stream": stream_path.name, "max_minutes": max_minutes,
                "session_id": None, "exit_code": None, "finished": None, "wall_seconds": None, "last_message": None,
            }
            _write_manifest(manifest_path, manifest)   # the reservation
    except TimeoutError:
        print("[agent_runner] BLOCKED: launch ledger busy — another launch is in progress, retry")
        return 1

    env = dict(os.environ)
    env[_DEPTH_ENV] = str(depth + 1)
    env["AUTOSCIENTIST_NO_GATE3"] = "1"   # Gate 3 is never delegated — guard.py finalization hard-stops it
    if backend == "opencode":
        env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")   # no mid-run autoupdate in a headless launch
        operm = ((prog.get("backends") or {}).get("opencode") or {}).get("permission")
        if operm:   # blank = opencode's defaults (in-repo allow + external_directory auto-deny = contained)
            env["OPENCODE_PERMISSION"] = json.dumps(operm)   # string "allow" or a full {bash,edit,…} object
    print(f"[agent_runner] launching {backend} agent '{agent_id}' in {pdir.name} (depth {depth + 1})", flush=True)
    lab = _Lab(HUB)
    lock = _procs.RunLock(_man.run_dir(adir, agent_id) / "lock")   # liveness for reconcile (kernel-freed on death)
    lock.try_acquire()
    state = {"sid": None, "last": None}

    def on_spawn(pid):
        manifest["pid"] = pid
        _write_manifest(manifest_path, manifest)
        _emit(pdir, "agent_launched", detail=agent_id, data={"backend": backend, "role": role, "pid": pid})
        if wlog:
            _worker_line(wlog, worker_id=agent_id, role=role, event="start", status="working", idea=pdir.name)

    def on_event(act):
        if act.get("session_id") and not state["sid"]:
            state["sid"] = act["session_id"]
            manifest["session_id"] = state["sid"]      # recorded the moment it is known, not at exit —
            _write_manifest(manifest_path, manifest)   # so the dashboard can join the run to its worker log
        if act.get("event") == "result" and act.get("last_message"):
            state["last"] = act["last_message"]
        if wlog and act.get("event") == "action":  # 'start' was already written at launch
            _worker_line(wlog, worker_id=agent_id, role=role, event="action",
                         tool=act.get("tool"), kind=act.get("kind"), summary=act.get("summary"),
                         idea=pdir.name)

    # Cap the persisted transcript so a runaway/looping agent can't fill the disk before the
    # max_minutes watchdog fires (default 200 MB; 0 = unlimited). Parsing for activity continues.
    max_bytes = _pos_int(prog.get("max_transcript_mb", 200), 200, 0) * 1024 * 1024
    try:
        res = _sup.run_process(cmd, cwd=pdir, env=env, stream_path=stream_path, backend=backend,
                               max_seconds=max_minutes * 60, max_bytes=max_bytes,
                               on_spawn=on_spawn, on_event=on_event,
                               stop_file=_man.run_dir(adir, agent_id) / "stop")   # the dashboard's stop
    finally:
        lock.release()
    if res.cli_missing:
        manifest.update(status="failed", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        last_message=f"backend CLI not found on PATH: {cmd[0]}")
        _write_manifest(manifest_path, manifest)
        _emit(pdir, "agent_finished", detail=agent_id, status="failed", data={"reason": "cli-not-found"})
        hint = {
            "claude": "install/login the Claude CLI",
            "codex": "install/auth the codex CLI",
            "opencode": "install opencode (curl -fsSL https://opencode.ai/install | bash, or "
                        "npm i -g opencode-ai) then 'opencode auth login'",
        }.get(backend, "install the backend CLI")
        print(f"[agent_runner] FAILED: backend CLI '{cmd[0]}' not found on PATH ({hint}).")
        return 1
    if res.breached:
        print(f"[agent_runner] TIMEOUT — max_minutes={max_minutes} breached; killed '{agent_id}'", flush=True)

    class _P:  # the returncode view the status logic below reads
        returncode = res.rc
    proc = _P()
    breached = {"v": res.breached}
    session_id = state["sid"] or res.session_id
    last_message = res.last_message or state["last"]
    t0 = time.time() - res.wall
    # Returncode is authoritative: a clean exit is 'completed' even if the watchdog raced at the
    # boundary; a non-zero exit is 'timeout' only when the watchdog actually killed it, else 'failed'.
    if proc.returncode == 0:
        status = "completed"
    elif res.stopped:
        status = "killed"
    elif breached["v"]:
        status = "timeout"
    else:
        status = "failed"
    try:
        (_man.run_dir(adir, agent_id) / "stop").unlink()
    except OSError:
        pass
    manifest.update(exit_code=proc.returncode, finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    wall_seconds=round(time.time() - t0, 1), session_id=session_id,
                    last_message=(last_message or "")[:1000] or None)
    _man.transition(lab, manifest_path, manifest, status, by="agent_runner",
                    reason=None if status == "completed" else
                    ("stopped by the PI" if status == "killed" else f"exit {proc.returncode}"))
    if wlog:
        _worker_line(wlog, worker_id=agent_id, role=role, event="stop", status="done", idea=pdir.name)
    _emit(pdir, "agent_finished", detail=agent_id, status=status, data={"exit_code": proc.returncode})
    print(f"[agent_runner] '{agent_id}' -> {status} (exit {proc.returncode}) · "
          f"transcript: .bus/agents/{stream_path.name}", flush=True)
    if last_message:
        print(f"[agent_runner] last message: {last_message[:300]}")
    return 0 if status == "completed" else 2


def cmd_list(a) -> int:
    pdir = _resolve_project(a.project)
    if not pdir:
        print(f"[agent_runner] no project for {a.project!r}")
        return 1
    ms = _list_manifests(pdir)
    print(f"## Launched agents — {pdir.name} ({len(ms)})")
    for m in ms:
        alive = " ·alive" if (m.get("status") == "running" and _pid_alive(m.get("pid"))) else ""
        print(f"- {m.get('agent_id')} [{m.get('backend')}] {m.get('status')}{alive} "
              f"exit={m.get('exit_code')} started={m.get('started')}")
    return 0


def _reconcile_project(pdir: Path) -> int:
    """Mark every orphaned 'running' manifest as failed. Returns the count. Executor-era manifests
    are judged by their supervisor's OS lock; legacy ones by pid liveness (tools/executor/scheduler.py)."""
    adir = pdir / ".bus" / "agents"
    lab = _Lab(HUB)
    n = 0
    for f, m in _man.list_manifests(adir):
        try:
            n += int(_sched.reconcile_manifest(lab, pdir, f, m))
        except OSError:
            continue
    return n


def _kill_project(pdir: Path, *, kill_all: bool = False, agent: str | None = None) -> int:
    """Stop agents on one project (all, or one by id) and reconcile. Returns how many were stopped.

    Goes through the executor's stop — the same as the dashboard button — so a supervised run is
    recorded as `killed` (and stays resumable), a queued one is cancelled, one paused for the PI is
    closed; a manifest the executor can't place (an unregistered path) falls back to killing its pid."""
    from executor import runs as _runs
    from executor.spec import SpecError
    lab = _Lab(HUB)
    stoppable = _man.ACTIVE | _man.PAUSED | {"queued"}
    killed = 0
    for m in _list_manifests(pdir):
        rid = m.get("run_id") or m.get("agent_id")
        if m.get("status") not in stoppable or not (kill_all or agent in (rid, m.get("agent_id"))):
            continue
        try:
            _runs.stop(lab, rid, by="agent_runner")
        except (SpecError, TypeError, KeyError):
            if not m.get("pid"):
                continue
            _kill_tree(m["pid"])
        killed += 1
        print(f"[agent_runner] stopped {rid}" + (f" (pid {m.get('pid')})" if m.get("pid") else ""))
    _reconcile_project(pdir)
    return killed


def cmd_reconcile(a) -> int:
    pdir = _resolve_project(a.project)
    if not pdir:
        print(f"[agent_runner] no project for {a.project!r}")
        return 1
    n = _reconcile_project(pdir)
    print(f"[agent_runner] reconciled {n} orphaned agent(s) in {pdir.name}")
    return 0


def cmd_kill(a) -> int:
    pdir = _resolve_project(a.project)
    if not pdir:
        print(f"[agent_runner] no project for {a.project!r}")
        return 1
    if not a.all and not a.agent:
        print("[agent_runner] need --agent ID or --all")
        return 1
    killed = _kill_project(pdir, kill_all=a.all, agent=a.agent)
    if killed == 0:
        print("[agent_runner] no running agents matched")
        return 1
    return 0


# ── multi-project campaign launcher ─────────────────────────────────────────────

def _campaign_cap(prog: dict, override) -> int:
    """How many project-agents may run concurrently: min(autopilot.max_concurrent_projects,
    agents.programmatic.max_concurrent), unless the caller overrides."""
    if override:
        return _pos_int(override, 1, 1)
    ap_cap = _pos_int((_load_yaml(LAB / "config.yaml").get("autopilot") or {}).get("max_concurrent_projects", 1), 1, 1)
    prog_cap = _pos_int(prog.get("max_concurrent", 3), 3, 1)
    return min(ap_cap, prog_cap)


def _campaign_id(campaign) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(campaign).stem if campaign else "campaign")
    return f"{stem}-{time.strftime('%Y%m%d-%H%M%S')}"


def _render_prompt(text: str, slug: str, campaign_id: str) -> str:
    return (text.replace("{{slug}}", slug).replace("{{project}}", slug)
                .replace("{{campaign}}", campaign_id))


def _count_escalations(pdir: Path) -> int:
    f = pdir / ".bus" / "events.jsonl"
    if not f.exists():
        return 0
    n = 0
    for line in f.read_text(encoding="utf-8-sig").splitlines():
        try:
            if json.loads(line).get("kind") == "escalation":
                n += 1
        except json.JSONDecodeError:
            continue
    return n


def _slug_of(lab, pdir: Path) -> str:
    """The registry slug whose project repo is `pdir` (else the dir name)."""
    want = Path(pdir).resolve()
    for slug, d in lab.project_dirs():
        if d.resolve() == want:
            return slug
    return Path(pdir).name


CAMPAIGN_POLL_S = 3.0


def _default_launch(pdir: Path, prompt_file: Path, *, backend=None, model=None,
                    role="orchestrator", label=None) -> dict:
    """ONE project's campaign worker, run by the executor — so it is a first-class run: listed in the
    dashboard with its subagents, stoppable, and able to pause on a PI question — then wait for it.

    The wait ends when the run finishes OR pauses for the PI (`waiting_input`): the campaign reports
    that project as waiting and moves on; the PI answers from the dashboard and the run resumes on
    its own. All executor gates apply (programmatic.enabled, max_depth, caps, daily brake)."""
    from executor import runs as _runs
    from executor.spec import RunSpec, SpecError
    lab = _Lab(HUB)
    slug = _slug_of(lab, pdir)
    spec = RunSpec(skill="", target=slug, prompt_override=Path(prompt_file).read_text(encoding="utf-8"),
                   backend=backend, model=model if model and model != "inherit" else None, role=role,
                   label=label or "campaign", parent=label, campaign=label, created_by="campaign")
    try:
        m = _runs.enqueue(lab, spec)
    except SpecError as e:
        return {"agent_id": None, "exit_code": None, "status": "launch-error", "error": str(e)}
    run_id = m["run_id"]
    while True:
        try:
            _sched.tick(lab)
        except Exception:  # noqa: BLE001 — another ticker (the dashboard) may hold the lock; just wait
            pass
        hit = _man.find_run(lab, run_id)
        st = (hit[3] if hit else {}).get("status")
        if st in _man.TERMINAL or st in _man.PAUSED:
            break
        time.sleep(CAMPAIGN_POLL_S)
    cur = hit[3] if hit else {}
    status = {"completed": "completed", "waiting_input": "waiting-for-pi"}.get(st, "agent-nonclean")
    return {"agent_id": run_id, "exit_code": cur.get("exit_code"), "status": status,
            "stdout_tail": str(cur.get("last_message") or "")[-400:]}


def run_campaign(projects: list[str], prompt_text: str, *, campaign=None, backend=None, model=None,
                 role="orchestrator", max_concurrent=None, prog=None, launch_fn=None) -> dict:
    """Launch ONE headless agent per project, up to `cap` concurrently, with per-project failure
    isolation. Writes an append-updated campaign manifest and returns it. `launch_fn` is injectable
    for tests (default spawns `agent_runner.py launch` per project)."""
    prog = _prog_cfg() if prog is None else prog
    launch_fn = launch_fn or _default_launch
    cap = _campaign_cap(prog, max_concurrent)
    campaign_id = _campaign_id(campaign)
    cdir = LAB / ".bus" / "campaign-agents"
    (cdir / campaign_id / "prompts").mkdir(parents=True, exist_ok=True)
    entries = [(p, _resolve_project(p)) for p in projects]
    manifest = {
        "campaign_id": campaign_id, "campaign": str(campaign) if campaign else None,
        "backend": backend or prog.get("backend") or "claude", "role": role, "cap": cap,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "finished": None,
        "projects": [p for p, _ in entries], "results": {}, "escalations": 0,
    }
    mpath = cdir / f"{campaign_id}.json"
    _write_manifest(mpath, manifest)
    lock = threading.Lock()

    def _one(entry):
        slug, pdir = entry
        if not pdir:
            r = {"project": slug, "status": "no-project", "agent_id": None, "exit_code": None}
        else:
            pf = cdir / campaign_id / "prompts" / f"{re.sub(r'[^A-Za-z0-9._-]', '_', slug)}.md"
            pf.write_text(_render_prompt(prompt_text, slug, campaign_id), encoding="utf-8")
            try:
                r = {"project": slug, **launch_fn(pdir, pf, backend=backend, model=model,
                                                  role=role, label=campaign_id)}
            except Exception as e:  # noqa: BLE001 — isolation: one project's failure never stops the rest
                r = {"project": slug, "status": "launch-error", "agent_id": None,
                     "exit_code": None, "error": str(e)}
            r["escalations"] = _count_escalations(pdir)
        with lock:
            manifest["results"][slug] = r
            _write_manifest(mpath, manifest)
        return r

    with ThreadPoolExecutor(max_workers=cap) as pool:
        list(pool.map(_one, entries))

    manifest["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    manifest["escalations"] = sum(int(r.get("escalations") or 0) for r in manifest["results"].values())
    _write_manifest(mpath, manifest)
    return manifest


def cmd_launch_many(a) -> int:
    prog = _prog_cfg()
    if not prog.get("enabled"):
        print("[agent_runner] BLOCKED: agents.programmatic.enabled is false — programmatic launching is "
              "a PI-owned opt-in. Enable via /configure (or a PI-signed /autopilot campaign brief) first.")
        return 1
    depth = _pos_int(os.environ.get(_DEPTH_ENV, "0") or 0, 0, 0)
    max_depth = _pos_int(prog.get("max_depth", 1), 1, 0)
    if depth >= max_depth:
        print(f"[agent_runner] BLOCKED: depth {depth} >= max_depth {max_depth} — a launched agent may "
              "not run a campaign of further agents. Only the top-level orchestrator launches.")
        return 1
    projects = [p.strip() for p in (a.projects or "").split(",") if p.strip()]
    if not projects:
        print("[agent_runner] BLOCKED: --projects is empty")
        return 1
    prompt = a.prompt
    if prompt is None and a.prompt_file:
        try:
            prompt = Path(a.prompt_file).read_text(encoding="utf-8")
        except OSError as e:
            print(f"[agent_runner] BLOCKED: cannot read --prompt-file {a.prompt_file}: {e}")
            return 1
    if not prompt:
        print("[agent_runner] BLOCKED: need --prompt or --prompt-file (the per-project worker instruction; "
              "{{slug}}/{{project}}/{{campaign}} are substituted per project)")
        return 1
    man = run_campaign(projects, prompt, campaign=a.campaign, backend=a.backend, model=a.model,
                       role=a.role or "orchestrator", max_concurrent=a.max_concurrent)
    results = man["results"]
    ok = sum(1 for r in results.values() if r.get("status") == "completed")
    print(f"[agent_runner] campaign {man['campaign_id']}: {ok}/{len(results)} completed, "
          f"{man['escalations']} escalation(s) · manifest lab/.bus/campaign-agents/{man['campaign_id']}.json",
          flush=True)
    for slug, r in results.items():
        print(f"  - {slug}: {r.get('status')} (agent={r.get('agent_id')}, exit={r.get('exit_code')})")
    return 0 if (ok == len(results) and ok > 0) else 2


def cmd_kill_campaign(a) -> int:
    path = Path(a.campaign)
    if not path.exists():
        name = a.campaign if a.campaign.endswith(".json") else f"{a.campaign}.json"
        path = LAB / ".bus" / "campaign-agents" / name
    if not path.exists():
        print(f"[agent_runner] no campaign manifest at {a.campaign}")
        return 1
    try:
        man = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[agent_runner] unreadable campaign manifest: {e}")
        return 1
    total = 0
    for slug in man.get("projects", []):
        pdir = _resolve_project(slug)
        if pdir:
            total += _kill_project(pdir, kill_all=True)
    print(f"[agent_runner] killed {total} running agent(s) across campaign {man.get('campaign_id')}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="launch + capture headless top-level agents into projects")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch")
    p.add_argument("--project", required=True, help="slug or project path")
    p.add_argument("--prompt", help="the instruction (or use --prompt-file)")
    p.add_argument("--prompt-file", help="file containing the instruction")
    p.add_argument("--role", default=None, help="worker role label (default: orchestrator)")
    p.add_argument("--label", default=None, help="agent id prefix (default: the role)")
    p.add_argument("--backend", default=None, choices=("claude", "codex", "opencode"),
                   help="override agents.programmatic.backend")
    p.add_argument("--model", default=None, help="override the backend model")
    p.set_defaults(fn=cmd_launch)

    for name, fn in (("list", cmd_list), ("reconcile", cmd_reconcile)):
        q = sub.add_parser(name)
        q.add_argument("--project", required=True)
        q.set_defaults(fn=fn)

    k = sub.add_parser("kill")
    k.add_argument("--project", required=True)
    k.add_argument("--agent", default=None, help="agent id to kill")
    k.add_argument("--all", action="store_true", help="kill all running agents on the project")
    k.set_defaults(fn=cmd_kill)

    lm = sub.add_parser("launch-many")
    lm.add_argument("--projects", required=True, help="comma-separated slugs/paths")
    lm.add_argument("--prompt", default=None, help="per-project instruction (or --prompt-file)")
    lm.add_argument("--prompt-file", default=None,
                    help="file with the per-project instruction ({{slug}}/{{project}}/{{campaign}} substituted)")
    lm.add_argument("--role", default=None)
    lm.add_argument("--backend", default=None, choices=("claude", "codex", "opencode"))
    lm.add_argument("--model", default=None)
    lm.add_argument("--campaign", default=None, help="campaign brief path (provenance + manifest id)")
    lm.add_argument("--max-concurrent", type=int, default=None, dest="max_concurrent",
                    help="override min(autopilot.max_concurrent_projects, agents.programmatic.max_concurrent)")
    lm.set_defaults(fn=cmd_launch_many)

    kc = sub.add_parser("kill-campaign")
    kc.add_argument("--campaign", required=True, help="campaign manifest path or id")
    kc.set_defaults(fn=cmd_kill_campaign)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
