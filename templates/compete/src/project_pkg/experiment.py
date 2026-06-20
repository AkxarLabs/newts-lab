"""Target SMOKE experiment — replace the toy with the real model, KEEP the contract.

A target-driven run produces:
  1. a local score on the frozen metric (returned dict) — the *selection* signal, tuned on
     the LOCAL validation split only; and
  2. (only if the target is scored on an artifact you produce) a validated output file in
     runs/<run_id>/ — the thing the scorer reads.

This toy version makes the target pipeline green end-to-end before any real modeling lands
(the analogue of the base template's noisy-mean toy). The real run(): tune on local
validation, predict the held-out/unlabeled input, write the output (if any), return the local
metric. NEVER read the external scorer's labels — an external score is read only via
scripts/report_score.py, under the PI-signed score envelope (hard rule 5).
"""

from __future__ import annotations

import random
from typing import Any

from .tracking import RunContext


def run(cfg: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    target = cfg.get("target") or {}
    metric = target.get("metric") or "score"

    # Toy "local CV" — a deterministic stand-in for the frozen metric (seed set upstream).
    score = 0.5 + random.random() * 0.1
    for step in range(1, 6):
        score += (random.random() - 0.5) * 0.01
        ctx.log({f"{metric}_running": round(score, 4)}, step=step)

    result: dict[str, Any] = {metric: round(score, 4)}

    # Output artifact contract is OPTIONAL — only when target.output is configured.
    out = target.get("output")
    if out and out.get("path"):
        from .output_io import toy_output, write_output  # local import: only when needed
        id_col = out.get("id_column") or "id"
        target_cols = list(out.get("target_columns") or ["target"])
        expected = out.get("expected_rows")
        n = int(expected) if expected else int((cfg.get("toy") or {}).get("n_rows", 20))
        rows = toy_output(n, id_column=id_col, target_columns=target_cols)
        write_output(ctx.run_dir, rows, id_column=id_col, target_columns=target_cols,
                     path=out.get("path"))
        result["n_predictions"] = n

    return result
