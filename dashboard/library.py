"""The library: every document a lab and its studies hold, the paper PDF and its figures.
"""

from __future__ import annotations

from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


_LIB_EXTS = {".md", ".markdown", ".txt", ".yaml", ".yml", ".tex", ".bib", ".json", ".jsonl", ".csv"}


_LIB_CLIP = 400_000        # a full proposal/log fits; never stream a truly huge file


_LIB_SECTION_CAP = 120     # per-section doc cap — keeps the tree (and the scan) bounded


def _lib_root(scope: str, slug: str | None) -> Path | None:
    if scope == "lab":
        return ctx.LAB
    s = ctx.slug(slug or "")
    if not s:
        return None
    if scope == "study":
        d = ctx.HUB / "studies" / s
        return d if d.is_dir() else None
    if scope == "project":
        return ctx.pdir(s)
    return None


def _lib_entry(scope: str, slug: str | None, base: Path, f: Path, title: str | None = None) -> dict | None:
    try:
        rel = f.relative_to(base).as_posix()
    except ValueError:
        return None
    try:
        mtime = int(f.stat().st_mtime)
    except OSError:
        mtime = 0
    return {"scope": scope, "slug": slug, "rel": rel, "title": title or f.name, "mtime": mtime}


def _lib_docs(scope: str, slug: str | None, base: Path, files) -> list[dict]:
    out = []
    for f in files:
        if len(out) >= _LIB_SECTION_CAP:
            break
        try:
            if not (f.is_file() and f.suffix.lower() in _LIB_EXTS):
                continue
        except OSError:
            continue
        e = _lib_entry(scope, slug, base, f)
        if e:
            out.append(e)
    return out


def _lib_glob(d: Path, pattern: str, recursive: bool = False) -> list[Path]:
    if not d.is_dir():
        return []
    try:
        files = sorted(d.rglob(pattern) if recursive else d.glob(pattern))
    except OSError:
        return []
    return files[: _LIB_SECTION_CAP * 2]


def _dated_first(files: list[Path]) -> list[Path]:
    """Newest first for dated names (ISO names sort reverse-chronologically); READMEs sink to the end."""
    dated = [f for f in sorted(files, key=lambda f: f.name, reverse=True) if f.name.lower() != "readme.md"]
    return dated + [f for f in files if f.name.lower() == "readme.md"]


def _lab_group() -> dict:
    secs = []
    idea_docs = _lib_docs("lab", None, ctx.LAB, _dated_first(_lib_glob(ctx.LAB / "ideation", "*.md")))
    secs.append({"title": "Ideation (pre-project)", "icon": "💡", "docs": idea_docs})
    know = [ctx.LAB / "knowledge" / f"{n}.md" for n in ("FINDINGS", "FAILURES", "OPEN-QUESTIONS", "REFERENCES")]
    know += [f for f in _lib_glob(ctx.LAB / "knowledge", "*.md") if f not in know and f.name.lower() != "readme.md"]
    secs.append({"title": "Knowledge", "icon": "🧠",
                 "docs": _lib_docs("lab", None, ctx.LAB, [f for f in know if f.exists()])})
    nb = _dated_first(_lib_glob(ctx.LAB / "notebook", "*.md"))[:60]
    secs.append({"title": "Notebook", "icon": "📓", "docs": _lib_docs("lab", None, ctx.LAB, nb)})
    camp = _dated_first(_lib_glob(ctx.LAB / "campaigns", "*.md"))
    if camp:
        secs.append({"title": "Campaigns", "icon": "🚩", "docs": _lib_docs("lab", None, ctx.LAB, camp)})
    return {"kind": "lab", "key": "lab", "title": "The Lab", "sections": secs}


_STUDY_CORE_ORDER = ["IDEA.md", "lit-review.md", "decisions.md", "proposal.md"]


_PROJECT_DOC_ORDER = ["PLAN.md", "EXPERIMENT_LOG.md", "NOTES.md", "TARGET.md", "LOOP_BRIEF.md", "TYPE.md", "README.md"]


