"""Smoke test: the full pipeline (config -> seed -> run -> artifacts -> registry) works.

A stranger cloning this repo runs `uv run pytest` and knows in seconds whether the
pipeline is intact. Keep this passing forever; add experiment-specific tests alongside.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_smoke_run(tmp_path):
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run.py"),
         "--config", str(REPO / "configs" / "experiments" / "exp-001-smoke.yaml"),
         "--seed", "0"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    registry = REPO / "runs" / "registry.jsonl"
    assert registry.exists()
    last = json.loads(registry.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert last["status"] == "completed"
    assert "toy_abs_error" in last["metrics"]

    run_dir = REPO / "runs" / last["run_id"]
    for artifact in ("config.resolved.yaml", "meta.json", "metrics.json", "metrics.jsonl"):
        assert (run_dir / artifact).exists(), f"missing artifact: {artifact}"


def test_seed_reproducibility():
    def run_once():
        return subprocess.run(
            [sys.executable, str(REPO / "scripts" / "run.py"),
             "--config", str(REPO / "configs" / "experiments" / "exp-001-smoke.yaml"),
             "--seed", "123"],
            capture_output=True, text=True, cwd=REPO,
        )

    for proc in (run_once(), run_once()):
        assert proc.returncode == 0, proc.stdout + proc.stderr

    registry = REPO / "runs" / "registry.jsonl"
    lines = [json.loads(l) for l in registry.read_text(encoding="utf-8").strip().splitlines()]
    a, b = lines[-2], lines[-1]
    assert a["metrics"]["estimate"] == b["metrics"]["estimate"], "same seed must reproduce"
