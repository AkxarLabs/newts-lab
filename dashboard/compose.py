"""Compose: the lab's own definition, edited as a draft and published as one change (the Compose page).

What it covers is every file that says how this lab works (ROOTS): the workflow and the rules (workflow/),
the procedures (.claude/skills/), the subagent roles (agent-roles/), the checks (checks/), the project
types and domain profiles (templates/…, lab/templates/), the rooms' looks (lab/rooms3d/) and the lab-wide
instructions (lab/workflow/). Settings (lab/config.yaml) stay on the Settings page; one study's own
instructions stay on its page.

The first edit copies those files into a draft (lab/.bus/compose/draft/, their shas in draft.json). Every
edit after that — a form, a file, a copy (tools/new.py), a delete — changes only the draft: the lab and
every run keep using the published files. `problems()` is tools/workflow.py check on the draft plus the
locks, what no lab changes from here: the three gates, the rules' tables the safety code reads, the hard
rules' numbering. Publishing copies the changed files over the lab's (refusing any the lab changed since
the draft began), renders the docs and the role files, and keeps the replaced files so it can be undone.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import yaml

import ctx  # noqa: E402
import sources  # noqa: E402

ROOTS = ("workflow", ".claude/skills", "agent-roles", "checks", "templates/project-types",
         "templates/domain-profiles", "lab/rooms3d", "lab/templates", "lab/workflow")
TEXT_EXT = {".md", ".yaml", ".yml", ".py", ".js", ".txt", ".json", ".toml", ".tex", ".bib", ".cfg", ".ini", ".sh", ".csv"}
LOCKED_TABLES = ("pi_owned_config", "protected_paths", "rigor_floors", "gate3_audits", "config_procedures")
MAX_FILE = 400_000
STAGE_MANIFEST, RULES = "workflow/stages.yaml", "workflow/rules.yaml"


class ComposeError(ValueError):
    """Refused, with a message fit to show the PI."""


def _wf():
    return sources.workflow


def _home() -> Path:
    return ctx.LAB / ".bus" / "compose"


def _draft() -> Path:
    return _home() / "draft"


def _meta() -> dict | None:
    try:
        return json.loads((_home() / "draft.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def active() -> bool:
    return _meta() is not None and _draft().is_dir()


def _root() -> Path:
    return _draft() if active() else ctx.HUB


def _sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None


def _walk(root: Path) -> dict[str, Path]:
    out = {}
    for r in ROOTS:
        d = root / r
        if d.is_dir():
            for f in d.rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    out[f.relative_to(root).as_posix()] = f
    return out


def _begin() -> Path:
    """The draft, made on the first edit: a copy of the lab's definition files."""
    if active():
        return _draft()
    d = _draft()
    if d.exists():
        shutil.rmtree(d)
    files = _walk(ctx.HUB)
    for rel, f in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, d / rel)
    d.mkdir(parents=True, exist_ok=True)
    (_home() / "draft.json").write_text(json.dumps({"created": ctx.ts(), "base": {r: _sha(f) for r, f in files.items()}},
                                                   indent=1), encoding="utf-8")
    return d


def changes() -> list[dict]:
    m = _meta()
    if not m or not _draft().is_dir():
        return []
    base, now = m.get("base") or {}, _walk(_draft())
    out = []
    for rel in sorted(set(base) | set(now)):
        if rel not in now:
            out.append({"path": rel, "status": "removed"})
        elif rel not in base:
            out.append({"path": rel, "status": "added"})
        elif _sha(now[rel]) != base[rel]:
            out.append({"path": rel, "status": "changed"})
    return out


# ── what's wrong with the draft ──────────────────────────────────────────────────────────────────
def problems(root: Path | None = None) -> list[str]:
    root = root or _root()
    try:
        probs = list(_wf().check(root))
    except Exception as e:  # noqa: BLE001 — a broken YAML file is a problem to show, not a crash
        return [f"the workflow can't be read: {e}"]
    return probs + (_locks(root) if root != ctx.HUB else []) + _orphans(root) + _room_files(root)


def _locks(root: Path) -> list[str]:
    wf, out = _wf(), []
    try:
        if wf.load(ctx.HUB).get("gates") != wf.load(root).get("gates"):
            out.append("The three gates are fixed: where each is signed and what it opens can't change.")
        ra, rb = wf.rules(ctx.HUB), wf.rules(root)
    except Exception:  # noqa: BLE001 — reported by check
        return out
    for k in LOCKED_TABLES:
        if ra.get(k) != rb.get(k):
            out.append(f"rules.yaml `{k}` is read by the lab's safety code and can't change from here.")
    ids_a = [r.get("id") for r in ra.get("hard_rules") or []]
    ids_b = [r.get("id") for r in rb.get("hard_rules") or []]
    if ids_b[:len(ids_a)] != ids_a:
        out.append("Hard rules are cited by number: edit their text or add new ones at the end, but don't "
                   "remove or reorder them.")
    return out


# ── a room's 3D look, as data ────────────────────────────────────────────────────────────────────
# The lab's own rooms (lab/rooms3d/<id>.json) — and every design an agent makes — are DATA, never code: a size,
# colours, furniture by name with positions, a station per procedure, and any new furniture as a list of
# boxes, cylinders, cones and spheres. The world builds them; nothing an agent writes ever runs in the page.
ROOM_KEYS = {"key", "title", "size", "floor", "wall", "walls", "accent", "props", "stations", "roleStation", "components"}
SHAPES = {"box": 3, "cyl": 3, "cone": 2, "sphere": 1}
_COLOR = re.compile(r"^(?:[a-zA-Z]{2,20}|#[0-9a-fA-F]{6})$")
_CNAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]{0,60}$")


def _nums(v, n, lo=-60.0, hi=60.0) -> bool:
    return isinstance(v, list) and len(v) == n and all(isinstance(x, (int, float)) and not isinstance(x, bool) and lo <= x <= hi for x in v)


