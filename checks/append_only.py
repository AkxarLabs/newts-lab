"""guard.py append-only — The project's ledgers were only appended, never rewritten (hard rule append-only-ledgers).

A check for tools/guard.py: `uv run --with pyyaml python tools/guard.py append-only …`. It gets the parsed arguments and the guard module (HUB, LAB, labfiles, _row, _project_dir, _verdict)
and returns the exit code: 0 = OK · 1 = BLOCKED · 2 = WARN."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

NAME = "append-only"


def add_args(p) -> None:
    p.add_argument("target", help="slug or project path")


def _ledger_files(target: str, g):
    p = Path(target)
    pdir = p if (p.exists() and (p / "control.yaml").exists()) else g._project_dir(target)
    files = []
    if pdir:
        for rel in ("EXPERIMENT_LOG.md", "runs/registry.jsonl"):
            f = pdir / rel
            if f.exists():
                files.append(f)
    return pdir, files


def run(a, g) -> int:
    """Verify the append-only ledgers were not rewritten since the last call (history removed or
    a prior line edited). Records a per-project baseline; call it after each ledger append."""
    pdir, files = _ledger_files(a.target, g)
    if not pdir:
        return g._verdict(1, f"no project for {a.target}")
    base_dir = pdir / ".guard"
    base_dir.mkdir(exist_ok=True)
    base_path = base_dir / "ledger-baseline.json"
    try:
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        base = {}   # corrupt/unreadable baseline -> re-baseline (fail-safe), like _load_yaml
    violations, new_base, present = [], {}, set()
    for f in files:
        present.add(f.name)
        lines = f.read_text(encoding="utf-8-sig").splitlines()
        prev = base.get(f.name)
        if prev:
            n = prev["lines"]
            if len(lines) < n:
                violations.append(f"{f.name}: shrank {n}→{len(lines)} lines (history removed)")
            elif hashlib.sha256("\n".join(lines[:n]).encode()).hexdigest() != prev["sha"]:
                violations.append(f"{f.name}: the first {n} lines changed (append-only history rewritten)")
        new_base[f.name] = {"lines": len(lines),
                            "sha": hashlib.sha256("\n".join(lines).encode()).hexdigest()}
    # a baselined ledger that has VANISHED entirely is the most extreme history removal
    for name in base:
        if name not in present:
            violations.append(f"{name}: ledger file deleted (history removed)")
    if violations:
        for v in violations:
            print(f"  - {v}")
        # Do NOT overwrite the baseline on a violation: that would launder the tamper so a re-run
        # reports clean and loses the trail. Keep the prior baseline until a human resolves it.
        return g._verdict(1, f"append-only VIOLATION in {pdir.name}")
    tmp = base_path.parent / (base_path.name + ".tmp")   # atomic write (no half-written baseline on a race)
    tmp.write_text(json.dumps(new_base, indent=2), encoding="utf-8")
    tmp.replace(base_path)
    return g._verdict(0, f"append-only intact ({', '.join(f.name for f in files) or 'no ledgers yet'}); baseline updated")
