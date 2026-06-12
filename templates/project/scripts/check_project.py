"""Project readiness lint + orientation: is this repo ready to run, and what's next?

    uv run --with pyyaml python scripts/check_project.py

Checks (exit 1 on any failure, 0 when ready):
  1. Required files exist: PLAN.md, control.yaml, EXPERIMENT_LOG.md, configs/base.yaml,
     at least one configs/experiments/*.yaml, pyproject.toml.
  2. No unfilled {{placeholders}} left in PLAN.md / control.yaml (template not filled).
  3. control.yaml parses and has budgets + gate2_envelope blocks.
  4. runs/registry.jsonl (if present) is readable line-JSON.

Then reports orientation regardless: last run, envelope status, SYSTEM.md presence,
and a suggested next procedure. The project-side analogue of the hub's check_lab.py.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    problems: list[str] = []
    notes: list[str] = []

    required = [
        "PLAN.md",
        "control.yaml",
        "EXPERIMENT_LOG.md",
        "configs/base.yaml",
        "pyproject.toml",
    ]
    for rel in required:
        if not (ROOT / rel).exists():
            problems.append(f"missing {rel}")

    exp_dir = ROOT / "configs" / "experiments"
    exp_configs = sorted(exp_dir.glob("*.yaml")) if exp_dir.exists() else []
    if not exp_configs:
        problems.append("no experiment configs in configs/experiments/")

    # Unfilled template placeholders ({{slug}} etc. — not the figure library's {{{...}}}).
    for rel in ("PLAN.md", "control.yaml"):
        path = ROOT / rel
        if path.exists() and re.search(r"\{\{(?!\{)[a-z_]+\}\}", path.read_text(encoding="utf-8")):
            problems.append(f"{rel} still contains template placeholders — spawn incomplete")

    control: dict = {}
    control_path = ROOT / "control.yaml"
    if control_path.exists():
        try:
            control = yaml.safe_load(control_path.read_text(encoding="utf-8")) or {}
            for block in ("budgets", "gate2_envelope"):
                if block not in control:
                    problems.append(f"control.yaml has no `{block}` block")
        except yaml.YAMLError as e:
            problems.append(f"control.yaml does not parse: {e}")

    last_run: dict | None = None
    registry = ROOT / "runs" / "registry.jsonl"
    n_runs = 0
    if registry.exists():
        for i, line in enumerate(registry.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                last_run = json.loads(line)
                n_runs += 1
            except json.JSONDecodeError:
                problems.append(f"runs/registry.jsonl line {i} is not valid JSON")

    envelope = (control.get("gate2_envelope") or {}) if isinstance(control, dict) else {}
    signed = bool(envelope.get("pi_signed"))
    system_md = (ROOT / "SYSTEM.md").exists()

    print(f"## Project check — {ROOT.name}\n")
    if problems:
        print("**Not ready (fix first):**")
        for p in problems:
            print(f"- {p}")
        print()

    print(f"- Runs recorded: {n_runs}")
    if last_run:
        metric_note = ", ".join(f"{k}={v}" for k, v in (last_run.get("metrics") or {}).items())
        print(
            f"- Last run: {last_run.get('run_id')} ({last_run.get('stage')}, "
            f"status {last_run.get('status')}{', ' + metric_note if metric_note else ''})"
        )
    print(f"- Gate 2 envelope: {'signed' if signed else 'none — every FULL run needs fresh PI approval'}")
    print(f"- SYSTEM.md: {'present — read it before acting' if system_md else 'not present'}")

    if problems:
        suggestion = "fix the items above (see AGENTS.md cold-start checklist), then re-run this check"
    elif n_runs == 0:
        suggestion = "run the smoke config (`experiment` procedure, exp-001-smoke) to verify the pipeline"
    elif last_run and last_run.get("status") in ("failed", "timeout"):
        suggestion = "last run did not complete — `experiment` procedure (debug, max 3 attempts, then record and move on)"
    else:
        suggestion = "next planned row in PLAN.md via `experiment`; if the baseline is established, `improve`; if the plan is done, `analyze`"
    print(f"- Suggested next: {suggestion}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
