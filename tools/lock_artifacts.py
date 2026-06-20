"""Lock a finalized paper's cited run artifacts INTO the hub, so it stays auditable forever.

    uv run --with pyyaml python tools/lock_artifacts.py <slug>

For every artifact cited in `studies/<slug>/paper/claims.yaml` (the small `runs/<id>/metrics.json` —
metrics only, never checkpoints), copy it into committed `studies/<slug>/paper/artifacts/<rel>` and
record its sha256 into the claim's `artifact_sha256:` map. After this,
`audit_claims.py studies/<slug>/paper --verify-hashes` PASSES from a fresh hub clone even if the
project repo is gone — the paper carries its own evidence ("secured" in the hub). Run at
`/finalize`. Idempotent: re-running re-copies + re-hashes from the (still-present) project, or
keeps the already-archived copy if the project source is gone.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]


def projects_root() -> Path:
    config = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8-sig")) or {}
    root = ((config.get("lab") or {}).get("projects_root")) or "../kartr-lab-projects"
    return (HUB / root).resolve()


_REG_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]


def _registry_project_path(slug: str) -> Path | None:
    """The slug's project dir from lab/REGISTRY.md's Project column (mirrors audit_claims.py),
    so an /adopt project outside projects_root still archives its cited artifacts."""
    reg = HUB / "lab" / "REGISTRY.md"
    if not slug or not reg.exists():
        return None
    for line in reg.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(_REG_COLS) or cells[0] != slug:
            continue
        raw = (dict(zip(_REG_COLS, cells)).get("project") or "").strip().strip("`")
        if raw and raw not in ("—", "-"):
            p = Path(raw)
            return p if p.is_absolute() else (HUB / p).resolve()
    return None


def resolve_claim_project(claim: dict) -> Path:
    """Where a claim's artifacts live. Precedence: explicit `project_path` > REGISTRY.md
    Project column > projects_root()/<slug> (matches audit_claims.resolve_project_dir)."""
    pp = str(claim.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (HUB / p).resolve()
    slug = str(claim.get("project", ""))
    return _registry_project_path(slug) or (projects_root() / slug)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    args = ap.parse_args()

    paper_dir = HUB / "studies" / args.slug / "paper"
    claims_path = paper_dir / "claims.yaml"
    if not claims_path.exists():
        print(f"[lock_artifacts] no claims.yaml at {claims_path}")
        return 1
    doc = yaml.safe_load(claims_path.read_text(encoding="utf-8-sig")) or {}
    claims = doc.get("claims") or []
    archive = paper_dir / "artifacts"

    locked, missing = 0, []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        project = resolve_claim_project(claim)
        hashes = dict(claim.get("artifact_sha256") or {})
        for rel in (claim.get("artifacts") or []):
            src, dest = project / rel, archive / rel
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                hashes[rel] = sha256(src)
                locked += 1
            elif dest.exists():                       # already archived, project gone — keep it
                hashes[rel] = sha256(dest)
            else:
                missing.append(f"{claim.get('id', '?')}: {rel}")
        if hashes:
            claim["artifact_sha256"] = hashes

    doc["claims"] = claims
    claims_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                           encoding="utf-8")
    print(f"locked {locked} artifact(s) into studies/{args.slug}/paper/artifacts/ + recorded "
          f"sha256 in claims.yaml")
    if missing:
        print(f"WARNING — {len(missing)} cited artifact(s) not found in the project and not "
              f"already archived (cannot lock):")
        for m in missing:
            print(f"  - {m}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
