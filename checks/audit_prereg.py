"""Audit pre-registration discipline (project rules: test-once, analysis-plan).

    uv run --with pyyaml python checks/audit_prereg.py studies/<slug>/paper

Three checks:
  1. The proposal's FROZEN "Analysis plan" names the primary comparison, the uncertainty method and the
     decision rule. An unfilled line is a FAIL: an analysis that was not planned cannot be confirmatory.
  2. The project's PLAN.md "Test-split access log" reads the held-out split once per configuration. A
     second row for the same configuration without a reason is a FAIL (the test split was re-opened
     silently). No log section at all routes to MANUAL (an older or adopted project).
  3. claims.yaml: every claim carries `status: confirmatory | exploratory`. An exploratory claim whose
     sentence does not say so FAILS; claims without a status route to MANUAL (label them).

Exit: 0 clean · 2 needs human review · 1 a real violation. Wired: part of `gate3_audits` in
workflow/rules.yaml (a campaign may not record a delegated Gate 3 unless it exits 0), WARN in /write-paper,
BLOCKING in /review-paper and /finalize.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
PLAN_LINES = ("Primary comparison", "Uncertainty", "Decision rule")


def _section(text: str, title_re: str) -> str | None:
    """The body of the first markdown heading matching title_re (any level), up to the next heading of
    the same or a higher level. None when absent."""
    m = re.search(r"^(#{2,4})\s+" + title_re + r".*$", text, re.M | re.I)
    if not m:
        return None
    level = len(m.group(1))
    rest = text[m.end():]
    nxt = re.search(r"^#{1,%d}\s" % level, rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _line_filled(text: str, label: str) -> bool | None:
    """Is '- **<label>:** <value>' filled with real content (comments stripped)? None if absent."""
    for line in text.splitlines():
        if re.search(r"\*\*[^*]*" + re.escape(label) + r"[^*]*\*\*", line, re.I):
            val = line.split("**", 2)[2] if line.count("**") >= 2 else ""
            val = re.sub(r"<!--.*?(-->|$)", "", val).lstrip(":").strip()
            return bool(val)
    return None


def _table_rows(body: str) -> list[list[str]]:
    rows = []
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or set("".join(cells)) <= set("-: "):
            continue
        rows.append(cells)
    return rows[1:] if rows else []     # drop the header row


def audit(paper_dir: Path) -> int:
    slug = paper_dir.parent.name
    have_fail = have_manual = False
    print(f"## Pre-registration audit — studies/{slug}\n")

    # Check 1: the proposal's frozen analysis plan.
    proposal = HUB / "studies" / slug / "proposal.md"
    if proposal.exists():
        body = _section(proposal.read_text(encoding="utf-8-sig"), r"Analysis plan")
        if body is None:
            print("- analysis plan: **FAIL** — the proposal has no \"Analysis plan\" section (templates/idea/proposal.md §4); "
                  "an unplanned analysis cannot be confirmatory.")
            have_fail = True
        else:
            missing = [lab for lab in PLAN_LINES if not _line_filled(body, lab)]
            if missing:
                print(f"- analysis plan: **FAIL** — not filled: {', '.join(missing)} (frozen at Gate 1 with the eval protocol).")
                have_fail = True
            else:
                print("- analysis plan: primary comparison, uncertainty and decision rule all defined ✓")
    else:
        print(f"- analysis plan: no proposal.md at studies/{slug}/ (MANUAL — is this an /adopt project?).")
        have_manual = True

    # Check 2: the test split was read once per configuration.
    pdir = labfiles.project_dir(HUB, slug)
    plan = (pdir / "PLAN.md") if pdir else None
    if plan and plan.exists():
        body = _section(plan.read_text(encoding="utf-8-sig"), r"Test-split access log")
        if body is None:
            print("- test split: PLAN.md has no \"Test-split access log\" (MANUAL — add it from templates/project/PLAN.md "
                  "and record every test read).")
            have_manual = True
        else:
            seen: dict[str, int] = {}
            reopened = []
            for cells in _table_rows(body):
                if len(cells) < 2:
                    continue
                cfg = cells[1]
                reason = cells[3] if len(cells) > 3 else ""
                seen[cfg] = seen.get(cfg, 0) + 1
                if seen[cfg] > 1 and not re.sub(r"<!--.*?-->", "", reason).strip():
                    reopened.append(cfg)
            if reopened:
                print(f"- test split: **FAIL** — re-opened without a reason: {', '.join(sorted(set(reopened)))} "
                      "(project rule test-once: a second read needs a written reason and makes the result exploratory).")
                have_fail = True
            else:
                n = sum(seen.values())
                print(f"- test split: {n} logged read(s), none re-opened silently ✓" if n else
                      "- test split: no reads logged yet ✓")
    else:
        print("- test split: no project PLAN.md found (MANUAL).")
        have_manual = True

    # Check 3: claims are labelled confirmatory or exploratory, and exploratory ones say so.
    claims = (labfiles.load_yaml(paper_dir / "claims.yaml").get("claims")) or []
    claims = [c for c in claims if isinstance(c, dict)]
    if claims:
        unlabelled = [str(c.get("id")) for c in claims if str(c.get("status", "")).strip().lower() not in ("confirmatory", "exploratory")]
        silent = [str(c.get("id")) for c in claims
                  if str(c.get("status", "")).strip().lower() == "exploratory" and "explorator" not in str(c.get("claim", "")).lower()]
        if silent:
            print(f"- claims: **FAIL** — exploratory but the sentence does not say so: {', '.join(silent)}.")
            have_fail = True
        if unlabelled:
            print(f"- claims: {len(unlabelled)} without `status:` — MANUAL (label each confirmatory or exploratory): "
                  f"{', '.join(unlabelled[:8])}{'…' if len(unlabelled) > 8 else ''}")
            have_manual = True
        if not silent and not unlabelled:
            n_ex = sum(1 for c in claims if str(c.get("status", "")).lower() == "exploratory")
            print(f"- claims: all {len(claims)} labelled ({n_ex} exploratory, each says so) ✓")
    else:
        print("- claims: none in claims.yaml — MANUAL (every quantitative claim gets an entry).")
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