def room_check(text: str, rid: str | None = None) -> tuple[dict | None, list[str]]:
    """A room look's problems (empty = fine to draw)."""
    try:
        d = json.loads(text or "")
    except ValueError as e:
        return None, [f"not valid JSON ({e})"]
    if not isinstance(d, dict):
        return None, ["a room is one JSON object"]
    p: list[str] = []
    if set(d) - ROOM_KEYS:
        p.append("unknown fields: " + ", ".join(sorted(set(d) - ROOM_KEYS)))
    if rid and d.get("key") != rid:
        p.append(f"key must be {rid!r}")
    if not _nums(d.get("size"), 2, 3, 30):
        p.append("size is [width, depth] in metres, 3–30")
    for k in ("floor", "wall", "accent"):
        if k in d and not (isinstance(d[k], str) and _COLOR.match(d[k])):
            p.append(f"{k} is a theme colour name or #rrggbb")
    if "walls" in d and not isinstance(d["walls"], bool):
        p.append("walls is true or false")
    comps, parts = d.get("components") or {}, 0
    if not isinstance(comps, dict) or len(comps) > 40:
        p.append("components is an object of at most 40 pieces of furniture")
        comps = {}
    for name, c in comps.items():
        if not _CNAME.match(str(name)) or not isinstance(c, dict) or not isinstance(c.get("parts"), list) or not 0 < len(c["parts"]) <= 120:
            p.append(f"component {name!r}: a name and 1–120 parts")
            continue
        for part in c["parts"]:
            parts += 1
            n = SHAPES.get((part or {}).get("shape")) if isinstance(part, dict) else None
            if not n or not _nums(part.get("size"), n, 0.005, 30) or not _nums(part.get("at"), 3, -30, 30) \
                    or ("rot" in part and not _nums(part["rot"], 3, -7, 7)) or not (isinstance(part.get("color"), str) and _COLOR.match(part["color"])) \
                    or ("glow" in part and not isinstance(part["glow"], bool)) or ("alpha" in part and not _nums([part["alpha"]], 1, 0, 1)) \
                    or set(part) - {"shape", "size", "at", "rot", "color", "glow", "alpha"}:
                p.append(f"component {name}: a part must be {{shape: box|cyl|cone|sphere, size, at: [x, y, z], color, rot?, glow?, alpha?}}")
                break
    if parts > 1500:
        p.append("too many parts (at most 1500 in a room)")
    props = d.get("props") or []
    if not isinstance(props, list) or len(props) > 150:
        p.append("props is a list of at most 150 pieces")
        props = []
    for pr in props:
        ok = isinstance(pr, dict) and isinstance(pr.get("c"), str) and _CNAME.match(pr["c"]) and _nums(pr.get("at"), 2, -30, 30) \
            and ("rot" not in pr or _nums([pr["rot"]], 1, -7, 7)) and not set(pr) - {"c", "at", "rot", "props"} \
            and all(isinstance(v, (str, int, float, bool)) for v in (pr.get("props") or {}).values()) if isinstance(pr, dict) else False
        if not ok:
            p.append("a prop is {c: furniture name, at: [x, z], rot?, props?: {simple values}}")
            break
    for k in ("stations", "roleStation"):
        st = d.get(k) or {}
        if not isinstance(st, dict) or not all(_CNAME.match(str(n)) and (_nums(v, 2, -30, 30) or _nums(v, 3, -30, 30)) for n, v in st.items()):
            p.append(f"{k} maps a name to [x, z] or [x, z, facing]")
    return (d if not p else None), p


def _room_files(root: Path) -> list[str]:
    out, d = [], root / "lab" / "rooms3d"
    for f in sorted(d.iterdir()) if d.is_dir() else []:
        if f.suffix != ".json":
            out.append(f"lab/rooms3d/{f.name}: a room's look is data — <room>.json")
            continue
        probs = room_check(ctx.read(f) or "", f.stem)[1]
        if probs:
            out.append(f"lab/rooms3d/{f.name}: " + "; ".join(probs[:3]))
    return out


STARTER_LOOKS = ctx.ROOT / "dashboard" / "static" / "world3d" / "looks"
LOOK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}(?:\.[a-z0-9][a-z0-9-]{0,30})?$")   # a room, or a room for one project type


def rooms3d(q: dict | None = None) -> tuple[dict, int]:
    """Room looks given as data, for the world to build: the starter looks this code ships (a Lab per project type,
    world3d/looks/), then the lab's own (lab/rooms3d/, published) — the lab's own win, being built last."""
    out = []
    for d, builtin in ((STARTER_LOOKS, True), (ctx.LAB / "rooms3d", False)):
        for f in sorted(d.glob("*.json")) if d.is_dir() else []:
            data = room_check(ctx.read(f) or "", f.stem)[0]
            if data:
                out.append({**data, "builtin": builtin})
    return {"ok": True, "rooms": out}, 200


def _orphans(root: Path) -> list[str]:
    """Studies whose state the edited workflow no longer has."""
    try:
        m = _wf().load(root)
        known = {s["id"] for s in m.get("states", []) + m.get("side_states", [])}
        rows = sources.parse_registry()
    except Exception:  # noqa: BLE001
        return []
    lost = sorted({r.get("state") for r in rows if r.get("state") and r.get("state") not in known})
    return [f"Studies are in state `{s}`, which this workflow no longer has." for s in lost]


# ── small text editors that keep the files' comments and layout ──────────────────────────────────
def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    if isinstance(v, dict):
        return _flow(v)
    s = str(v)
    try:
        plain = not re.search(r"[,\[\]{}#&*!|>%@`\"':]", s) and s == s.strip() and yaml.safe_load(f"k: {s}") == {"k": s}
    except yaml.YAMLError:
        plain = False
    return s if plain and s else json.dumps(s, ensure_ascii=False)


