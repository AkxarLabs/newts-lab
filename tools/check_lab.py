"""Lint lab state: registry vs idea frontmatter, orphan dirs, stale rows.

    uv run --with pyyaml python tools/check_lab.py [--stale-days N] [--strict]

Checks:
  1. Every studies/<slug>/IDEA.md frontmatter `state` matches its lab/REGISTRY.md row.
  2. Orphans: studies/<slug>/ or <projects_root>/<slug> without a registry row,
     and registry rows pointing at missing study dirs. (The paper lives at
     studies/<slug>/paper/ — nested under the study, so it needs no separate check.)
  3. Stale: non-terminal rows not updated in --stale-days (default lab/config.yaml
     lab.stale_days, else 14) or with an empty "Next action".
  4. Executor (headless runs): a configured backend CLI that can't be found; dashboard
     auto_spawn_on_gate1 on while programmatic launching is off (no effect); runs stuck "live"
     past 2x their max_minutes (orphans — `executor_cli.py reconcile`); runs waiting days for an answer.

Exit 1 on mismatches/orphans (always) or stale items (with --strict); else 0.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import labfiles  # noqa: E402 — the lab's files, read one way
import workflow  # noqa: E402

TERMINAL_STATES = workflow.terminal_states(HUB)


def parse_registry() -> list[dict]:
    rows = []
    for line in (HUB / "lab" / "REGISTRY.md").read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 8 or cells[0] in ("ID", "") or set(cells[0]) <= {"-"} or cells[0] == "—":
            continue
        rows.append(dict(zip(["id", "title", "state", "idea", "project", "paper", "updated", "next"], cells)))
    return rows


def parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8-sig")
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

    config = labfiles.config(HUB)
    lab_cfg = config.get("lab") or {}
    stale_days = args.stale_days if args.stale_days is not None else lab_cfg.get("stale_days", 14)
    projects_root = labfiles.projects_root(HUB)

    rows = {r["id"]: r for r in parse_registry()}
    problems, stale = [], []

    # 1. Study frontmatter vs registry state. (each studies/<slug>/ is one research effort)
    study_dirs = slug_dirs(HUB / "studies")
    for slug in sorted(study_dirs):
        idea_md = HUB / "studies" / slug / "IDEA.md"
        if not idea_md.exists():
            problems.append(f"studies/{slug}/ has no IDEA.md")
            continue
        fm = parse_frontmatter(idea_md)
        if slug not in rows:
            problems.append(f"studies/{slug}/ has no registry row")
        elif str(fm.get("state")) != rows[slug]["state"]:
            problems.append(f"{slug}: IDEA.md state '{fm.get('state')}' != registry '{rows[slug]['state']}'")

    # 2. Orphans. Worktree dirs (<slug>-wt-*) in the projects root are transient — skip them.
    #    A paper at studies/<slug>/paper/ needs no separate check — it's nested under the study,
    #    which is already orphan-checked above.
    for slug, row in rows.items():
        if slug not in study_dirs:
            problems.append(f"registry row '{slug}' has no studies/{slug}/ dir")
    for slug in sorted(slug_dirs(projects_root)):
        if slug not in rows and "-wt-" not in slug and not slug.endswith("-wt"):  # skip transient worktrees (matches trace_hook)
            problems.append(f"{projects_root.name}/{slug}/ has no registry row")

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

    # 4. The workflow definition (workflow/stages.yaml) is consistent; registry states are ones it knows.
    problems.extend(f"workflow: {x}" for x in workflow.check(HUB))
    known = set(workflow.lifecycle(HUB)) | set(workflow.side_states(HUB))
    for slug, row in rows.items():
        if row["state"] not in known:
            problems.append(f"{slug}: registry state '{row['state']}' is not a workflow state")

    # 5. Executor hygiene (review-level: configuration and orphans, never a hard inconsistency).
    stale.extend(executor_checks(config, rows, projects_root))

    print(f"## Lab check — {len(rows)} registry rows, {len(study_dirs)} study dirs\n")
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


def _tracing_stale(pdir: Path) -> bool:
    """A spawned project missing the current tracer plumbing (subagents then show up less completely)."""
    tmpl = HUB / "templates" / "project"
    for rel in ("scripts/trace_hook.py", ".opencode/plugins/newts-trace.js", ".codex/hooks.json"):
        want, have = tmpl / rel, pdir / rel
        try:
            if want.exists() and (not have.exists() or
                                  have.read_bytes().replace(b"\r\n", b"\n") != want.read_bytes().replace(b"\r\n", b"\n")):
                return True
        except OSError:
            return True
    return False


def executor_checks(config: dict, rows: dict, projects_root: Path) -> list[str]:
    out = []
    prog = ((config.get("agents") or {}).get("programmatic")) or {}
    dash = config.get("dashboard") or {}
    if dash.get("auto_spawn_on_gate1") and not prog.get("enabled"):
        out.append("dashboard.auto_spawn_on_gate1 is on but agents.programmatic.enabled is off — it has no effect")
    for name, b in (prog.get("backends") or {}).items():
        cmd = (b or {}).get("command") if isinstance(b, dict) else None
        if isinstance(cmd, str) and cmd.strip() and not (Path(cmd).expanduser().exists() or shutil.which(cmd)):
            out.append(f"agents.programmatic.backends.{name}.command = {cmd!r} was not found")
    try:
        max_min = float(prog.get("max_minutes") or 240)
    except (TypeError, ValueError):
        max_min = 240.0
    dirs = [HUB / "lab" / ".bus" / "agents"]
    for slug, row in rows.items():
        raw = (row.get("project") or "").strip().strip("`")
        pdir = (Path(raw) if Path(raw).is_absolute() else (HUB / raw).resolve()) if raw and raw not in ("-", "—") \
            else projects_root / slug
        dirs.append(pdir / ".bus" / "agents")
        if (pdir / "control.yaml").exists() and _tracing_stale(pdir):
            out.append(f"project {slug}: its subagent-tracing files predate the template (trace_hook / hooks / "
                       "opencode plugin) — run `tools/upgrade_project.py " + slug + "`")
    now = time.time()
    for d in dirs:
        for f in (sorted(d.glob("*.json")) if d.is_dir() else []):
            try:
                m = json.loads(f.read_text(encoding="utf-8-sig"))
                ts = time.mktime(time.strptime(str(m.get("status_ts") or m.get("started") or "")[:19], "%Y-%m-%dT%H:%M:%S"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            age_min = (now - ts) / 60
            rid = m.get("run_id") or m.get("agent_id") or f.stem
            if m.get("status") in ("starting", "running", "resuming") and age_min > 2 * float(m.get("max_minutes") or max_min):
                out.append(f"run {rid} has been '{m.get('status')}' for {age_min:.0f} min (> 2x max_minutes) — "
                           "orphaned? run `executor_cli.py reconcile`")
            elif m.get("status") == "waiting_input" and age_min > 3 * 24 * 60:
                out.append(f"run {rid} has waited {age_min / 1440:.0f} days for your answer (dashboard → Needs you)")
    return out


if __name__ == "__main__":
    sys.exit(main())
