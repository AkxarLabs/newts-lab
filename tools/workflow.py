#!/usr/bin/env python3
"""The research workflow: one definition (workflow/stages.yaml + each skill's own frontmatter) + the PI's own
instructions per stage.

    uv run --with pyyaml python tools/workflow.py check                    # validate the manifest
    uv run --with pyyaml python tools/workflow.py brief <proc> [--study S] # what an agent reads for a stage
    uv run --with pyyaml python tools/workflow.py propose --proc P [--study S] --mode add|replace --file F
    uv run --with pyyaml python tools/workflow.py render-docs [--check]   # regenerate the docs tables
    uv run --with pyyaml python tools/workflow.py show                    # the effective customisations

Layers, all PI-owned (agents read them, never edit them — they `propose`):
    lab/workflow/<proc>.add.md          instructions ADDED to a procedure, lab-wide
    lab/workflow/<proc>.method.md       a REPLACEMENT for the procedure's default method (METHOD.md)
    lab/workflow/stage.<stage>.add.md   instructions for every procedure of a stage
    lab/workflow/roles/<role>.add.md    instructions added to a subagent role (rendered by role_sync)
    studies/<slug>/workflow/…           the same names, for one study (they win over the lab's)

A procedure is a skill folder, .claude/skills/<name>/: its SKILL.md frontmatter's `newts:` block defines it
(kind, level, mode, args, launchable, replaceable, title, does, stops, outputs, …; a skill without one is a
launchable utility), so adding a procedure is adding a folder. A procedure's SKILL.md is its fixed contract (guard calls, ledgers, gates, stop points, the run footer) and
always binds; METHOD.md is how the work is done, and is what a replacement swaps out. Precedence on a
conflict: the contract + AGENTS.md hard rules > the project's TYPE.md > study instructions > lab
instructions > the method.

Import-safe and cheap (guard.py imports it for the lifecycle): no I/O at import, the manifest is cached by
mtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import textwrap
import time
from pathlib import Path

import yaml

HUB = Path(__file__).resolve().parents[1]
MANIFEST = Path("workflow") / "stages.yaml"
SKILLS = Path(".claude") / "skills"
# what a skill's `newts:` block may leave out (a skill with no block at all is a launchable utility)
PROC_DEFAULTS = {"kind": "utility", "level": "hub", "mode": "headless", "args": "text?", "launchable": True,
                 "replaceable": False}
_KIND_ORDER = {"stage": 0, "driver": 1, "entry": 2, "utility": 3}
MAX_CUSTOM = 20000          # characters per customisation file
GATES = (1, 2, 3)            # fixed: the manifest must declare exactly these
NEVER_LAUNCH = {"finalize"}  # never from a click / chain / campaign — a Gate 3 signature is the only door
                             # (the executor's spec.NEVER is this set; `check` refuses a manifest that disagrees)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_cache: dict[str, tuple[float, dict]] = {}


def _hub(hub=None) -> Path:
    return Path(hub).resolve() if hub else HUB


def _skill_files(root: Path) -> list[Path]:
    return sorted(f for f in root.glob("*/SKILL.md") if f.is_file()) if root.is_dir() else []


def load(hub=None) -> dict:
    """The manifest as a dict, with `procedures` built from the skills (cached until any of those files
    changes): the lab's own copies (they ship with the lab), else this code's. Raises yaml errors."""
    h = _hub(hub)
    p = h / MANIFEST if (h / MANIFEST).is_file() else HUB / MANIFEST
    root = h / SKILLS if (h / SKILLS).is_dir() else HUB / SKILLS
    files = _skill_files(root)
    sig = (p.stat().st_mtime, tuple((f.parent.name, f.stat().st_mtime) for f in files))
    key = f"{p}|{root}"
    hit = _cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data["procedures"] = _procedures(files, data)
    _cache[key] = (sig, data)
    return data


def skill_meta(text: str) -> dict:
    """A SKILL.md's frontmatter, read the way agent CLIs read it: top-level `key: value` lines taken as text
    (descriptions need not be strict YAML), and the `newts:` block — the procedure definition — as YAML."""
    m = _FM.match((text or "").replace("\r\n", "\n"))
    out: dict = {}
    if not m:
        return out
    key, buf = None, []

    def flush():
        if key == "newts":
            try:
                block = yaml.safe_load(textwrap.dedent("\n".join(buf[1:])))
            except yaml.YAMLError:
                block = None
            out["newts"] = block if isinstance(block, dict) else {}
        elif key:
            out[key] = " ".join(x.strip() for x in buf).strip().strip("'\"")

    for ln in m.group(1).split("\n"):
        if ln[:1] not in ("", " ", "\t", "#") and ":" in ln:
            flush()
            key, _, val = ln.partition(":")
            key, buf = key.strip(), [val]
        else:
            buf.append(ln)
    flush()
    return out


def _procedures(files: list[Path], m: dict) -> dict[str, dict]:
    """{name: definition} from each skill's frontmatter — the stages' procedures first, in stage order."""
    found = {}
    # a lab made before skills defined themselves: its manifest still lists the procedures, and a skill of
    # its with no `newts:` block takes this code's definition of the same procedure
    legacy = m.get("procedures") if isinstance(m.get("procedures"), dict) else {}
    for f in files:
        fm = skill_meta(_read(f))
        block = fm.get("newts")
        p = dict(PROC_DEFAULTS)
        if not isinstance(block, dict):
            ours = HUB / SKILLS / f.parent.name / "SKILL.md"
            if ours.is_file() and ours.resolve() != f.resolve():
                p.update(skill_meta(_read(ours)).get("newts") or {})
        p.update(legacy.get(f.parent.name) or {})
        p.update(block if isinstance(block, dict) else {})
        p.setdefault("title", fm.get("name") or f.parent.name)
        p.setdefault("does", str(fm.get("description") or "").split(". ")[0][:200])
        found[f.parent.name] = p
    staged = [n for st in m.get("stages", []) for n in st.get("procedures", []) if n in found]
    first = list(dict.fromkeys(staged))
    rest = sorted((n for n in found if n not in first), key=lambda n: (_KIND_ORDER.get(found[n].get("kind"), 9), n))
    return {n: found[n] for n in first + rest}


# ── the lifecycle (guard.py's transition oracle reads these) ─────────────────────────────────────
def lifecycle(hub=None) -> list[str]:
    return [s["id"] for s in load(hub).get("states", [])]


def side_states(hub=None) -> list[str]:
    return [s["id"] for s in load(hub).get("side_states", [])]


def back_edges(hub=None) -> set[tuple[str, str]]:
    return {(a, b) for a, b in load(hub).get("back_edges", [])}


def terminal_states(hub=None) -> set[str]:
    m = load(hub)
    return {s["id"] for s in m.get("states", []) + m.get("side_states", []) if s.get("terminal")}


def revivable_states(hub=None) -> list[str]:
    return [s["id"] for s in load(hub).get("states", []) if s.get("revivable")]


def procedure(name: str, hub=None) -> dict | None:
    return (load(hub).get("procedures") or {}).get(name)


def launch_registry(hub=None) -> dict[str, dict]:
    """{skill: {level, mode, args, hint}} for every procedure a click may launch (the executor's allowlist)."""
    out = {}
    for name, p in (load(hub).get("procedures") or {}).items():
        if p.get("launchable") and name not in NEVER_LAUNCH:
            out[name] = {"level": p["level"], "mode": p["mode"], "args": p.get("args", ""), "hint": p.get("hint", ""),
                         "in_project": bool(p.get("in_project"))}
    return out


def not_dispatchable(hub=None) -> set[str]:
    """Procedures a campaign pass may not dispatch as their own runs (`dispatchable: false`, plus finalize)."""
    return {n for n, p in (load(hub).get("procedures") or {}).items() if p.get("dispatchable") is False} | NEVER_LAUNCH


def gate_state(n: int, hub=None) -> str | None:
    """The registry state a gate is signed at (Gate 1: proposal · Gate 3: internal-review)."""
    return next((g.get("at") for g in load(hub).get("gates", []) if g.get("n") == n), None)


def gate_before(n: int, hub=None) -> str | None:
    """The state a gate opens (Gate 1: active · Gate 3: final) — what the guard and the dashboard refuse to
    enter until the gate is signed."""
    return next((g.get("before") for g in load(hub).get("gates", []) if g.get("n") == n), None)


def after_gate(n: int, hub=None) -> str | None:
    """The procedure that runs once a gate is signed (Gate 1 → spawn-project)."""
    v = (load(hub).get("next_for_state") or {}).get(gate_state(n, hub))
    return v.get("signed") if isinstance(v, dict) else v


def tracks(hub=None) -> dict[str, list[str]]:
    return load(hub).get("tracks") or {}


def results_states(hub=None) -> set[str]:
    """States where a study has results (`results: true`)."""
    m = load(hub)
    return {s["id"] for s in m.get("states", []) + m.get("side_states", []) if s.get("results")}


def revive_default(hub=None) -> str:
    rev = revivable_states(hub)
    want = load(hub).get("revive_to")
    return want if want in rev else (rev[0] if rev else lifecycle(hub)[0])


def campaign_driver(hub=None) -> str | None:
    """The procedure that runs a signed campaign (its args are `campaign`): what the keeper starts each cycle."""
    return next((n for n, p in (load(hub).get("procedures") or {}).items() if p.get("args") == "campaign"), None)


def stages_of(proc: str, hub=None) -> list[dict]:
    return [s for s in load(hub).get("stages", []) if proc in s.get("procedures", [])]


def stage_of_state(state: str, hub=None) -> str | None:
    for s in load(hub).get("states", []):
        if s["id"] == state:
            return s.get("stage")
    return None


def ui_view(hub=None) -> dict:
    """What the dashboard needs: the manifest's vocabulary + the PI's customisations + pending proposals."""
    m = load(hub)
    keep = ("title", "does", "stops", "kind", "level", "mode", "args", "hint", "launchable", "replaceable",
            "outputs", "anchors", "uses", "start")
    procs = {n: {k: p[k] for k in keep if k in p} for n, p in (m.get("procedures") or {}).items()}
    pend = proposals(hub)
    return {
        "states": m.get("states", []), "side_states": m.get("side_states", []), "gates": m.get("gates", []),
        "stages": m.get("stages", []), "rooms": m.get("rooms", []), "tracks": m.get("tracks", {}),
        "next_for_state": m.get("next_for_state", {}), "offer_for_state": m.get("offer_for_state", {}),
        "back_edges": m.get("back_edges", []), "roles": m.get("roles", []), "procedures": procs,
        "revive_to": revive_default(hub),
        "custom": status(hub), "study_custom": studies_customised(hub),
        "proposals": [{k: r.get(k) for k in ("id", "kind", "name", "study", "why", "by", "ts")} for r in pend],
    }


# ── validation ───────────────────────────────────────────────────────────────────────────────────
def check(hub=None) -> list[str]:
    """Problems with the manifest (empty = consistent)."""
    hub = _hub(hub)
    try:
        m = load(hub)
    except (OSError, yaml.YAMLError) as e:
        return [f"{MANIFEST}: {e}"]
    probs: list[str] = []
    states = [s.get("id") for s in m.get("states", [])]
    side = [s.get("id") for s in m.get("side_states", [])]
    allst = states + side
    procs = m.get("procedures") or {}
    stage_ids = [s.get("id") for s in m.get("stages", [])]
    if len(set(allst)) != len(allst):
        probs.append("duplicate state ids")
    for s in m.get("states", []):
        if s.get("stage") not in stage_ids:
            probs.append(f"state {s.get('id')}: unknown stage {s.get('stage')!r}")
    for a, b in m.get("back_edges", []):
        if a not in states or b not in states:
            probs.append(f"back edge {a}→{b}: unknown state")
    if sorted(g.get("n") for g in m.get("gates", [])) != list(GATES):
        probs.append("gates must be exactly 1, 2 and 3")
    for g in m.get("gates", []):
        for k in ("at", "before"):
            if g.get(k) and g[k] not in states:
                probs.append(f"gate {g.get('n')}: unknown state {g[k]!r}")
    for st in m.get("stages", []):
        for x in st.get("states", []):
            if x not in states:
                probs.append(f"stage {st.get('id')}: unknown state {x!r}")
        for p in st.get("procedures", []):
            if p not in procs:
                probs.append(f"stage {st.get('id')}: unknown procedure {p!r}")
    covered = {x for st in m.get("stages", []) for x in st.get("states", [])}
    for x in states:
        if x not in covered:
            probs.append(f"state {x} belongs to no stage")
    roomed = {x for r in m.get("rooms", []) for x in r.get("states", [])}
    for x in allst:
        if x not in roomed:
            probs.append(f"state {x} has no room")
    for table in ("next_for_state", "offer_for_state"):
        for st, v in (m.get(table) or {}).items():
            if st not in allst:
                probs.append(f"{table}: unknown state {st!r}")
            vals = list(v.values()) if isinstance(v, dict) else (v if isinstance(v, list) else [v])
            for p in vals:
                if p not in procs:
                    probs.append(f"{table}[{st}]: unknown procedure {p!r}")
    for name, p in procs.items():
        skill = (hub / SKILLS if (hub / SKILLS).is_dir() else HUB / SKILLS) / name / "SKILL.md"
        fm_name = skill_meta(_read(skill)).get("name")
        if fm_name and fm_name != name:
            probs.append(f"skill {name}: its frontmatter says name: {fm_name} (the folder name is the procedure)")
        if p.get("kind") not in _KIND_ORDER:
            probs.append(f"procedure {name}: kind must be one of {', '.join(_KIND_ORDER)}")
        if p.get("level") not in ("hub", "project") or p.get("mode") not in ("headless", "interactive"):
            probs.append(f"procedure {name}: level must be hub|project and mode headless|interactive")
        if name in NEVER_LAUNCH and p.get("launchable"):
            probs.append(f"procedure {name} must never be launchable (Gate 3 is the only door)")
        if p.get("replaceable"):
            if not (skill.parent / "METHOD.md").is_file():
                probs.append(f"procedure {name}: replaceable but has no METHOD.md")
            elif skill.is_file() and "workflow.py brief" not in skill.read_text(encoding="utf-8"):
                probs.append(f"procedure {name}: SKILL.md has no `workflow.py brief` step")
    for r in m.get("roles", []):
        if not (hub / "agent-roles" / f"{r}.md").is_file():
            probs.append(f"role {r}: no agent-roles/{r}.md")
    return probs + check_rules(hub)


BUILT_IN_CHECKS = {"spawn", "full-run", "release-full-run", "frozen", "state", "finalization"}   # in tools/guard.py


def check_rules(hub=None) -> list[str]:
    """Problems with workflow/rules.yaml: every rule has an id and text, ids are unique, every check it names
    exists (built into the guard, or a checks/<name>.py), every Gate 3 audit script exists."""
    hub = _hub(hub)
    try:
        rl = rules(hub)
    except (OSError, yaml.YAMLError) as e:
        return [f"{RULES}: {e}"]
    probs, seen = [], set()
    roots = [d for d in (hub / "checks", HUB / "checks") if d.is_dir()]
    have = BUILT_IN_CHECKS | {f.stem.replace("_", "-") for d in roots for f in d.glob("*.py")} | \
        {f.stem for d in roots for f in d.glob("*.py")}
    for group in ("hard_rules", "subagent_rules", "project_rules"):
        for r in rl.get(group) or []:
            rid = (r or {}).get("id")
            if not rid or not str((r or {}).get("text") or "").strip():
                probs.append(f"rules.yaml {group}: every rule needs an id and text ({rid or r!r})")
                continue
            if rid in seen:
                probs.append(f"rules.yaml: duplicate rule id {rid}")
            seen.add(rid)
            for c in r.get("checks") or []:
                if c not in have:
                    probs.append(f"rules.yaml {rid}: unknown check {c!r} (not built in, no checks/{c}.py)")
    for a in rl.get("gate3_audits") or []:
        script = ((a or {}).get("run") or [None])[0]
        if not script or not any((d / script).is_file() for d in roots):
            probs.append(f"rules.yaml gate3_audits: no checks/{script}")
    return probs


# ── system rules: what a method (or the PI's text) must never carry ──────────────────────────────
# Tool invocations, gates, the run footer, hard rules and the executor's env contract belong to a
# procedure's SKILL.md contract. A default METHOD.md contains none of these (a test enforces it), so
# replacing a method can never remove a system rule; the dashboard warns when PI text restates them.
SYSTEM_PATTERNS = [
    r"(?:tools|scripts)/[\w.-]+\.py(?: (?!-)[a-z][\w-]*)?",
    r"\bguard\.py [a-z][\w-]*",
    r"\blab_bus\.py (?:emit|inbox|escalate|ack)(?: [a-z_]+)?",
    r"\bneeds_pi=\w+",
    r"\brun_report\b",
    r"\bGate[ -]?[123]\b",
    r"\bhard rule \d+",
    r"\b(?:AUTOSCIENTIST|NEWTS)_[A-Z_]+\b",
    r"\bAskUserQuestion\b",
    r"\bclaims\.yaml\b",
    r"\bHUB-WRITEBACK\b",
    r"\bstate\s*(?:→|->)\s*`?[a-z][\w-]*`?",
    r"\blab/REGISTRY\.md\b",
]
_SYS = re.compile("|".join(f"(?:{p})" for p in SYSTEM_PATTERNS))


def system_tokens(text: str) -> set[str]:
    return {m.group(0) for m in _SYS.finditer(text or "")}


# ── the PI's customisations ──────────────────────────────────────────────────────────────────────
def _safe(name: str) -> bool:
    return bool(name) and bool(_SLUG.match(name))


def custom_dir(hub=None, study: str | None = None) -> Path:
    hub = _hub(hub)
    if study:
        if not _safe(study):
            raise ValueError(f"bad study slug {study!r}")
        return hub / "studies" / study / "workflow"
    return hub / "lab" / "workflow"


def custom_file(kind: str, name: str, hub=None, study: str | None = None) -> Path:
    """kind: add | method | stage | role → the file that holds that customisation."""
    if not _safe(name):
        raise ValueError(f"bad name {name!r}")
    d = custom_dir(hub, study)
    if kind == "add":
        return d / f"{name}.add.md"
    if kind == "method":
        return d / f"{name}.method.md"
    if kind == "stage":
        return d / f"stage.{name}.add.md"
    if kind == "role":
        if study:
            raise ValueError("role instructions are lab-wide")
        return d / "roles" / f"{name}.add.md"
    raise ValueError(f"unknown customisation kind {kind!r}")


_FM = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


def split_frontmatter(text: str) -> tuple[dict, str]:
    text = (text or "").replace("\r\n", "\n")
    m = _FM.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def read_custom(kind: str, name: str, hub=None, study: str | None = None) -> tuple[dict, str]:
    p = custom_file(kind, name, hub, study)
    return split_frontmatter(_read(p)) if p.is_file() else ({}, "")


def sha(text: str) -> str:
    return hashlib.sha256((text or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()[:12]


def skill_dir(proc: str, hub=None) -> Path:
    h = _hub(hub)
    return (h / SKILLS if (h / SKILLS).is_dir() else HUB / SKILLS) / proc


def default_method(proc: str, hub=None) -> str:
    return _read(skill_dir(proc, hub) / "METHOD.md")


def write_custom(kind: str, name: str, text: str, hub=None, study: str | None = None) -> Path | None:
    """Save (or, with empty text, remove) one customisation. Stamps a replacement with the sha of the
    default method it replaced, so a later change to the default is flagged."""
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > MAX_CUSTOM:
        raise ValueError(f"too long ({len(text)} characters; the limit is {MAX_CUSTOM})")
    p = custom_file(kind, name, hub, study)
    if not text:
        if p.exists():
            p.unlink()
        return None
    meta = {"updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if kind == "method":
        meta["base_sha"] = sha(default_method(name, hub))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False).strip() + "\n---\n" + text + "\n",
                 encoding="utf-8", newline="\n")
    return p


def status(hub=None, study: str | None = None) -> dict:
    """What is customised: {procedures: {p: {add, method, stale}}, stages: {s: bool}, roles: {r: bool}}."""
    hub = _hub(hub)
    m = load(hub)
    out = {"procedures": {}, "stages": {}, "roles": {}}
    for name, p in (m.get("procedures") or {}).items():
        add = custom_file("add", name, hub, study).is_file()
        meth = custom_file("method", name, hub, study).is_file() if p.get("replaceable") else False
        stale = False
        if meth:
            base = read_custom("method", name, hub, study)[0].get("base_sha")
            stale = bool(base) and base != sha(default_method(name, hub))
        if add or meth:
            out["procedures"][name] = {"add": add, "method": meth, "stale": stale}
    for st in m.get("stages", []):
        if custom_file("stage", st["id"], hub, study).is_file():
            out["stages"][st["id"]] = True
    if not study:
        for r in m.get("roles", []):
            if custom_file("role", r, hub).is_file():
                out["roles"][r] = True
    return out


def studies_customised(hub=None) -> dict[str, dict]:
    hub = _hub(hub)
    out = {}
    root = hub / "studies"
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if (d / "workflow").is_dir() and _safe(d.name) and any((d / "workflow").glob("*.md")):
                out[d.name] = status(hub, d.name)
    return out


def role_addon(role: str, hub=None) -> str:
    """The PI's lab-wide instructions for a subagent role (appended by role_sync render)."""
    try:
        return read_custom("role", role, hub)[1].strip()
    except ValueError:
        return ""


# ── the brief: exactly what an agent reads for one procedure ─────────────────────────────────────
def _project_of(hub: Path, study: str) -> Path | None:
    try:
        sys.path.insert(0, str(hub / "tools"))
        from executor.lab import Lab  # noqa: PLC0415 — lazy: guard.py imports this module
        return Lab(hub).project_dir(study)
    except Exception:  # noqa: BLE001 — no registry / not spawned: no project context
        return None
    finally:
        try:
            sys.path.remove(str(hub / "tools"))
        except ValueError:
            pass


def _state_of(hub: Path, study: str) -> str | None:
    txt = _read(hub / "studies" / study / "IDEA.md")
    m = re.search(r"^state:\s*([\w-]+)", txt, re.M)
    return m.group(1) if m else None


def brief(proc: str, hub=None, study: str | None = None) -> tuple[str, str]:
    """(text, sha) — the stage brief for `proc` (optionally for one study). Raises KeyError for an unknown
    procedure."""
    hub = _hub(hub)
    p = procedure(proc, hub)
    if p is None:
        raise KeyError(proc)
    if study and not _safe(study):
        raise ValueError(f"bad study slug {study!r}")
    parts: list[str] = []
    # which stage's add-ons apply: the study's current stage if it's one of this procedure's, else all of them
    stages = stages_of(proc, hub)
    cur = stage_of_state(_state_of(hub, study) or "", hub) if study else None
    if cur and any(s["id"] == cur for s in stages):
        stages = [s for s in stages if s["id"] == cur]
    project = _project_of(hub, study) if study else None
    target = False
    if project:
        ctl = _read(project / "control.yaml")
        target = bool(re.search(r"^target:\s*\n(?:[ \t].*\n)*?[ \t]+active:\s*true", ctl, re.M))

    method_src, method = "default", default_method(proc, hub)
    if p.get("replaceable"):
        levels = ([(study, "this study")] if study else []) + [(None, "the lab")]
        for lvl, who in levels:                      # the study's replacement wins over the lab's
            meta, body = read_custom("method", proc, hub, lvl)
            if body.strip():
                method_src, method = f"replaced by the PI for {who}", body
                if meta.get("base_sha") and meta["base_sha"] != sha(default_method(proc, hub)):
                    method_src += " (the default method has changed since — the PI may want to review)"
                break

    if p.get("outputs") or p.get("anchors"):
        req = ["## What this procedure must still produce"]
        req += [f"- {o}" for o in p.get("outputs", [])]
        if p.get("anchors"):
            req.append("- other procedures rely on these parts of the contract, so any method must work "
                       "with them: " + ", ".join(p["anchors"]))
        parts.append("\n".join(req))
    if method.strip():
        parts.append(f"## Method ({method_src})\n\n" + method.strip())
    if project and (project / "TYPE.md").is_file():
        parts.append(f"## Project type\n\nThis project's `TYPE.md` ({(project / 'TYPE.md').as_posix()}) defines what a "
                     "run, a stage, multi-seed and the frozen eval mean here; it overrides the method on those "
                     "points." + (" It is target-driven: the paper stages are N/A." if target else ""))
    for who, lvl in (("lab-wide", None), ("for this study", study)):
        if who == "for this study" and not study:
            continue
        adds = []
        for st in stages:
            body = read_custom("stage", st["id"], hub, lvl)[1].strip()
            if body:
                adds.append(f"### {st['title']} (every procedure of this stage)\n\n{body}")
        body = read_custom("add", proc, hub, lvl)[1].strip()
        if body:
            adds.append(f"### /{proc}\n\n{body}")
        if adds:
            parts.append(f"## The PI's instructions — {who}\n\n" + "\n\n".join(adds))

    body = "\n\n".join(parts)
    h = sha(body)
    head = (f"NEWTS STAGE BRIEF /{proc}{' · study ' + study if study else ''} · sha={h}\n"
            "This is how to do this stage's work. The procedure's SKILL.md contract (its guard calls, ledgers, "
            "gates, stop points and run footer) and AGENTS.md's hard rules always bind and win on any conflict; "
            "then the project's TYPE.md; then the study's instructions; then the lab's; then the method. The "
            "PI owns these instructions: never edit them — to suggest a change, run "
            f"`python {(hub / 'tools' / 'workflow.py').as_posix()} propose --proc {proc} --mode add|replace --file <draft.md>`.")
    return head + ("\n\n" + body if body else "\n\n(No method file: follow SKILL.md.)"), h


# ── agent proposals (the only way an agent changes instructions) ─────────────────────────────────
def proposals_dir(hub=None) -> Path:
    return _hub(hub) / "lab" / ".bus" / "workflow-proposals"


def propose(proc: str, mode: str, text: str, hub=None, study: str | None = None, why: str = "",
            by: str = "") -> dict:
    hub = _hub(hub)
    if mode not in ("add", "replace", "stage", "role"):
        raise ValueError("mode must be add | replace | stage | role")
    kind = {"add": "add", "replace": "method", "stage": "stage", "role": "role"}[mode]
    m = load(hub)
    if kind in ("add", "method") and proc not in (m.get("procedures") or {}):
        raise ValueError(f"unknown procedure {proc!r}")
    if kind == "method" and not m["procedures"][proc].get("replaceable"):
        raise ValueError(f"/{proc}'s method is not replaceable (its SKILL.md is all contract)")
    if kind == "stage" and proc not in {s["id"] for s in m.get("stages", [])}:
        raise ValueError(f"unknown stage {proc!r}")
    if kind == "role" and proc not in m.get("roles", []):
        raise ValueError(f"unknown role {proc!r}")
    custom_file(kind, proc, hub, study)            # validates names
    text = (text or "").replace("\r\n", "\n").strip()
    if not text or len(text) > MAX_CUSTOM:
        raise ValueError(f"the proposal must be 1–{MAX_CUSTOM} characters")
    pid = time.strftime("%Y%m%d-%H%M%S") + "-" + sha(proc + mode + text)[:6]
    rec = {"id": pid, "kind": kind, "name": proc, "study": study, "text": text, "why": (why or "")[:1000],
           "by": by or "", "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "status": "pending"}
    d = proposals_dir(hub)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pid}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec


def proposals(hub=None, pending_only: bool = True) -> list[dict]:
    d = proposals_dir(hub)
    out = []
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not pending_only or r.get("status") == "pending":
                out.append(r)
    return out


def resolve_proposal(pid: str, accept: bool, hub=None) -> dict:
    if not re.match(r"^[\w-]{1,60}$", pid or ""):
        raise ValueError("bad proposal id")
    f = proposals_dir(hub) / f"{pid}.json"
    r = json.loads(f.read_text(encoding="utf-8"))
    if r.get("status") != "pending":
        raise ValueError(f"already {r.get('status')}")
    if accept:
        cur = read_custom(r["kind"], r["name"], hub, r.get("study"))[1].strip()
        text = r["text"] if r["kind"] == "method" or not cur else cur + "\n\n" + r["text"]
        write_custom(r["kind"], r["name"], text, hub, r.get("study"))
    r["status"] = "accepted" if accept else "declined"
    r["resolved"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    f.write_text(json.dumps(r, indent=1), encoding="utf-8")
    return r


# ── the rules (workflow/rules.yaml) ──────────────────────────────────────────────────────────────
RULES = Path("workflow") / "rules.yaml"
_rules_cache: dict[str, tuple[float, dict]] = {}


def rules(hub=None) -> dict:
    """workflow/rules.yaml (the lab's own, else this code's) — {} when absent."""
    h = _hub(hub)
    p = h / RULES if (h / RULES).is_file() else HUB / RULES
    if not p.is_file():
        return {}
    mt = p.stat().st_mtime
    hit = _rules_cache.get(str(p))
    if hit and hit[0] == mt:
        return hit[1]
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    _rules_cache[str(p)] = (mt, data)
    return data


def pi_owned(key: str, hub=None) -> bool:
    """A config key only the PI changes (rules.yaml pi_owned_config): an entry covers that key and everything
    under it (`agents` → `agents.tiers.strong`); `*` is a wildcard (`loop.explore_*`)."""
    import fnmatch  # noqa: PLC0415
    return any(key == k or key.startswith(k + ".") or fnmatch.fnmatchcase(key, k)
               for k in (str(x) for x in rules(hub).get("pi_owned_config") or []))


def rigor_violations(flat: dict, hub=None) -> list[str]:
    """Why these {dotted.key: value} settings would lower a rigor floor (rules.yaml rigor_floors)."""
    out = []
    for key, value in flat.items():
        f = (rules(hub).get("rigor_floors") or {}).get(key)
        if not isinstance(f, dict):
            continue
        why = f.get("why", "a rigor floor")
        if "min" in f:
            try:
                if float(value) < float(f["min"]):
                    out.append(f"{key}={value} < {f['min']} ({why})")
            except (TypeError, ValueError):
                out.append(f"{key}={value!r} is not a number ({why})")
        if "never" in f and (value == f["never"] or str(value).lower() == str(f["never"]).lower()):
            out.append(f"{key}={value} ({why})")
    return out


# ── generated docs ───────────────────────────────────────────────────────────────────────────────
DOC_BEGIN = "<!-- workflow:begin (generated by tools/workflow.py render-docs — edit workflow/stages.yaml) -->"
DOC_END = "<!-- workflow:end -->"


def docs_table(hub=None) -> str:
    m = load(hub)
    procs = m.get("procedures") or {}
    gates = {g["at"]: g["n"] for g in m.get("gates", [])}
    rows = ["| Stage | States | Procedures | Gate |", "|---|---|---|---|"]
    for st in m.get("stages", []):
        g = st.get("gate") or next((gates[x] for x in st["states"] if x in gates), None)
        rows.append(f"| {st['title']} | {', '.join('`' + x + '`' for x in st['states'])} | "
                    + ", ".join(f"`/{p}`" for p in st["procedures"] if p in procs)
                    + f" | {('Gate ' + str(g)) if g else ''} |")
    return "\n".join(rows)


DOC_TARGETS = [Path("docs") / "workflow.md"]
SKILLS_BEGIN, SKILLS_END = "<!-- skills:begin -->", "<!-- skills:end -->"   # inline: the lab's skill list
SKILLS_TARGETS = [Path("AGENTS.md")]
PROJECT_MANUAL = Path("templates") / "project" / "AGENTS.md"
_GEN = "generated by tools/workflow.py render-docs from workflow/"


def _numbered(items: list[dict]) -> str:
    return "\n".join(f"{i}. {r.get('text', '').strip()}" for i, r in enumerate(items, 1))


def lifecycle_line(hub=None) -> str:
    """seed → … → proposal → [PI GATE] → active → … (the AGENTS.md lifecycle line)."""
    m = load(hub)
    before = {g.get("before"): g["n"] for g in m.get("gates", []) if g.get("before")}
    out = []
    for s in m.get("states", []):
        if s["id"] in before:
            out.append("[PI GATE]")
        out.append(s["id"])
    return "`" + " → ".join(out) + "`"


def advance_table(hub=None) -> str:
    """The state → next procedure table /advance and /lab-status follow (from next_for_state)."""
    m = load(hub)
    gate_at = {g.get("at"): g for g in m.get("gates", []) if g.get("at")}
    rows = ["| Registry state | The next procedure | Stops at |", "|---|---|---|"]
    for s in m.get("states", []) + m.get("side_states", []):
        nxt = (m.get("next_for_state") or {}).get(s["id"])
        if isinstance(nxt, dict):
            proc = f"`/{nxt.get('unsigned')}` until Gate {gate_at[s['id']]['n']} is signed, then `/{nxt.get('signed')}`" \
                if s["id"] in gate_at else ", ".join(f"`/{v}` ({k})" for k, v in nxt.items())
        elif nxt == "advance":   # /advance on such a state is its own step for it (the prose below says which)
            proc = "this procedure's own step for it (below)"
        elif nxt:
            proc = f"`/{nxt}`"
        else:
            proc = "nothing — report the state"
        g = gate_at.get(s["id"])
        stop = f"**Gate {g['n']}** — stop for the PI" if g and g.get("before") else ""
        rows.append(f"| `{s['id']}` | {proc} | {stop} |")
    return "\n".join(rows)


def contract_block(proc: str, hub=None) -> str:
    """The generated head of a procedure's SKILL.md: load the brief, what the method is, what it must produce."""
    p = procedure(proc, hub) or {}
    arg = " --study <slug>" if "slug" in str(p.get("args", "")) else " [--study <slug>]"
    project = p.get("level") == "project"
    tool = "<hub>/tools/workflow.py" if project else "tools/workflow.py"
    lines = [f"**First, load this procedure's brief:** `uv run --with pyyaml python {tool} brief {proc}{arg}` "
             + ("(`<hub>` = this project's `control.yaml` `hub_path`; " if project else "(")
             + f"skip it if a `NEWTS STAGE BRIEF /{proc}` block is already in your context). "
             + (str(p["brief_note"]).strip() + " " if p.get("brief_note") else "")
             + "It carries "
             + ("the method — this lab's default `METHOD.md` beside this file, or the PI's replacement — and "
                if p.get("replaceable") else "")
             + "the PI's own instructions for this procedure. This file is the procedure's **contract**: its "
             "steps, guard calls, gates, stop points and records always bind, and win over the brief on any conflict."]
    if p.get("outputs"):
        lines.append("\n**Whatever the method, it must produce:**")
        lines += [f"- {o}" for o in p["outputs"]]
    if p.get("anchors"):
        lines.append(f"\nOther procedures rely on these parts of this contract: {', '.join(p['anchors'])}.")
    return "\n".join(lines)


def project_types_line(hub=None) -> str:
    """`ml` (default) · `empirical` · … — every folder in templates/project-types/ (the TYPE.md that says
    "(default)" in its title is the default)."""
    root = _hub(hub) / "templates" / "project-types"
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        head = _read(d / "TYPE.md").split("\n", 1)[0]
        if head:
            out.append(f"`{d.name}`" + (" (default)" if "(default)" in head else ""))
    return " · ".join(out)


INLINE = {"project-types"}      # generated spans that sit inside a sentence


def _blocks(hub) -> list[tuple[Path, str, str]]:
    """(file, block name, content) for every generated span — each file holds
    <!-- newts:<name> (generated…) --> … <!-- /newts:<name> --> where its content goes."""
    hub = _hub(hub)
    rl = rules(hub)
    out = [(Path("AGENTS.md"), "hard-rules", _numbered(rl.get("hard_rules") or [])),
           (Path("AGENTS.md"), "subagent-rules", _numbered(rl.get("subagent_rules") or [])),
           (Path("AGENTS.md"), "lifecycle", lifecycle_line(hub)),
           (PROJECT_MANUAL, "project-rules", _numbered(rl.get("project_rules") or [])),
           (SKILLS / "advance" / "SKILL.md", "next-table", advance_table(hub)),
           (Path("AGENTS.md"), "project-types", project_types_line(hub)),
           (SKILLS / "spawn-project" / "SKILL.md", "project-types", project_types_line(hub))]
    for name in load(hub).get("procedures") or {}:
        if not (load(hub)["procedures"][name].get("engineering")):
            out.append((SKILLS / name / "SKILL.md", "contract", contract_block(name, hub)))
    return out


def _span(name: str) -> tuple[str, str]:
    return f"<!-- newts:{name} ({_GEN}) -->", f"<!-- /newts:{name} -->"


def skills_list(hub=None) -> str:
    """`a`, `b`, … — every lab procedure in manifest order (the vendored engineering helpers aside)."""
    return ", ".join(f"`{n}`" for n, p in (load(hub).get("procedures") or {}).items() if not p.get("engineering"))
UI_DEFAULT = Path("dashboard") / "static" / "ui" / "workflow-default.js"


def ui_default_js(hub=None) -> str:
    """The dashboard's built-in copy of the manifest (demo/static pages; a live lab's snapshot overrides it)."""
    view = ui_view(hub)
    for k in ("custom", "study_custom", "proposals"):
        view.pop(k, None)
    return ("/* GENERATED by tools/workflow.py render-docs from workflow/stages.yaml — do not edit. The live\n"
            "   snapshot's `workflow` replaces this; it only serves demo/static pages. */\n"
            "window.__WORKFLOW_DEFAULT__ = " + json.dumps(view, ensure_ascii=False, sort_keys=True) + ";\n")


def render_docs(hub=None, check_only: bool = False) -> list[Path]:
    hub = _hub(hub)
    stale = []
    js = hub / UI_DEFAULT
    if js.parent.is_dir():
        want = ui_default_js(hub)
        if _read(js) != want:
            stale.append(UI_DEFAULT)
            if not check_only:
                js.write_text(want, encoding="utf-8", newline="\n")
    block = f"{DOC_BEGIN}\n{docs_table(hub)}\n{DOC_END}"
    for rel in DOC_TARGETS:
        p = hub / rel
        txt = _read(p)
        if DOC_BEGIN not in txt or DOC_END not in txt:
            continue
        new = re.sub(re.escape(DOC_BEGIN) + r".*?" + re.escape(DOC_END), lambda _m: block, txt, flags=re.S)
        if new != txt:
            stale.append(rel)
            if not check_only:
                p.write_text(new, encoding="utf-8", newline="\n")
    for rel, name, content in _blocks(hub):
        p = hub / rel
        txt = _read(p)
        begin, end = _span(name)
        if begin not in txt or end not in txt:
            continue
        nl = "\r\n" if "\r\n" in txt else "\n"
        body = content.replace("\n", nl)
        gen = f"{begin}{body}{end}" if name in INLINE else f"{begin}{nl}{body}{nl}{end}"
        new = re.sub(re.escape(begin) + r".*?" + re.escape(end), lambda _m: gen, txt, flags=re.S)
        if new != txt:
            stale.append(rel)
            if not check_only:
                p.write_text(new, encoding="utf-8", newline="")
    skills = f"{SKILLS_BEGIN}{skills_list(hub)}{SKILLS_END}"
    for rel in SKILLS_TARGETS:
        p = hub / rel
        txt = _read(p)
        if SKILLS_BEGIN not in txt or SKILLS_END not in txt:
            continue
        new = re.sub(re.escape(SKILLS_BEGIN) + r".*?" + re.escape(SKILLS_END), lambda _m: skills, txt, flags=re.S)
        if new != txt:
            stale.append(rel)
            if not check_only:
                p.write_text(new, encoding="utf-8", newline="\n" if "\r\n" not in txt else "\r\n")
    return stale


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    b = sub.add_parser("brief")
    b.add_argument("proc")
    b.add_argument("--study")
    pr = sub.add_parser("propose")
    pr.add_argument("--proc", required=True, help="procedure (or stage id with --mode stage, role with --mode role)")
    pr.add_argument("--study")
    pr.add_argument("--mode", required=True, choices=["add", "replace", "stage", "role"])
    pr.add_argument("--file", required=True)
    pr.add_argument("--why", default="")
    rd = sub.add_parser("render-docs")
    rd.add_argument("--check", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("--study")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        probs = check()
        for x in probs:
            print(f"[workflow] {x}")
        stale = render_docs(check_only=True)
        for x in stale:
            print(f"[workflow] {x.as_posix()} is stale — run `tools/workflow.py render-docs`")
        if not probs and not stale:
            print("[workflow] ok")
        return 1 if probs or stale else 0
    if a.cmd == "brief":
        try:
            text, _h = brief(a.proc, study=a.study)
        except KeyError:
            print(f"[workflow] unknown procedure {a.proc!r}", file=sys.stderr)
            return 2
        print(text)
        return 0
    if a.cmd == "propose":
        import os  # noqa: PLC0415
        try:
            text = Path(a.file).read_text(encoding="utf-8")
            rec = propose(a.proc, a.mode, text, study=a.study, why=a.why, by=os.environ.get("NEWTS_RUN_ID", ""))
        except (OSError, ValueError) as e:
            print(f"[workflow] {e}", file=sys.stderr)
            return 2
        try:
            sys.path.insert(0, str(HUB / "tools"))
            import lab_bus  # noqa: PLC0415
            lab_bus.emit("instruction_proposal", idea=a.study, run_id=os.environ.get("NEWTS_RUN_ID"),
                         detail=f"{a.mode} /{a.proc}", data={"proposal": rec["id"]})
        except Exception:  # noqa: BLE001 — the proposal file is the record; the event is a nudge
            pass
        print(f"[workflow] proposal {rec['id']} filed — the PI accepts or declines it in the dashboard (Workflow)")
        return 0
    if a.cmd == "render-docs":
        stale = render_docs(check_only=a.check)
        for x in stale:
            print(f"[workflow] {'stale' if a.check else 'updated'}: {x.as_posix()}")
        return 1 if (a.check and stale) else 0
    if a.cmd == "show":
        print(json.dumps(status(study=a.study), indent=1))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
