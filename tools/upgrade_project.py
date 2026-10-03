"""Bring already-spawned projects up to date with the template's TRACING + HARNESS wiring.

A project is a snapshot of `templates/project/` taken at spawn. Later hub improvements to how agents
are traced (subagent hooks, the codex/opencode tracers, bus event kinds, role files) never reach it
on their own — its subagents then show up less completely in the dashboard. This copies ONLY the
template-owned plumbing, never research content:

  scripts/trace_hook.py · scripts/lab_bus.py        (verbatim template copies)
  .claude/settings.json                             ("hooks" block replaced; permissions untouched)
  .codex/hooks.json                                 (codex tracer hooks, used once the repo is trusted)
  .opencode/plugins/newts-trace.js · .opencode/.gitignore   (opencode tracer plugin)
  .claude/agents · .codex/agents · .opencode/agents (role files, resolved from the hub tiers)
  the RUNNER (scripts/run.py · _scheduler.py · _runner_guards.py · status.py · reconcile.py ·
  src/project_pkg/tracking.py) — job-scheduler support — and .codex/config.toml (its top-level keys once
  sat inside [agents], which codex ≥ 0.160 refuses); a file is replaced only while it still equals
  SOME past version of the template's (git history), so a project's own edits are never overwritten —
  a customized file is reported to merge by hand

    uv run --with pyyaml python tools/upgrade_project.py --all            # every registered project
    uv run --with pyyaml python tools/upgrade_project.py <slug> [<slug>…]
    uv run --with pyyaml python tools/upgrade_project.py --all --check    # report only; exit 1 if stale

Idempotent: an up-to-date project is left byte-identical. It does not commit — review the diff in the
project repo and commit it like any other change.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import role_sync  # noqa: E402
from executor.lab import Lab  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
TEMPLATE = HUB / "templates" / "project"
VERBATIM = ("scripts/trace_hook.py", "scripts/lab_bus.py", ".codex/hooks.json",
            ".opencode/plugins/newts-trace.js", ".opencode/.gitignore")


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


RUNNER = ("scripts/run.py", "scripts/_scheduler.py", "scripts/_runner_guards.py", "scripts/status.py",
          "scripts/reconcile.py", "src/project_pkg/tracking.py", ".codex/config.toml")
_HISTORY: dict[str, set[bytes]] = {}
CUSTOMIZED: list[str] = []


def _template_history(rel: str) -> set[bytes]:
    """Every committed version of templates/project/<rel> (normalized) — the versions a project could
    have been spawned with. A project file equal to one of them is untouched template code."""
    if rel in _HISTORY:
        return _HISTORY[rel]
    path = f"templates/project/{rel}"
    seen: set[bytes] = set()
    try:
        revs = subprocess.run(["git", "-C", str(HUB), "rev-list", "HEAD", "--", path], capture_output=True,
                              text=True, timeout=60).stdout.split()
        for rev in revs[:200]:
            r = subprocess.run(["git", "-C", str(HUB), "show", f"{rev}:{path}"], capture_output=True, timeout=60)
            if r.returncode == 0:
                seen.add(_norm(r.stdout))
    except (OSError, subprocess.TimeoutExpired):
        pass
    _HISTORY[rel] = seen
    return seen


def _settings_with_template_hooks(current: str | None) -> str:
    tmpl = json.loads((TEMPLATE / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cur = json.loads(current) if current else {}
    if not isinstance(cur, dict):
        cur = {}
    cur["hooks"] = tmpl.get("hooks") or {}   # replaced in place: key order (and permissions) kept
    if "permissions" not in cur and "permissions" in tmpl:
        cur["permissions"] = tmpl["permissions"]
    return json.dumps(cur, indent=2, ensure_ascii=False) + "\n"


def plan(project: Path) -> list[tuple[Path, bytes]]:
    """(path, desired bytes) for every template-owned file whose content differs."""
    out = []
    for rel in VERBATIM:
        src, dst = TEMPLATE / rel, project / rel
        want = src.read_bytes()
        if not dst.exists() or _norm(dst.read_bytes()) != _norm(want):
            out.append((dst, want))
    for rel in RUNNER:
        src, dst = TEMPLATE / rel, project / rel
        if not src.exists():
            continue
        want = src.read_bytes()
        if dst.exists() and _norm(dst.read_bytes()) == _norm(want):
            continue
        if not dst.exists() and rel.startswith("src/"):
            continue                       # an adopted repo with its own package: not ours to add
        if dst.exists() and _norm(dst.read_bytes()) not in _template_history(rel):
            if f"{project.name}/{rel}" not in CUSTOMIZED:
                CUSTOMIZED.append(f"{project.name}/{rel}")
            continue                       # the project changed it: never overwrite its own edits
        out.append((dst, want))
    sp = project / ".claude" / "settings.json"
    cur = sp.read_text(encoding="utf-8") if sp.exists() else None
    try:
        want = _settings_with_template_hooks(cur)
    except json.JSONDecodeError:
        print(f"  ! {sp} is not valid JSON — left alone; fix it by hand")
        want = None
    if want is not None and (cur is None or json.loads(cur).get("hooks") != json.loads(want).get("hooks")):
        out.append((sp, want.encode("utf-8")))
    return out


def upgrade(project: Path, *, check: bool = False) -> int:
    """Returns the number of files that are (or were) stale."""
    changes = plan(project)
    for path, data in changes:
        rel = path.relative_to(project).as_posix()
        print(f"  {'STALE' if check else 'wrote'}: {rel}")
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if check:
        stale_roles = role_sync.project_stale(project)
        for path in stale_roles:
            print(f"  STALE: {path.relative_to(project).as_posix()}")
        roles = len(stale_roles)
    else:
        roles = role_sync.render_project(project)
        if roles:
            print(f"  wrote: {roles} role file(s) (.claude/.codex/.opencode agents)")
    return len(changes) + roles


def main() -> int:
    ap = argparse.ArgumentParser(description="sync template-owned tracing/harness files into spawned projects")
    ap.add_argument("projects", nargs="*", help="project slugs (or paths)")
    ap.add_argument("--all", action="store_true", help="every registered project with a repo")
    ap.add_argument("--check", action="store_true", help="report stale files; change nothing (exit 1 if any)")
    ap.add_argument("--hub", default=str(HUB))
    a = ap.parse_args()
    lab = Lab(Path(a.hub))
    targets: list[tuple[str, Path]] = []
    if a.all:
        targets = lab.project_dirs()
    for p in a.projects:
        d = lab.project_dir(p) or (Path(p) if Path(p).is_dir() else None)
        if not d:
            print(f"[upgrade_project] no project repo for '{p}'")
            return 1
        targets.append((p, d))
    if not targets:
        print("[upgrade_project] nothing to do (no registered project repos; pass slugs or --all)")
        return 0
    stale = 0
    for slug, d in targets:
        print(f"[upgrade_project] {slug} ({d})")
        n = upgrade(d, check=a.check)
        stale += n
        if not n:
            print("  up to date")
    if CUSTOMIZED:
        print("[upgrade_project] customized in the project, left alone (merge the template's changes by hand):")
        for c in CUSTOMIZED:
            print(f"  - {c}  ← templates/project/{c.split('/', 1)[1]}")
    if a.check:
        print(f"[upgrade_project] {stale} stale file(s)" if stale else "[upgrade_project] all projects up to date")
        return 1 if stale else 0
    print(f"[upgrade_project] done — {stale} file(s) updated; review and commit in each project repo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
