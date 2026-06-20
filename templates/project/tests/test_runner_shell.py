"""The runner/artifact seam: `runner: shell-command` flows an external tool's metrics through
RunContext into the canonical artifacts (same contract as the default python-import path), so a
non-Python project TYPE (empirical/simulation/theory) reuses the whole engine unchanged.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_shell_command_runner(tmp_path):
    # an external "tool" in any language — here a tiny script that honors the artifact contract:
    # read $RUN_DIR / $SEED, write a flat JSON metrics dict to $RUN_DIR/result.json.
    runner = tmp_path / "ext_runner.py"
    runner.write_text(
        'import json, os\n'
        'rd = os.environ["RUN_DIR"]\n'
        'json.dump({"shell_metric": 0.42, "seed_seen": os.environ.get("SEED")},\n'
        '          open(os.path.join(rd, "result.json"), "w"))\n',
        encoding="utf-8",
    )
    py = sys.executable.replace("\\", "/")
    cfg = REPO / "configs" / "experiments" / "_test_shell.yaml"
    base = (REPO / "configs" / "experiments" / "exp-001-smoke.yaml").read_text(encoding="utf-8")
    cfg.write_text(
        base + "\nrunner: shell-command\n"
        + f"runner_command: ['{py}', '{runner.as_posix()}']\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "run.py"), "--config", str(cfg), "--seed", "7"],
            capture_output=True, text=True, cwd=REPO, timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        last = json.loads((REPO / "runs" / "registry.jsonl")
                          .read_text(encoding="utf-8").strip().splitlines()[-1])
        assert last["status"] == "completed"
        assert last["metrics"]["shell_metric"] == 0.42      # external metrics reached the registry
        assert last["metrics"]["seed_seen"] == "7"          # $SEED was passed through to the tool

        md = json.loads((REPO / "runs" / last["run_id"] / "metrics.json").read_text(encoding="utf-8"))
        assert (md.get("metrics", md)).get("shell_metric") == 0.42   # and the canonical metrics.json
    finally:
        cfg.unlink(missing_ok=True)


def test_unknown_runner_fails_fast():
    cfg = REPO / "configs" / "experiments" / "_test_badrunner.yaml"
    base = (REPO / "configs" / "experiments" / "exp-001-smoke.yaml").read_text(encoding="utf-8")
    cfg.write_text(base + "\nrunner: nonsense\n", encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "run.py"), "--config", str(cfg)],
            capture_output=True, text=True, cwd=REPO, timeout=60,
        )
        assert result.returncode != 0
        assert "unknown runner" in (result.stdout + result.stderr).lower()
    finally:
        cfg.unlink(missing_ok=True)
