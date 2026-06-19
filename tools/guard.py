"""Mechanical lifecycle guards — the lock on the door behind the prose procedures.

    uv run --with pyyaml python tools/guard.py spawn <slug>
    uv run --with pyyaml python tools/guard.py full-run <slug>
    uv run --with pyyaml python tools/guard.py frozen <slug>
    uv run --with pyyaml python tools/guard.py state <slug> <from> <to>
    uv run --with pyyaml python tools/guard.py append-only <slug | project-path>
    uv run --with pyyaml python tools/guard.py writeback <slug>

Each command validates a precondition/postcondition the protocol otherwise only states in
prose, so unattended autonomy doesn't depend on perfect agent memory. Idempotent and read-only
(except `append-only`, which records a per-project baseline under `<project>/.guard/`).

Exit codes:  0 = OK to proceed · 1 = BLOCKED (do not proceed) · 2 = WARNING (proceed with care).

The guard is the lock; the skills are still the human-readable procedures. A guard never grants a
gate — it only confirms one is already recorded, or refuses an unsafe transition.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
_COLS = ["id", "title", "state", "idea", "project", "paper", "updated", "next"]
LIFECYCLE = ["seed", "triaged", "lit-review", "scoping", "proposal", "active",
             "analysis", "writing", "internal-review", "final"]
# documented back-edges (the paper-phase round-trip) + forward steps are legal; park/kill anytime.
BACK_EDGES = {("analysis", "active"), ("writing", "active"), ("internal-review", "active"),
              ("writing", "analysis"), ("internal-review", "writing"), ("analysis", "writing")}


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _load_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception:
        return {}


def _registry_rows() -> list[dict]:
    reg = LAB / "REGISTRY.md"
    out = []
    if not reg.exists():
        return out
    for line in reg.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < len(_COLS) or cells[0] in ("ID", "") or set(cells[0]) <= {"-"}:
            continue
        out.append(dict(zip(_COLS, cells)))
    return out


def _row(slug: str) -> dict | None:
    return next((r for r in _registry_rows() if r["id"] == slug), None)


def _projects_root() -> Path:
    root = ((_load_yaml(LAB / "config.yaml").get("lab") or {}).get("projects_root")) \
        or "../AutoScientist-Projects"
    return (HUB / root).resolve()


def _project_dir(slug: str, row: dict | None = None) -> Path | None:
    row = row or _row(slug)
    if row:
        raw = (row.get("project") or "").strip().strip("`")
        if raw and raw not in ("—", "-"):
            p = Path(raw)
            return p if p.is_absolute() else (HUB / p).resolve()
    cand = _projects_root() / slug
    return cand if cand.exists() else None


def _verdict(code: int, msg: str) -> int:
    label = {0: "OK", 1: "BLOCKED", 2: "WARN"}[code]
    print(f"[guard] {label}: {msg}")
    return code


# ── commands ──────────────────────────────────────────────────────────────────

def c_spawn(a) -> int:
    """Gate 1 must be recorded before /spawn-project spends compute."""
    prop = HUB / "ideas" / a.slug / "proposal.md"
    if not prop.exists():
        return _verdict(1, f"no proposal at ideas/{a.slug}/proposal.md — run /propose first")
    if not re.search(r"gate ?1 approved|PI Gate 1|gate1_approved", prop.read_text(encoding="utf-8-sig"), re.I):
        return _verdict(1, f"Gate 1 not recorded in ideas/{a.slug}/proposal.md — needs PI sign-off before spawn")
    row = _row(a.slug)
    pd = _project_dir(a.slug, row)
    if pd and any(pd.glob("runs/*")):
        return _verdict(1, f"{pd.name} already has runs — refusing to overwrite (reused slug?)")
    if row and row["state"] != "proposal":
        return _verdict(2, f"Gate 1 present, but registry state is '{row['state']}' (expected 'proposal')")
    return _verdict(0, f"Gate 1 recorded — clear to /spawn-project {a.slug}")


def c_full_run(a) -> int:
    """A FULL run needs a signed, unexpired, non-empty gate2_envelope — else fresh PI approval."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    env = _load_yaml(pdir / "control.yaml").get("gate2_envelope") or {}
    if not env.get("pi_signed"):
        return _verdict(1, "no signed gate2_envelope — every FULL run needs fresh PI approval")
    exp = str(env.get("expires") or "").strip()
    if exp and exp.lower() not in ("null", "none") and exp < _today():
        return _verdict(1, f"gate2_envelope expired ({exp}) — needs re-signing before any FULL run")
    if not any(env.get(k) for k in ("full_runs", "per_run_max_minutes", "total_max_minutes")):
        return _verdict(1, "gate2_envelope authorizes nothing (all caps 0/null) — FULL needs PI approval")
    return _verdict(0, f"signed gate2_envelope covers FULL (full_runs={env.get('full_runs')}, expires={exp or 'n/a'})")


