"""Config loading — layered, fully resolved per run.

Resolution order (low → high precedence):
    control.yaml (project root)  →  configs/base.yaml  →  experiment yaml  →  CLI overrides

control.yaml holds the project's end-to-end run controls (budgets, seeds, parallelism,
loop, Gate-2 envelope) and is created at spawn; base.yaml holds shared domain defaults;
the experiment yaml is the unit of experimentation. The resolved result is dumped into
the run's artifact dir so any run is replayable even if lower layers later change.

Stage budgets: if neither the experiment yaml nor a CLI override sets
budget.max_minutes, it is mapped from control.yaml's budgets.<stage>_max_minutes for
the run's stage — so per-stage caps apply automatically without repeating them in
every experiment file.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def load_config(experiment_yaml: str | Path, overrides: list[str] | None = None) -> dict[str, Any]:
    """Load control.yaml + base.yaml + experiment yaml + dotted overrides ("seed=1")."""
    exp_path = Path(experiment_yaml).resolve()
    if not exp_path.exists():
        # A typo'd --config must fail loudly, not silently run an empty config that then
        # KeyErrors deep in experiment.run and records a misleading 'failed' run.
        raise FileNotFoundError(f"experiment config not found: {exp_path}")
    base_path = exp_path.parent.parent / "base.yaml"          # configs/base.yaml
    control_path = exp_path.parent.parent.parent / "control.yaml"  # project root

    control_cfg = _load_yaml(control_path)
    exp_cfg = _load_yaml(exp_path)

    cfg = _deep_merge(control_cfg, _load_yaml(base_path))
    cfg = _deep_merge(cfg, exp_cfg)

    overrides = overrides or []
    for item in overrides:
        key, _, raw = item.partition("=")
        node = cfg
        parts = key.strip().split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = yaml.safe_load(raw)

    # Stage-budget mapping: control.yaml's per-stage cap applies unless a higher layer
    # (experiment yaml, base.yaml, or a CLI override) set budget.max_minutes explicitly.
    explicit = (
        "max_minutes" in (exp_cfg.get("budget") or {})
        or "max_minutes" in (_load_yaml(base_path).get("budget") or {})
        or any(o.partition("=")[0].strip() == "budget.max_minutes" for o in overrides)
    )
    stage = str(cfg.get("stage", "SMOKE")).lower()
    stage_cap = (control_cfg.get("budgets") or {}).get(f"{stage}_max_minutes")
    if not explicit and stage_cap is not None:
        cfg.setdefault("budget", {})["max_minutes"] = stage_cap

    cfg["_config_path"] = str(exp_path)
    return cfg
