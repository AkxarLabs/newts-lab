"""Project → hub write-back, atomically. Run from a PROJECT session at session-end.

    uv run --with pyyaml python <hub>/tools/hub_writeback.py --slug <slug> \
        [--notebook "..."] [--finding "..."] [--failure "..."] [--question "..."] \
        [--state <state>] [--evidence "..."]

The normal write-back path (hard rule 11) as one safe call: appends a dated `lab/notebook/`
entry, promotes durable insights to `lab/knowledge/{FINDINGS,FAILURES,OPEN-QUESTIONS}.md`, and
(with `--state`) sets the project's registry row. The hub is found from this script's own
location. Appends are single-write (atomic for small blocks); the registry rewrite takes a
short lock. If you CANNOT run this tool (hub unreachable), append a `HUB-WRITEBACK-PENDING:`
block to the project's `EXPERIMENT_LOG.md` instead (see the project CLAUDE.md) — a hub session
reconciles it via `tools/process_writebacks.py --apply`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _append(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:        # single write — atomic for small blocks
        f.write(text)


def _promote(name: str, slug: str, text: str, evidence: str) -> None:
    ev = f" (evidence: {evidence})" if evidence else ""
    _append(LAB / "knowledge" / name, f"\n- [{_today()}] ({slug}) {text}{ev}\n")


def _notebook(slug: str, text: str, evidence: str) -> str:
    nb = LAB / "notebook" / f"{_today()}-{slug}.md"
    if not nb.exists():
        _append(nb, f"# Notebook — {slug} — {_today()}\n")
    block = f"\n## {time.strftime('%H:%M')} — {slug}\n\n{text}\n"
    if evidence:
        block += f"\n_evidence: {evidence}_\n"
    _append(nb, block)
    return str(nb.relative_to(HUB))


def _set_state(slug: str, state: str) -> str:
    reg = LAB / "REGISTRY.md"
    if not reg.exists():
        return "no REGISTRY.md"
    lock = LAB / ".registry.lock"
    for _ in range(50):                                # best-effort exclusive lock (~5s)
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            # Reclaim a crashed holder's lock: the registry rewrite takes milliseconds, so a lock
            # older than 60s is certainly abandoned — without this a killed writer wedges ALL future
            # registry state changes forever ("registry busy" on every session).
            try:
                if time.time() - lock.stat().st_mtime > 60:
                    lock.unlink()
                    continue
            except OSError:
                pass
            time.sleep(0.1)
    else:
        return "registry busy (lock not acquired)"
    try:
        lines = reg.read_text(encoding="utf-8-sig").splitlines()
        for i, line in enumerate(lines):
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= len(_COLS) and cells[0] == slug:
                cells[2] = state
                if len(cells) > 6:
                    cells[6] = _today()
                lines[i] = "| " + " | ".join(cells) + " |"
                reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
                return "ok"
        return f"no registry row for '{slug}'"
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--notebook")
    ap.add_argument("--finding")
    ap.add_argument("--failure")
    ap.add_argument("--question")
    ap.add_argument("--state")
    ap.add_argument("--evidence")
    args = ap.parse_args()

    if not LAB.exists():
        print("[hub_writeback] hub lab/ not found — append a HUB-WRITEBACK-PENDING block to "
              "EXPERIMENT_LOG.md instead", file=sys.stderr)
        return 1

    did = []
    if args.notebook:
        did.append("notebook:" + _notebook(args.slug, args.notebook, args.evidence or ""))
    if args.finding:
        _promote("FINDINGS.md", args.slug, args.finding, args.evidence or "")
        did.append("finding")
    if args.failure:
        _promote("FAILURES.md", args.slug, args.failure, args.evidence or "")
        did.append("failure")
    if args.question:
        _promote("OPEN-QUESTIONS.md", args.slug, args.question, args.evidence or "")
        did.append("question")
    if args.state:
        r = _set_state(args.slug, args.state)
        did.append(f"state→{args.state}" if r == "ok" else f"state FAILED ({r})")

    if not did:
        print("[hub_writeback] nothing to write — give "
              "--notebook/--finding/--failure/--question/--state")
        return 1
    print("hub write-back done: " + ", ".join(did))
    return 0


if __name__ == "__main__":
    sys.exit(main())