def c_frozen(a) -> int:
    """The frozen set must stay frozen: eval_frozen true + the PI-owned blocks present."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    ctl = _load_yaml(pdir / "control.yaml")
    problems = []
    if ctl.get("eval_frozen") is not True:
        problems.append("eval_frozen is not true — the eval/test protocol must never be unfrozen by the agent")
    for block in ("budgets", "seeds", "gate2_envelope"):
        if block not in ctl:
            problems.append(f"PI-owned block '{block}' missing from control.yaml")
    if problems:
        for p in problems:
            print(f"  - {p}")
        return _verdict(1, f"frozen-set integrity FAILED for {a.slug}")
    return _verdict(0, f"frozen set intact for {a.slug} (eval_frozen + budgets/seeds/envelope present)")


def c_state(a) -> int:
    """A registry state transition must be legal AND start from the row's actual current state."""
    row = _row(a.slug)
    if not row:
        return _verdict(1, f"no registry row for {a.slug}")
    if row["state"] != a.frm:
        return _verdict(1, f"registry state is '{row['state']}', not '{a.frm}' — refusing the {a.frm}→{a.to} transition")
    if a.to in ("parked", "killed"):
        return _verdict(0, f"{a.frm}→{a.to} (park/kill is allowed from any state)")
    legal = (a.frm in LIFECYCLE and a.to in LIFECYCLE
             and (LIFECYCLE.index(a.to) == LIFECYCLE.index(a.frm) + 1 or (a.frm, a.to) in BACK_EDGES))
    if not legal:
        return _verdict(1, f"{a.frm}→{a.to} is not a legal lifecycle transition")
    return _verdict(0, f"{a.frm}→{a.to} is legal — now update REGISTRY.md to match")


def _ledger_files(target: str):
    p = Path(target)
    pdir = p if (p.exists() and (p / "control.yaml").exists()) else _project_dir(target)
    files = []
    if pdir:
        for rel in ("EXPERIMENT_LOG.md", "runs/registry.jsonl"):
            f = pdir / rel
            if f.exists():
                files.append(f)
    return pdir, files


def c_append_only(a) -> int:
    """Verify the append-only ledgers were not rewritten since the last call (history removed or
    a prior line edited). Records a per-project baseline; call it after each ledger append."""
    pdir, files = _ledger_files(a.target)
    if not pdir:
        return _verdict(1, f"no project for {a.target}")
    base_dir = pdir / ".guard"
    base_dir.mkdir(exist_ok=True)
    base_path = base_dir / "ledger-baseline.json"
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    violations, new_base = [], {}
    for f in files:
        lines = f.read_text(encoding="utf-8-sig").splitlines()
        prev = base.get(f.name)
        if prev:
            n = prev["lines"]
            if len(lines) < n:
                violations.append(f"{f.name}: shrank {n}→{len(lines)} lines (history removed)")
            elif hashlib.sha256("\n".join(lines[:n]).encode()).hexdigest() != prev["sha"]:
                violations.append(f"{f.name}: the first {n} lines changed (append-only history rewritten)")
        new_base[f.name] = {"lines": len(lines),
                            "sha": hashlib.sha256("\n".join(lines).encode()).hexdigest()}
    base_path.write_text(json.dumps(new_base, indent=2), encoding="utf-8")
    if violations:
        for v in violations:
            print(f"  - {v}")
        return _verdict(1, f"append-only VIOLATION in {pdir.name}")
    return _verdict(0, f"append-only intact ({', '.join(f.name for f in files) or 'no ledgers yet'}); baseline updated")


def c_writeback(a) -> int:
    """Rule 11: a session must write back. Pass if a dated notebook entry names the slug today,
    or a HUB-WRITEBACK-PENDING block is queued in the project log."""
    nb = LAB / "notebook"
    has_nb = nb.exists() and any(
        _today() in p.name and a.slug in p.read_text(encoding="utf-8-sig") for p in nb.glob("*.md"))
    pdir = _project_dir(a.slug)
    pending = bool(pdir and (pdir / "EXPERIMENT_LOG.md").exists()
                   and "HUB-WRITEBACK-PENDING" in (pdir / "EXPERIMENT_LOG.md").read_text(encoding="utf-8-sig"))
    if has_nb or pending:
        return _verdict(0, f"write-back present for {a.slug} ({'notebook' if has_nb else 'pending block'})")
    return _verdict(2, f"no dated write-back for {a.slug} today — run tools/hub_writeback.py before ending (rule 11)")


def main() -> int:
    ap = argparse.ArgumentParser(description="mechanical lifecycle guards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("spawn", c_spawn), ("full-run", c_full_run), ("frozen", c_frozen),
                     ("writeback", c_writeback)]:
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=fn)
    p = sub.add_parser("append-only")
    p.add_argument("target", help="slug or project path")
    p.set_defaults(fn=c_append_only)
    p = sub.add_parser("state")
    p.add_argument("slug")
    p.add_argument("frm", metavar="from")
    p.add_argument("to")
    p.set_defaults(fn=c_state)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
