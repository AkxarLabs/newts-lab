"""Single entry point for every experiment run.

    uv run python scripts/run.py --config configs/experiments/exp-001-smoke.yaml [--seed N] [-o key=value ...]

Loads config, seeds, creates the run artifact dir, executes, records — success or failure.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _resolve_pkg() -> str:
    """The project's importable package under src/ that this runner drives (config /
    experiment / seeding / tracking). Spawned projects use `project_pkg`; an ADOPTED
    external repo keeps its own package name by setting `package:` in control.yaml (or
    $PROJECT_PKG) — no renaming required. Autodetected when there's exactly one package."""
    src = Path(__file__).resolve().parents[1] / "src"
    override = os.environ.get("PROJECT_PKG")
    if override:
        return override
    ctl = Path(__file__).resolve().parents[1] / "control.yaml"
    if ctl.exists():
        try:
            import yaml
            name = (yaml.safe_load(ctl.read_text(encoding="utf-8-sig")) or {}).get("package")
            if name:
                return str(name)
        except Exception:  # noqa: BLE001 — config read is best-effort; fall through to autodetect
            pass
    if (src / "project_pkg" / "__init__.py").exists():
        return "project_pkg"
    pkgs = [p.name for p in src.iterdir() if (p / "__init__.py").exists()] if src.exists() else []
    if len(pkgs) == 1:
        return pkgs[0]
    raise SystemExit("[run] cannot resolve the project package under src/ — set `package:` in "
                     "control.yaml (or $PROJECT_PKG) to your package name")


import importlib  # noqa: E402 — after sys.path is set up

_PKG = _resolve_pkg()
load_config = importlib.import_module(f"{_PKG}.config").load_config
set_seed = importlib.import_module(f"{_PKG}.seeding").set_seed
RunContext = importlib.import_module(f"{_PKG}.tracking").RunContext
# NOTE: <pkg>.experiment is imported LAZILY (only for runner: python-import) so a non-Python
# project TYPE (runner: shell-command) needs no experiment.py at all.


# ── the runner/artifact seam (domain-general) ────────────────────────────────────────────────
# A run is executed one of two ways, declared by `runner:` in control.yaml / the experiment yaml.
# EITHER WAY the same artifact contract holds — a flat dict of final metrics reaches
# RunContext.finish (→ runs/<id>/metrics.json + the registry line + budget handling):
#   python-import (default): import <pkg>.experiment.run(cfg, ctx)               — the ML/Python path.
#   shell-command:           run `runner_command` (ANY language: Rscript/Stata/Julia/…). It reads
#                            $CONFIG_PATH / $SEED / $RUN_DIR and writes the metrics dict to
#                            $RUN_DIR/result.json. This lets non-Python project TYPES reuse the whole
#                            engine (config layering, seeding, artifacts, watchdog, registry) unchanged.
_RUNNERS = {"python-import", "python", "import", "shell-command", "shell", "command"}
_NEW_GROUP = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" \
    else {"start_new_session": True}
_CHILD: dict = {"proc": None}   # the shell-command child, so the watchdog can kill its tree on breach


def _kill_tree(proc) -> None:
    """Kill the runner subprocess AND its children (a bare kill leaves grandchildren — an R/Julia
    worker, a torchrun — running and the machine busy)."""
    import signal
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        proc.kill()


def _run_command(cfg: dict, ctx) -> dict:
    """runner: shell-command — execute an external tool (any language) that writes a flat JSON dict
    of final metrics to $RUN_DIR/result.json. Returns that dict for RunContext.finish to record."""
    import json
    import shlex
    spec = cfg.get("runner_command") or (cfg.get("experiment") or {}).get("command")
    if not spec:
        raise SystemExit("[run] runner: shell-command needs `runner_command` (a string or list) in the config")
    cmd = spec if isinstance(spec, list) else shlex.split(spec)
    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ, RUN_DIR=str(ctx.run_dir), RUN_ID=str(ctx.run_id),
               CONFIG_PATH=str(cfg.get("_config_path", "")), SEED=str(cfg.get("seed", 0)),
               REPO_ROOT=str(repo))
    print(f"[run] runner=shell-command: {cmd}", flush=True)
    proc = subprocess.Popen(cmd, cwd=str(repo), env=env, **_NEW_GROUP)
    _CHILD["proc"] = proc
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"runner command exited {rc}: {cmd}")
    out = ctx.run_dir / "result.json"
    if not out.exists():
        raise RuntimeError(f"runner wrote no {out.name} in the run dir — the metrics contract is: "
                           "write a flat JSON dict of final metrics to $RUN_DIR/result.json")
    return json.loads(out.read_text(encoding="utf-8-sig"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="experiment yaml under configs/experiments/")
    parser.add_argument("--seed", type=int, default=None, help="override config seed")
    parser.add_argument("-o", "--override", action="append", default=[], help="dotted override, e.g. toy.n_samples=200")
    args = parser.parse_args()

    overrides = list(args.override)
    if args.seed is not None:
        overrides.append(f"seed={args.seed}")

    cfg = load_config(args.config, overrides)
    runner = str(cfg.get("runner") or "python-import").strip().lower()
    if runner not in _RUNNERS:
        raise SystemExit(f"[run] unknown runner {runner!r} — use python-import | shell-command")
    set_seed(int(cfg.get("seed", 0)))
    ctx = RunContext(cfg)
    print(f"[run] {ctx.run_id} -> {ctx.run_dir}", flush=True)

    # Budget watchdog: budget.max_minutes is ENFORCED, not advisory. Daemon thread +
    # Event (works on Windows; no SIGALRM). On breach: record timeout in the run
    # artifacts and registry, then hard-exit 2 — arbitrary experiment code cannot be
    # stopped gracefully in-process. NOTE: os._exit kills only THIS process; if your
    # experiment code spawns subprocesses (torchrun, an external trainer), launch them in
    # a killable process group so the watchdog/your harness can reap them — otherwise they
    # outlive the breach. sweep.py launches run.py in its own process group and kills the
    # whole tree on timeout, so sweep-driven runs are covered; a bare backgrounded run.py
    # is not.
    done = threading.Event()
    max_minutes = (cfg.get("budget") or {}).get("max_minutes")
    if max_minutes:

        def _watchdog() -> None:
            if not done.wait(timeout=float(max_minutes) * 60):
                child = _CHILD["proc"]
                if child is not None and child.poll() is None:
                    _kill_tree(child)   # shell-command: reap the external tool tree first
                ctx.breach_budget()
                print(f"[run] TIMEOUT — budget.max_minutes={max_minutes} breached", flush=True)
                os._exit(2)

        threading.Thread(target=_watchdog, daemon=True).start()

    try:
        if runner in ("shell-command", "shell", "command"):
            final_metrics = _run_command(cfg, ctx)
        else:
            run_experiment = importlib.import_module(f"{_PKG}.experiment").run
            final_metrics = run_experiment(cfg, ctx)
    except Exception:
        done.set()
        ctx.fail(traceback.format_exc())
        print(f"[run] FAILED — see {ctx.run_dir / 'error.txt'}")
        return 1

    done.set()
    ctx.finish(final_metrics)
    print(f"[run] completed: {final_metrics}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