def _flow(d: dict) -> str:
    return "{" + ", ".join(f"{k}: {_scalar(v)}" for k, v in d.items()) + "}"


def _section(text: str, key: str) -> tuple[int, int]:
    """[start, end) of a top-level key's body (the lines after `key:` up to the next top-level key)."""
    m = re.search(rf"^{re.escape(key)}:[^\n]*\n?", text, re.M)
    if not m:
        raise ComposeError(f"no `{key}:` in the file")
    nxt = re.search(r"^[^\s#]", text[m.end():], re.M)
    return m.end(), m.end() + (nxt.start() if nxt else len(text) - m.end())


def _entries(text: str, key: str) -> list[tuple[int, int, dict]]:
    """(start, end, value) of each `  - {…}` flow entry in a top-level list; an entry may wrap lines."""
    a, b = _section(text, key)
    out, i = [], a
    while i < b:
        line_end = text.find("\n", i)
        line_end = b if line_end < 0 or line_end > b else line_end
        if text.startswith("  - {", i):
            k = text.index("{", i)
            depth, q, pos = 0, None, k
            for pos in range(k, b):
                c = text[pos]
                if q:
                    q = None if c == q else q
                elif c in "\"'":
                    q = c
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        break
            out.append((i, pos + 1, yaml.safe_load(text[k:pos + 1]) or {}))
            nl = text.find("\n", pos)
            i = b if nl < 0 else nl + 1
            continue
        i = line_end + 1
    return out


def _entry(text: str, key: str, eid: str) -> tuple[int, int, dict]:
    hit = next((e for e in _entries(text, key) if str(e[2].get("id")) == eid), None)
    if not hit:
        raise ComposeError(f"no {key[:-1] if key.endswith('s') else key} `{eid}`")
    return hit


def _set_entry(text: str, key: str, eid: str, d: dict) -> str:
    a, b, _ = _entry(text, key, eid)
    return text[:a] + "  - " + _flow(d) + text[b:]


def _insert_entry(text: str, key: str, d: dict, after: str | None = None) -> str:
    ents = _entries(text, key)
    if after:
        hit = next((e for e in ents if str(e[2].get("id")) == after), None)
        if not hit:
            raise ComposeError(f"no `{after}` in {key}")
        at = hit[1]
    elif ents:
        at = ents[-1][1]
    else:
        at = _section(text, key)[0] - 1
    nl = text.find("\n", at)
    at = len(text) if nl < 0 else nl
    return text[:at] + "\n  - " + _flow(d) + text[at:]


def _remove_entry(text: str, key: str, eid: str) -> str:
    a, b, _ = _entry(text, key, eid)
    nl = text.find("\n", b)
    return text[:a] + text[(len(text) if nl < 0 else nl + 1):]


def _set_map(text: str, key: str, name: str, value) -> str:
    """Set (or, with None, remove) `  name: value` under a top-level mapping; keeps a trailing comment."""
    a, b = _section(text, key)
    rx = re.compile(rf"^  {re.escape(name)}:[ \t]*(.*?)([ \t]+#[^\n]*)?$", re.M)
    hit = rx.search(text, a, b)
    if value is None:
        if not hit:
            return text
        nl = text.find("\n", hit.end())
        return text[:hit.start()] + text[(len(text) if nl < 0 else nl + 1):]
    line = f"  {name}: {_scalar(value)}"
    if hit:
        return text[:hit.start()] + line + (hit.group(2) or "") + text[hit.end():]
    end = b
    while end > a and text[end - 1] == "\n" and text[end - 2:end] == "\n\n":
        end -= 1
    return text[:end] + line + "\n" + text[end:]


def _list_without(v, name: str):
    if isinstance(v, list):
        return [x for x in v if x != name]
    if isinstance(v, dict):
        return {k: x for k, x in v.items() if x != name}
    return None if v == name else v


# ── reading and writing the draft ────────────────────────────────────────────────────────────────
def _rel(path) -> str:
    rel = str(path or "").replace("\\", "/").strip().strip("/")
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") for p in parts) or not any(rel.startswith(r + "/") for r in ROOTS):
        raise ComposeError(f"`{path}` is not part of the lab's definition")
    if Path(rel).suffix.lower() not in TEXT_EXT:
        raise ComposeError(f"`{rel}` is not a text file Compose edits")
    return rel


def _read(rel: str, root: Path | None = None) -> str:
    return (ctx.read((root or _draft()) / rel) or "").replace("\r\n", "\n")


def _put(rel: str, text: str | None) -> None:
    """Write one file of the draft (None removes it)."""
    d = _begin()
    p = d / rel
    if text is None:
        if p.is_file():
            p.unlink()
            _prune(p.parent, d)
        return
    if len(text) > MAX_FILE:
        raise ComposeError(f"`{rel}` is too long ({len(text)} characters)")
    p.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_keep_eol(p, ctx.read(p) or "", text)


def _prune(d: Path, top: Path) -> None:
    stops = {top} | {top / r for r in ROOTS}
    while d not in stops and d.is_dir() and not any(d.iterdir()):
        d.rmdir()
        d = d.parent


def _rmtree(rel: str) -> None:
    d = _begin()
    if (d / rel).is_dir():
        shutil.rmtree(d / rel)
        _prune((d / rel).parent, d)


def _edit(rel: str, fn) -> None:
    _put(rel, fn(_read(rel, _begin())))


def _skill_md(name: str) -> str:
    return f".claude/skills/{name}/SKILL.md"


