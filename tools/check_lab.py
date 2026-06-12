"""Lint lab state: registry vs idea frontmatter, orphan dirs, stale rows.

    uv run --with pyyaml python tools/check_lab.py [--stale-days N] [--strict]

Checks:
  1. Every ideas/<slug>/IDEA.md frontmatter `state` matches its lab/REGISTRY.md row.
  2. Orphans: idea dirs / <projects_root>/<slug> / papers/<slug> without a registry row,
     and registry rows pointing at missing idea dirs.
  3. Stale: non-terminal rows not updated in --stale-days (default lab/config.yaml
     lab.stale_days, else 14) or with an empty "Next action".

Exit 1 on mismatches/orphans (always) or stale items (with --strict); else 0.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
TERMINAL_STATES = {"final", "killed", "parked"}


def parse_registry() -> list[dict]:
    rows = []
    for line in (HUB / "lab" / "REGISTRY.md").read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= {"-"} or cells[0] == "—":
            continue
        rows.append(dict(zip(["id", "title", "state", "idea", "project", "paper", "updated", "next"], cells)))
    return rows


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(text[3:end]) or {}


def slug_dirs(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {d.name for d in root.iterdir() if d.is_dir()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stale-days", type=int, default=None)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    config_path = HUB / "lab" / "config.yaml"
    config = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}) if config_path.exists() else {}
    lab_cfg = config.get("lab") or {}
    stale_days = args.stale_days if args.stale_days is not None else lab_cfg.get("stale_days", 14)
    projects_root = (HUB / (lab_cfg.get("projects_root") or "../AutoScientist-Projects")).resolve()

    rows = {r["id"]: r for r in parse_registry()}
    problems, stale = [], []

    # 1. Idea frontmatter vs registry state.
    idea_dirs = slug_dirs(HUB / "ideas")
    for slug in sorted(idea_dirs):
        idea_md = HUB / "ideas" / slug / "IDEA.md"
        if not idea_md.exists():
            problems.append(f"ideas/{slug}/ has no IDEA.md")
            continue
        fm = parse_frontmatter(idea_md)
        if slug not in rows:
            problems.append(f"ideas/{slug}/ has no registry row")
        elif str(fm.get("state")) != rows[slug]["state"]:
            problems.append(f"{slug}: IDEA.md state '{fm.get('state')}' != registry '{rows[slug]['state']}'")

    # 2. Orphans. Worktree dirs (<slug>-wt-*) in the projects root are transient — skip them.
    for slug, row in rows.items():
        if slug not in idea_dirs:
            problems.append(f"registry row '{slug}' has no ideas/{slug}/ dir")
    for slug in sorted(slug_dirs(projects_root)):
        if slug not in rows and "-wt-" not in slug:
            problems.append(f"{projects_root.name}/{slug}/ has no registry row")
    for slug in sorted(slug_dirs(HUB / "papers")):
        if slug not in rows:
            problems.append(f"papers/{slug}/ has no registry row")

    # 3. Staleness.
    today = date.today()
    for slug, row in rows.items():
        if row["state"] in TERMINAL_STATES:
            continue
        if not row["next"]:
            stale.append(f"{slug}: empty 'Next action'")
        try:
            updated = datetime.strptime(row["updated"], "%Y-%m-%d").date()
            if (today - updated).days > stale_days:
                stale.append(f"{slug}: not updated since {row['updated']} (> {stale_days}d), state {row['state']}")
        except ValueError:
            stale.append(f"{slug}: unparseable Updated date '{row['updated']}'")

    print(f"## Lab check — {len(rows)} registry rows, {len(idea_dirs)} idea dirs\n")
    if problems:
        print("**Inconsistencies (fix now):**")
        for p in problems:
            print(f"- {p}")
    if stale:
        print("\n**Stale (review):**")
        for s in stale:
            print(f"- {s}")
    if not problems and not stale:
        print("All consistent.")

    if problems or (args.strict and stale):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
