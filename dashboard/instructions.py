"""The Workflow page: the PI's own instructions per procedure, stage and role (tools/workflow.py layers),
and agents' proposals to change them (accept / decline).
"""

from __future__ import annotations

import re
import subprocess
import sys

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None


def _wf():
    return sources.workflow


def _study_arg(v) -> str | None:
    v = str(v or "").strip()
    if not v or v == "lab":
        return None
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,79}$", v) or not (ctx.HUB / "studies" / v).is_dir():
        raise ValueError(f"no study '{v}'")
    return v


def _strip_fm(text: str) -> str:
    return _wf().split_frontmatter(text or "")[1].strip()


def workflow_item(q: dict) -> tuple[dict, int]:
    """Everything the Workflow page shows for one procedure, stage or role — at lab level, or one study's."""
    wf, hub = _wf(), ctx.HUB
    kind = str(q.get("kind") or "procedure")
    name = str(q.get("name") or "")
    try:
        study = _study_arg(q.get("study"))
        m = wf.load(hub)
        if kind == "procedure":
            p = (m.get("procedures") or {}).get(name)
            if not p:
                return {"error": f"unknown procedure '{name}'"}, 404
            skill = ctx.read(hub / ".claude" / "skills" / name / "SKILL.md") or ""
            out = {"ok": True, "kind": kind, "name": name, "study": study, "procedure": p,
                   "contract": _strip_fm(skill), "default_method": wf.default_method(name, hub),
                   "lab": {"add": wf.read_custom("add", name, hub)[1].strip(),
                           "method": wf.read_custom("method", name, hub)[1].strip() if p.get("replaceable") else ""},
                   "stages": [s["id"] for s in wf.stages_of(name, hub)]}
            if study:
                out["study_layer"] = {"add": wf.read_custom("add", name, hub, study)[1].strip(),
                                      "method": wf.read_custom("method", name, hub, study)[1].strip() if p.get("replaceable") else ""}
            st = wf.status(hub, study).get("procedures", {}).get(name) or {}
            lab_st = wf.status(hub).get("procedures", {}).get(name) or {}
            out["stale"] = bool(st.get("stale") or lab_st.get("stale"))
            out["brief"], out["brief_sha"] = wf.brief(name, hub, study=study)
            return out, 200
        if kind == "stage":
            st = next((s for s in m.get("stages", []) if s["id"] == name), None)
            if not st:
                return {"error": f"unknown stage '{name}'"}, 404
            out = {"ok": True, "kind": kind, "name": name, "study": study, "stage": st,
                   "lab": {"add": wf.read_custom("stage", name, hub)[1].strip()}}
            if study:
                out["study_layer"] = {"add": wf.read_custom("stage", name, hub, study)[1].strip()}
            return out, 200
        if kind == "role":
            if name not in m.get("roles", []):
                return {"error": f"unknown role '{name}'"}, 404
            return {"ok": True, "kind": kind, "name": name, "study": None,
                    "contract": (ctx.read(hub / "agent-roles" / f"{name}.md") or "").strip(),
                    "lab": {"add": wf.read_custom("role", name, hub)[1].strip()}}, 200
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"error": "kind must be procedure | stage | role"}, 400


