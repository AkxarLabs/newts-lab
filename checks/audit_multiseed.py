"""Audit that HEADLINE paper claims carry multi-seed confirmation (hard rule 6).

    uv run --with pyyaml python checks/audit_multiseed.py studies/<slug>/paper [--rel-tol ...]

Only claims marked `headline: true` in claims.yaml are enforced (hard rule 6: "headline results get
multi-seed confirmation"). For each, the distinct seeds behind its artifacts are counted — a claim's
artifact `runs/<run_id>/metrics.json` resolves its seed from the project's `runs/registry.jsonl`
(fallback `runs/<run_id>/meta.json`). A headline claim backed by fewer than `seeds.multi_seed_n`
(project control.yaml) / `experiment.multi_seed_n` (lab, default 3) distinct seeds FAILS — unless it
carries a `multi_seed_waiver:` (a PI-facing rationale), which routes to MANUAL review instead.

Exit: 0 all headline claims confirmed (or none marked) · 2 a waiver needs human review · 1 a headline
claim lacks the required seeds. Wired: WARN in /write-paper, BLOCKING in /review-paper + /finalize.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]


def _projects_root() -> Path:
    return labfiles.projects_root(HUB)


def _registry_project_path(slug: str) -> Path | None:
    return labfiles.registry_project_path(HUB, slug)


def resolve_project_dir(claim: dict) -> Path:
    pp = str(claim.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (HUB / p).resolve()
    slug = str(claim.get("project", ""))
    return _registry_project_path(slug) or (_projects_root() / slug)


def multi_seed_n(project_dir: Path) -> int:
    """Resolve the seed floor: project control.yaml seeds.multi_seed_n > lab experiment.multi_seed_n > 3."""
    seeds = labfiles.load_yaml(project_dir / "control.yaml").get("seeds")
    n = seeds.get("multi_seed_n") if isinstance(seeds, dict) else None
    if n:
        return int(n)
    n = ((labfiles.load_yaml(HUB / "lab" / "config.yaml").get("experiment") or {}).get("multi_seed_n"))
    return int(n) if n else 3


def run_seed_map(project_dir: Path) -> dict:
    """run_id -> seed, from the committed runs/registry.jsonl."""
    out: dict = {}
    reg = project_dir / "runs" / "registry.jsonl"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid, seed = row.get("run_id"), row.get("seed")
            if rid and seed is not None:
                out[rid] = seed
    return out


def claim_seeds(claim: dict, project_dir: Path, seed_map: dict) -> set:
    """Distinct seeds across the claim's artifacts (run_id from runs/<run_id>/..., seed from the
    registry, falling back to the run's meta.json)."""
    seeds = set()
    for rel in (claim.get("artifacts") or []):
        m = re.match(r"runs/([^/]+)/", str(rel).replace("\\", "/"))
        if not m:
            continue
        rid = m.group(1)
        if rid in seed_map:
            seeds.add(seed_map[rid])
            continue
        meta = project_dir / "runs" / rid / "meta.json"
        if meta.exists():
            d = _load_json(meta)
            if d.get("seed") is not None:
                seeds.add(d["seed"])
    return seeds


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}


def audit(paper_dir: Path) -> int:
    claims_path = paper_dir / "claims.yaml"
    if not claims_path.exists():
        print(f"no claims.yaml at {claims_path}")
        return 1
    claims = (labfiles.load_yaml(claims_path).get("claims")) or []
    headline = [c for c in claims if isinstance(c, dict) and c.get("headline")]
    if not headline:
        print("[multiseed] no claims marked `headline: true` — nothing to enforce "
              "(mark the load-bearing results so hard rule 6 can be checked).")
        return 0
    print(f"## Multi-seed audit — {len(headline)} headline claim(s)\n")
    print("| id | status | detail |")
    print("|---|---|---|")
    have_fail = have_manual = False
    for c in headline:
        cid = c.get("id", "(no id)")
        pdir = resolve_project_dir(c)
        if str(c.get("multi_seed_waiver", "")).strip():
            print(f"| {cid} | **MANUAL** | multi_seed_waiver: {str(c['multi_seed_waiver'])[:80]} |")
            have_manual = True
            continue
        n = multi_seed_n(pdir)
        seeds = claim_seeds(c, pdir, run_seed_map(pdir))
        if len(seeds) >= n:
            print(f"| {cid} | **PASS** | {len(seeds)} distinct seeds ({sorted(seeds)}) |")
        else:
            print(f"| {cid} | **FAIL** | {len(seeds)}/{n} distinct seeds — a headline result needs "
                  f">= {n} (hard rule 6) |")
            have_fail = True
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
