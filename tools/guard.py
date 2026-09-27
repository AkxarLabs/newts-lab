"""Mechanical lifecycle guards — the lock on the door behind the prose procedures.

    uv run --with pyyaml python tools/guard.py spawn <slug>
    uv run --with pyyaml python tools/guard.py full-run <slug> [--config <yaml> --planned-runs N --planned-minutes M --reserve --reservation-label L]
    uv run --with pyyaml python tools/guard.py release-full-run <slug> <reservation-id>
    uv run --with pyyaml python tools/guard.py frozen <slug>
    uv run --with pyyaml python tools/guard.py state <slug> <from> <to>
    uv run --with pyyaml python tools/guard.py append-only <slug | project-path>
    uv run --with pyyaml python tools/guard.py writeback <slug>
    uv run --with pyyaml python tools/guard.py evolve <slug>
    uv run --with pyyaml python tools/guard.py decisions <slug> [--strict]
    uv run --with pyyaml python tools/guard.py plan-trace <slug>
    uv run --with pyyaml python tools/guard.py finalization <slug> [--pi-approved]

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
import os
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow  # noqa: E402 — the one definition of the lifecycle (workflow/stages.yaml)

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
        if len(cells) < len(_COLS) or cells[0] in ("ID", "", "—") or set(cells[0]) <= {"-"}:
            continue
        out.append(dict(zip(_COLS, cells)))
    return out


def _row(slug: str) -> dict | None:
    return next((r for r in _registry_rows() if r["id"] == slug), None)


def _projects_root() -> Path:
    root = ((_load_yaml(LAB / "config.yaml").get("lab") or {}).get("projects_root")) \
        or "../newts-lab-projects"
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
    if not re.search(r"gate ?1 approved|PI Gate 1|gate1_approved", prop.read_text(encoding="utf-8-sig"), re.I):
        return _verdict(1, f"Gate 1 not recorded in studies/{a.slug}/proposal.md — needs PI sign-off before spawn")
    row = _row(a.slug)
    pd = _project_dir(a.slug, row)
    if pd and any(p.is_dir() for p in pd.glob("runs/*")):   # a run is a dir; ignore the template's runs/README.md
        return _verdict(1, f"{pd.name} already has runs — refusing to overwrite (reused slug?)")
    if row and row["state"] != "proposal":
        return _verdict(2, f"Gate 1 present, but registry state is '{row['state']}' (expected 'proposal')")
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
        stg = str((_load_yaml(Path(cfg_path)) or {}).get("stage") or "").upper()
        if stg and stg != "FULL":
            return _verdict(0, f"config stage is {stg} (not FULL) — no Gate-2 envelope needed")
    env = _load_yaml(pdir / "control.yaml").get("gate2_envelope") or {}
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
    if not legal_transition(a.frm, a.to):
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


def _knowledge_has(name: str, slug: str) -> bool:
    """A hub knowledge file carries a line promoted for this slug (hub_writeback tags them `(slug)`)."""
    f = LAB / "knowledge" / name
    return f.exists() and f"({slug})" in f.read_text(encoding="utf-8-sig")


def _notes_section_filled(pdir: Path | None, needle: str) -> bool:
    """True if the project NOTES.md section whose heading contains `needle` has a real line —
    not the `*(none yet)*` placeholder and not the example HTML comment (single- or multi-line)."""
    notes = (pdir / "NOTES.md") if pdir else None
    if not notes or not notes.exists():
        return False
    in_sec, in_comment = False, False
    for ln in notes.read_text(encoding="utf-8-sig").splitlines():
        s = ln.strip()
        if in_comment:
            in_comment = "-->" not in s
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s
            continue
        if s.startswith("## "):
            in_sec = needle.lower() in s.lower()
        elif in_sec and s and "none yet" not in s.lower() and not s.startswith("#"):
            return True
    return False


def c_evolve(a) -> int:
    """The triggered write-back operators (rule 11) fired where the state demands them: a KILL must
    leave a CORRECTION (a failed direction + reason, so the next project doesn't retry it), and a
    project that reached the results half should leave a RECIPE (a settled keeper). A DIRECTION
    (feasible next thread) is opportunistic, never forced. Read-only."""
    row = _row(a.slug)
    if not row:
        return _verdict(2, f"no registry row for {a.slug} — nothing to check")
    state = (row.get("state") or "").lower()
    pdir = _project_dir(a.slug, row)
    correction = _knowledge_has("FAILURES.md", a.slug) or _notes_section_filled(pdir, "abandoned")
    recipe = _knowledge_has("FINDINGS.md", a.slug) or _notes_section_filled(pdir, "worked")
    # A CORRECTION is only owed when something was actually TRIED — i.e. a project exists. A kill at
    # triage (no project: non-novel / out of scope) is recorded in IDEA.md + OPEN-QUESTIONS, never in
    # FAILURES.md (that file is for tried-and-failed only), so it must not be forced here.
    if state == "killed" and pdir and not correction:
        return _verdict(1, f"{a.slug} is killed after work began but no CORRECTION recorded — add a "
                           "FAILURES.md entry (or NOTES.md 'Tried & abandoned') so the next project "
                           "doesn't retry it")
    if state in ("analysis", "writing", "internal-review", "final") and not recipe:
        return _verdict(2, f"{a.slug} reached {state} but no RECIPE distilled — add a FINDINGS.md entry "
                           "(or NOTES.md 'What worked / settled here')")
    return _verdict(0, f"write-back operators satisfied for {a.slug} (state={state}; "
                       f"correction={'y' if correction else '—'}, recipe={'y' if recipe else '—'})")


def c_append_only(a) -> int:
    """Verify the append-only ledgers were not rewritten since the last call (history removed or
    a prior line edited). Records a per-project baseline; call it after each ledger append."""
    pdir, files = _ledger_files(a.target)
    if not pdir:
        return _verdict(1, f"no project for {a.target}")
    base_dir = pdir / ".guard"
    base_dir.mkdir(exist_ok=True)
    base_path = base_dir / "ledger-baseline.json"
    try:
        base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        base = {}   # corrupt/unreadable baseline -> re-baseline (fail-safe), like _load_yaml
    violations, new_base, present = [], {}, set()
    for f in files:
        present.add(f.name)
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
    # a baselined ledger that has VANISHED entirely is the most extreme history removal
    for name in base:
        if name not in present:
            violations.append(f"{name}: ledger file deleted (history removed)")
    if violations:
        for v in violations:
            print(f"  - {v}")
        # Do NOT overwrite the baseline on a violation: that would launder the tamper so a re-run
        # reports clean and loses the trail. Keep the prior baseline until a human resolves it.
        return _verdict(1, f"append-only VIOLATION in {pdir.name}")
    tmp = base_path.parent / (base_path.name + ".tmp")   # atomic write (no half-written baseline on a race)
    tmp.write_text(json.dumps(new_base, indent=2), encoding="utf-8")
    tmp.replace(base_path)
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


# grammar for a machine-checkable Revisit predicate: FN(...) OP value [within tol of ref]
_PRED_RE = re.compile(r"^(metric|best|delta|status)\s*\([^)]*\)\s*(<=|>=|==|!=|<|>|within)\b", re.I)


def _decision_blocks(text: str):
    """Yield (D-NNN, block_body) for each '## D-NNN' section of a decisions.md."""
    parts = re.split(r"(?m)^##\s+(D-\d+)\b", text)
    for i in range(1, len(parts), 2):
        yield parts[i], (parts[i + 1] if i + 1 < len(parts) else "")


def _index_status(text: str) -> dict:
    """Map D-NNN -> status (lowercased) from the '## Decision index' table."""
    out = {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"D-\d+", cells[0] or ""):
            out[cells[0]] = (cells[2] if len(cells) > 2 else "").lower()
    return out


def c_decisions(a) -> int:
    """Every SETTLED, non-headline decision must carry a machine-checkable **Revisit predicate:**
    so an explore loop's revisit trigger is parseable, not free prose. (The overseer still
    adjudicates whether it actually fired; this only shape-checks the trigger.) Headline:yes
    decisions are exempt; OPEN decisions are resolved by a pilot, not revisited. Target-driven
    (/compete) projects have no headline-hypothesis boundary and never run /scope — no decisions.md
    is expected, so they're exempt entirely."""
    row = _row(a.slug)
    pdir = _project_dir(a.slug, row)
    target = (_load_yaml(pdir / "control.yaml").get("target") or {}) if pdir else {}
    if bool(target.get("active")):
        return _verdict(0, f"target-driven — no decisions.md expected for {a.slug}")
    dfile = HUB / "studies" / a.slug / "decisions.md"
    if not dfile.exists():
        return _verdict(2, f"no decisions.md at studies/{a.slug}/ — run /scope first")
    text = dfile.read_text(encoding="utf-8-sig")
    status = _index_status(text)
    missing, malformed, checked = [], [], 0
    for dnnn, body in _decision_blocks(text):
        hm = re.search(r"\*\*Headline:\*\*\s*(yes|no)\b", body, re.I)
        if not hm or hm.group(1).lower() != "no":
            continue  # unfilled placeholder, or Headline:yes (exempt — it escalates)
        if status.get(dnnn, "settled") == "open":
            continue  # OPEN → resolved by a pilot, not revisited
        checked += 1
        pm = re.search(r"(?m)^\s*\*\*Revisit predicate:\*\*\s*(.+?)\s*$", body)
        pred = pm.group(1).strip().strip("`").strip() if pm else ""
        if pred.startswith("<!--"):
            pred = ""  # unfilled HTML-comment placeholder
        if not pred:
            missing.append(dnnn)
        elif not _PRED_RE.match(pred):
            malformed.append(dnnn)
    if malformed:
        for d in malformed:
            print(f"  - {d}: **Revisit predicate** present but ungrammatical (want FN(...) OP value)")
        return _verdict(1, f"{len(malformed)} malformed Revisit predicate(s) in studies/{a.slug}/decisions.md")
    if missing:
        for d in missing:
            print(f"  - {d}: settled Headline:no decision has no machine **Revisit predicate:**")
        return _verdict(1 if getattr(a, "strict", False) else 2,
                        f"{len(missing)} settled non-headline decision(s) without a machine predicate")
    return _verdict(0, f"all {checked} settled non-headline decision(s) carry a well-formed Revisit predicate")


