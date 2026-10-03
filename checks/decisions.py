"""guard.py decisions — Every settled non-headline decision in decisions.md carries a machine-checkable Revisit predicate.

A check for tools/guard.py: `uv run --with pyyaml python tools/guard.py decisions …`. It gets the parsed arguments and the guard module (HUB, LAB, labfiles, _row, _project_dir, _verdict)
and returns the exit code: 0 = OK · 1 = BLOCKED · 2 = WARN."""

from __future__ import annotations

import re

NAME = "decisions"


def add_args(p) -> None:
    p.add_argument("slug")
    p.add_argument("--strict", action="store_true", help="treat a missing predicate as BLOCKED")


# grammar for a machine-checkable Revisit predicate: FN(...) OP value [within tol of ref]
_PRED_RE = re.compile(r"^(metric|best|delta|status)\s*\([^)]*\)\s*(<=|>=|==|!=|<|>|within)\b", re.I)


def _decision_blocks(text: str):
    """Yield (D-NNN, block_body) for each '## D-NNN' section of a decisions.md."""
    parts = re.split(r"(?m)^##\s+(D-\d+)\b", text)
    for i in range(1, len(parts), 2):
        yield parts[i], (parts[i + 1] if i + 1 < len(parts) else "")


def _index_status(text: str) -> dict:
    """Map D-NNN -> status (lowercased) from the '## Decision index' table."""
    out = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"D-\d+", cells[0] or ""):
            out[cells[0]] = (cells[2] if len(cells) > 2 else "").lower()
    return out


def run(a, g) -> int:
    """Every SETTLED, non-headline decision must carry a machine-checkable **Revisit predicate:**
    so an explore loop's revisit trigger is parseable, not free prose. (The overseer still
    adjudicates whether it actually fired; this only shape-checks the trigger.) Headline:yes
    decisions are exempt; OPEN decisions are resolved by a pilot, not revisited. Target-driven
    (/compete) projects have no headline-hypothesis boundary and never run /scope — no decisions.md
    is expected, so they're exempt entirely."""
    row = g._row(a.slug)
    pdir = g._project_dir(a.slug, row)
    target = (g.labfiles.load_yaml(pdir / "control.yaml").get("target") or {}) if pdir else {}
    if bool(target.get("active")):
        return g._verdict(0, f"target-driven — no decisions.md expected for {a.slug}")
    dfile = g.HUB / "studies" / a.slug / "decisions.md"
    if not dfile.exists():
        return g._verdict(2, f"no decisions.md at studies/{a.slug}/ — run /scope first")
    text = dfile.read_text(encoding="utf-8-sig")
    status = _index_status(text)
    missing, malformed, checked = [], [], 0
    for dnnn, body in _decision_blocks(text):
        hm = re.search(r"\*\*Headline:\*\*\s*(yes|no)\b", body, re.I)
        if not hm or hm.group(1).lower() != "no":
            continue  # unfilled placeholder, or Headline:yes (exempt — it escalates)
        if status.get(dnnn, "settled") == "open":
            continue  # OPEN → resolved by a pilot, not revisited
        checked += 1
        pm = re.search(r"(?m)^\s*\*\*Revisit predicate:\*\*\s*(.+?)\s*$", body)
        pred = pm.group(1).strip().strip("`").strip() if pm else ""
        if pred.startswith("<!--"):
            pred = ""  # unfilled HTML-comment placeholder
        if not pred:
            missing.append(dnnn)
        elif not _PRED_RE.match(pred):
            malformed.append(dnnn)
    if malformed:
        for d in malformed:
            print(f"  - {d}: **Revisit predicate** present but ungrammatical (want FN(...) OP value)")
        return g._verdict(1, f"{len(malformed)} malformed Revisit predicate(s) in studies/{a.slug}/decisions.md")
    if missing:
        for d in missing:
            print(f"  - {d}: settled Headline:no decision has no machine **Revisit predicate:**")
        return g._verdict(1 if getattr(a, "strict", False) else 2,
                        f"{len(missing)} settled non-headline decision(s) without a machine predicate")
    return g._verdict(0, f"all {checked} settled non-headline decision(s) carry a well-formed Revisit predicate")
