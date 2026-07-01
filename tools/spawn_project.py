"""Mechanical project scaffolder — the deterministic half of /spawn-project.

Copy `templates/project/` → `<projects_root>/<slug>`, substitute the four placeholders as UTF-8 with
**NO BOM** (so `pyproject.toml` never gets a BOM that breaks `tomllib`/`uv` on Windows), drop the
runtime cruft the hub-side template accumulates (`.pytest_cache`, `.bus`, `__pycache__`, stale
`runs/` dirs), apply the project-TYPE card + optional domain profile + optional target-driven
overlay, then optionally `git init` + `uv sync` + smoke + tests + `check_project.py` and commit only
if every check passes.

    uv run --with pyyaml python tools/spawn_project.py --slug demo --title "Demo" \
        --project-type ml [--domain econ] [--overlay compete] [--run-smoke] [--skip-guard]

The JUDGMENT steps stay in `/spawn-project`: fill `PLAN.md` from the proposal, pick the type,
sign the Gate-2 envelope, and update `lab/REGISTRY.md`. This tool owns the copy/substitute/init
mechanics that are easy to get subtly wrong by hand. Exit: 0 = scaffolded (+ committed if green) ·
1 = blocked (guard / collision) · 2 = scaffolded but a smoke/test check failed (left uncommitted).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]

# Runtime cruft that must never travel into a fresh project (it's regenerated / gitignored there).
_EXCLUDE_DIRS = {".git", ".pytest_cache", ".venv", "__pycache__", ".bus", ".guard"}
_PLACEHOLDERS = ("{{slug}}", "{{title}}", "{{date}}", "{{hub_path}}")  # ONLY these four — leave {{c}} etc.


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _projects_root(hub: Path) -> Path:
    root = ((_load_yaml(hub / "lab" / "config.yaml").get("lab") or {}).get("projects_root")) \
        or "../newts-lab-projects"
    return (hub / root).resolve()


def _copy_file(src: Path, dst: Path, subs: dict) -> None:
    """Copy one file. Text (UTF-8-decodable, no NUL) is placeholder-substituted and written with NO
    BOM; anything else is copied byte-for-byte."""
    data = src.read_bytes()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if b"\x00" in data:
        dst.write_bytes(data)
        return
    try:
        text = data.decode("utf-8-sig")  # strips a BOM if the source has one
    except UnicodeDecodeError:
        dst.write_bytes(data)
        return
    for key in _PLACEHOLDERS:
        text = text.replace(key, subs.get(key, ""))
    dst.write_text(text, encoding="utf-8", newline="")  # utf-8 == no BOM


def _copy_tree(src: Path, dst: Path, subs: dict) -> int:
    """Recursively copy src→dst, skipping runtime cruft and stale runs/ dirs. Returns file count."""
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        rel = Path(root).relative_to(src)
        if rel.parts[:1] == ("runs",):
            dirs[:] = []  # never descend into per-run dirs; only the two committed files below travel
        for f in files:
            if f.endswith(".pyc"):
                continue
            if rel.parts[:1] == ("runs",) and (len(rel.parts) > 1 or f not in ("README.md", "registry.jsonl")):
                continue  # a fresh project starts with an empty runs/ (just its README)
            _copy_file(Path(root) / f, dst / rel / f, subs)
            n += 1
    return n


def _set_control_type(control: Path, project_type: str) -> None:
    """Point control.yaml project_type: at the chosen type (default template is `ml`)."""
    if project_type == "ml" or not control.exists():
        return
    import re
    text = control.read_text(encoding="utf-8-sig")
    new = re.sub(r"(?m)^project_type:\s*\S+", f"project_type: {project_type}", text, count=1)
    if new != text:
        control.write_text(new, encoding="utf-8", newline="")


def scaffold(dest: Path, *, hub: Path, slug: str, title: str, date: str,
             project_type: str = "ml", domain: str | None = None, overlay: str | None = None) -> dict:
    """Copy + substitute the template into dest, apply the TYPE card / domain / overlay. No git/uv."""
    # hub_path uses forward slashes: a raw Windows path (C:\Users\...) inside the double-quoted YAML
    # string in control.yaml is an invalid escape sequence (\U, \s) and breaks the config parser;
    # C:/Users/... is valid YAML and pathlib resolves it fine on Windows.
    subs = {"{{slug}}": slug, "{{title}}": title, "{{date}}": date,
            "{{hub_path}}": str(hub).replace("\\", "/")}
    files = _copy_tree(hub / "templates" / "project", dest, subs)
    # SYSTEM.md — the lab machine card, if the PI wrote one.
    sysmd = hub / "lab" / "SYSTEM.md"
    if sysmd.exists():
        _copy_file(sysmd, dest / "SYSTEM.md", subs)
    # project-TYPE card + control.yaml project_type.
    card = hub / "templates" / "project-types" / project_type / "TYPE.md"
    if card.exists():
        _copy_file(card, dest / "TYPE.md", subs)
    _set_control_type(dest / "control.yaml", project_type)
    # optional domain profile.
    if domain:
        prof = hub / "templates" / "domain-profiles" / f"{domain}.md"
        if prof.exists():
            _copy_file(prof, dest / "DOMAIN.md", subs)
    # optional overlay (target-driven = templates/compete/, copied ON TOP).
    if overlay:
        odir = hub / "templates" / overlay
        if odir.exists():
            _copy_tree(odir, dest, subs)
    return {"files": files, "dest": str(dest), "project_type": project_type,
            "has_type_card": card.exists(), "domain": domain, "overlay": overlay}


def _runs_nonempty(dest: Path) -> bool:
    runs = dest / "runs"
    return runs.exists() and any(p.is_dir() for p in runs.glob("*"))


def _has_commits(dest: Path) -> bool:
    if not (dest / ".git").exists():
        return False
    r = subprocess.run(["git", "-C", str(dest), "rev-parse", "--verify", "HEAD"],
                       capture_output=True, text=True)
    return r.returncode == 0


def initialize(dest: Path, *, run_smoke: bool = True) -> dict:
    """git init (+ uv sync / smoke / tests / check_project when run_smoke). Returns per-step results."""
    results: dict = {}

    def _step(name, cmd):
        r = subprocess.run(cmd, cwd=str(dest), capture_output=True, text=True)
        results[name] = {"ok": r.returncode == 0, "code": r.returncode,
                         "out": (r.stdout or "")[-1500:], "err": (r.stderr or "")[-1500:]}
        return results[name]["ok"]

    if not (dest / ".git").exists():
        _step("git-init", ["git", "init"])
    if not run_smoke:
        return results
    if not _step("uv-sync", ["uv", "sync"]):
        return results
    _step("smoke", ["uv", "run", "python", "scripts/run.py", "--config",
                    "configs/experiments/exp-001-smoke.yaml"])
    # project-local basetemp (inside the gitignored .pytest_cache) so a locked/corrupt SYSTEM temp
    # dir — a real Windows failure mode — can't spuriously fail the scaffold gate.
    _step("pytest", ["uv", "run", "pytest", "tests/", "-q", "--basetemp=.pytest_cache/tmp"])
    _step("check-project", ["uv", "run", "--with", "pyyaml", "python", "scripts/check_project.py"])
    return results


def run(a) -> int:
    if not getattr(a, "skip_guard", False):
        g = subprocess.run([sys.executable, str(HUB / "tools" / "guard.py"), "spawn", a.slug],
                           capture_output=True, text=True)
        sys.stdout.write(g.stdout)
        if g.returncode != 0:
            print("[spawn] BLOCKED by guard.py spawn — Gate 1 not recorded (run /propose first).")
            return 1
    dest = _projects_root(HUB) / a.slug
    if dest.exists() and (_has_commits(dest) or _runs_nonempty(dest)):
        print(f"[spawn] BLOCKED: {dest} already has commits or runs — a reused slug overwrites a recorded "
              "kill/result. Pick a distinct slug (link the old one in the successor's triage notes).")
        return 1
    date = getattr(a, "date", None) or time.strftime("%Y-%m-%d")
    info = scaffold(dest, hub=HUB, slug=a.slug, title=a.title, date=date,
                    project_type=a.project_type, domain=a.domain, overlay=a.overlay)
    print(f"[spawn] scaffolded {dest} — {info['files']} files, type={a.project_type}"
          + (f", domain={a.domain}" if a.domain else "") + (f", overlay={a.overlay}" if a.overlay else ""))
    res = initialize(dest, run_smoke=a.run_smoke)
    for name, r in res.items():
        print(f"  - {name}: {'ok' if r['ok'] else 'FAILED (' + str(r['code']) + ')'}")
    if not a.run_smoke:
        print("[spawn] scaffold only (no --run-smoke). Fill PLAN.md/control.yaml, then init + commit.")
        return 0
    green = all(res.get(k, {}).get("ok") for k in ("uv-sync", "smoke", "pytest", "check-project"))
    if green:
        subprocess.run(["git", "add", "-A"], cwd=str(dest), capture_output=True)
        subprocess.run(["git", "commit", "-m", "scaffold: spawn from Newts' Lab template, smoke green"],
                       cwd=str(dest), capture_output=True)
        print("[spawn] committed green scaffold. Next: fill PLAN.md from the proposal, set the "
              "gate2_envelope, update lab/REGISTRY.md (→ active), then /experiment.")
        return 0
    print("[spawn] LEFT UNCOMMITTED — a smoke/test/check step failed (see output above). Fix, then re-run "
          "(a red scaffold is never committed).")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="mechanically scaffold a project from templates/project/")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--project-type", default="ml", dest="project_type",
                    choices=["ml", "empirical", "simulation", "theory", "target-driven"])
    ap.add_argument("--domain", default=None, help="a domain profile (e.g. econ) → DOMAIN.md")
    ap.add_argument("--overlay", default=None, help="an overlay dir under templates/ (e.g. compete)")
    ap.add_argument("--date", default=None)
    ap.add_argument("--run-smoke", action="store_true", dest="run_smoke",
                    help="also uv sync + smoke + tests + check_project, and commit if green")
    ap.add_argument("--skip-guard", action="store_true", dest="skip_guard",
                    help="skip the guard.py spawn Gate-1 check (TESTS ONLY)")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
