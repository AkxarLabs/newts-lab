"""Audit selection discipline (hard rule 5): tune on validation, report on a held-out test set.

    uv run --with pyyaml python tools/audit_eval_discipline.py studies/<slug>/paper

Two checks:
  1. The FROZEN eval protocol in the proposal (§4 "Metrics & evaluation protocol") must define BOTH a
     validation set (selection signal) and a held-out test set (reporting only). An unfilled line is a
     FAIL — the discipline can't hold if the split isn't specified.
  2. Headline claims should REPORT on test. A headline claim with `split: validation`/`val` FAILS
     (reporting a selection-time metric as a result). Headline claims that declare `split: test` PASS;
     if none declare a split, it routes to MANUAL (declare it, or verify test-only reporting by hand).

For project types without a val/test split (theory / simulation, per control.yaml `project_type`),
check 2 relaxes to MANUAL with a note (the TYPE card defines the analogue). Exit: 0 clean · 2 needs
human review · 1 a real violation. Wired: WARN in /write-paper, BLOCKING in /review-paper + /finalize.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
_REG_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
_SPLIT_ANALOGUE_TYPES = {"theory", "simulation"}   # no literal held-out test split


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _projects_root() -> Path:
    root = ((_load_yaml(HUB / "lab" / "config.yaml").get("lab") or {}).get("projects_root")) \
        or "../newts-lab-projects"
    return (HUB / root).resolve()


def _project_dir(slug: str) -> Path | None:
    reg = HUB / "lab" / "REGISTRY.md"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= len(_REG_COLS) and cells[0] == slug:
                raw = (dict(zip(_REG_COLS, cells)).get("project") or "").strip().strip("`")
                if raw and raw not in ("—", "-"):
                    p = Path(raw)
                    return p if p.is_absolute() else (HUB / p).resolve()
    cand = _projects_root() / slug
    return cand if cand.exists() else None


def _line_filled(text: str, label: str) -> bool | None:
    """Is the proposal's '- **<label>** (hint): <value>' line filled with real content (not just the
    template's label+hint)? The value is whatever follows the LAST colon on the line, so the
    '(selection signal):' hint can't masquerade as a value. None if the label line is absent."""
    for line in text.splitlines():
        if re.search(r"\*\*[^*]*" + re.escape(label) + r"[^*]*", line):
            val = line.rsplit(":", 1)[1] if ":" in line else ""
            val = re.sub(r"<!--.*?-->", "", val).strip()
            return bool(val)
    return None


def audit(paper_dir: Path) -> int:
    slug = paper_dir.parent.name
    proposal = HUB / "studies" / slug / "proposal.md"
    have_fail = have_manual = False
    print(f"## Eval-discipline audit — studies/{slug}\n")

    # Check 1: the frozen protocol defines validation + held-out test.
    ptype = ""
    pdir = _project_dir(slug)
    if pdir:
        ptype = str(_load_yaml(pdir / "control.yaml").get("project_type") or "").strip().lower()
    if proposal.exists():
        text = proposal.read_text(encoding="utf-8-sig")
        val = _line_filled(text, "Validation")
        test = _line_filled(text, "Held-out test")
        if ptype in _SPLIT_ANALOGUE_TYPES:
            print(f"- protocol: project_type={ptype} — val/test split is analogue-defined in TYPE.md "
                  "(MANUAL: verify the type's selection discipline).")
            have_manual = True
        elif val and test:
            print("- protocol: validation + held-out test both defined ✓")
        else:
            missing = [n for n, ok in (("validation", val), ("held-out test", test)) if not ok]
            print(f"- protocol: **FAIL** — {', '.join(missing)} not defined in the frozen §4 "
                  "eval protocol (selection discipline can't hold without it).")
            have_fail = True
    else:
        print(f"- protocol: no proposal.md at studies/{slug}/ (MANUAL — is this an /adopt project?).")
        have_manual = True

    # Check 2: headline claims report on test, not validation.
    claims = (_load_yaml(paper_dir / "claims.yaml").get("claims")) or []
    headline = [c for c in claims if isinstance(c, dict) and c.get("headline")]
    if headline:
        declared = 0
        for c in headline:
            split = str(c.get("split", "")).strip().lower()
            if split in ("val", "validation", "dev"):
                print(f"- claim {c.get('id')}: **FAIL** — headline result reports a "
                      f"{split}-selected metric; report on the held-out test set (hard rule 5).")
                have_fail = True
            elif split in ("test", "held-out", "heldout"):
                declared += 1
        if declared == len(headline):
            print(f"- claims: all {declared} headline claim(s) declare test-set reporting ✓")
        elif not any(str(c.get("split", "")).strip().lower() in ("val", "validation", "dev") for c in headline):
            print("- claims: headline claims don't declare `split:` — MANUAL (add `split: test`, or "
                  "verify test-only reporting by hand).")
            have_manual = True
    else:
        print("- claims: no `headline: true` claims marked — MANUAL (mark the load-bearing results).")
        have_manual = True
    print()
    return 1 if have_fail else (2 if have_manual else 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paper_dir", help="e.g. studies/<slug>/paper")
    a = ap.parse_args()
    paper_dir = (HUB / a.paper_dir) if not Path(a.paper_dir).is_absolute() else Path(a.paper_dir)
    return audit(paper_dir)


if __name__ == "__main__":
    sys.exit(main())
