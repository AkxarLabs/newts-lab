"""Launch a headless TOP-LEVEL agent into a project repo and capture everything it does.

    uv run --with pyyaml python tools/agent_runner.py launch --project <slug|path> \
        --prompt-file <f> [--role R] [--label L] [--backend claude|codex] [--model M]
    uv run --with pyyaml python tools/agent_runner.py list      --project <slug|path>
    uv run --with pyyaml python tools/agent_runner.py reconcile --project <slug|path>
    uv run --with pyyaml python tools/agent_runner.py kill      --project <slug|path> [--agent ID | --all]

The hub orchestrator (e.g. an `/autopilot` coordinator) calls `launch` to spin up ONE headless
session **per project** — a **top-level session** (`claude -p` / `codex exec`), NOT a nested
subagent — so it sidesteps the no-nested-subagents rule and can itself spawn its own
experiment-runner subagents. It runs in the project's cwd, so the project's `.claude/settings.json`
hooks + `run.py` already emit run/worker signals into `<project>/.bus/` (the dashboard catches them
live). On top of that, this tool persists, so **nothing is lost** even on a crash:
  - `<project>/.bus/agents/<id>.stream.jsonl` — the full captured stdout JSONL transcript
  - `<project>/.bus/agents/<id>.json`        — a manifest (status running→terminal, pid, timing)
  - `agent_launched` / `agent_finished`      — bus events on the project bus
  - a synthesized `<project>/.bus/workers/<id>.jsonl` worker log for backends that DON'T fire
    Claude Code hooks (codex), so they still render as a dashboard sprite (claude relies on hooks).

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
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
_DEPTH_ENV = "AUTOSCIENTIST_AGENT_DEPTH"
# Match sweep.py: a killable process group so we can reap the whole tree on timeout.
_NEW_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
    else {"start_new_session": True}


# ── config / registry ───────────────────────────────────────────────────────────

def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _prog_cfg() -> dict:
    return ((_load_yaml(LAB / "config.yaml").get("agents") or {}).get("programmatic")) or {}


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
        or "../kartr-lab-projects"
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


# ── process helpers (mirror sweep.py) ─────────────────────────────────────────────

def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                                 capture_output=True, text=True, check=False).stdout
            return f'"{pid}"' in out  # CSV quotes the PID column; "No tasks" banner won't contain it
        os.kill(int(pid), 0)
        return True
    except (OSError, ProcessLookupError, ValueError):
        return False


def _kill_tree(pid) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass


# ── persistence (mirror tracking.py shapes) ───────────────────────────────────────

def _agents_dir(pdir: Path) -> Path:
    d = pdir / ".bus" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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


# ── backends ──────────────────────────────────────────────────────────────────────

def _build_command(backend: str, prompt: str, pdir: Path, model: str,
                   permission_mode: str, prog: dict) -> tuple[list[str], bool]:
    """Return (argv, fires_claude_hooks). The launcher only synthesizes a worker log when the
    backend does NOT fire Claude Code hooks (claude does; codex / test backends don't)."""
    bcfg = (prog.get("backends") or {}).get(backend) or {}
    extra = str(bcfg.get("extra_args") or "")

    def _guard_extra(forbidden: tuple[str, ...]) -> None:
        # extra_args is a PI-owned advanced knob; it must NOT silently negate the human-in-loop
        # permission/sandbox defaults this tool promises. Refuse rather than override.
        hit = [f for f in forbidden if f in extra.split()]
        if hit:
            raise SystemExit(f"[agent_runner] backends.{backend}.extra_args may not set {hit} — that "
                             "would defeat the human-in-loop default; set the dedicated config key instead")

    if backend == "claude":
        _guard_extra(("--permission-mode", "--dangerously-skip-permissions"))
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if model and model != "inherit":
            cmd += ["--model", str(model)]
        if permission_mode:
            cmd += ["--permission-mode", str(permission_mode)]
        if extra:
            cmd += extra.split()
        return cmd, True
    if backend == "codex":
        _guard_extra(("--sandbox", "-a", "--ask-for-approval", "--dangerously-bypass-approvals-and-sandbox", "--yolo"))
        cmd = ["codex", "exec", prompt, "--json", "--sandbox", str(bcfg.get("sandbox") or "workspace-write"),
               "-a", "never", "--skip-git-repo-check", "-C", str(pdir)]
        if model and model != "inherit":
            cmd += ["-m", str(model)]
        if extra:
            cmd += extra.split()
        return cmd, False
    if backend == "_dummy":  # test backend: a portable JSONL emitter configured in lab/config.yaml
        c = bcfg.get("command")
        if not c:
            raise SystemExit("_dummy backend needs agents.programmatic.backends._dummy.command")
        return (c if isinstance(c, list) else str(c).split()), False
    raise SystemExit(f"[agent_runner] unknown backend {backend!r} (claude | codex)")


def _parse_activity(backend: str, obj: dict) -> dict | None:
    """Translate one stream JSON object into a worker-activity dict, or None to ignore."""
    t = obj.get("type")
    if backend == "claude":
        # `claude -p --output-format stream-json` emits envelope objects: system(init),
        # assistant/user (each with a full message.content[] of complete tool_use/text/tool_result
        # blocks — NOT raw Messages-API deltas), and a final result.
        if t == "system" and obj.get("subtype") == "init":
            return {"event": "start", "status": "working", "session_id": obj.get("session_id")}
        if t == "assistant":
            for block in ((obj.get("message") or {}).get("content") or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    return {"event": "action", "tool": block.get("name"), "kind": "tool",
                            "summary": str(block.get("input") or "")[:200]}
            return None
        if t == "result":
            return {"event": "result", "last_message": obj.get("result"), "session_id": obj.get("session_id")}
        return None
    # codex (and the _dummy test backend mimics codex's ThreadEvent JSONL shape)
    if t in ("thread.started",):
        return {"event": "start", "status": "working",
                "session_id": obj.get("thread_id") or obj.get("session_id")}
    if t in ("item.started", "item.completed"):
        it = obj.get("item") or {}
        itype = it.get("type")
        if itype in ("command_execution", "mcp_tool_calls", "web_searches", "file_changes"):
            return {"event": "action", "tool": itype, "kind": "tool",
                    "summary": str(it.get("command") or it.get("status") or itype)[:200]}
        if itype == "agent_message" and t == "item.completed":
            return {"event": "result", "last_message": str(it.get("text") or "")[:500]}
    return None


# ── commands ────────────────────────────────────────────────────────────────────

def cmd_launch(a) -> int:
    prog = _prog_cfg()
    if not prog.get("enabled"):
        print("[agent_runner] BLOCKED: agents.programmatic.enabled is false — programmatic launching is "
              "a PI-owned opt-in. Enable via /configure (or a PI-signed /autopilot campaign brief) first.")
        return 1
    depth = int(os.environ.get(_DEPTH_ENV, "0") or 0)
    max_depth = int(prog.get("max_depth", 1))
    if depth >= max_depth:
        print(f"[agent_runner] BLOCKED: launch depth {depth} >= max_depth {max_depth} — a launched agent "
              "may not launch further agents (mirrors the no-nested-subagents rule). Only the top-level "
              "orchestrator launches.")
        return 1
    pdir = _resolve_project(a.project)
    if not pdir or not pdir.exists():
        print(f"[agent_runner] BLOCKED: no project dir for {a.project!r}")
        return 1
    prompt = a.prompt or (Path(a.prompt_file).read_text(encoding="utf-8") if a.prompt_file else None)
    if not prompt:
        print("[agent_runner] BLOCKED: need --prompt or --prompt-file")
        return 1

    running = [m for m in _list_manifests(pdir)
               if m.get("status") == "running" and _pid_alive(m.get("pid"))]
    cap = int(prog.get("max_concurrent", 2))
    if len(running) >= cap:
        print(f"[agent_runner] BLOCKED: {len(running)} agent(s) already running on {pdir.name} "
              f"(agents.programmatic.max_concurrent={cap})")
        return 1

    backend = a.backend or prog.get("backend") or "claude"
    model = a.model or prog.get("model") or "inherit"
    perm = prog.get("permission_mode") or "acceptEdits"
    role = a.role or "orchestrator"
    # A headless agent ALWAYS has a wall-clock cap — 0/unset is the default, never "unbounded"
    # (the watchdog is the only kill for a hung/non-terminating child, so it must always run).
    max_minutes = float(prog.get("max_minutes") or 0)
    if max_minutes <= 0:
        max_minutes = 240.0

    adir = _agents_dir(pdir)
    base = f"{a.label or role}-{time.strftime('%Y%m%d-%H%M%S')}"
    agent_id, manifest_path = base, adir / f"{base}.json"
    for i in range(1, 100):  # collision suffix (same-second launches)
        if not manifest_path.exists():
            break
        agent_id = f"{base}-{i}"
        manifest_path = adir / f"{agent_id}.json"
    stream_path = adir / f"{agent_id}.stream.jsonl"

    cmd, fires_hooks = _build_command(backend, prompt, pdir, model, perm, prog)
    wlog = None if fires_hooks else (pdir / ".bus" / "workers" / f"{agent_id}.jsonl")

    manifest = {
        "agent_id": agent_id, "backend": backend, "model": model, "role": role,
        "label": a.label, "project": pdir.name, "cwd": str(pdir),
        "prompt_summary": prompt.strip()[:200], "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "running", "pid": None, "stream": stream_path.name, "max_minutes": max_minutes,
        "session_id": None, "exit_code": None, "finished": None, "wall_seconds": None, "last_message": None,
    }
    _write_manifest(manifest_path, manifest)

    env = dict(os.environ)
    env[_DEPTH_ENV] = str(depth + 1)
    print(f"[agent_runner] launching {backend} agent '{agent_id}' in {pdir.name} (depth {depth + 1})", flush=True)
    try:
        proc = subprocess.Popen(cmd, cwd=str(pdir), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env, **_NEW_GROUP)
    except FileNotFoundError:
        manifest.update(status="failed", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        last_message=f"backend CLI not found on PATH: {cmd[0]}")
        _write_manifest(manifest_path, manifest)
        _emit(pdir, "agent_finished", detail=agent_id, status="failed", data={"reason": "cli-not-found"})
        print(f"[agent_runner] FAILED: backend CLI '{cmd[0]}' not found on PATH "
              f"({'install/login the Claude CLI' if backend == 'claude' else 'install/auth the codex CLI'}).")
        return 1

    manifest["pid"] = proc.pid
    _write_manifest(manifest_path, manifest)
    _emit(pdir, "agent_launched", detail=agent_id, data={"backend": backend, "role": role, "pid": proc.pid})
    if wlog:
        _worker_line(wlog, worker_id=agent_id, role=role, event="start", status="working", idea=pdir.name)

    t0 = time.time()
    done = threading.Event()
    breached = {"v": False}

    def _watchdog() -> None:
        if not done.wait(timeout=max_minutes * 60):
            if done.is_set():   # the drain loop finished in the wake-up window — stand down
                return
            breached["v"] = True
            _kill_tree(proc.pid)
            print(f"[agent_runner] TIMEOUT — max_minutes={max_minutes} breached; killed '{agent_id}'", flush=True)

    threading.Thread(target=_watchdog, daemon=True).start()

    last_message = session_id = None
    with stream_path.open("a", encoding="utf-8") as sf:
        for line in proc.stdout:  # type: ignore[union-attr]
            sf.write(line)
            sf.flush()
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except json.JSONDecodeError:
                continue
            act = _parse_activity(backend, obj)
            if not act:
                continue
            session_id = act.get("session_id") or session_id
            last_message = act.get("last_message") or last_message
            if wlog and act.get("event") == "action":  # 'start' was already written at launch
                _worker_line(wlog, worker_id=agent_id, role=role, event="action",
                             tool=act.get("tool"), kind=act.get("kind"), summary=act.get("summary"),
                             idea=pdir.name)
    done.set()  # pipe closed -> child is finishing; tell the watchdog to stand down before status
    proc.wait()
    # Returncode is authoritative: a clean exit is 'completed' even if the watchdog raced at the
    # boundary; a non-zero exit is 'timeout' only when the watchdog actually killed it, else 'failed'.
    if proc.returncode == 0:
        status = "completed"
    elif breached["v"]:
        status = "timeout"
    else:
        status = "failed"
    manifest.update(status=status, exit_code=proc.returncode, finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    wall_seconds=round(time.time() - t0, 1), session_id=session_id,
                    last_message=(last_message or "")[:1000] or None)
    _write_manifest(manifest_path, manifest)
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


def cmd_reconcile(a) -> int:
    pdir = _resolve_project(a.project)
    if not pdir:
        print(f"[agent_runner] no project for {a.project!r}")
        return 1
    adir = pdir / ".bus" / "agents"
    n = 0
    for f in (sorted(adir.glob("*.json")) if adir.exists() else []):
        try:
            m = json.loads(f.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue
        if m.get("status") != "running" or _pid_alive(m.get("pid")):
            continue
        m.update(status="failed", finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
                 last_message=(m.get("last_message") or "") + " [reconciled: process gone]")
        _write_manifest(f, m)
        _emit(pdir, "agent_finished", detail=m.get("agent_id"), status="failed", data={"reconciled": True})
        n += 1
    print(f"[agent_runner] reconciled {n} orphaned agent(s) in {pdir.name}")
    return 0


def cmd_kill(a) -> int:
    pdir = _resolve_project(a.project)
    if not pdir:
        print(f"[agent_runner] no project for {a.project!r}")
        return 1
    targets = [m for m in _list_manifests(pdir)
               if m.get("status") == "running" and (a.all or m.get("agent_id") == a.agent)]
    if not targets:
        print("[agent_runner] no running agents matched")
        return 1
    for m in targets:
        if m.get("pid"):
            _kill_tree(m["pid"])
            print(f"[agent_runner] killed {m.get('agent_id')} (pid {m.get('pid')})")
    return cmd_reconcile(a)


def main() -> int:
    ap = argparse.ArgumentParser(description="launch + capture headless top-level agents into projects")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("launch")
    p.add_argument("--project", required=True, help="slug or project path")
    p.add_argument("--prompt", help="the instruction (or use --prompt-file)")
    p.add_argument("--prompt-file", help="file containing the instruction")
    p.add_argument("--role", default=None, help="worker role label (default: orchestrator)")
    p.add_argument("--label", default=None, help="agent id prefix (default: the role)")
    p.add_argument("--backend", default=None, choices=("claude", "codex"),
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

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
