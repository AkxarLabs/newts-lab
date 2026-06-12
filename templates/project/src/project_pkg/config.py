"""Config loading: configs/base.yaml deep-merged with an experiment YAML, plus CLI overrides.

Every run is fully specified by (experiment yaml, overrides). The resolved result is dumped
into the run's artifact dir so any run is replayable even if base.yaml later changes.
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


def load_config(experiment_yaml: str | Path, overrides: list[str] | None = None) -> dict[str, Any]:
    """Load base.yaml + experiment yaml + dotted overrides ("seed=1", "toy.n_samples=200")."""
    exp_path = Path(experiment_yaml)
    base_path = exp_path.parent.parent / "base.yaml"

    cfg: dict[str, Any] = {}
    if base_path.exists():
        cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    exp_cfg = yaml.safe_load(exp_path.read_text(encoding="utf-8")) or {}
    cfg = _deep_merge(cfg, exp_cfg)

    for item in overrides or []:
        key, _, raw = item.partition("=")
        node = cfg
        parts = key.strip().split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = yaml.safe_load(raw)

    cfg["_config_path"] = str(exp_path)
    return cfg