def _set_skill_meta(name: str, fields: dict) -> None:
    """Rewrite a SKILL.md's frontmatter: `description`, and the `newts:` block (the procedure's definition)."""
    rel = _skill_md(name)
    text = _read(rel, _begin())
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise ComposeError(f"/{name}'s SKILL.md has no frontmatter")
    chunks: list[list] = []
    for ln in m.group(1).split("\n"):
        if ln[:1] not in ("", " ", "\t", "#") and ":" in ln:
            chunks.append([ln.split(":", 1)[0].strip(), [ln]])
        elif chunks:
            chunks[-1][1].append(ln)
        else:
            chunks.append([None, [ln]])
    block = dict(_wf().skill_meta(text).get("newts") or {})
    fields = dict(fields)
    if "description" in fields:
        desc = " ".join(str(fields.pop("description") or "").split())
        line = [f"description: {json.dumps(desc, ensure_ascii=False)}"]
        hit = next((c for c in chunks if c[0] == "description"), None)
        if hit:
            hit[1] = line
        else:
            chunks.insert(1, ["description", line])
    for k, v in fields.items():
        if v is None or v == "" or v == []:
            block.pop(k, None)
        else:
            block[k] = v
    newts = ("newts:\n" + textwrap.indent(yaml.safe_dump(block, sort_keys=False, allow_unicode=True, width=110), "  ")).rstrip("\n").split("\n") if block else None
    hit = next((c for c in chunks if c[0] == "newts"), None)
    if hit and newts:
        hit[1] = newts
    elif newts:
        chunks.append(["newts", newts])
    elif hit:
        chunks.remove(hit)
    fm = "\n".join(ln for c in chunks for ln in c[1])
    _put(rel, f"---\n{fm}\n---\n" + text[m.end():])


PROC_FIELDS = {"title", "does", "stops", "description", "kind", "level", "mode", "args", "hint", "launchable",
               "replaceable", "dispatchable", "start", "outputs", "brief_note", "show_pi"}


# ── the operations (POST /api/compose {op, …}) ───────────────────────────────────────────────────
def _op_write(b: dict) -> str:
    rel = _rel(b.get("path"))
    text = b.get("text")
    if text is not None and not isinstance(text, str):
        raise ComposeError("text must be a string (or null to remove the file)")
    _put(rel, text.replace("\r\n", "\n") if isinstance(text, str) else None)
    return f"{'removed' if text is None else 'saved'} {rel}"


def _op_instructions(b: dict) -> str:
    """The lab-wide layers the brief adds: kind add | method | stage | role (empty text removes it)."""
    kind, name = str(b.get("kind") or ""), str(b.get("name") or "")
    if kind not in ("add", "method", "stage", "role"):
        raise ComposeError("kind must be add | method | stage | role")
    d = _begin()
    _wf().write_custom(kind, name, str(b.get("text") or ""), d)
    return "saved" if str(b.get("text") or "").strip() else "back to the default"


def _op_procedure(b: dict) -> str:
    name = str(b.get("name") or "")
    if name not in (_wf().load(_begin()).get("procedures") or {}):
        raise ComposeError(f"no procedure /{name}")
    fields = {k: v for k, v in (b.get("fields") or {}).items() if k in PROC_FIELDS}
    if fields:
        _set_skill_meta(name, fields)
    if isinstance(b.get("stages"), list):
        want = {str(s) for s in b["stages"]}

        def fn(text):
            for _a, _b, st in _entries(text, "stages"):
                procs = list(st.get("procedures") or [])
                if (name in procs) != (st["id"] in want):
                    st["procedures"] = procs + [name] if st["id"] in want else [p for p in procs if p != name]
                    text = _set_entry(text, "stages", st["id"], st)
            return text
        _edit(STAGE_MANIFEST, fn)
    return f"/{name} updated"


def _op_stage(b: dict) -> str:
    sid = str(b.get("id") or "")

    def fn(text):
        st = dict(_entry(text, "stages", sid)[2])
        f = b.get("fields") or {}
        if "title" in f and str(f["title"]).strip():
            st["title"] = str(f["title"]).strip()
        if isinstance(f.get("procedures"), list):
            st["procedures"] = [str(p) for p in f["procedures"]]
        return _set_entry(text, "stages", sid, st)
    _edit(STAGE_MANIFEST, fn)
    return "stage updated"


def _op_state(b: dict) -> str:
    """A state's label, or the room it stands in (moving it out of its old room)."""
    sid, f = str(b.get("id") or ""), b.get("fields") or {}

    def fn(text):
        key = "states" if any(e[2].get("id") == sid for e in _entries(text, "states")) else "side_states"
        st = dict(_entry(text, key, sid)[2])
        if str(f.get("label") or "").strip():
            st["label"] = str(f["label"]).strip()
        room = f.get("room")
        if room and room != st.get("room"):
            rooms = {e[2]["id"]: e[2] for e in _entries(text, "rooms")}
            if room not in rooms:
                raise ComposeError(f"no room `{room}`")
            for rid, r in rooms.items():
                states = list(r.get("states") or [])
                if rid == room and sid not in states:
                    text = _set_entry(text, "rooms", rid, {**r, "states": states + [sid]})
                elif rid != room and sid in states:
                    text = _set_entry(text, "rooms", rid, {**r, "states": [x for x in states if x != sid]})
            st["room"] = room
        return _set_entry(text, key, sid, st)
    _edit(STAGE_MANIFEST, fn)
    return "state updated"


def _op_room(b: dict) -> str:
    rid, f = str(b.get("id") or ""), b.get("fields") or {}

    def fn(text):
        r = dict(_entry(text, "rooms", rid)[2])
        for k in ("label", "title"):
            if str(f.get(k) or "").strip():
                r[k] = str(f[k]).strip()
        if "per_project" in f:                # one room per live project (the Lab), or one for the whole lab
            if f["per_project"]:
                r["per_project"] = True
            else:
                r.pop("per_project", None)
        return _set_entry(text, "rooms", rid, r)
    _edit(STAGE_MANIFEST, fn)
    return "room updated"


