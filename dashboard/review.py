"""What the PI reads to sign a gate: the review bundles (proposal, pilot evidence and accounting, the
paper and its reviews), any lab or study document, and the claims map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None


_DOC_CLIP = 16000   # never stream a whole repo — clip each file


def _read_clip(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    txt = path.read_text(encoding="utf-8-sig", errors="replace")
    return txt if len(txt) <= _DOC_CLIP else txt[:_DOC_CLIP] + "\n\n… (clipped — open the file for the rest)"


def _filesec(title: str, f: Path, fallback: str = "") -> dict:
    """A doc-viewer section for a real file: its clipped text plus an absolute `path` (when the file
    exists) so the frontend can offer an 'open in editor' deep-link. The dashboard is local-only."""
    sec = {"title": title, "text": _read_clip(f) or fallback}
    if f.exists() and f.is_file():
        sec["path"] = str(f.resolve())
    return sec


def _read_full(path: Path) -> str:
    """Unclipped read — for parsing/extraction where a 16 KB clip could cut a section mid-way (the
    extracted section itself is small, so this never streams much). Empty string if absent."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _md_section(text: str, pattern) -> str:
    """Return one markdown section (heading + body) whose HEADING TEXT matches `pattern` (a compiled
    regex). Body runs until the next heading of equal-or-shallower level (## stops at ##/#). '' if
    not found. Used to lift the decision-critical bits out of proposal.md / lit-review.md / a
    meta-review — tolerant of the numbered ('## 5. Budget') and suffixed ('Kill criteria (…)') headings."""
    lines = text.split("\n")
    heads = [(i, len(m.group(1)), m.group(2)) for i, ln in enumerate(lines)
             for m in (_HEADING.match(ln),) if m]
    for n, (i, level, htext) in enumerate(heads):
        if pattern.search(htext):
            end = len(lines)
            for (j, lvl, _h) in heads[n + 1:]:
                if lvl <= level:
                    end = j
                    break
            return "\n".join(lines[i:end]).strip()
    return ""


def _gate1_bundle(slug: str) -> dict:
    prop = ctx.HUB / "studies" / slug / "proposal.md"
    lit = ctx.HUB / "studies" / slug / "lit-review.md"
    secs = []
    nov = _md_section(_read_full(lit), re.compile(r"Novelty verdict", re.I))
    if nov:
        secs.append({"title": "Novelty verdict (lit-review)", "text": nov, "path": str(lit.resolve())})
    prop_full = _read_full(prop)
    if prop_full:
        crit = [s for s in (_md_section(prop_full, re.compile(pat, re.I))
                            for pat in (r"\bBudget\b(?![-\w])", r"Kill criteria", r"Success criteria")) if s]
        if crit:
            secs.append({"title": "Decision-critical — budget · kill criteria · success criteria",
                         "text": "\n\n".join(crit), "path": str(prop.resolve())})
        secs.append(_filesec(f"studies/{slug}/proposal.md", prop))
    else:
        secs.append(_filesec(f"studies/{slug}/proposal.md", prop, f"no proposal at studies/{slug}/proposal.md"))
    return {"ok": True, "title": f"Gate 1 · {slug} · proposal + novelty", "sections": secs}


def _pilot_evidence(pdir: Path | None) -> dict:
    """The completed PILOT runs — the evidence that justifies signing a FULL-run envelope."""
    if not pdir:
        return {"title": "Pilot evidence", "text": "project not reachable — no runs to show"}
    reg = pdir / "runs" / "registry.jsonl"
    rows = ctx.labfiles.read_jsonl(reg)
    pilots = [r for r in rows if r.get("status") == "completed" and str(r.get("stage", "")).upper() == "PILOT"]
    sec = {"title": f"Pilot evidence — {len(pilots)} completed PILOT run(s)"}
    if reg.exists():
        sec["path"] = str(reg.resolve())
    if not pilots:
        sec["text"] = ("no completed PILOT runs yet — pilots are the evidence that justifies a "
                       "FULL-scale launch (Gate 2 should usually wait for them)")
        return sec
    lines = []
    for r in pilots[-12:]:
        m = r.get("metrics") or {}
        mtxt = " · ".join(f"{k}={v}" for k, v in list(m.items())[:4] if isinstance(v, (int, float)))
        lines.append(f"{str(r.get('run_id', '?')):<34}  seed={r.get('seed', '?')}  {mtxt}")
    sec["text"] = "\n".join(lines)
    return sec


