"""Audit that every planned ablation was run, waived, or routed back — not silently dropped.

    uv run --with pyyaml python tools/audit_ablation_coverage.py studies/<slug>/paper

Reads the proposal's `### Planned ablations` bullets (studies/<slug>/proposal.md) and checks each is
ACCOUNTED FOR: some significant token from it appears in the project's `PLAN.md` experiment table or
`EXPERIMENT_LOG.md` (it was run / planned), OR the bullet itself marks it waived / N/A / dropped /
needs-experiment. A planned ablation with no trace anywhere is a FAIL — "stacked, un-ablated changes
are banned" (proposal discipline). Heuristic by necessity (the plan is free prose); it flags the
clear gaps, the reviewer reads the table.

Exit: 0 all accounted · 2 the ablation plan is empty/unparseable (verify by hand) · 1 a planned
ablation is unaccounted for. Wired: WARN in /write-paper, BLOCKING in /review-paper + /finalize.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "with", "without", "vs", "versus",
         "removal", "test", "ablation", "ablate", "remove", "removing", "each", "component",
         "this", "that", "our", "its", "on", "in", "by", "no", "not", "is", "are", "be"}
_WAIVED = re.compile(r"\b(waived|n/?a|not applicable|dropped|deferred|needs[-\s]experiment|skip)\b", re.I)


def _load_yaml(path: Path) -> dict:
    return labfiles.load_yaml(path)


def _projects_root() -> Path:
    return labfiles.projects_root(HUB)


def _project_dir(slug: str) -> Path | None:
    return labfiles.project_dir(HUB, slug)


def planned_ablations(proposal: Path) -> list[str]:
    """Bullet items under the '### Planned ablations' (or 'Ablation plan') heading, minus template
    comments/placeholders."""
    if not proposal.exists():
        return []
    text = proposal.read_text(encoding="utf-8-sig")
    m = re.search(r"(?im)^#{2,4}\s*(?:planned\s+)?ablation(?:s| plan)?\b", text)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r"(?m)^#{2,4}\s", rest)
    body = rest[:nxt.start()] if nxt else rest
    items = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith(("<!--", "#")) or not s:
            continue
        if s.startswith(("-", "*", "+")):
            item = s.lstrip("-*+ ").strip()
            if item and not item.startswith("<!--"):
                items.append(item)
    return items


def _tokens(item: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", item.lower()) if t not in _STOP]


def audit(paper_dir: Path) -> int:
    slug = paper_dir.parent.name
    proposal = HUB / "studies" / slug / "proposal.md"
    items = planned_ablations(proposal)
    if not items:
        print(f"[ablation] no parseable ablation plan in studies/{slug}/proposal.md — verify by hand "
              "(a results paper with un-ablated stacked changes violates proposal discipline).")
        return 2
    pdir = _project_dir(slug)
    haystack = ""
    for rel in ("PLAN.md", "EXPERIMENT_LOG.md"):
        f = (pdir / rel) if pdir else None
        if f and f.exists():
            haystack += "\n" + f.read_text(encoding="utf-8-sig").lower()
    print(f"## Ablation coverage — {len(items)} planned ablation(s) [studies/{slug}]\n")
    print("| ablation | status |")
    print("|---|---|")
    worst = 0
    for item in items:
        short = item[:70]
        if _WAIVED.search(item):
            print(f"| {short} | **WAIVED/routed** |")
            continue
        toks = _tokens(item)
        if toks and not any(t in haystack for t in toks):
            print(f"| {short} | **FAIL** (no trace in PLAN.md/EXPERIMENT_LOG.md) |")
            worst = 1
        else:
            print(f"| {short} | accounted |")
    print()
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir", help="e.g. studies/<slug>/paper")
    a = ap.parse_args()
    paper_dir = (HUB / a.paper_dir) if not Path(a.paper_dir).is_absolute() else Path(a.paper_dir)
    return audit(paper_dir)


if __name__ == "__main__":
    sys.exit(main())
