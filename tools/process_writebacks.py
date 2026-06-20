"""Reconcile project → hub write-backs that were deferred while the hub was unreachable.

    uv run --with pyyaml python tools/process_writebacks.py            # list pending
    uv run --with pyyaml python tools/process_writebacks.py --apply    # apply + mark done

Scans every registry project's `EXPERIMENT_LOG.md` for `HUB-WRITEBACK-PENDING: <id>` blocks
without a matching `HUB-WRITEBACK-DONE: <id>` marker, applies them to the hub notebook/knowledge,
and appends a DONE marker (append-only — it never edits the pending line). Run at hub-session
orientation (`/lab-status`). Idempotent: each block is applied at most once.

Block format (written by a project session when it can't reach the hub):
    HUB-WRITEBACK-PENDING: <short-id>
    notebook: <one-line>
    finding: <one-line, optional>
    failure: <one-line, optional>
    question: <one-line, optional>
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
PENDING_RE = re.compile(r"^HUB-WRITEBACK-PENDING:\s*(\S+)\s*$")
# Match only a tool-emitted marker (id + ISO timestamp), so a casual mention of an id in prose
# can't masquerade as 'done' and suppress a genuinely-pending block of the same id.
DONE_RE = re.compile(r"^HUB-WRITEBACK-DONE:\s*(\S+)\s+\d{4}-\d\d-\d\dT")
KEY_RE = re.compile(r"^(notebook|finding|failure|question):\s*(.*)$")
_KNOW = {"finding": "FINDINGS.md", "failure": "FAILURES.md", "question": "OPEN-QUESTIONS.md"}


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


def projects_root() -> Path:
    config = yaml.safe_load((LAB / "config.yaml").read_text(encoding="utf-8-sig")) or {}
    root = ((config.get("lab") or {}).get("projects_root")) or "../kartr-lab-projects"
    return (HUB / root).resolve()


def registry_projects() -> list[tuple[str, Path]]:
    reg = LAB / "REGISTRY.md"
    out = []
    if not reg.exists():
        return out
    for line in reg.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(_COLS) or cells[0] in ("ID", "") or set(cells[0]) <= {"-"}:
            continue
        row = dict(zip(_COLS, cells))
        raw = (row.get("project") or "").strip().strip("`")
        if raw and raw not in ("—", "-"):
            p = Path(raw)
            p = p if p.is_absolute() else (HUB / p).resolve()
        else:
            p = projects_root() / row["id"]
        out.append((row["id"], p))
    return out


def parse_pending(text: str) -> list[tuple[str, dict]]:
    lines = text.splitlines()
    done = {m.group(1) for ln in lines for m in [DONE_RE.match(ln.strip())] if m}
    blocks, i = [], 0
    while i < len(lines):
        m = PENDING_RE.match(lines[i].strip())
        if m:
            bid, fields, j = m.group(1), {}, i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                km = KEY_RE.match(stripped)
                if km:
                    fields[km.group(1)] = km.group(2).strip()
                elif not stripped and not fields:
                    pass   # tolerate blank line(s) between the marker and the first field
                else:
                    break
                j += 1
            blocks.append((bid, fields))
            i = j
        else:
            i += 1
    return [(bid, f) for bid, f in blocks if bid not in done]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    total = 0
    for slug, pdir in registry_projects():
        log = pdir / "EXPERIMENT_LOG.md"
        if not log.exists():
            if not pdir.exists():
                print(f"  ! {slug}: project path not found ({pdir}) — cannot scan for write-backs",
                      file=sys.stderr)
            continue
        for bid, f in parse_pending(log.read_text(encoding="utf-8-sig")):
            total += 1
            print(f"- {slug}: pending {bid} — {f}")
            if not args.apply:
                continue
            applied = False
            if f.get("notebook"):
                nb = LAB / "notebook" / f"{_today()}-{slug}.md"
                if not nb.exists():
                    _append(nb, f"# Notebook — {slug} — {_today()}\n")
                _append(nb, f"\n## reconciled write-back {bid}\n\n{f['notebook']}\n")
                applied = True
            for key, fname in _KNOW.items():
                if f.get(key):
                    _append(LAB / "knowledge" / fname,
                            f"\n- [{_today()}] ({slug}) {f[key]} (reconciled {bid})\n")
                    applied = True
            if applied:
                _append(log, f"\nHUB-WRITEBACK-DONE: {bid} {time.strftime('%Y-%m-%dT%H:%M:%S')}\n")
            else:
                # an empty/malformed block: do NOT retire it — that would discard the deferred insight.
                print(f"  ! {slug}: pending {bid} parsed to no fields — NOT marking done; fix the block",
                      file=sys.stderr)

    if total == 0:
        print("no pending write-backs.")
    elif not args.apply:
        print(f"\n{total} pending — re-run with --apply to reconcile.")
    else:
        print(f"\nreconciled {total} write-back(s) into hub knowledge/notebook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