def _experiment_rows(text: str):
    """Yield (id, full_row_text) for each PLAN.md Experiments-table data row. Id-convention-agnostic
    (theory/simulation projects may label rows E-002/run-002, not just exp-002), and the whole row is
    returned so a Headline-change / D-NNN marker is seen no matter which column it sits in."""
    in_tbl = False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("| ID ") and "Question" in ln and "Stage" in ln:
            in_tbl = True
            continue
        if in_tbl:
            if not s.startswith("|"):
                break
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not cells or set("".join(cells)) <= {"-", ":", " "}:
                continue
            if cells[0]:                       # any non-empty id cell, not just 'exp-*'
                yield cells[0], " ".join(cells)


def c_plan_trace(a) -> int:
    """Every non-baseline PLAN.md experiment row must trace to an authorized origin: a decisions.md
    D-NNN, an `(expand Rn)` tag backed by a Re-planning-log row, or the exp-001 seed. A row carrying
    a `Headline-change: yes` marker is BLOCKED regardless of any D-NNN citation (a decisions.md
    decision is not a /propose origin — a headline change must re-enter /propose)."""
    pdir = _project_dir(a.slug)
    if not pdir:
        return _verdict(1, f"no project dir for {a.slug}")
    plan = pdir / "PLAN.md"
    if not plan.exists():
        return _verdict(1, f"no PLAN.md in {pdir.name}")
    text = plan.read_text(encoding="utf-8-sig")
    dfile = HUB / "studies" / a.slug / "decisions.md"
    dids = set(re.findall(r"\bD-\d+\b", dfile.read_text(encoding="utf-8-sig"))) if dfile.exists() else set()
    replan = text.split("## Re-planning log", 1)[1] if "## Re-planning log" in text else ""
    has_expand_log = bool(re.search(r"frontier_expand|decision_revisit", replan))
    rows = list(_experiment_rows(text))
    untraceable, blocked = [], []
    for i, (rid, blob) in enumerate(rows):
        # A Headline-change:yes row is ALWAYS blocked (even the seed) — it must re-enter /propose, and a
        # decisions.md D-NNN is not a /propose origin. Classified BEFORE the seed/traced short-circuits,
        # and scanned over the WHOLE row so the marker can't hide in an unscanned column.
        if re.search(r"headline[-\s]?change:\s*yes", blob, re.I):
            blocked.append(rid)
            continue
        if i == 0 or re.fullmatch(r"[a-z]*[-_]?0*1", rid, re.I):
            continue  # the seed/baseline row (first row, or an *-001 id) needs no D-NNN origin
        traced = any(d in blob for d in dids) or \
            (bool(re.search(r"\(expand\s+R\d+\)", blob, re.I)) and has_expand_log)
        if not traced:
            untraceable.append(rid)
    if blocked:
        for r in blocked:
            print(f"  - {r}: Headline-change:yes row with no /propose origin — must re-enter /propose")
        return _verdict(1, f"{len(blocked)} headline-changing PLAN.md row(s) bypassing /propose in {a.slug}")
    if untraceable:
        for r in untraceable:
            print(f"  - {r}: no D-NNN / (expand Rn) origin — provenance undocumented")
        return _verdict(2, f"{len(untraceable)} PLAN.md row(s) with undocumented origin in {a.slug}")
    return _verdict(0, f"all {len(rows)} PLAN.md experiment row(s) trace to an authorized origin")


