"""Determinism: one entry point that seeds every library present in the environment.

The seed is always a config field and is recorded in the run's meta.json — never an
implicit default inside experiment code.
"""

from __future__ import annotations

import os
import random


def set_seed(seed: int) -> None:
    random.seed(seed)
    # CPython reads PYTHONHASHSEED only at interpreter startup, so setting it here does NOT
    # fix str/bytes hash randomization in THIS process — it only propagates to child
    # processes. For exact replay, avoid iterating sets/dicts keyed on strings in experiment
    # logic, or launch with PYTHONHASHSEED=0 set in the environment before Python starts.
    os.environ.setdefault("PYTHONHASHSEED", str(seed))

    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass

    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        # Note: full GPU determinism may also need torch.use_deterministic_algorithms(True)
        # and CUBLAS_WORKSPACE_CONFIG=:4096:8 — enable per-project if exact replay matters
        # more than speed.
    except ImportError:
        pass