def _gate2_accounting(pdir: Path | None, env: dict | None) -> dict:
    """Envelope capacity vs what's already booked — formats sources.envelope_accounting (the ONE
    source of truth, which mirrors tools/guard.py's c_full_run) into the review-bundle text so the PI
    sees, before signing, whether a FULL request would even fit (completed + reserved vs caps)."""
    a = sources.envelope_accounting(pdir, env)
    lines = [
        f"signed:            {'yes' if a['signed'] else 'NO — every FULL run needs fresh PI approval'}",
        f"expires:           {a['expires'] or 'n/a'}{'   (EXPIRED)' if a['expired'] else ''}",
        f"signed_via:        {a['signed_via'] or 'PI direct'}",
        "",
        f"full_runs cap:     {a['full_cap'] or 'unset'}      per-run ≤ {a['per_cap'] or 'unset'} min      total ≤ {a['total_cap'] or 'unset'} min",
        f"completed FULL:    {a['full_done']} run(s)   (~{a['min_done']:.0f} min booked)",
        f"reserved FULL:     {a['full_resv']} run(s)   (~{a['min_resv']:.0f} min, in-flight sweeps)",
        f"remaining FULL:    {a['full_rem'] if a['full_rem'] is not None else '∞'} run(s)",
        f"remaining minutes: {a['min_rem'] if a['min_rem'] is not None else '∞'}",
    ]
    return {"title": f"Envelope capacity — {a['status']}", "text": "\n".join(lines)}


def _gate2_bundle(slug: str) -> dict:
    pdir = ctx.pdir(slug)
    ctrl = (pdir / "control.yaml") if pdir else None
    env = (ctx.labfiles.load_yaml(ctrl).get("gate2_envelope") if ctrl and ctrl.exists() else None)
    secs = [_gate2_accounting(pdir, env),
            {"title": "gate2_envelope (control.yaml)",
             "text": json.dumps(env, indent=2, default=str) if env else "no gate2_envelope found — spawn the project first"}]
    secs.append(_pilot_evidence(pdir))
    if ctrl and ctrl.exists():
        secs.append(_filesec("control.yaml", ctrl))
    return {"ok": True, "title": f"Gate 2 · {slug} · envelope + accounting + pilot evidence", "sections": secs}


def _find_review_files(paper: Path, pattern: str) -> list:
    """Reviews live under studies/<slug>/paper/reviews/[critique-<date>/], so search RECURSIVELY
    (a plain glob — what the old gate-3 view used — finds none of them). Bounded."""
    if not paper.is_dir():
        return []
    return [f for f in sorted(paper.rglob(pattern)) if f.is_file()][:30]


def _meta_verdict(text: str) -> str:
    """Lift the headline decision + Overall-score row out of a meta-review.md."""
    if not text:
        return ""
    out = []
    for ln in text.split("\n"):
        if re.search(r"\|\s*\*{0,2}Overall", ln, re.I):
            out.append(ln.strip())
            break
    dec = _md_section(text, re.compile(r"^Decision\b", re.I))
    if dec:
        out.append(dec)
    return "\n\n".join(out).strip()


def _gate3_bundle(slug: str) -> dict:
    paper = ctx.HUB / "studies" / slug / "paper"
    secs = [_filesec(f"studies/{slug}/paper/claims.yaml", paper / "claims.yaml", "no claims.yaml yet")]
    metas = _find_review_files(paper, "*meta*.md")
    if metas:
        verdict = _meta_verdict(_read_full(metas[-1]))
        if verdict:
            secs.append({"title": "Meta-review verdict", "text": verdict, "path": str(metas[-1].resolve())})
    seen = set()
    for f in _find_review_files(paper, "*review*.md") + metas + _find_review_files(paper, "*response*.md"):
        if f in seen:
            continue
        seen.add(f)
        secs.append(_filesec(f"paper/{f.relative_to(paper).as_posix()}", f))
    return {"ok": True, "title": f"Gate 3 · {slug} · claims + review (read-only)", "sections": secs,
            "note": "Signing Gate 3 needs the study name typed; it allows exactly one /finalize run, started by you."}


def _as_list(v) -> list:
    """Coerce a YAML scalar to a one-item list — so a hand-edited `artifacts: foo` / `numbers: "0.9"`
    (a string written where a list belongs) isn't iterated character-by-character."""
    if isinstance(v, list):
        return v
    return [v] if v not in (None, "") else []