# Gate-3 approval marker (mirrors the Gate-1 marker convention in proposal.md), recorded by the PI
# in the meta-review after /review-paper accepts.
_GATE3_RE = re.compile(r"gate ?3 approved|PI Gate 3|gate3_approved|Gate 3:\s*approved", re.I)


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
    target = (_load_yaml(pdir / "control.yaml").get("target") or {}) if pdir else {}
    target_driven = bool(target.get("active"))
    if target_driven:
        if state != "active":
            return _verdict(1, f"target-driven {a.slug} is '{state}', not 'active' — nothing to finalize")
    elif state != "internal-review":
        return _verdict(1, f"{a.slug} is '{state}', not 'internal-review' — /review-paper must accept first")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="mechanical lifecycle guards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("spawn", c_spawn), ("frozen", c_frozen),
                     ("writeback", c_writeback), ("evolve", c_evolve), ("plan-trace", c_plan_trace)]:
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=fn)
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
    p = sub.add_parser("decisions")
    p.add_argument("slug")
    p.add_argument("--strict", action="store_true", help="treat a missing predicate as BLOCKED")
    p.set_defaults(fn=c_decisions)
    p = sub.add_parser("finalization")
    p.add_argument("slug")
    p.add_argument("--pi-approved", action="store_true", dest="pi_approved",
                   help="the PI authorizing Gate 3 directly in this session")
    p.set_defaults(fn=c_finalization)
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
