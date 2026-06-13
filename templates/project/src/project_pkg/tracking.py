"""Run tracking: per-run artifact directory + append-only registry.

Each run gets runs/<run_id>/ containing:
    config.resolved.yaml   the full config this run actually used
    meta.json              run_id, git SHA (+dirty flag), seed, timestamps, status
    metrics.jsonl          streamed metrics (one JSON object per log call)
    metrics.json           final metrics summary (the citable artifact)

On finish, one summary line is appended to runs/registry.jsonl (committed to git).
The artifact dir — not any external tracker — is the source of truth.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import yaml


@contextlib.contextmanager
def _locked_append(path: Path):
    """Append one record to `path` while holding a portable sidecar lock, so parallel sweep
    jobs that finalize at the same instant don't interleave/garble lines in the append-only
    registry. The lock is a `<path>.lock` file created with O_EXCL and spun on; it is
    best-effort (a stale lock from a crash is force-broken after a few seconds)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    deadline = time.time() + 10
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if time.time() > deadline:
                with contextlib.suppress(OSError):
                    lock.unlink()  # presumed crashed holder — break it
            time.sleep(0.05)
    try:
        with path.open("a", encoding="utf-8") as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
    finally:
        with contextlib.suppress(OSError):
            lock.unlink()


def _bus_emit(repo_root: Path, kind: str, **fields: Any) -> None:
    """Append one dashboard event to <project>/.bus/events.jsonl. Best-effort: any failure
    is swallowed so run tracking is never affected by the (optional) dashboard bus."""
    try:
        bus = repo_root / ".bus"
        bus.mkdir(parents=True, exist_ok=True)
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": repo_root.name, "kind": kind}
        record.update({k: v for k, v in fields.items() if v is not None})
        with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _git_info(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
        ).stdout.strip()

    sha = run("rev-parse", "HEAD")
    dirty = bool(run("status", "--porcelain"))
    return {"commit": sha or None, "dirty": dirty}


class RunContext:
    def __init__(self, cfg: dict[str, Any], repo_root: str | Path | None = None):
        self.cfg = cfg
        self.repo_root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
        self.runs_dir = self.repo_root / "runs"

        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = f"{cfg.get('experiment_name', 'run')}-s{cfg.get('seed', 0)}-{stamp}"
        # Concurrent runs (e.g. a parallel sweep) can start within the same second —
        # resolve run_id collisions with a numeric suffix instead of failing.
        for suffix in ("", *(f"-{i}" for i in range(1, 100))):
            candidate = self.runs_dir / (base + suffix)
            try:
                candidate.mkdir(parents=True, exist_ok=False)
                self.run_id = base + suffix
                self.run_dir = candidate
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError(f"could not allocate a unique run dir for {base}")

        self._t0 = time.time()
        self._lock = threading.Lock()
        self._finalized = False
        self._metrics_stream = (self.run_dir / "metrics.jsonl").open("a", encoding="utf-8")
        self.meta: dict[str, Any] = {
            "run_id": self.run_id,
            "experiment_name": cfg.get("experiment_name"),
            "stage": cfg.get("stage"),
            "seed": cfg.get("seed"),
            "config_path": cfg.get("_config_path"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "running",
            "budget": {
                "max_minutes": (cfg.get("budget") or {}).get("max_minutes"),
                "breached": False,
            },
            **_git_info(self.repo_root),
        }

        (self.run_dir / "config.resolved.yaml").write_text(
            yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8"
        )
        self._write_meta()
        _bus_emit(self.repo_root, "run_started", run_id=self.run_id,
                  stage=self.meta["stage"], status="running",
                  detail=self.meta["experiment_name"])

    def _write_meta(self) -> None:
        # Atomic: write a temp file then os.replace, so a concurrent status.py poll never
        # reads a half-written meta.json.
        target = self.run_dir / "meta.json"
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def log(self, metrics: dict[str, Any], step: int | None = None) -> None:
        """Stream intermediate metrics (e.g., per training step)."""
        record = {"t": round(time.time() - self._t0, 3), **({"step": step} if step is not None else {}), **metrics}
        self._metrics_stream.write(json.dumps(record) + "\n")
        self._metrics_stream.flush()

    def finish(self, final_metrics: dict[str, Any], status: str = "completed") -> None:
        """Write the citable artifact (metrics.json) and append to the registry.

        Idempotent under the lock: the budget watchdog and the normal exit path can
        race; whichever finalizes first wins, the other is a no-op.
        """
        with self._lock:
            if self._finalized:
                return
            self._finalized = True
        (self.run_dir / "metrics.json").write_text(
            json.dumps(final_metrics, indent=2), encoding="utf-8"
        )
        self.meta.update(
            status=status,
            finished=time.strftime("%Y-%m-%dT%H:%M:%S"),
            wall_seconds=round(time.time() - self._t0, 1),
        )
        self._write_meta()
        self._metrics_stream.close()

        registry_line = {
            "run_id": self.run_id,
            "experiment_name": self.meta["experiment_name"],
            "stage": self.meta["stage"],
            "seed": self.meta["seed"],
            "commit": self.meta["commit"],
            "dirty": self.meta["dirty"],
            "status": status,
            "wall_seconds": self.meta["wall_seconds"],
            "metrics": final_metrics,
        }
        with _locked_append(self.runs_dir / "registry.jsonl") as f:
            f.write(json.dumps(registry_line) + "\n")
        _bus_emit(self.repo_root, "run_finished", run_id=self.run_id,
                  stage=self.meta["stage"], status=status,
                  data={"metrics": final_metrics} if final_metrics else None)

    def fail(self, error: str) -> None:
        (self.run_dir / "error.txt").write_text(error, encoding="utf-8")
        self.finish({}, status="failed")

    def breach_budget(self) -> None:
        """Called by the run.py watchdog when budget.max_minutes is exceeded."""
        minutes = self.meta.get("budget", {}).get("max_minutes")
        (self.run_dir / "error.txt").write_text(
            f"budget breached: max_minutes={minutes}\n", encoding="utf-8"
        )
        self.meta["budget"]["breached"] = True
        self.finish({}, status="timeout")
