"""The experiment itself. Replace the toy with the project's real logic.

Contract:
    run(cfg, ctx) -> dict of final metrics
- All variation comes from cfg — no hardcoded variants.
- Stream intermediate metrics via ctx.log(); return the final summary dict.
- New method variants: add a function + a config switch here (or a new module),
  alongside the baseline path — never replace it.

The toy experiment (estimate a noisy mean) exists so the template pipeline is
verifiable end-to-end before any domain code lands.
"""

from __future__ import annotations

import random
import time
from typing import Any

from .tracking import RunContext


def run(cfg: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    toy = cfg["toy"]
    if toy.get("sleep_seconds"):
        time.sleep(float(toy["sleep_seconds"]))
    samples = [random.gauss(toy["true_mean"], toy["noise_std"]) for _ in range(toy["n_samples"])]

    estimate = 0.0
    for i, x in enumerate(samples, start=1):
        estimate += (x - estimate) / i
        if i % 10 == 0:
            ctx.log({"running_estimate": round(estimate, 4)}, step=i)

    return {
        "toy_abs_error": abs(estimate - toy["true_mean"]),
        "estimate": estimate,
        "n_samples": toy["n_samples"],
    }
