"""Mechanical lifecycle guards — the lock on the door behind the prose procedures.

    uv run --with pyyaml python tools/guard.py spawn <slug>
    uv run --with pyyaml python tools/guard.py full-run <slug> [--config <yaml> --planned-runs N --planned-minutes M --reserve --reservation-label L]
    uv run --with pyyaml python tools/guard.py release-full-run <slug> <reservation-id>
    uv run --with pyyaml python tools/guard.py frozen <slug>
    uv run --with pyyaml python tools/guard.py state <slug> <from> <to>
    uv run --with pyyaml python tools/guard.py finalization <slug> [--pi-approved]
    uv run --with pyyaml python tools/guard.py <check> …          # every checks/<check>.py (see --list)
    uv run --with pyyaml python tools/guard.py --list

The gates and transitions above are built in. The lab's other mechanical rules are CHECKS, one file each
in checks/ (append-only, writeback, evolve, decisions, plan-trace, and whatever the lab adds): a module with
NAME, add_args(parser) and run(args, guard) → exit code, named by the rules in workflow/rules.yaml.

Each command validates a precondition/postcondition the protocol otherwise only states in
prose, so unattended autonomy doesn't depend on perfect agent memory. Idempotent and read-only
(except `append-only`, which records a per-project baseline under `<project>/.guard/`).

Exit codes:  0 = OK to proceed · 1 = BLOCKED (do not proceed) · 2 = WARNING (proceed with care).

The guard is the lock; the skills are still the human-readable procedures. A guard never grants a
gate — it only confirms one is already recorded, or refuses an unsafe transition.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
LAB = HUB / "lab"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow  # noqa: E402 — the one definition of the lifecycle (workflow/stages.yaml)
from markers import GATE1_RE, GATE3_RE  # noqa: E402 — the one definition of the PI's marks
import labfiles  # noqa: E402 — the lab's files, read one way (tools/labfiles.py)

LIFECYCLE = workflow.lifecycle(HUB)
# documented back-edges (the paper-phase round-trip) + forward steps are legal; park/kill anytime.
BACK_EDGES = workflow.back_edges(HUB)
SIDE_STATES = tuple(workflow.side_states(HUB))   # parked, killed


def legal_transition(frm: str, to: str) -> bool:
    """The one transition oracle: is a registry state move frm→to legal? park/kill are reachable from
    ANY state; a same-state re-assert (frm==to, e.g. an active→active timestamp bump) is an idempotent
    no-op, never an illegal move; otherwise it must be a single forward step in LIFECYCLE or a
    documented BACK_EDGE. Pure (no I/O), so the write-back tools import and reuse it instead of
    re-encoding the table. (Un-parking a `parked`/`killed` row is a deliberate PI-manual action — the
    oracle refuses it here so it can't happen silently in an automated write-back.)"""
    if to in SIDE_STATES or frm == to:
        return True
    return (frm in LIFECYCLE and to in LIFECYCLE
            and (LIFECYCLE.index(to) == LIFECYCLE.index(frm) + 1 or (frm, to) in BACK_EDGES))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _registry_rows() -> list[dict]:
    return labfiles.registry_rows(HUB)


def _row(slug: str) -> dict | None:
    return labfiles.row(HUB, slug)


def _projects_root() -> Path:
    return labfiles.projects_root(HUB)


def _project_dir(slug: str, row: dict | None = None) -> Path | None:
    return labfiles.project_dir(HUB, slug, row)


def _verdict(code: int, msg: str) -> int:
    label = {0: "OK", 1: "BLOCKED", 2: "WARN"}[code]
    print(f"[guard] {label}: {msg}")
    return code


# ── commands ──────────────────────────────────────────────────────────────────

def c_spawn(a) -> int:
    """Gate 1 must be recorded before /spawn-project spends compute. The paper path records it in
    proposal.md; a target-driven (/compete) project has no proposal — its Gate-1 compute authorization
    is the /compete interview, marked in IDEA.md — so accept that as the equivalent Gate-1 record."""
    prop = HUB / "studies" / a.slug / "proposal.md"
    if not prop.exists():
        # Target-driven fallback: no proposal, but IDEA.md carries BOTH the `N/A (target-driven)` record
        # AND the /compete Gate-1 (compute authorization) marker → the same mechanical stop, satisfied.
        idea = HUB / "studies" / a.slug / "IDEA.md"
        if idea.exists():
            itext = idea.read_text(encoding="utf-8-sig")
            if re.search(r"N/A \(target-driven\)", itext) \
                    and re.search(r"gate\s*1.*(approved|authorized)", itext, re.I):
                return _verdict(0, f"target-driven Gate-1 (compute authorization) marker found — "
                                   f"clear to /spawn-project {a.slug}")
        return _verdict(1, f"no proposal at studies/{a.slug}/proposal.md — run /propose first")
    if not GATE1_RE.search(prop.read_text(encoding="utf-8-sig")):
        return _verdict(1, f"Gate 1 not recorded in studies/{a.slug}/proposal.md — needs PI sign-off before spawn")
    row = _row(a.slug)
    pd = _project_dir(a.slug, row)
    if pd and any(p.is_dir() for p in pd.glob("runs/*")):   # a run is a dir; ignore the template's runs/README.md
        return _verdict(1, f"{pd.name} already has runs — refusing to overwrite (reused slug?)")
    at = workflow.gate_state(1, HUB)
    if row and row["state"] != at:
        return _verdict(2, f"Gate 1 present, but registry state is '{row['state']}' (expected '{at}')")
    return _verdict(0, f"Gate 1 recorded — clear to /spawn-project {a.slug}")


# A guard reservation (a sweep about to launch N FULL runs whose rows aren't in the registry yet)
# is presumed abandoned after this window, so a crashed sweep can't wedge the envelope forever.
_RESV_TTL_SECONDS = 24 * 3600
_RESV_REL = ".guard/full-run-reservations.jsonl"


def _full_run_rows(pdir: Path) -> tuple[int, float]:
    """Consumed FULL capacity in the project's runs/registry.jsonl: (row count, wall-minutes summed).
    Every FULL row is one launch that drew on the envelope; wall_seconds (when present) → minutes."""
    reg = pdir / "runs" / "registry.jsonl"
    count, wall = 0, 0.0
    if reg.exists():
        for line in reg.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a partial/corrupt line — skip, never crash the gate
            if str(row.get("stage", "")).upper() == "FULL":
                count += 1
                ws = row.get("wall_seconds")
                if isinstance(ws, (int, float)):
                    wall += ws / 60.0
    return count, wall


def _active_reservations(pdir: Path) -> list[dict]:
    """Reservations still holding capacity: status 'active' and younger than the TTL (a crashed
    sweep's reservation ages out rather than wedging the envelope)."""
    f = pdir / _RESV_REL
    out: list[dict] = []
    if not f.exists():
        return out
    now = time.time()
    for line in f.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(r.get("status", "active")).lower() != "active":
            continue
        ts = r.get("ts")
        if isinstance(ts, (int, float)) and (now - ts) > _RESV_TTL_SECONDS:
            continue  # stale — presumed abandoned
        out.append(r)
    return out


def _full_run_accounting(env: dict, pdir: Path, planned_runs, planned_minutes) -> tuple[bool, str]:
    """Does a request of `planned_runs` FULL runs, each budgeted `planned_minutes`, still fit the
    signed envelope given prior completed FULL rows + active reservations? Returns (ok, message).
    A cap of 0/None means 'unbounded on that axis' (the non-empty-envelope check already ran)."""
    done_count, done_minutes = _full_run_rows(pdir)
    resv = _active_reservations(pdir)
    resv_runs = sum(int(r.get("planned_runs") or 0) for r in resv)
    resv_minutes = sum(int(r.get("planned_runs") or 0) * float(r.get("planned_minutes") or 0) for r in resv)
    req_runs = int(planned_runs or 1)
    req_per = float(planned_minutes or 0)
    req_total = req_runs * req_per
    full_cap = int(env.get("full_runs") or 0)
    per_cap = float(env.get("per_run_max_minutes") or 0)
    total_cap = float(env.get("total_max_minutes") or 0)
    if per_cap and req_per > per_cap:
        return False, f"per-run budget {req_per:g}m exceeds per_run_max_minutes={per_cap:g}"
    if full_cap and (done_count + resv_runs + req_runs) > full_cap:
        return False, (f"would use {done_count + resv_runs + req_runs} FULL run(s) "
                       f"(done {done_count} + reserved {resv_runs} + requested {req_runs}) > full_runs={full_cap}")
    if total_cap and (done_minutes + resv_minutes + req_total) > total_cap:
        return False, (f"would book ~{done_minutes + resv_minutes + req_total:g}m "
                       f"(done {done_minutes:g} + reserved {resv_minutes:g} + requested {req_total:g}) "
                       f"> total_max_minutes={total_cap:g}")
    return True, (f"fits envelope (runs {done_count}+{resv_runs}+{req_runs}/{full_cap or '∞'}, "
                  f"~{done_minutes + resv_minutes + req_total:g}m/{total_cap or '∞'})")


def _reserve_full_run(pdir: Path, label, planned_runs, planned_minutes) -> str:
    """Append an active reservation so a *concurrent* sweep can't double-book capacity between now and
    when this sweep's rows land in the registry. Released by `release-full-run` (or aged out by TTL)."""
    d = pdir / ".guard"
    d.mkdir(exist_ok=True)
    rid = re.sub(r"[^A-Za-z0-9._-]", "_", f"{time.strftime('%Y%m%d-%H%M%S')}-{label or 'full'}")
    rec = {"id": rid, "ts": time.time(), "label": label, "planned_runs": int(planned_runs or 1),
           "planned_minutes": float(planned_minutes or 0), "expires_at": time.time() + _RESV_TTL_SECONDS,
           "status": "active"}
    with (pdir / _RESV_REL).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return rid


def c_full_run(a) -> int:
    """A FULL run needs a signed, unexpired, non-empty gate2_envelope — else fresh PI approval. When the
    caller declares its intent (--planned-runs/--planned-minutes), also account prior FULL rows + active
    reservations against the envelope caps (and optionally --reserve capacity for a sweep)."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    # Convenience: a named config whose stage isn't FULL needs no Gate 2 at all.
    cfg_path = getattr(a, "config", None)
    if cfg_path:
        stg = str((labfiles.load_yaml(Path(cfg_path)) or {}).get("stage") or "").upper()
        if stg and stg != "FULL":
            return _verdict(0, f"config stage is {stg} (not FULL) — no Gate-2 envelope needed")
    env = labfiles.load_yaml(pdir / "control.yaml").get("gate2_envelope") or {}
    if not env.get("pi_signed"):
        return _verdict(1, "no signed gate2_envelope — every FULL run needs fresh PI approval")
    exp = str(env.get("expires") or "").strip()
    if exp and exp.lower() not in ("null", "none") and exp < _today():
        return _verdict(1, f"gate2_envelope expired ({exp}) — needs re-signing before any FULL run")
    if not any(env.get(k) for k in ("full_runs", "per_run_max_minutes", "total_max_minutes")):
        return _verdict(1, "gate2_envelope authorizes nothing (all caps 0/null) — FULL needs PI approval")
    planned_runs = getattr(a, "planned_runs", None)
    planned_minutes = getattr(a, "planned_minutes", None)
    if planned_runs is None and planned_minutes is None:
        return _verdict(0, f"signed gate2_envelope covers FULL (full_runs={env.get('full_runs')}, expires={exp or 'n/a'})")
    ok, msg = _full_run_accounting(env, pdir, planned_runs, planned_minutes)
    if not ok:
        return _verdict(1, f"gate2_envelope exceeded — {msg}")
    if getattr(a, "reserve", False):
        rid = _reserve_full_run(pdir, getattr(a, "reservation_label", None), planned_runs, planned_minutes)
        print(f"[guard] reserved FULL capacity: {rid}")
    return _verdict(0, f"signed gate2_envelope covers this FULL request — {msg}")


def c_release_full_run(a) -> int:
    """Mark a FULL-run reservation released (its rows have landed in the registry, so the reservation
    would otherwise double-count). Idempotent; a missing/unknown id is not an error."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    f = pdir / _RESV_REL
    if not f.exists():
        return _verdict(0, "no reservations file — nothing to release")
    out, released = [], False
    for line in f.read_text(encoding="utf-8-sig").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            r = json.loads(s)
        except json.JSONDecodeError:
            out.append(s)
            continue
        if r.get("id") == a.reservation_id and str(r.get("status", "active")).lower() == "active":
            r["status"] = "released"
            released = True
        out.append(json.dumps(r))
    tmp = f.parent / (f.name + ".tmp")
    tmp.write_text("\n".join(out) + ("\n" if out else ""), encoding="utf-8")
    tmp.replace(f)
    return _verdict(0, f"released reservation {a.reservation_id}" if released
                   else f"reservation {a.reservation_id} not active/found (already released?)")


def c_frozen(a) -> int:
    """The frozen set must stay frozen: eval_frozen true + the PI-owned blocks present."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    ctl = labfiles.load_yaml(pdir / "control.yaml")
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
    if a.to in SIDE_STATES:
        return _verdict(0, f"{a.frm}→{a.to} (park/kill is allowed from any state)")
    if not legal_transition(a.frm, a.to):
        return _verdict(1, f"{a.frm}→{a.to} is not a legal lifecycle transition")
    return _verdict(0, f"{a.frm}→{a.to} is legal — now update REGISTRY.md to match")


# Gate-3 approval marker (markers.GATE3_RE), recorded by the PI in the meta-review after
# /review-paper accepts.
_GATE3_RE = GATE3_RE


def _gate3_marker(slug: str) -> bool:
    """True if a PI Gate-3 approval marker is recorded for a paper project (in any review file, or a
    gate3-approval.md note)."""
    paper = HUB / "studies" / slug / "paper"
    reviews = paper / "reviews"
    if reviews.exists():
        for f in reviews.rglob("*.md"):
            try:
                if _GATE3_RE.search(f.read_text(encoding="utf-8-sig")):
                    return True
            except OSError:
                continue
    note = paper / "gate3-approval.md"
    if not note.exists():
        return False
    text = note.read_text(encoding="utf-8-sig")
    if re.search(r"signed_via:\s*campaign:", text):   # delegated by a campaign: valid only while it still is
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import gate3  # noqa: PLC0415
        return gate3.delegation_valid(HUB, slug)[0]
    return bool(_GATE3_RE.search(text))


def c_finalization(a) -> int:
    """Gate 3 is NEVER delegated. Block finalization unless: (1) not in a headless/launched agent
    (AUTOSCIENTIST_NO_GATE3 unset), (2) the registry state is right (`internal-review` for a paper,
    or `active` + `target.active` for a target-driven project), and (3) a PI Gate-3 approval is
    recorded (a marker in the meta-review / a target's `final_run_id`) or `--pi-approved` is passed in
    a live PI session. A guard never grants the gate — it refuses when one isn't recorded."""
    if os.environ.get("AUTOSCIENTIST_NO_GATE3"):
        return _verdict(1, "AUTOSCIENTIST_NO_GATE3 is set — Gate 3 is never delegated. A launched/headless "
                        "agent stops its pipeline at internal-review; finalization is done by the PI in a session.")
    row = _row(a.slug)
    if not row:
        return _verdict(1, f"no registry row for {a.slug}")
    state = (row.get("state") or "").lower()
    pdir = _project_dir(a.slug, row)
    target = (labfiles.load_yaml(pdir / "control.yaml").get("target") or {}) if pdir else {}
    target_driven = bool(target.get("active"))
    if target_driven:
        track = workflow.tracks(HUB).get("target") or []
        ready = track[-2] if len(track) >= 2 else None      # the state a target-driven project finalizes from
        if state != ready:
            return _verdict(1, f"target-driven {a.slug} is '{state}', not '{ready}' — nothing to finalize")
    elif state != workflow.gate_state(3, HUB):
        return _verdict(1, f"{a.slug} is '{state}', not '{workflow.gate_state(3, HUB)}' — /review-paper must accept first")
    if getattr(a, "pi_approved", False):
        return _verdict(0, f"Gate 3 authorized by --pi-approved for {a.slug} — clear to /finalize")
    if target_driven:
        if str(target.get("final_run_id") or "").strip():
            return _verdict(0, f"target final output selected (target.final_run_id) for {a.slug} — clear to finalize")
        return _verdict(1, f"no target.final_run_id selected for {a.slug} and no --pi-approved — the PI selects "
                        "the final output (Gate 3)")
    if _gate3_marker(a.slug):
        return _verdict(0, f"Gate 3 approval recorded for {a.slug} — clear to /finalize")
    return _verdict(1, f"no Gate 3 approval recorded (meta-review marker / gate3-approval.md) for {a.slug} and "
                    "no --pi-approved — finalization needs explicit PI sign-off")


# ── checks: one file each in checks/ (this code's, plus the lab's own) ───────────────────────────
def _load_checks() -> dict:
    import importlib.util  # noqa: PLC0415
    out = {}
    roots = dict.fromkeys([Path(__file__).resolve().parents[1] / "checks", HUB / "checks"])
    for root in roots:
        for f in sorted(root.glob("*.py")) if root.is_dir() else []:
            spec = importlib.util.spec_from_file_location(f"newts_check_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
            except Exception as e:  # noqa: BLE001 — a broken check is reported, never fatal to the guard
                print(f"[guard] WARN: checks/{f.name} did not load: {e}", file=sys.stderr)
                continue
            if callable(getattr(mod, "run", None)) and callable(getattr(mod, "add_args", None)):
                out[getattr(mod, "NAME", f.stem.replace("_", "-"))] = mod
    return out


CHECKS = _load_checks()
_SELF = sys.modules[__name__]
for _name, _mod in CHECKS.items():   # c_<name>(args) — the same call shape as the built-in commands
    globals()["c_" + _name.replace("-", "_")] = (lambda m: (lambda a: m.run(a, _SELF)))(_mod)


def main() -> int:
    if "--list" in sys.argv[1:]:
        print("built in: spawn, full-run, release-full-run, frozen, state, finalization")
        for name, mod in CHECKS.items():
            print(f"check:    {name:<14} {((mod.__doc__ or '').strip().splitlines() or [''])[0]}")
        return 0
    ap = argparse.ArgumentParser(description="mechanical lifecycle guards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("spawn", c_spawn), ("frozen", c_frozen)]:
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=fn)
    for name, mod in CHECKS.items():
        p = sub.add_parser(name, help=((mod.__doc__ or "").strip().splitlines() or [""])[0])
        mod.add_args(p)
        p.set_defaults(fn=globals()["c_" + name.replace("-", "_")])
    p = sub.add_parser("full-run")
    p.add_argument("slug")
    p.add_argument("--config", default=None, help="experiment yaml (skips the gate if its stage isn't FULL)")
    p.add_argument("--planned-runs", type=int, default=None, dest="planned_runs",
                   help="how many FULL runs this request launches (enables envelope accounting)")
    p.add_argument("--planned-minutes", type=float, default=None, dest="planned_minutes",
                   help="per-run budget in minutes (checked vs per_run_max_minutes; ×runs vs total)")
    p.add_argument("--reserve", action="store_true", help="reserve the accounted capacity (for a sweep)")
    p.add_argument("--reservation-label", default=None, dest="reservation_label")
    p.set_defaults(fn=c_full_run)
    p = sub.add_parser("release-full-run")
    p.add_argument("slug")
    p.add_argument("reservation_id")
    p.set_defaults(fn=c_release_full_run)
    p = sub.add_parser("finalization")
    p.add_argument("slug")
    p.add_argument("--pi-approved", action="store_true", dest="pi_approved",
                   help="the PI authorizing Gate 3 directly in this session")
    p.set_defaults(fn=c_finalization)
    p = sub.add_parser("state")
    p.add_argument("slug")
    p.add_argument("frm", metavar="from")
    p.add_argument("to")
    p.set_defaults(fn=c_state)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
