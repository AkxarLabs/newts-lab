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

import json
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml


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
        self.run_id = f"{cfg.get('experiment_name', 'run')}-s{cfg.get('seed', 0)}-{stamp}"
        self.run_dir = self.runs_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=False)

        self._t0 = time.time()
        self._metrics_stream = (self.run_dir / "metrics.jsonl").open("a", encoding="utf-8")
        self.meta: dict[str, Any] = {
            "run_id": self.run_id,
            "experiment_name": cfg.get("experiment_name"),
            "stage": cfg.get("stage"),
            "seed": cfg.get("seed"),
            "config_path": cfg.get("_config_path"),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "status": "running",
            **_git_info(self.repo_root),
        }

        (self.run_dir / "config.resolved.yaml").write_text(
            yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8"
        )
        self._write_meta()

    def _write_meta(self) -> None:
        (self.run_dir / "meta.json").write_text(
            json.dumps(self.meta, indent=2), encoding="utf-8"
        )

    def log(self, metrics: dict[str, Any], step: int | None = None) -> None:
        """Stream intermediate metrics (e.g., per training step)."""
        record = {"t": round(time.time() - self._t0, 3), **({"step": step} if step is not None else {}), **metrics}
        self._metrics_stream.write(json.dumps(record) + "\n")
        self._metrics_stream.flush()

    def finish(self, final_metrics: dict[str, Any], status: str = "completed") -> None:
        """Write the citable artifact (metrics.json) and append to the registry."""
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
        with (self.runs_dir / "registry.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(registry_line) + "\n")

    def fail(self, error: str) -> None:
        (self.run_dir / "error.txt").write_text(error, encoding="utf-8")
        self.finish({}, status="failed")
