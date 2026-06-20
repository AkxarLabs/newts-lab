"""Validate a target-driven project's output artifact against the contract in control.yaml.

    uv run --with pyyaml python scripts/check_output.py [runs/<run_id>/submission.csv]

With no path, validates the output in the most recent run dir. Checks the file against
`control.yaml` -> `target.output`: header has the id + target column(s), exact row count (if
declared), and no empty id/target cells. Also flags a passed deadline. Built-in support is for
`format: csv`; for `format: other` the agent provides its own check (this exits 2 with a note).

Exit codes:  0 = valid · 1 = INVALID (the scorer would reject) · 2 = WARNING (proceed with care).
This is the output analogue of scripts/check_project.py — a mechanical gate so a malformed
output is caught here, not by a wasted external read.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def _target() -> dict:
    ctl = ROOT / "control.yaml"
    if not ctl.exists():
        return {}
    try:
        doc = yaml.safe_load(ctl.read_text(encoding="utf-8-sig")) or {}
    except yaml.YAMLError:
        return {}
    return doc.get("target") or {}


def _latest_output(rel_path: str) -> Path | None:
    runs = ROOT / "runs"
    if not runs.exists():
        return None
    # Pick by run-dir name (run_ids are timestamped — `...-sN-YYYYMMDD-HHMMSS`), NOT mtime:
    # a re-touched/copied older file must not shadow the newest run's output.
    cands = sorted(
        (d for d in runs.iterdir() if d.is_dir() and (d / rel_path).exists()),
        key=lambda d: d.name,
    )
    return (cands[-1] / rel_path) if cands else None


def _deadline_passed(deadline) -> bool:
    """True only if `deadline` parses as a date strictly before today (robust to non-zero-
    padded ISO like `2026-6-9`, which a naive string-slice compare got wrong)."""
    d = str(deadline or "").strip()
    if not d or d.lower() in ("null", "none"):
        return False
    head = d[:10]
    try:
        dl = date.fromisoformat(head)
    except ValueError:
        try:
            y, m, dd = (int(x) for x in head.replace("/", "-").split("-")[:3])
            dl = date(y, m, dd)
        except (ValueError, IndexError):
            return False
    return dl < date.today()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="output file (default: newest runs/*/<output.path>)")
    args = ap.parse_args()

    target = _target()
    if not target or not target.get("active"):
        print("[check_output] WARN: control.yaml has no active `target` block — is this a /compete project?")
        return 2
    out = target.get("output")
    if not out or not out.get("path"):
        print("[check_output] no `target.output` contract (local-metric-only target) — nothing to validate")
        return 0
    if (out.get("format") or "csv") != "csv":
        print(f"[check_output] WARN: target.output.format is '{out.get('format')}', not csv — "
              "provide your own validation for this format")
        return 2

    rel = out.get("path") or "submission.csv"
    id_col = out.get("id_column") or ""
    target_cols = list(out.get("target_columns") or [])
    expected_rows = out.get("expected_rows")

    path = Path(args.path) if args.path else _latest_output(rel)
    if not path or not path.exists():
        print(f"[check_output] INVALID: no output file found ({args.path or 'runs/*/' + rel})")
        return 1

    problems: list[str] = []
    warnings: list[str] = []
    if not id_col or not target_cols:
        warnings.append("control.yaml target.output is missing id_column/target_columns — "
                        "header check skipped; fill it from TARGET.md")

    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            rows = list(reader)
    except (OSError, csv.Error) as e:
        print(f"[check_output] INVALID: cannot parse {path} as CSV: {e}")
        return 1

    # Drop wholly-empty rows (a trailing newline yields a [] / blank final row) so the count
    # isn't off-by-one. A row with a present id but empty target is NOT dropped — it's flagged.
    rows = [r for r in rows if any((c or "").strip() for c in r)]

    if header is None:
        problems.append("file is empty (no header)")
    else:
        required = ([id_col] if id_col else []) + target_cols
        missing = [c for c in required if c not in header]
        if missing:
            problems.append(f"header is missing required column(s): {missing} (have {header})")
        elif required and header != required:
            warnings.append(f"header {header} differs in order/extra from expected {required} "
                            "— some scorers are strict; confirm against TARGET.md")
        idx = {c: header.index(c) for c in required if c in header}
        bad = 0
        for r in rows:
            for c, j in idx.items():
                if j >= len(r) or r[j].strip() == "":
                    bad += 1
                    break
        if bad:
            problems.append(f"{bad} row(s) have an empty id/target cell")

    n = len(rows)
    exp_n = None
    if expected_rows is not None:
        try:
            exp_n = int(expected_rows)
        except (TypeError, ValueError):
            warnings.append(f"expected_rows '{expected_rows}' is not an integer — row-count check skipped")
    if exp_n is not None and n != exp_n:
        problems.append(f"row count {n} != expected {exp_n} (the scorer would reject)")

    if _deadline_passed(target.get("deadline")):
        warnings.append(f"target deadline {target.get('deadline')} has PASSED — the scoring window may be closed")

    print(f"## Output check — {path.relative_to(ROOT) if ROOT in path.parents else path}\n")
    print(f"- Rows: {n}" + (f" (expected {expected_rows})" if expected_rows is not None else ""))
    print(f"- Header: {header}")
    for w in warnings:
        print(f"- WARN: {w}")
    if problems:
        for p in problems:
            print(f"- INVALID: {p}")
        return 1
    print("- Valid against the contract.")
    return 2 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
