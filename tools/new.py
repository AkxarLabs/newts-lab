#!/usr/bin/env python3
"""Add something to the lab by copying the closest thing it already has — no hand-edited YAML.

    uv run --with pyyaml python tools/new.py skill <name> --like <skill> [--stage <stage>] [--title "…"]
    uv run --with pyyaml python tools/new.py room  <id>   --like <room>  [--states a,b] [--title "…"] [--plain]
    uv run --with pyyaml python tools/new.py role  <name> --like <role>  [--label "…"]
    uv run --with pyyaml python tools/new.py check <name> --like <check>
    uv run --with pyyaml python tools/new.py type  <name> --like <type>
    uv run --with pyyaml python tools/new.py rule  <id>   --text "**Title.** What it says." [--list hard|subagent|project] [--check <name>]

What each one does:
  skill  copies the skill's folder (SKILL.md contract, METHOD.md); the copy's frontmatter says `like: <skill>`, so
         it inherits the definition (level, mode, args, outputs, …) and overrides what you change; `--stage`
         lists it in that stage. Edit its contract and method — they are the copy's own.
  room   adds its line to workflow/stages.yaml (on the next free plot of the table) and, when the lab has its own
         look for the like (lab/rooms3d/<like>.json), copies it as lab/rooms3d/<id>.json — else the room is drawn
         plain until it is designed (Compose → the room → Look, or /design-room <id> "…"); `--plain`: never copy.
         `--states` moves those states into it.
  role   copies agent-roles/<role>.yaml + .md with `like: <role>` and renders it for every CLI.
  check  copies checks/<check>.py under the new name (the guard finds it by itself).
  type   copies templates/project-types/<type>/ into lab/templates/project-types/<name>/.
  rule   appends a rule to workflow/rules.yaml.
Then the generated docs are refreshed (tools/workflow.py render-docs). A lab's own components are the
PI's: a headless run can't write them, and the signature guard refuses this tool from a run.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HUB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import workflow  # noqa: E402

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")


class NewError(ValueError):
    """Refused, with a message fit to show the PI."""


def _name(name: str) -> str:
    if not NAME_RE.match(name or ""):
        raise NewError(f"'{name}': use lower-case letters, digits and dashes (e.g. data-room)")
    return name


def _title(name: str) -> str:
    return name.replace("-", " ").capitalize()


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _rename_refs(text: str, old: str, new: str) -> str:
    """`/old` (the slash command) and `brief old` → the new name; other mentions are left to the PI."""
    text = re.sub(r"(?<![\w/-])/" + re.escape(old) + r"(?![\w-])", "/" + new, text)
    return re.sub(r"\bbrief " + re.escape(old) + r"(?![\w-])", "brief " + new, text)


# ── skill ────────────────────────────────────────────────────────────────────────────────────────
def new_skill(hub: Path, name: str, like: str, stage: str | None = None, title: str | None = None) -> list[Path]:
    name = _name(name)
    skills = hub / ".claude" / "skills"
    src, dst = skills / like, skills / name
    if not (src / "SKILL.md").is_file():
        raise NewError(f"no skill '{like}' to copy (.claude/skills/{like}/SKILL.md)")
    if dst.exists():
        raise NewError(f".claude/skills/{name}/ already exists")
    text = _read(src / "SKILL.md")
    m = re.match(r"\A---\n(.*?)\n---\n", text.replace("\r\n", "\n"), re.S)
    if not m:
        raise NewError(f"/{like}'s SKILL.md has no frontmatter")
    meta = workflow.skill_meta(text)
    desc = str(meta.get("description") or "").replace('"', "'")
    fm = (f"---\nname: {name}\ndescription: \"A variant of /{like} — say here what /{name} does. ({desc[:200]})\"\n"
          f"newts:\n  like: {like}            # its definition is /{like}'s, except what is listed below\n"
          f"  title: {title or _title(name)}\n---\n")
    body = _rename_refs(text.replace("\r\n", "\n")[m.end():], like, name)
    out = [dst / "SKILL.md"]
    _write(dst / "SKILL.md", fm + body)
    if (src / "METHOD.md").is_file():
        _write(dst / "METHOD.md", _read(src / "METHOD.md"))
        out.append(dst / "METHOD.md")
    if stage:
        _add_to_stage(hub, stage, name)
        out.append(hub / "workflow" / "stages.yaml")
    return out


def _add_to_stage(hub: Path, stage: str, proc: str) -> None:
    p = hub / "workflow" / "stages.yaml"
    text = _read(p)
    rx = re.compile(r"^(  - \{id: " + re.escape(stage) + r",[^\n]*?procedures: \[)([^\]]*)\]", re.M)
    hit = rx.search(text)
    if not hit:
        raise NewError(f"no stage '{stage}' in workflow/stages.yaml")
    procs = [x.strip() for x in hit.group(2).split(",") if x.strip()]
    if proc not in procs:
        text = text[:hit.start()] + hit.group(1) + ", ".join(procs + [proc]) + "]" + text[hit.end():]
        _write(p, text)


# ── room ─────────────────────────────────────────────────────────────────────────────────────────
def _room_look(hub: Path, room: str) -> Path | None:
    """The lab's own look for a room (data), if it has one — a built-in look is code, and stays the built-in's."""
    f = hub / "lab" / "rooms3d" / f"{room}.json"
    return f if f.is_file() else None


def new_room(hub: Path, rid: str, like: str, states: list[str] | None = None, title: str | None = None,
             plain: bool = False) -> list[Path]:
    rid = _name(rid)
    m = workflow.load(hub)
    rooms = {r["id"]: r for r in m.get("rooms", [])}
    if rid in rooms:
        raise NewError(f"there is already a room '{rid}'")
    if like not in rooms:
        raise NewError(f"no room '{like}' to copy")
    known = {s["id"]: s for s in m.get("states", []) + m.get("side_states", [])}
    states = [s for s in (states or []) if s]
    for s in states:
        if s not in known:
            raise NewError(f"no state '{s}' (add it to workflow/stages.yaml first)")
    out = []
    look = None if plain else _room_look(hub, like)
    if look:
        data = json.loads(_read(look))
        data["key"] = rid
        if title:
            data["title"] = title
        dst = hub / "lab" / "rooms3d" / f"{rid}.json"
        _write(dst, json.dumps(data, indent=1) + "\n")
        out.append(dst)
    p = hub / "workflow" / "stages.yaml"
    text = _read(p)
    for s in states:                    # move each state: out of its old room, into this one
        old = known[s].get("room")
        text = re.sub(r"(^  - \{id: " + re.escape(old) + r",[^\n]*?states: \[)([^\]]*)\]",
                      lambda h: h.group(1) + ", ".join(x.strip() for x in h.group(2).split(",") if x.strip() and x.strip() != s) + "]",
                      text, count=1, flags=re.M)
        line = re.compile(r"^(  - \{id: " + re.escape(s) + r",[^\n]*)$", re.M)
        hit = line.search(text)
        if hit:
            text = text[:hit.start()] + re.sub(r"room: [\w-]+", f"room: {rid}", hit.group(1)) + text[hit.end():]
    head = re.search(r"^rooms:[^\n]*\n((?:  - \{[^\n]*\n|\s*#[^\n]*\n)*)", text, re.M)
    last = list(re.finditer(r"^  - \{id: [\w-]+,[^\n]*$", head.group(1), re.M)) if head else []
    if not last:
        raise NewError("can't find the rooms: list in workflow/stages.yaml")
    entry = (f"  - {{id: {rid}, label: {_title(rid)}, title: {title or 'The ' + _title(rid)}, "
             f"states: [{', '.join(states)}]}}")
    at = head.start(1) + last[-1].end()
    text = text[:at] + "\n" + entry + text[at:]
    _write(p, text)
    out.append(p)
    return out


# ── role, check, type, rule ──────────────────────────────────────────────────────────────────────
def new_role(hub: Path, name: str, like: str, label: str | None = None) -> list[Path]:
    name = _name(name)
    d = hub / "agent-roles"
    if not (d / f"{like}.yaml").is_file():
        raise NewError(f"no role '{like}' to copy (agent-roles/{like}.yaml)")
    if (d / f"{name}.yaml").exists():
        raise NewError(f"agent-roles/{name}.yaml already exists")
    _write(d / f"{name}.yaml", f"name: {name}\nlabel: {label or _title(name)}\nlike: {like}             # tools, model key and "
                               f"codex settings are {like}'s unless set here\ndescription: \"A variant of {like} — say here what it does.\"\n")
    _write(d / f"{name}.md", _read(d / f"{like}.md"))
    import role_sync  # noqa: PLC0415
    old, role_sync.HUB = role_sync.HUB, hub
    try:
        role_sync.render()
    finally:
        role_sync.HUB = old
    return [d / f"{name}.yaml", d / f"{name}.md"]


def new_check(hub: Path, name: str, like: str) -> list[Path]:
    name = _name(name)
    src = next((d / f"{like.replace('-', '_')}.py" for d in (hub / "checks", HUB / "checks")
                if (d / f"{like.replace('-', '_')}.py").is_file()), None)
    if not src:
        raise NewError(f"no check '{like}' to copy (checks/{like.replace('-', '_')}.py)")
    dst = hub / "checks" / f"{name.replace('-', '_')}.py"
    if dst.exists():
        raise NewError(f"checks/{dst.name} already exists")
    text = re.sub(r'^NAME = "[^"]*"', f'NAME = "{name}"', _read(src), count=1, flags=re.M)
    _write(dst, text.replace(f"guard.py {like}", f"guard.py {name}"))
    return [dst]


def new_type(hub: Path, name: str, like: str) -> list[Path]:
    name = _name(name)
    sys.path.insert(0, str(HUB / "tools"))
    import labfiles  # noqa: PLC0415
    src = labfiles.template(hub, f"project-types/{like}")
    if not (src / "TYPE.md").is_file():
        raise NewError(f"no project type '{like}' to copy")
    if name in labfiles.project_types(hub):
        raise NewError(f"there is already a project type '{name}'")
    dst = hub / "lab" / "templates" / "project-types" / name
    shutil.copytree(src, dst)
    card = dst / "TYPE.md"
    text = re.sub(r"\A# Project type: `[^`]*`( \(default\))?", f"# Project type: `{name}`", _read(card), count=1)
    _write(card, text)
    return [card]


def new_rule(hub: Path, rid: str, text: str, which: str = "hard", check: str | None = None) -> list[Path]:
    rid = _name(rid)
    p = hub / "workflow" / "rules.yaml"
    body = _read(p)
    key = f"{which}_rules"
    if any(r.get("id") == rid for g in ("hard_rules", "subagent_rules", "project_rules")
           for r in (workflow.rules(hub).get(g) or [])):
        raise NewError(f"there is already a rule '{rid}'")
    if not (text or "").strip():
        raise NewError("say what the rule is (--text)")
    start = re.search(rf"^{key}:", body, re.M)
    if not start:
        raise NewError(f"workflow/rules.yaml has no {key}: list")
    nxt = re.search(r"^\S", body[start.end():], re.M)
    end = start.end() + (nxt.start() if nxt else len(body) - start.end())
    while body[end - 1:end] == "\n" and body[end - 2:end] == "\n\n":
        end -= 1
    import json  # noqa: PLC0415 — a JSON string is a valid YAML scalar, and escapes everything that needs it
    entry = f"  - id: {rid}\n" + (f"    checks: [{check}]\n" if check else "") + f"    text: {json.dumps(text.strip(), ensure_ascii=False)}\n"
    _write(p, body[:end] + entry + body[end:])
    return [p]


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="kind", required=True)
    for kind in ("skill", "room", "role", "check", "type"):
        p = sub.add_parser(kind)
        p.add_argument("name")
        p.add_argument("--like", required=True, help=f"the {kind} to copy")
        if kind == "skill":
            p.add_argument("--stage")
            p.add_argument("--title")
        if kind == "room":
            p.add_argument("--states", default="")
            p.add_argument("--title")
            p.add_argument("--plain", action="store_true")
        if kind == "role":
            p.add_argument("--label")
    r = sub.add_parser("rule")
    r.add_argument("name")
    r.add_argument("--text", required=True)
    r.add_argument("--list", default="hard", choices=["hard", "subagent", "project"])
    r.add_argument("--check")
    a = ap.parse_args(argv)
    try:
        if a.kind == "skill":
            files = new_skill(HUB, a.name, a.like, a.stage, a.title)
        elif a.kind == "room":
            files = new_room(HUB, a.name, a.like, [s.strip() for s in a.states.split(",")], a.title, a.plain)
        elif a.kind == "role":
            files = new_role(HUB, a.name, a.like, a.label)
        elif a.kind == "check":
            files = new_check(HUB, a.name, a.like)
        elif a.kind == "type":
            files = new_type(HUB, a.name, a.like)
        else:
            files = new_rule(HUB, a.name, a.text, a.list, a.check)
    except NewError as e:
        print(f"[new] {e}", file=sys.stderr)
        return 2
    workflow.render_docs(HUB)
    for f in files:
        print(f"[new] wrote {f.relative_to(HUB).as_posix() if f.is_relative_to(HUB) else f}")
    probs = workflow.check(HUB)
    for x in probs:
        print(f"[new] check: {x}")
    return 1 if probs else 0


if __name__ == "__main__":
    raise SystemExit(main())
