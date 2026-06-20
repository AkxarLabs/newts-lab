"""Output-artifact I/O for target-driven projects (stdlib-only — no pandas dependency).

When the target is scored on an artifact you produce (a submission / predictions file), a run
writes that artifact into its run dir so it is reproducible and validatable:

    from project_pkg.output_io import write_output
    out = write_output(ctx.run_dir, rows, id_column="id", target_columns=["target"])

`rows` is an iterable of dicts, each carrying the id column and every target column.
`scripts/check_output.py` validates the written file against control.yaml's `target.output`
contract (header, row count, no empty cells). This is the generic CSV path — nothing here is
specific to any host or tool. If a task needs a different output format, write it directly into
`ctx.run_dir` and set `target.output.format: other` (then provide your own validation).

Keep this stdlib-only: many task runners use a fixed image and the lab must not silently assume
pandas. If a project already uses pandas, `df.to_csv(ctx.run_dir / "submission.csv", index=False)`
produces the same artifact — this helper is the dependency-free path.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def write_output(
    run_dir: str | Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    id_column: str,
    target_columns: Sequence[str],
    path: str = "submission.csv",
) -> Path:
    """Write `rows` to `<run_dir>/<path>` as CSV with header `[id_column, *target_columns]`.

    Raises ValueError if a row is missing the id or a target column — a malformed output must
    fail at write time, not silently when it is scored."""
    run_dir = Path(run_dir)
    header = [id_column, *target_columns]
    out = run_dir / path
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        for i, row in enumerate(rows):
            missing = [c for c in header if c not in row or row[c] is None or row[c] == ""]
            if missing:
                raise ValueError(f"output row {i} is missing required field(s): {missing}")
            writer.writerow({c: row[c] for c in header})
            n += 1
    if n == 0:
        raise ValueError("output is empty — at least one prediction row is required")
    return out


def toy_output(
    n_rows: int = 20,
    *,
    id_column: str = "id",
    target_columns: Sequence[str] = ("target",),
) -> list[dict[str, Any]]:
    """Deterministic toy predictions so the target SMOKE produces a *valid* output end-to-end
    before any real model exists. Seed is set by scripts/run.py upstream."""
    return [
        {id_column: i, **{c: round(random.random(), 6) for c in target_columns}}
        for i in range(n_rows)
    ]
