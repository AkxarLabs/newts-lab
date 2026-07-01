"""Owner-aware config editor — the mechanical half of /configure.

    uv run --with pyyaml python tools/configure.py view [--project <slug|path>] [--experiment <yaml>]
    uv run --with pyyaml python tools/configure.py set <key=value> [--project <slug|path>] \
        [--pi-approved] [--signed-via <path>]
    uv run --with pyyaml python tools/configure.py profile <list|show|diff|apply|save> [<name>]

`view` prints the effective 3-layer config with provenance (via tools/show_config.py). `set` stamps
ONE value into the right layer — `lab/config.yaml`, or a project's `control.yaml` with `--project` —
preserving comments (reuses tools/profiles.stamp), and **refuses a PI-owned key without
`--pi-approved`** (owners per docs/configuration.md). Setting `eval_frozen=false` warns loudly; a
`gate2_envelope.pi_signed=true` records `--signed-via` when given. After an `agents.*` change it
re-renders the backend role files (tools/role_sync.py). `profile` delegates to tools/profiles.py
(which enforces the rigor floor). Exit 0 = done · 1 = blocked/error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))  # tools/ — reuse the profiles helpers
import profiles  # noqa: E402 — stamp / _fmt / _sync_agent_model / AGENT_FILE

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"

# PI-owned keys (docs/configuration.md Owner column). Prefixes catch whole trees; the exact set is
# for keys that would be wrongly matched (or missed) by a prefix — e.g. loop.no_progress_backoff_cycles
# is agent-readable, so only loop.mode / loop.explore_ are prefixes, never a bare "loop.".
PI_OWNED_PREFIXES = ("lab.", "compute.", "agents.", "oversight.level", "critique.",
                     "writing.page_limit", "budgets.", "gate2_envelope.", "eval_frozen",
                     "loop.mode", "loop.explore_")
PI_OWNED_EXACT = {"ideation.in_project", "ideation.in_project_approval",
                  "writing.venue", "autopilot.max_concurrent_projects"}


def is_pi_owned(key: str) -> bool:
    return key in PI_OWNED_EXACT or any(key.startswith(p) for p in PI_OWNED_PREFIXES)


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:  # noqa: BLE001
        return {}


def _projects_root() -> Path:
    root = ((_load_yaml(LAB / "config.yaml").get("lab") or {}).get("projects_root")) or "../newts-lab-projects"
    return (HUB / root).resolve()


def _resolve_project(arg: str) -> Path | None:
    p = Path(arg)
    if p.exists() and (p / "control.yaml").exists():
        return p.resolve()
    reg = LAB / "REGISTRY.md"
    if reg.exists():
        for line in reg.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("|"):
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if cells and cells[0] == arg and len(cells) >= 5:
                    raw = (cells[4] or "").strip().strip("`")
                    if raw and raw not in ("—", "-"):
                        pp = Path(raw)
                        return pp if pp.is_absolute() else (HUB / pp).resolve()
    cand = _projects_root() / arg
    return cand if cand.exists() else None


def _parse_value(s: str):
    low = s.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    for cast in (int, float):
        try:
            return cast(s)
        except ValueError:
            continue
    return s


def cmd_view(a) -> int:
    cmd = [sys.executable, str(HUB / "tools" / "show_config.py")]
    if a.project:
        pdir = _resolve_project(a.project)
        cmd.append(str(pdir) if pdir else a.project)
        if a.experiment:
            cmd.append(a.experiment)
    return subprocess.run(cmd).returncode


def cmd_set(a) -> int:
    if "=" not in a.assignment:
        print("[configure] set needs key=value (e.g. experiment.num_drafts=4)")
        return 1
    key, _, raw = a.assignment.partition("=")
    key, value = key.strip(), _parse_value(raw)
    if is_pi_owned(key) and not a.pi_approved:
        print(f"[configure] BLOCKED: '{key}' is PI-owned — re-run with --pi-approved (you are the PI). "
              "See the Owner column in docs/configuration.md.")
        return 1
    if key == "eval_frozen" and value is False:
        print("[configure] WARNING: eval_frozen=false UNFREEZES the eval/test protocol — selection "
              "discipline (hard rule 5) rests on this. Only the PI, only with cause.")
    if a.project:
        pdir = _resolve_project(a.project)
        if not pdir:
            print(f"[configure] no project for {a.project!r}")
            return 1
        target = pdir / "control.yaml"
    else:
        target = LAB / "config.yaml"
    if not target.exists():
        print(f"[configure] no config file at {target}")
        return 1
    new, changed = profiles.stamp(target.read_text(encoding="utf-8-sig"), key.split("."), value)
    if not changed:
        print(f"[configure] key path '{key}' not found in {target.name} — check the name, or add it by hand")
        return 1
    target.write_text(new, encoding="utf-8", newline="")
    where = target.relative_to(HUB) if target.is_relative_to(HUB) else target
    print(f"[configure] set {key} = {profiles._fmt(value)} in {where}")
    if key == "gate2_envelope.pi_signed" and value and a.signed_via:
        n2, c2 = profiles.stamp(target.read_text(encoding="utf-8-sig"),
                                ["gate2_envelope", "signed_via"], a.signed_via)
        if c2:
            target.write_text(n2, encoding="utf-8", newline="")
            print(f"[configure] set gate2_envelope.signed_via = {a.signed_via}")
    if key.startswith("agents.") and target == (LAB / "config.yaml"):
        r = subprocess.run([sys.executable, str(HUB / "tools" / "role_sync.py"), "render"],
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
    return 0


def cmd_profile(a) -> int:
    cmd = [sys.executable, str(HUB / "tools" / "profiles.py"), a.action]
    if a.name:
        cmd.append(a.name)
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="owner-aware config view/set/profile")
    sub = ap.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("view")
    v.add_argument("--project", default=None)
    v.add_argument("--experiment", default=None)
    v.set_defaults(fn=cmd_view)

    s = sub.add_parser("set")
    s.add_argument("assignment", help="key=value (dotted key)")
    s.add_argument("--project", default=None, help="edit this project's control.yaml instead of lab config")
    s.add_argument("--pi-approved", action="store_true", dest="pi_approved",
                   help="authorize a PI-owned key change (you are the PI)")
    s.add_argument("--signed-via", default=None, dest="signed_via",
                   help="provenance path when signing gate2_envelope.pi_signed=true")
    s.set_defaults(fn=cmd_set)

    p = sub.add_parser("profile")
    p.add_argument("action", choices=["list", "show", "diff", "validate", "apply", "save"])
    p.add_argument("name", nargs="?", default=None)
    p.set_defaults(fn=cmd_profile)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
