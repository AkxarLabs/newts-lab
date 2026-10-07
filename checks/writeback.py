"""guard.py writeback — A session wrote back to the hub (hard rule knowledge-write-back).

A check for tools/guard.py: `uv run --with pyyaml python tools/guard.py writeback …`. It gets the parsed arguments and the guard module (HUB, LAB, labfiles, _row, _project_dir, _verdict)
and returns the exit code: 0 = OK · 1 = BLOCKED · 2 = WARN."""

from __future__ import annotations


NAME = "writeback"


def add_args(p) -> None:
    p.add_argument("slug")


def run(a, g) -> int:
    """Rule 11: a session must write back. Pass if a dated notebook entry names the slug today,
    or a HUB-WRITEBACK-PENDING block is queued in the project log."""
    nb = g.LAB / "notebook"
    has_nb = nb.exists() and any(
        g._today() in p.name and a.slug in p.read_text(encoding="utf-8-sig") for p in nb.glob("*.md"))
    pdir = g._project_dir(a.slug)
    pending = bool(pdir and (pdir / "EXPERIMENT_LOG.md").exists()
                   and "HUB-WRITEBACK-PENDING" in (pdir / "EXPERIMENT_LOG.md").read_text(encoding="utf-8-sig"))
    if has_nb or pending:
        return g._verdict(0, f"write-back present for {a.slug} ({'notebook' if has_nb else 'pending block'})")
    return g._verdict(2, f"no dated write-back for {a.slug} today — run tools/hub_writeback.py before ending (rule 11)")