def _op_room_place(b: dict) -> str:
    """Where a room stands on the table: place [col, row] (None = let the lab place it) and facing n|e|s|w."""
    rid = str(b.get("id") or "")
    place, facing = b.get("place"), b.get("facing")
    if place is not None and not (isinstance(place, list) and len(place) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in place)):
        raise ComposeError("place is [column, row] — two whole numbers")
    if place == [0, 0]:
        raise ComposeError("the middle plot is your desk's plaza")
    if facing is not None and facing not in ("n", "e", "s", "w"):
        raise ComposeError("facing is n, e, s or w")

    def fn(text):
        r = dict(_entry(text, "rooms", rid)[2])
        for k, v in (("place", place), ("facing", facing)):
            if v is None:
                r.pop(k, None)
            else:
                r[k] = v
        return _set_entry(text, "rooms", rid, r)
    _edit(STAGE_MANIFEST, fn)
    return "placed" if place else "the lab places it"


def _designs_dir() -> Path:
    return ctx.LAB / ".bus" / "designs"


def designs() -> list[dict]:
    """Room looks agents have designed (/design-room), newest first, each with its problems."""
    out, d = [], _designs_dir()
    for f in sorted(d.glob("*/room.json"), key=lambda x: x.stat().st_mtime, reverse=True) if d.is_dir() else []:
        name = f.parent.name
        if re.match(r"^[a-z0-9][a-z0-9-]{0,40}$", name):
            out.append({"room": name, "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(f.stat().st_mtime)),
                        "notes": (ctx.read(f.parent / "notes.md") or "").strip()[:1500],
                        "problems": room_check(ctx.read(f) or "", name)[1]})
    return out


def design_get(q: dict) -> tuple[dict, int]:
    name = str(q.get("room") or "")
    f = _designs_dir() / name / "room.json"
    if not LOOK_ID.match(name) or not f.is_file():
        return {"error": "no such design"}, 404
    data, probs = room_check(ctx.read(f) or "", name)
    return {"ok": True, "room": name, "data": data, "problems": probs, "notes": (ctx.read(f.parent / "notes.md") or "").strip()}, 200


def _op_design_use(b: dict) -> str:
    """Take an agent's design for a room into the draft (lab/rooms3d/<room>.json, reviewed before it's published)."""
    d, code = design_get({"room": b.get("room")})
    if code != 200:
        raise ComposeError(d["error"])
    if d["problems"]:
        raise ComposeError("this design has problems (" + "; ".join(d["problems"][:2]) + ") — ask for another")
    _put(f"lab/rooms3d/{d['room']}.json", json.dumps(d["data"], indent=1, ensure_ascii=False) + "\n")
    return f"the design for {d['room']} is in your draft — review it, then publish"


def _op_role(b: dict) -> str:
    name, f = str(b.get("name") or ""), b.get("fields") or {}
    rel = f"agent-roles/{name}.yaml"
    if not (_begin() / rel).is_file():
        raise ComposeError(f"no role {name}")

    def fn(text):
        for k in ("label", "description"):
            if k in f:
                v = _scalar(" ".join(str(f[k] or "").split()))
                rx = re.compile(rf"^{k}:[ \t]*(?:\"(?:[^\"\\]|\\.)*\"|'[^']*'|[^#\n]*?)([ \t]+#[^\n]*)?$", re.M)
                text = rx.sub(lambda m, v=v, k=k: f"{k}: {v}{m.group(1) or ''}", text, count=1) if rx.search(text) \
                    else text.rstrip("\n") + f"\n{k}: {v}\n"
        return text
    _edit(rel, fn)
    return "role updated"


