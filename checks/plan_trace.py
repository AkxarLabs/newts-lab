"""guard.py plan-trace — Every non-baseline PLAN.md row traces to an authorized origin (a D-NNN or an expand round).

A check for tools/guard.py: `uv run --with pyyaml python tools/guard.py plan-trace …`. It gets the parsed arguments and the guard module (HUB, LAB, labfiles, _row, _project_dir, _verdict)
and returns the exit code: 0 = OK · 1 = BLOCKED · 2 = WARN."""

from __future__ import annotations

import re

NAME = "plan-trace"


def add_args(p) -> None:
    p.add_argument("slug")


def _experiment_rows(text: str):
    """Yield (id, full_row_text) for each PLAN.md Experiments-table data row. Id-convention-agnostic
    (theory/simulation projects may label rows E-002/run-002, not just exp-002), and the whole row is
    returned so a Headline-change / D-NNN marker is seen no matter which column it sits in."""
    in_tbl = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("| ID ") and "Question" in ln and "Stage" in ln:
            in_tbl = True
            continue
        if in_tbl:
            if not s.startswith("|"):
                break
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or set("".join(cells)) <= {"-", ":", " "}:
                continue
            if cells[0]:                       # any non-empty id cell, not just 'exp-*'
                yield cells[0], " ".join(cells)


def run(a, g) -> int:
    """Every non-baseline PLAN.md experiment row must trace to an authorized origin: a decisions.md
    D-NNN, an `(expand Rn)` tag backed by a Re-planning-log row, or the exp-001 seed. A row carrying
    a `Headline-change: yes` marker is BLOCKED regardless of any D-NNN citation (a decisions.md
    decision is not a /propose origin — a headline change must re-enter /propose)."""
    pdir = g._project_dir(a.slug)
    if not pdir:
        return g._verdict(1, f"no project dir for {a.slug}")
    plan = pdir / "PLAN.md"
    if not plan.exists():
        return g._verdict(1, f"no PLAN.md in {pdir.name}")
    text = plan.read_text(encoding="utf-8-sig")
    dfile = g.HUB / "studies" / a.slug / "decisions.md"
    dids = set(re.findall(r"\bD-\d+\b", dfile.read_text(encoding="utf-8-sig"))) if dfile.exists() else set()
    replan = text.split("## Re-planning log", 1)[1] if "## Re-planning log" in text else ""
    has_expand_log = bool(re.search(r"frontier_expand|decision_revisit", replan))
    rows = list(_experiment_rows(text))
    untraceable, blocked = [], []
    for i, (rid, blob) in enumerate(rows):
        # A Headline-change:yes row is ALWAYS blocked (even the seed) — it must re-enter /propose, and a
        # decisions.md D-NNN is not a /propose origin. Classified BEFORE the seed/traced short-circuits,
        # and scanned over the WHOLE row so the marker can't hide in an unscanned column.
        if re.search(r"headline[-\s]?change:\s*yes", blob, re.I):
            blocked.append(rid)
            continue
        if i == 0 or re.fullmatch(r"[a-z]*[-_]?0*1", rid, re.I):
            continue  # the seed/baseline row (first row, or an *-001 id) needs no D-NNN origin
        traced = any(d in blob for d in dids) or \
            (bool(re.search(r"\(expand\s+R\d+\)", blob, re.I)) and has_expand_log)
        if not traced:
            untraceable.append(rid)
    if blocked:
        for r in blocked:
            print(f"  - {r}: Headline-change:yes row with no /propose origin — must re-enter /propose")
        return g._verdict(1, f"{len(blocked)} headline-changing PLAN.md row(s) bypassing /propose in {a.slug}")
    if untraceable:
        for r in untraceable:
            print(f"  - {r}: no D-NNN / (expand Rn) origin — provenance undocumented")
        return g._verdict(2, f"{len(untraceable)} PLAN.md row(s) with undocumented origin in {a.slug}")
    return g._verdict(0, f"all {len(rows)} PLAN.md experiment row(s) trace to an authorized origin")
