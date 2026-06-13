"""Show the effective 3-layer configuration with per-key provenance.

    uv run --with pyyaml python tools/show_config.py
        -> lab config (layer 1)
    uv run --with pyyaml python tools/show_config.py <project-path>
        -> + project control.yaml (layer 2) and the effective skill values
    uv run --with pyyaml python tools/show_config.py <project-path> exp-004.yaml
        -> + the fully resolved run config (control -> base -> experiment) with
           the layer that set each key

Resolution order: experiment yaml > control.yaml > lab/config.yaml. stdlib + pyyaml.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def flatten(node, prefix: str = "") -> dict[str, object]:
    out: dict[str, object] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = node
    return out


def print_flat(title: str, data: dict, sources: dict[str, str] | None = None) -> None:
    print(f"\n### {title}\n")
    flat = flatten(data)
    if not flat:
        print("*(empty / file missing)*")
        return
    if sources:
        print("| key | value | set by |")
        print("|---|---|---|")
        for key in sorted(flat):
            print(f"| `{key}` | `{flat[key]}` | {sources.get(key, '?')} |")
    else:
        print("| key | value |")
        print("|---|---|")
        for key in sorted(flat):
            print(f"| `{key}` | `{flat[key]}` |")


# Skill values resolved control-first, lab-fallback: (label, control path, lab path)
SKILL_KEYS = [
    ("multi_seed_n", "seeds.multi_seed_n", "experiment.multi_seed_n"),
    ("max_parallel_subagents", "parallelism.max_parallel_subagents", "experiment.max_parallel_subagents"),
    ("sweep_parallel", "parallelism.sweep_parallel", None),
    ("max_debug_depth", None, "experiment.max_debug_depth"),
    ("num_drafts", None, "experiment.num_drafts"),
    ("loop.no_progress_backoff_cycles", "loop.no_progress_backoff_cycles", "loop.no_progress_backoff_cycles"),
    ("loop.monitor_poll_seconds", "loop.monitor_poll_seconds", "loop.monitor_poll_seconds"),
    ("loop.mode", "loop.mode", "loop.mode"),
    ("loop.explore_max_expansion_rounds", "loop.explore_max_expansion_rounds", "loop.explore_max_expansion_rounds"),
    ("loop.explore_max_new_lines_per_round", "loop.explore_max_new_lines_per_round", "loop.explore_max_new_lines_per_round"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", help="path to a project repo")
    parser.add_argument("experiment", nargs="?", help="experiment yaml name (e.g. exp-004.yaml)")
    args = parser.parse_args()

    lab_cfg = load(HUB / "lab" / "config.yaml")
    print("# Effective configuration")
    print("\nResolution: experiment yaml > project control.yaml > hub lab/config.yaml")
    print_flat("Layer 1 — lab/config.yaml", lab_cfg)

    if not args.project:
        root = (lab_cfg.get("lab") or {}).get("projects_root", "../AutoScientist-Projects")
        print(f"\n(projects root: `{(HUB / root).resolve()}` — pass a project path for layers 2-3)")
        return 0

    project = Path(args.project)
    if not project.is_absolute():
        project = (HUB / project).resolve()
    control = load(project / "control.yaml")
    print_flat(f"Layer 2 — {project.name}/control.yaml", control)

    flat_control, flat_lab = flatten(control), flatten(lab_cfg)
    print("\n### Effective skill values (control-first, lab fallback)\n")
    print("| value | effective | source |")
    print("|---|---|---|")
    for label, control_key, lab_key in SKILL_KEYS:
        if control_key and control_key in flat_control:
            print(f"| {label} | `{flat_control[control_key]}` | control.yaml |")
        elif lab_key and lab_key in flat_lab:
            print(f"| {label} | `{flat_lab[lab_key]}` | lab/config.yaml |")
        else:
            print(f"| {label} | — | unset |")

    if args.experiment:
        exp_path = project / "configs" / "experiments" / args.experiment
        base = load(project / "configs" / "base.yaml")
        exp = load(exp_path)
        merged: dict[str, object] = {}
        sources: dict[str, str] = {}
        for name, layer in (("control.yaml", control), ("base.yaml", base), (args.experiment, exp)):
            for key, value in flatten(layer).items():
                merged[key] = value
                sources[key] = name
        # Stage-budget mapping (mirrors project_pkg.config.load_config: explicit if set in
        # the experiment yaml OR base.yaml)
        if "budget.max_minutes" not in flatten(exp) and "budget.max_minutes" not in flatten(base):
            stage = str(merged.get("stage", "SMOKE")).lower()
            cap = flatten(control).get(f"budgets.{stage}_max_minutes")
            if cap is not None:
                merged["budget.max_minutes"] = cap
                sources["budget.max_minutes"] = f"control.yaml (budgets.{stage}_max_minutes)"
        print(f"\n### Layer 3 — resolved run config for {args.experiment}\n")
        print("| key | value | set by |")
        print("|---|---|---|")
        for key in sorted(merged):
            print(f"| `{key}` | `{merged[key]}` | {sources[key]} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