def _rule_span(text: str, rid: str) -> tuple[int, int]:
    m = re.search(rf"^  - id: {re.escape(rid)}[ \t]*$", text, re.M)
    if not m:
        raise ComposeError(f"no rule `{rid}`")
    nxt = re.search(r"^(?:  - |\S)", text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    while text[m.start():end].endswith("\n\n"):
        end -= 1
    return m.start(), end


def _op_rule(b: dict) -> str:
    rid = str(b.get("id") or "")
    if b.get("remove"):
        _edit(RULES, lambda t: (lambda a, e: t[:a] + t[e:])(*_rule_span(t, rid)))
        return f"rule {rid} removed"
    text = " ".join(str(b.get("text") or "").split())
    if not text:
        raise ComposeError("a rule needs its text")
    checks = [str(c) for c in (b.get("checks") or []) if str(c).strip()]
    entry = f"  - id: {rid}\n" + (f"    checks: [{', '.join(checks)}]\n" if checks else "") + \
        f"    text: {json.dumps(text, ensure_ascii=False)}\n"

    def fn(t):
        a, e = _rule_span(t, rid)
        return t[:a] + entry + t[e:]
    _edit(RULES, fn)
    return f"rule {rid} updated"


def _blank_type(name: str, title: str | None) -> None:
    """A project type from nothing — for a lab that has none to copy yet: one TYPE.md to fill in."""
    rel = f"lab/templates/project-types/{name}/TYPE.md"
    if (_begin() / rel).exists() or (_begin() / f"templates/project-types/{name}/TYPE.md").exists():
        raise ComposeError(f"there is already a project type '{name}'")
    _put(rel, f"# Project type: `{name}`\n\n{title or 'What a project of this type is, in a sentence or two.'}\n\n"
              "- **An experiment is:** …\n- **Runner:** …\n- **Conventions:** what every agent in a project of this type should know.\n")


def _op_copy(b: dict) -> str:
    """Add a component by copying the closest one (tools/new.py, run on the draft)."""
    new, d = ctx.tool("new"), _begin()
    kind, name, like = str(b.get("kind") or ""), str(b.get("name") or "").strip(), str(b.get("like") or "")
    title = str(b.get("title") or "").strip() or None
    try:
        if kind == "procedure":
            stage = b.get("stage") or next((s["id"] for s in _wf().stages_of(like, d)), None)
            new.new_skill(d, name, like, stage=stage or None, title=title)
        elif kind == "room":
            new.new_room(d, name, like, states=[s for s in (b.get("states") or []) if s], title=title, plain=bool(b.get("plain")))
        elif kind == "role":
            new.new_role(d, name, like, label=title)
        elif kind == "check":
            new.new_check(d, name, like)
        elif kind == "type" and not like:
            _blank_type(new._name(name), title)
        elif kind == "type":
            new.new_type(d, name, like)
        elif kind == "rule":
            new.new_rule(d, name, str(b.get("text") or ""), which=str(b.get("list") or "hard"),
                         check=str(b.get("check") or "") or None)
        else:
            raise ComposeError("kind must be procedure | room | role | check | type | rule")
    except new.NewError as e:
        raise ComposeError(str(e)) from None
    return f"made {name} from {like}" if like else f"added {name}"


def _op_stage_add(b: dict) -> str:
    """A new stage after another, with its first state (in a room you pick): `add a stage` without YAML."""
    new = ctx.tool("new")
    sid, sname = new._name(str(b.get("id") or "")), str(b.get("title") or "").strip()
    after, room = str(b.get("after") or ""), str(b.get("room") or "")
    state = new._name(str(b.get("state") or sid))
    label = str(b.get("state_label") or sname or state).strip()

    def fn(text):
        m = yaml.safe_load(text) or {}
        if any(s.get("id") == sid for s in m.get("stages", [])):
            raise ComposeError(f"there is already a stage `{sid}`")
        if any(s.get("id") == state for s in m.get("states", []) + m.get("side_states", [])):
            raise ComposeError(f"there is already a state `{state}`")
        prev = next((s for s in m.get("stages", []) if s.get("id") == after), None)
        if not prev:
            raise ComposeError(f"no stage `{after}` to put it after")
        rooms = {r["id"]: r for r in m.get("rooms", [])}
        if room not in rooms:
            raise ComposeError("choose the room it happens in")
        last = (prev.get("states") or [None])[-1]
        station = next((s.get("station") for s in m.get("states", []) if s.get("room") == room and s.get("station")), None)
        st = {"id": state, "label": label, "stage": sid, "room": room}
        if station:
            st["station"] = station
        text = _insert_entry(text, "states", st, after=last)
        text = _insert_entry(text, "stages", {"id": sid, "title": sname or sid.capitalize(), "states": [state], "procedures": []}, after=after)
        text = _set_entry(text, "rooms", room, {**rooms[room], "states": list(rooms[room].get("states") or []) + [state]})
        paper = ((m.get("tracks") or {}).get("paper") or [])
        if last in paper:
            text = _set_map(text, "tracks", "paper", paper[:paper.index(last) + 1] + [state] + paper[paper.index(last) + 1:])
        return text
    _edit(STAGE_MANIFEST, fn)
    return f"stage {sid} added"


def _op_delete(b: dict) -> str:
    kind, name = str(b.get("kind") or ""), str(b.get("name") or "")
    d = _begin()
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,79}$", name):
        raise ComposeError(f"bad name {name!r}")
    if kind == "procedure":
        if not (d / ".claude/skills" / name).is_dir():
            raise ComposeError(f"no procedure /{name}")
        _rmtree(f".claude/skills/{name}")
        for f in (f"lab/workflow/{name}.add.md", f"lab/workflow/{name}.method.md"):
            _put(f, None)

        def fn(text):
            for _a, _b, st in _entries(text, "stages"):
                if name in (st.get("procedures") or []):
                    text = _set_entry(text, "stages", st["id"], {**st, "procedures": _list_without(st["procedures"], name)})
            a, e = _section(text, "offer_for_state")
            for k, v in ((yaml.safe_load(textwrap.dedent(text[a:e])) or {}).items()):
                if isinstance(v, list) and name in v:
                    text = _set_map(text, "offer_for_state", k, _list_without(v, name))
            return text
        _edit(STAGE_MANIFEST, fn)
    elif kind == "role":
        for f in (f"agent-roles/{name}.yaml", f"agent-roles/{name}.md", f"lab/workflow/roles/{name}.add.md"):
            _put(f, None)
    elif kind == "check":
        _put(f"checks/{name.replace('-', '_')}.py", None)
    elif kind == "type":
        own = f"lab/templates/project-types/{name}"
        _rmtree(own if (d / own).is_dir() else f"templates/project-types/{name}")
    elif kind == "room":
        _put(f"lab/rooms3d/{name}.json", None)
        move = str(b.get("move_to") or "")

        def fn(text):
            r = _entry(text, "rooms", name)[2]
            states = list(r.get("states") or [])
            if states and not move:
                raise ComposeError(f"say which room its states ({', '.join(states)}) move to")
            for s in states:
                key = "states" if any(e[2].get("id") == s for e in _entries(text, "states")) else "side_states"
                st = _entry(text, key, s)[2]
                text = _set_entry(text, key, s, {**st, "room": move})
            if states:
                to = _entry(text, "rooms", move)[2]
                text = _set_entry(text, "rooms", move, {**to, "states": list(to.get("states") or []) + states})
            return _remove_entry(text, "rooms", name)
        _edit(STAGE_MANIFEST, fn)
        _put(f"lab/rooms3d/{name}.json", None)
    elif kind == "stage":
        def fn(text):
            st = _entry(text, "stages", name)[2]
            gone = list(st.get("states") or [])
            for s in gone:
                text = _remove_entry(text, "states", s)
            for _a, _b, r in _entries(text, "rooms"):
                if set(r.get("states") or []) & set(gone):
                    text = _set_entry(text, "rooms", r["id"], {**r, "states": [x for x in r["states"] if x not in gone]})
            for table in ("next_for_state", "offer_for_state"):
                for s in gone:
                    text = _set_map(text, table, s, None)
            paper = ((yaml.safe_load(text).get("tracks") or {}).get("paper") or [])
            if set(paper) & set(gone):
                text = _set_map(text, "tracks", "paper", [x for x in paper if x not in gone])
            return _remove_entry(text, "stages", name)
        _edit(STAGE_MANIFEST, fn)
        _put(f"lab/workflow/stage.{name}.add.md", None)
    else:
        raise ComposeError("kind must be procedure | role | check | type | room | stage")
    return f"{kind} {name} removed"