def workflow_save(body: dict) -> tuple[dict, int]:
    """Save (empty text = remove) one layer: kind add | method | stage | role, lab-wide or for one study."""
    wf, hub = _wf(), ctx.HUB
    kind, name = str(body.get("kind") or ""), str(body.get("name") or "")
    text = body.get("text")
    if kind not in ("add", "method", "stage", "role") or not isinstance(text, str):
        return {"error": "kind (add | method | stage | role), name and text"}, 400
    try:
        study = _study_arg(body.get("study"))
        m = wf.load(hub)
        if kind in ("add", "method"):
            p = (m.get("procedures") or {}).get(name)
            if not p:
                return {"error": f"unknown procedure '{name}'"}, 404
            if kind == "method" and not p.get("replaceable"):
                return {"error": f"/{name} is all contract — you can add instructions to it, not replace its method"}, 400
        elif kind == "stage" and name not in {s["id"] for s in m.get("stages", [])}:
            return {"error": f"unknown stage '{name}'"}, 404
        elif kind == "role" and name not in m.get("roles", []):
            return {"error": f"unknown role '{name}'"}, 404
        path = wf.write_custom(kind, name, text, hub, study)
    except ValueError as e:
        return {"error": str(e)}, 400
    warnings = []
    toks = sorted(wf.system_tokens(text))
    if toks:
        warnings.append("This text mentions the lab's fixed rules (" + ", ".join(toks[:4]) + "). That's fine as a "
                        "reminder, but it can't change them — the procedure's contract always wins.")
    if kind == "role":
        r = subprocess.run([sys.executable, str(hub / "tools" / "role_sync.py"), "render"], cwd=str(hub),
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            warnings.append("saved, but re-rendering the role files failed: " + (r.stderr or r.stdout)[-300:])
    rel = path.relative_to(hub).as_posix() if path else None
    ctx.pi_log({"action": "workflow.save", "kind": kind, "name": name, "study": study, "chars": len(text.strip()),
               "file": rel})
    where = f"for {study}" if study else "lab-wide"
    return {"ok": True, "note": (f"saved {where}" if path else f"reset to the default ({where})"), "file": rel,
            "warnings": warnings}, 200


def workflow_new(body: dict) -> tuple[dict, int]:
    """Make a copy of a procedure or a role (tools/new.py) — the PI's way to add one without editing files."""
    if not body.get("confirm"):
        return {"error": "making a copy needs explicit confirm"}, 400
    kind, name, like = str(body.get("kind") or ""), str(body.get("name") or "").strip(), str(body.get("like") or "")
    new = ctx.tool("new")
    try:
        if kind == "skill":
            stage = next((s["id"] for s in _wf().stages_of(like, ctx.HUB)), None)   # beside the one it copies
            files = new.new_skill(ctx.HUB, name, like, stage=stage, title=str(body.get("title") or "") or None)
        elif kind == "role":
            files = new.new_role(ctx.HUB, name, like, label=str(body.get("title") or "") or None)
        else:
            return {"error": "kind must be skill or role"}, 400
    except new.NewError as e:
        return {"error": str(e)}, 400
    _wf().render_docs(ctx.HUB)
    rel = [f.relative_to(ctx.HUB).as_posix() for f in files if f.is_relative_to(ctx.HUB)]
    ctx.pi_log({"action": "workflow.new", "kind": kind, "name": name, "like": like, "files": rel})
    return {"ok": True, "note": f"made {'/' if kind == 'skill' else ''}{name} from {like} — edit it to make it its own",
            "files": rel, "name": name}, 200


def workflow_proposal(body: dict) -> tuple[dict, int]:
    """Accept or decline an agent's suggested instruction change."""
    wf = _wf()
    pid, accept = str(body.get("id") or ""), body.get("accept")
    if not isinstance(accept, bool):
        return {"error": "accept must be true or false"}, 400
    try:
        rec = wf.resolve_proposal(pid, accept, ctx.HUB)
    except (OSError, ValueError) as e:
        return {"error": str(e)}, 400
    if rec["kind"] == "role" and accept:
        subprocess.run([sys.executable, str(ctx.HUB / "tools" / "role_sync.py"), "render"], cwd=str(ctx.HUB),
                       capture_output=True, timeout=120)
    ctx.emit_hub("instruction_resolved", idea=rec.get("study"), detail=f"{rec['status']}: {rec['kind']} {rec['name']}")
    ctx.pi_log({"action": "workflow.proposal", "id": pid, "accept": accept, "kind": rec["kind"], "name": rec["name"],
               "study": rec.get("study")})
    return {"ok": True, "note": "added to the instructions" if accept else "declined"}, 200


def workflow_proposal_get(q: dict) -> tuple[dict, int]:
    pid = str(q.get("id") or "")
    for r in _wf().proposals(ctx.HUB, pending_only=False):
        if r.get("id") == pid:
            return {"ok": True, **r}, 200
    return {"error": "no such proposal"}, 404