def _study_group(slug: str, row: dict | None) -> dict | None:
    sdir = ctx.HUB / "studies" / slug
    pdir = sources._project_path(row or {"id": slug, "project": ""})
    if not sdir.is_dir() and not pdir:
        return None
    secs = []
    if sdir.is_dir():
        core = [sdir / n for n in _STUDY_CORE_ORDER if (sdir / n).exists()]
        core += [f for f in _lib_glob(sdir, "*.md") if f.name not in _STUDY_CORE_ORDER]
        secs.append({"title": "Study", "icon": "📋", "docs": _lib_docs("study", slug, sdir, core)})
        sess = _dated_first(_lib_glob(sdir / "sessions", "*.md"))
        if sess:
            secs.append({"title": "Sessions", "icon": "🗣", "docs": _lib_docs("study", slug, sdir, sess)})
        crit = _lib_glob(sdir / "critiques", "*.md", recursive=True)
        if crit:
            secs.append({"title": "Critiques", "icon": "🔍", "docs": _lib_docs("study", slug, sdir, crit)})
        paper_dir = sdir / "paper"
        if paper_dir.is_dir():
            pap = [paper_dir / "main.tex", paper_dir / "claims.yaml"]
            pap = [f for f in pap if f.exists()] + _lib_glob(paper_dir, "*.md")
            rev = _lib_glob(paper_dir / "reviews", "*.md", recursive=True)
            if pap:
                secs.append({"title": "Paper", "icon": "📜", "docs": _lib_docs("study", slug, sdir, pap)})
            if rev:
                secs.append({"title": "Reviews", "icon": "🧾", "docs": _lib_docs("study", slug, sdir, rev)})
    if pdir and pdir.is_dir():
        pdocs = [pdir / n for n in _PROJECT_DOC_ORDER if (pdir / n).exists()]
        pdocs += _lib_glob(pdir / "analysis", "*.md", recursive=True)
        pdocs += [f for f in _lib_glob(pdir, "*.md") if f.name not in _PROJECT_DOC_ORDER]
        secs.append({"title": "Project repo", "icon": "🛠", "docs": _lib_docs("project", slug, pdir, pdocs)})
    if not any(s["docs"] for s in secs):
        return None
    return {"kind": "study", "key": f"study:{slug}", "slug": slug,
            "title": (row or {}).get("title") or slug, "state": (row or {}).get("state") or "",
            "sections": [s for s in secs if s["docs"]]}


def lib_tree() -> dict:
    rows = {r["id"]: r for r in sources.parse_registry()}
    slugs = list(rows)
    sdirs = ctx.HUB / "studies"
    if sdirs.is_dir():
        for d in sorted(sdirs.iterdir()):
            if d.is_dir() and d.name not in slugs:
                slugs.append(d.name)
    groups = [_lab_group()]
    for slug in slugs:
        g = _study_group(slug, rows.get(slug))
        if g:
            groups.append(g)
    return {"ok": True, "groups": groups}


def lib_doc(scope: str, slug: str | None, rel: str) -> dict:
    root = _lib_root(str(scope or ""), slug)
    if not root or not root.is_dir():
        return {"error": f"unknown scope/slug ({scope}/{slug})"}
    rel = str(rel or "").replace("\\", "/").strip().lstrip("/")
    if not rel:
        return {"error": "no document given"}
    target = (root / rel)
    try:
        resolved = target.resolve()
        resolved.relative_to(root.resolve())     # containment — no ../ escape, no absolute override
    except (ValueError, OSError):
        return {"error": "document is outside its root"}
    if resolved.suffix.lower() not in _LIB_EXTS:
        return {"error": f"'{resolved.suffix}' files aren't readable here"}
    if not resolved.is_file():
        return {"error": f"no document at {rel}"}
    try:
        text = resolved.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as e:
        return {"error": f"unreadable: {e}"}
    clipped = len(text) > _LIB_CLIP
    if clipped:
        text = text[:_LIB_CLIP]
    fmt = "markdown" if resolved.suffix.lower() in (".md", ".markdown") else "text"
    try:
        mtime = int(resolved.stat().st_mtime)
    except OSError:
        mtime = 0
    return {"ok": True, "scope": scope, "slug": slug, "rel": rel, "title": rel.rsplit("/", 1)[-1],
            "path": str(resolved), "mtime": mtime, "format": fmt, "clipped": clipped, "text": text}


def lib_file(scope: str, slug: str | None, rel: str) -> tuple[Path, str] | None:
    """Resolve an IMAGE (or PDF) referenced by a doc — same roots + containment as lib_doc, so a
    proposal's relative `figures/x.png` renders inline. None if it isn't a safe, contained image."""
    root = _lib_root(str(scope or ""), slug)
    if not root or not root.is_dir():
        return None
    rel = str(rel or "").replace("\\", "/").strip().lstrip("/")
    target = (root / rel)
    try:
        resolved = target.resolve()
        resolved.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    ctype = _FIG_CTYPE.get(resolved.suffix.lower())
    if not ctype or not resolved.is_file():
        return None
    return resolved, ctype


_FIG_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf"}


_FIG_CTYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
              ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}


def _paper_dir(idea: str) -> Path | None:
    slug = ctx.slug(idea or "")
    return (ctx.HUB / "studies" / slug / "paper") if slug else None


def paper_pdf(idea: str) -> Path | None:
    pdir = _paper_dir(idea)
    f = (pdir / "main.pdf") if pdir else None
    return f if (f and f.is_file()) else None


def figure_list(idea: str) -> list[str]:
    pdir = _paper_dir(idea)
    fdir = (pdir / "figures") if pdir else None
    if not fdir or not fdir.is_dir():
        return []
    return sorted(f.name for f in fdir.iterdir() if f.is_file() and f.suffix.lower() in _FIG_EXTS)


def figure_file(idea: str, name: str) -> Path | None:
    pdir = _paper_dir(idea)
    fdir = (pdir / "figures") if pdir else None
    if not fdir or not fdir.is_dir():
        return None
    target = (fdir / Path(name or "").name).resolve()   # basename only — strips any path components
    if fdir.resolve() not in target.parents:            # re-confirm it lands inside figures/
        return None
    if not target.is_file() or target.suffix.lower() not in _FIG_EXTS:
        return None
    return target