def _op_discard(b: dict) -> str:
    if _draft().exists():
        shutil.rmtree(_draft())
    (_home() / "draft.json").unlink(missing_ok=True)
    return "draft discarded — nothing changed in the lab"


OPS = {"write": _op_write, "instructions": _op_instructions, "procedure": _op_procedure, "stage": _op_stage,
       "state": _op_state, "room": _op_room, "role": _op_role, "rule": _op_rule, "copy": _op_copy,
       "stage-add": _op_stage_add, "room-place": _op_room_place, "design-use": _op_design_use,
       "delete": _op_delete, "discard": _op_discard}


def op(body: dict) -> tuple[dict, int]:
    """One edit of the draft. After it the draft's generated text (each skill's contract head) is refreshed,
    so what the review shows is what will be published."""
    name = str(body.get("op") or "")
    if name == "publish":
        return publish(body)
    if name == "undo":
        return undo(body)
    fn = OPS.get(name)
    if not fn:
        return {"error": f"unknown op {name!r}"}, 400
    try:
        note = fn(body)
    except (ComposeError, ValueError, OSError, yaml.YAMLError) as e:
        return {"error": str(e)}, 400
    if active():
        try:
            _wf().render_docs(_draft())
        except Exception:  # noqa: BLE001 — a broken file shows up in problems()
            pass
    return {"ok": True, "note": note, "draft": draft_info()}, 200


