"""guard.py evolve — The write-back operators fired where the state demands them (hard rule knowledge-write-back).

A check for tools/guard.py: `uv run --with pyyaml python tools/guard.py evolve …`. It gets the parsed arguments and the guard module (HUB, LAB, labfiles, _row, _project_dir, _verdict)
and returns the exit code: 0 = OK · 1 = BLOCKED · 2 = WARN."""

from __future__ import annotations

from pathlib import Path

NAME = "evolve"


def add_args(p) -> None:
    p.add_argument("slug")


def _knowledge_has(name: str, slug: str, g) -> bool:
    """A hub knowledge file carries a line promoted for this slug (hub_writeback tags them `(slug)`)."""
    f = g.LAB / "knowledge" / name
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


def run(a, g) -> int:
    """The triggered write-back operators (rule 11) fired where the state demands them: a KILL must
    leave a CORRECTION (a failed direction + reason, so the next project doesn't retry it), and a
    project that reached the results half should leave a RECIPE (a settled keeper). A DIRECTION
    (feasible next thread) is opportunistic, never forced. Read-only."""
    row = g._row(a.slug)
    if not row:
        return g._verdict(2, f"no registry row for {a.slug} — nothing to check")
    state = (row.get("state") or "").lower()
    pdir = g._project_dir(a.slug, row)
    correction = _knowledge_has("FAILURES.md", a.slug, g) or _notes_section_filled(pdir, "abandoned")
    recipe = _knowledge_has("FINDINGS.md", a.slug, g) or _notes_section_filled(pdir, "worked")
    # A CORRECTION is only owed when something was actually TRIED — i.e. a project exists. A kill at
    # triage (no project: non-novel / out of scope) is recorded in IDEA.md + OPEN-QUESTIONS, never in
    # FAILURES.md (that file is for tried-and-failed only), so it must not be forced here.
    if state == "killed" and pdir and not correction:   # a kill (not a park) owes a CORRECTION
        return g._verdict(1, f"{a.slug} is killed after work began but no CORRECTION recorded — add a "
                           "FAILURES.md entry (or NOTES.md 'Tried & abandoned') so the next project "
                           "doesn't retry it")
    if state in g.workflow.results_states(g.HUB) and not recipe:
        return g._verdict(2, f"{a.slug} reached {state} but no RECIPE distilled — add a FINDINGS.md entry "
                           "(or NOTES.md 'What worked / settled here')")
    return g._verdict(0, f"write-back operators satisfied for {a.slug} (state={state}; "
                       f"correction={'y' if correction else '—'}, recipe={'y' if recipe else '—'})")