def _within(base: Path | None, target: Path) -> bool:
    """True iff `target` resolves to inside `base` — a cheap containment guard so a claim artifact
    like `../../x` can't surface an out-of-project absolute path as an openable editor link."""
    if not base:
        return False
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _claim_project_dir(c: dict, slug: str) -> Path | None:
    # project_path is a documented override for /adopt or oddly-located projects, so it is NOT
    # contained to projects_root — it points wherever the PI's project actually lives.
    pp = str(c.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (ctx.HUB / p).resolve()
    return ctx.pdir(c.get("project") or slug)


def claims_map(idea: str | None = None) -> dict:
    slug = ctx.slug(idea or "")
    if not slug:
        return {"error": "no idea given"}
    cfile = ctx.HUB / "studies" / slug / "paper" / "claims.yaml"
    if not cfile.exists():
        return {"error": f"no claims.yaml at studies/{slug}/paper/claims.yaml"}
    doc = ctx.labfiles.load_yaml(cfile)
    if not isinstance(doc, dict):        # a malformed top-level scalar/list → empty map, never a 500
        doc = {}
    claims_in = doc.get("claims")
    if not isinstance(claims_in, list):  # the schema's top-level `claims:` is a list; anything else → none
        claims_in = []
    archive = ctx.HUB / "studies" / slug / "paper" / "artifacts"
    out = []
    for c in claims_in:
        if not isinstance(c, dict):      # count parity: sources._claims_count also counts dict items only
            continue
        proj = str(c.get("project") or slug)
        pdir = _claim_project_dir(c, slug)
        arts = []
        for rel in _as_list(c.get("artifacts")):
            rel = str(rel).replace("\\", "/")
            info = {"rel": rel, "exists": False}
            target = None
            live = (pdir / rel) if pdir else None
            if live and live.exists() and _within(pdir, live):                  # must stay inside its project
                target = live
            elif (archive / rel).exists() and _within(archive, archive / rel):  # hub archive (locked at /finalize)
                target = archive / rel
            if target:
                info.update(exists=True, abs=str(target.resolve()))
                mm = re.match(r"runs/([^/]+)/", rel)                            # a run artifact → peekable in the doc viewer
                if mm and mm.group(1) not in ("..", "."):
                    info.update(project=proj, run_id=mm.group(1))
            arts.append(info)
        out.append({
            "id": str(c.get("id") or ""), "claim": str(c.get("claim") or ""),
            "numbers": [str(n) for n in _as_list(c.get("numbers"))],
            "metric": str(c.get("metric") or ""), "location": str(c.get("location") or ""),
            "derivation": str(c.get("derivation") or ""), "project": proj,
            "has_hashes": bool(c.get("artifact_sha256")), "artifacts": arts,
            "linked": bool(arts) and all(a["exists"] for a in arts),
        })
    return {"ok": True, "title": f"{slug} · claims ↔ artifacts", "n": len(out),
            "claims_path": str(cfile.resolve()), "claims": out}


def read_doc(what: str, idea: str | None = None, gate: int | None = None, run: str | None = None) -> dict:
    if what == "run":
        slug, rid = ctx.slug(idea or ""), ctx.slug(run or "")
        if not slug or not rid:
            return {"error": "need a project + run id"}
        pdir = ctx.pdir(slug)
        if not pdir:
            return {"error": f"no project dir for {slug}"}
        rdir = pdir / "runs" / rid
        secs = []
        for fn in ("metrics.json", "meta.json", "config.yaml"):
            f = rdir / fn
            if f.exists():
                secs.append(_filesec(f"runs/{rid}/{fn}", f))
        stream = rdir / "metrics.jsonl"
        if stream.exists():
            lines = [ln for ln in _read_clip(stream).splitlines() if ln.strip()]
            if lines:
                secs.append({"title": f"runs/{rid}/metrics.jsonl · last {min(8, len(lines))} of {len(lines)}",
                             "text": "\n".join(lines[-8:]), "path": str(stream.resolve())})
        if not secs:
            return {"error": f"no artifacts under {slug}/runs/{rid} (runs are gitignored; the project may be elsewhere)"}
        return {"ok": True, "title": f"{slug} · {rid}", "sections": secs}

    if what == "knowledge":
        secs = []
        for name in ("FINDINGS", "FAILURES", "OPEN-QUESTIONS", "REFERENCES"):
            secs.append(_filesec(name.replace("-", " ").title(),
                                 ctx.LAB / "knowledge" / f"{name}.md", "(none recorded yet)"))
        nb_dir = ctx.LAB / "notebook"
        entries = sorted(nb_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if nb_dir.exists() else []
        dated = [f for f in entries if f.name.lower() != "readme.md"]
        latest = (dated or entries)[0] if (dated or entries) else None
        if latest:
            secs.append(_filesec("Latest notebook entry · " + latest.name, latest))
        return {"ok": True, "title": "Lab knowledge", "sections": secs}

    if what == "gate":
        slug = ctx.slug(idea or "")
        if not slug:
            return {"error": "no idea given"}
        try:
            gate = int(gate or 0)
        except (TypeError, ValueError):
            gate = 0
        if gate == 1:
            return _gate1_bundle(slug)
        if gate == 2:
            return _gate2_bundle(slug)
        if gate == 3:
            return _gate3_bundle(slug)
        return {"error": f"unknown gate {gate}"}
    return {"error": f"unknown document '{what}'"}
