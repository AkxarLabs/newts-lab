"""Sync a paper's figures from its project repo into the hub, with a verifiable manifest.

    uv run --with pyyaml python tools/sync_figures.py <slug>          # copy + record manifest
    uv run --with pyyaml python tools/sync_figures.py <slug> --check  # verify, exit!=0 on drift

Figures are GENERATED in the project (`<projects_root>/<slug>/figures/` by `scripts/figures/*.py`)
and CONSUMED by the paper in the hub (`papers/<slug>/figures/`). This copies the `*.pdf/*.tex/*.png`
across and records, per file, the sha256 at copy time + the project's git commit, into
`papers/<slug>/figures/.manifest.json`. `--check` re-hashes and reports drift:
  - stale     : the project source changed since the last sync (regenerated, not re-synced)
  - diverged  : the hub copy was hand-edited (no longer matches what was synced)
  - missing   : a manifested file is gone from the hub or the project
Exit 0 = clean; 1 = any drift / missing. Used by `/make-figures` (sync) and `/review-paper`,
`/finalize` (`--check`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
EXTS = (".pdf", ".tex", ".png")


def projects_root() -> Path:
    config = yaml.safe_load((HUB / "lab" / "config.yaml").read_text(encoding="utf-8-sig")) or {}
    root = ((config.get("lab") or {}).get("projects_root")) or "../AutoScientist-Projects"
    return (HUB / root).resolve()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_commit(project: Path) -> str:
    try:
        r = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    project = projects_root() / args.slug
    src_dir = project / "figures"
    paper_fig = HUB / "papers" / args.slug / "figures"
    manifest_path = paper_fig / ".manifest.json"

    if args.check:
        if not manifest_path.exists():
            print(f"[sync_figures] no manifest at {manifest_path} — run "
                  f"`sync_figures.py {args.slug}` first")
            return 1
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        problems = []
        for name, ent in manifest.items():
            hub_f, src_f = paper_fig / name, src_dir / name
            if not hub_f.exists():
                problems.append(f"missing (hub copy gone): {name}")
                continue
            if sha256(hub_f) != ent["sha256"]:
                problems.append(f"diverged (hub copy hand-edited): {name}")
            if not src_f.exists():
                problems.append(f"missing (project source gone): {name}")
            elif sha256(src_f) != ent["sha256"]:
                problems.append(f"stale (project regenerated, not re-synced): {name}")
        if problems:
            print(f"## Figure sync check — {args.slug}: {len(problems)} issue(s)")
            for p in problems:
                print(f"- {p}")
            print(f"\nRe-run `tools/sync_figures.py {args.slug}` after regenerating; never "
                  f"hand-edit hub figures.")
            return 1
        print(f"figure sync OK — {len(manifest)} file(s) match their project sources ({args.slug})")
        return 0

    # sync mode
    if not src_dir.exists():
        print(f"[sync_figures] no figures dir at {src_dir} — run the /make-figures scripts first")
        return 1
    paper_fig.mkdir(parents=True, exist_ok=True)
    commit = project_commit(project)
    manifest, copied = {}, 0
    for f in sorted(src_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in EXTS:
            shutil.copy2(f, paper_fig / f.name)
            manifest[f.name] = {"sha256": sha256(f), "src": f"figures/{f.name}",
                                "project_commit": commit}
            copied += 1
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not copied:
        print(f"[sync_figures] {src_dir} has no .pdf/.tex/.png to sync")
        return 1
    print(f"synced {copied} figure file(s) → papers/{args.slug}/figures/ "
          f"(project commit {commit[:8] or '?'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