# ── publish and undo ─────────────────────────────────────────────────────────────────────────────
def _after_change(touched: list[str]) -> list[str]:
    warnings = []
    try:
        _wf().render_docs(ctx.HUB)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"the generated docs could not be refreshed: {e}")
    if any(p.startswith(("agent-roles/", "lab/workflow/roles/")) for p in touched):
        r = subprocess.run([sys.executable, str(ctx.HUB / "tools" / "role_sync.py"), "render"], cwd=str(ctx.HUB),
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            warnings.append("re-rendering the role files failed: " + (r.stderr or r.stdout)[-300:])
    return warnings


def _history() -> list[dict]:
    out = []
    for f in sorted((_home() / "history").glob("*/publish.json"), reverse=True):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def publish(body: dict) -> tuple[dict, int]:
    ch = changes()
    if not ch:
        return {"error": "the draft has no changes"}, 400
    probs = problems()
    if probs:
        return {"error": "fix these first: " + " · ".join(probs[:3]), "problems": probs}, 409
    base = (_meta() or {}).get("base") or {}
    moved = [c["path"] for c in ch if _sha(ctx.HUB / c["path"]) != base.get(c["path"])]
    if moved:
        return {"error": "changed in the lab since your draft began (by a proposal you accepted, or by hand): "
                         + ", ".join(moved[:5]) + " — discard the draft and redo the edit", "conflicts": moved}, 409
    hid = time.strftime("%Y%m%d-%H%M%S")
    hdir = _home() / "history" / hid
    rec = {"id": hid, "ts": ctx.ts(), "note": str(body.get("note") or "").strip()[:300], "files": []}
    for c in ch:
        rel, real = c["path"], ctx.HUB / c["path"]
        if real.is_file():
            (hdir / "before" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(real, hdir / "before" / rel)
        if c["status"] == "removed":
            real.unlink(missing_ok=True)
            _prune(real.parent, ctx.HUB)
        else:
            real.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_draft() / rel, real)
        rec["files"].append({"path": rel, "status": c["status"], "after": _sha(real)})
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / "publish.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    _op_discard({})
    warnings = _after_change([f["path"] for f in rec["files"]])
    ctx.pi_log({"action": "compose.publish", "id": hid, "files": [f["path"] for f in rec["files"]], "note": rec["note"]})
    ctx.emit_hub("lab_composed", detail=rec["note"] or f"{len(ch)} change(s) to the lab's definition")
    return {"ok": True, "id": hid, "note": f"Published {len(ch)} change{'s' if len(ch) != 1 else ''} — runs started "
                                            "from now use them", "warnings": warnings}, 200


def undo(body: dict) -> tuple[dict, int]:
    hid = str(body.get("id") or "")
    hist = [h for h in _history() if not h.get("undone")]
    if not hist or hist[0].get("id") != hid:
        return {"error": "only the latest publish can be undone"}, 400
    if active():
        return {"error": "publish or discard your draft first"}, 409
    rec, hdir = hist[0], _home() / "history" / hid
    moved = [f["path"] for f in rec["files"] if _sha(ctx.HUB / f["path"]) != f.get("after")]
    if moved:
        return {"error": "changed since that publish: " + ", ".join(moved[:5]), "conflicts": moved}, 409
    for f in rec["files"]:
        real, before = ctx.HUB / f["path"], hdir / "before" / f["path"]
        if before.is_file():
            real.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(before, real)
        else:
            real.unlink(missing_ok=True)
            _prune(real.parent, ctx.HUB)
    rec["undone"] = ctx.ts()
    (hdir / "publish.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    warnings = _after_change([f["path"] for f in rec["files"]])
    ctx.pi_log({"action": "compose.undo", "id": hid})
    ctx.emit_hub("lab_composed", detail=f"undid the publish of {rec['ts']}")
    return {"ok": True, "note": "Undone — the lab is back as it was before that publish", "warnings": warnings}, 200


# ── what the page shows (GET /api/compose, /api/compose/file) ─────────────────────────────────────
def draft_info() -> dict:
    on = active()
    ch = changes() if on else []
    return {"active": on, "created": (_meta() or {}).get("created") if on else None, "changes": ch,
            "problems": problems() if on else []}


def _origin(rel: str) -> str:
    """'built-in' when this code ships the same path, else 'yours'."""
    return "built-in" if (ctx.ROOT / rel).exists() else "yours"


def _first_doc(text: str) -> str:
    m = re.search(r'"""(.*?)"""', text or "", re.S)
    return " ".join((m.group(1) if m else "").split())[:220]


def view(q: dict | None = None) -> tuple[dict, int]:
    on = active()
    root = _draft() if on else ctx.HUB
    wf = _wf()
    labfiles = ctx.labfiles
    out: dict = {"ok": True, "draft": draft_info()}
    try:
        m = wf.load(root)
    except Exception as e:  # noqa: BLE001 — show the draft and the error; the PI fixes the file
        out["error"] = f"the workflow can't be read: {e}"
        return out, 200
    skills = root / ".claude" / "skills"
    procs = {}
    for name, p in (m.get("procedures") or {}).items():
        meta = wf.skill_meta(ctx.read(skills / name / "SKILL.md") or "")
        own = meta.get("newts") or {}
        folder = skills / name
        procs[name] = {**{k: v for k, v in p.items() if not k.startswith("_")}, "description": meta.get("description", ""),
                       "own": sorted(own), "like": own.get("like"), "origin": _origin(f".claude/skills/{name}/SKILL.md"),
                       "stages": [s["id"] for s in m.get("stages", []) if name in (s.get("procedures") or [])],
                       "has_method": (folder / "METHOD.md").is_file(),
                       "files": sorted(f.relative_to(root).as_posix() for f in folder.rglob("*")
                                       if f.is_file() and "__pycache__" not in f.parts) if folder.is_dir() else []}
    roles = []
    rdir = root / "agent-roles"
    for r in wf.roles(root):
        y = labfiles.load_yaml(rdir / f"{r}.yaml")
        roles.append({"name": r, "label": wf.role_labels(root).get(r, r), "description": str(y.get("description") or ""),
                      "like": y.get("like"), "origin": _origin(f"agent-roles/{r}.yaml"),
                      "files": [f"agent-roles/{r}.yaml", f"agent-roles/{r}.md"]})
    rooms = []
    for r in m.get("rooms", []):
        look = "yours" if (root / "lab" / "rooms3d" / f"{r['id']}.json").is_file() else \
            "built-in" if (ctx.ROOT / "dashboard" / "static" / "world3d" / "rooms" / f"{r['id']}.js").is_file() else "plain"
        rooms.append({**r, "look3d": look})
    rl = wf.rules(root)
    rules = {g: [{"id": x.get("id"), "text": str(x.get("text") or ""), "checks": x.get("checks") or []}
                 for x in rl.get(f"{g}_rules") or []] for g in ("hard", "subagent", "project")}
    locked = {k: rl.get(k) for k in LOCKED_TABLES if k in rl}
    checks = []
    files = {f.name: f for d in (ctx.ROOT / "checks", root / "checks") if d.is_dir() for f in d.glob("*.py")}   # the lab's win
    for fname, f in sorted(files.items()):
        txt = ctx.read(f) or ""
        nm = re.search(r'^NAME = "([^"]+)"', txt, re.M)
        checks.append({"name": nm.group(1) if nm else f.stem.replace("_", "-"), "file": f"checks/{fname}",
                       "guard": bool(nm), "doc": _first_doc(txt), "origin": _origin(f"checks/{fname}")})
    types = []
    for name, txt in labfiles.project_types(root).items():
        own = (root / "lab" / "templates" / "project-types" / name).is_dir()
        base = f"{'lab/templates' if own else 'templates'}/project-types/{name}"
        types.append({"name": name, "title": (txt.splitlines() or [""])[0].lstrip("# ").strip(), "origin": "yours" if own else "built-in",
                      "files": sorted(f.relative_to(root).as_posix() for f in (root / base).rglob("*") if f.is_file())})
    domains = [{"name": n, "file": p.relative_to(root).as_posix() if p.is_relative_to(root) else None}
               for n, p in labfiles.domain_profiles(root).items()]
    lab_custom = wf.status(root)
    out.update({
        "states": m.get("states", []), "side_states": m.get("side_states", []), "gates": m.get("gates", []),
        "stages": m.get("stages", []), "rooms": rooms, "next_for_state": m.get("next_for_state", {}),
        "offer_for_state": m.get("offer_for_state", {}), "procedures": procs, "roles": roles,
        "designs": designs(),
        "rules": rules, "locked": locked, "built_in_checks": sorted(wf.BUILT_IN_CHECKS), "checks": checks,
        "types": types, "domains": domains, "custom": lab_custom,
        "proposals": [{k: r.get(k) for k in ("id", "kind", "name", "study", "why", "by", "ts")} for r in wf.proposals(ctx.HUB)],
        "history": [{k: h.get(k) for k in ("id", "ts", "note", "undone")} | {"n": len(h.get("files") or []),
                    "files": [f["path"] for f in h.get("files") or []][:12]} for h in _history()[:15]],
        "studies_in": {s: n for s, n in _study_counts().items()},
    })
    return out, 200


def _study_counts() -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        for r in sources.parse_registry():
            if r.get("state"):
                out[r["state"]] = out.get(r["state"], 0) + 1
    except Exception:  # noqa: BLE001
        pass
    return out


def file_get(q: dict) -> tuple[dict, int]:
    """One definition file: as the draft has it (or the lab, with no draft) and as published."""
    try:
        rel = _rel(q.get("path"))
    except ComposeError as e:
        return {"error": str(e)}, 400
    def norm(s):
        return s.replace("\r\n", "\n") if s is not None else None
    cur, pub = ctx.read(_root() / rel), ctx.read(ctx.HUB / rel)
    if cur is None and pub is None and rel.startswith("checks/"):
        cur = pub = ctx.read(ctx.ROOT / rel)      # a check this code ships that the lab doesn't override
    return {"ok": True, "path": rel, "text": norm(cur), "published": norm(pub)}, 200
