"""Mechanical lifecycle guards — the lock on the door behind the prose procedures.

    uv run --with pyyaml python tools/guard.py spawn <slug>
    uv run --with pyyaml python tools/guard.py full-run <slug>
    uv run --with pyyaml python tools/guard.py frozen <slug>
    uv run --with pyyaml python tools/guard.py state <slug> <from> <to>
    uv run --with pyyaml python tools/guard.py append-only <slug | project-path>
    uv run --with pyyaml python tools/guard.py writeback <slug>
    uv run --with pyyaml python tools/guard.py evolve <slug>
    uv run --with pyyaml python tools/guard.py decisions <slug> [--strict]
    uv run --with pyyaml python tools/guard.py plan-trace <slug>

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
    """Gate 1 must be recorded before /spawn-project spends compute."""
    prop = HUB / "studies" / a.slug / "proposal.md"
    if not prop.exists():
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
    decisions are exempt; OPEN decisions are resolved by a pilot, not revisited."""
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


def main() -> int:
    ap = argparse.ArgumentParser(description="mechanical lifecycle guards")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("spawn", c_spawn), ("full-run", c_full_run), ("frozen", c_frozen),
                     ("writeback", c_writeback), ("evolve", c_evolve), ("plan-trace", c_plan_trace)]:
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=fn)
    p = sub.add_parser("decisions")
    p.add_argument("slug")
    p.add_argument("--strict", action="store_true", help="treat a missing predicate as BLOCKED")
    p.set_defaults(fn=c_decisions)
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
