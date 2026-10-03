"""Settings: whitelisted keys of lab/config.yaml written in place (comments kept, refused unless the file
reads back), the PI's documents, and first-run setup. (Research keys and notifications: keys.py; the
System page and compute.scheduler: system.py.)
"""

from __future__ import annotations

import re
import subprocess
import sys
import time

import ctx  # noqa: E402
import sources  # noqa: E402
import attention  # noqa: E402
from labs import lab_name  # noqa: E402

executor = sources.executor   # tools/executor, or None


# ── writing lab/config.yaml: one path for every setting ─────────────────────
# A table maps a setting to (its dotted path, a parser). Parsers raise ValueError with what they want.

def _enum(*allowed):
    def f(v):
        v = str(v).strip()
        if v not in allowed:
            raise ValueError(f"one of {', '.join(allowed)}")
        return v
    return f


def _num(lo, integer=False, hi=None):
    def f(v):
        x = int(v) if integer else float(v)
        if x != x or x < lo or (hi is not None and x > hi):
            raise ValueError(f"a {'whole ' if integer else ''}number ≥ {lo}" + (f" and ≤ {hi}" if hi is not None else ""))
        return int(x) if float(x).is_integer() else x
    return f


def _text(maxlen, rx=None):
    def f(v):
        v = str(v).strip()
        if not v or len(v) > maxlen or (rx and not re.match(rx, v)):
            raise ValueError("a short text value")
        return v
    return f


def _bool(v):
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")


def _model(v):
    v = str(v).strip() or "inherit"
    if v != "inherit" and not executor.spec.MODEL_RE.match(v):
        raise ValueError("a model id or alias")
    return v


_P = ["agents", "programmatic"]
EXEC_CONFIG = {
    "backend": (_P + ["backend"], _enum(*(executor.backends.BACKENDS if executor else ("claude",)))),
    "model": (_P + ["model"], _model),
    # bypassPermissions is deliberately absent: it would remove the human-in-loop floor
    "permission_mode": (_P + ["permission_mode"], _enum("auto", "acceptEdits", "default", "plan", "dontAsk")),
    "max_minutes": (_P + ["max_minutes"], _num(5)),
    "max_concurrent": (_P + ["max_concurrent"], _num(1, True)),
    "max_concurrent_total": (_P + ["max_concurrent_total"], _num(1, True)),
    "hub_max_concurrent": (_P + ["hub_max_concurrent"], _num(1, True)),
    "daily_max_runs": (_P + ["daily_max_runs"], _num(0, True)),
    "daily_max_minutes": (_P + ["daily_max_minutes"], _num(0)),
    "chain_max_steps": (_P + ["chain_max_steps"], _num(1, True)),
    "live": (_P + ["live", "enabled"], _bool),
    "park_minutes": (_P + ["live", "park_minutes"], _num(1)),
    "permission_minutes": (_P + ["live", "permission_minutes"], _num(1)),
    "campaign_question_minutes": (_P + ["live", "campaign_question_minutes"], _num(1)),
    "linger_minutes": (_P + ["live", "linger_minutes"], _num(0)),
    "auto_spawn_on_gate1": (["dashboard", "auto_spawn_on_gate1"], _bool),
}
LAB_CONFIG = {
    "name": (["lab", "name"], _text(80)),
    "projects_root": (["lab", "projects_root"], _text(300, r"^[^\n\"]+$")),
    "max_concurrent_runs": (["compute", "max_concurrent_runs"], _num(1, True, 64)),
    "oversight": (["oversight", "level"], _enum("standard", "strict")),
    "venue": (["writing", "venue"], _text(40, r"^[A-Za-z0-9 ._-]+$")),
    "page_limit": (["writing", "page_limit"], _num(1, True, 100)),
    "max_concurrent_projects": (["autopilot", "max_concurrent_projects"], _num(1, True, 16)),
    "loop_mode": (["loop", "mode"], _enum("execute", "explore")),
    "explore_rounds": (["loop", "explore_max_expansion_rounds"], _num(0, True, 20)),
    "in_project_approval": (["ideation", "in_project_approval"], _enum("pi", "campaign_auto")),
    # "off" is stored as YAML false (a bare `off` would read back as false anyway)
    "keep_awake": (["lab", "keep_awake"], lambda v: False if _enum("auto", "off")("off" if v is False else v) == "off" else "auto"),
}


def _parse(table: dict, changes) -> tuple[dict, str | None]:
    """{setting: value} → ({dotted path: parsed value}, None) — or ({}, what's wrong)."""
    if not isinstance(changes, dict) or not changes:
        return {}, "no changes"
    out = {}
    for k, v in changes.items():
        if k not in table:
            return {}, f"'{k}' can't be changed here"
        try:
            out[tuple(table[k][0])] = table[k][1](v)
        except (TypeError, ValueError) as e:
            return {}, f"{k}: must be {e}"
    return out, None


def reads_back(text: str, updates: dict) -> str | None:
    try:
        import yaml
        doc = yaml.safe_load(text) or {}
    except Exception as e:  # noqa: BLE001
        return f"refused: lab/config.yaml would not parse ({e})"
    for dotted, v in updates.items():
        node = doc
        for part in dotted:
            node = node.get(part) if isinstance(node, dict) else None
        if node != v and not (isinstance(v, str) and str(node) == v):   # (a date reads back as a date)
            return f"refused: lab/config.yaml would not read back {'.'.join(dotted)} correctly"
    return None


def write_config(updates: dict, *, new_sections: bool = False) -> str | None:
    """Stamp each {dotted path: value} into lab/config.yaml in place (comments and every other byte kept,
    tools/profiles.stamp — the /configure writer). A nested block an older config lacks is added; a missing
    top-level section only with `new_sections`. Nothing is written unless the file reads back with every
    value. Returns None, or what went wrong."""
    profiles = ctx.tool("profiles")
    cfg = ctx.LAB / "config.yaml"
    text = ctx.read(cfg)
    if text is None:
        return "no lab/config.yaml"
    new = text.replace("\r\n", "\n")
    for dotted, v in updates.items():
        new, ok = _stamp_or_insert(profiles, new, list(dotted), v)
        if not ok:
            if not new_sections:
                return f"lab/config.yaml has no '{dotted[0]}' section to put {'.'.join(dotted)} in"
            new = new.rstrip("\n") + "\n\n" + "".join("  " * d + f"{k}:\n" for d, k in enumerate(dotted[:-1])) + \
                "  " * (len(dotted) - 1) + f"{dotted[-1]}: {profiles._fmt(v)}\n"
    err = reads_back(new, updates)
    if err:
        return err
    ctx.write_keep_eol(cfg, text, new)
    return None


def _stamp_or_insert(profiles, text: str, dotted: list, value) -> tuple[str, bool]:
    """profiles.stamp, plus: a key missing from an OLDER lab/config.yaml is inserted at the end of its
    parent block (the parent must exist). Comments and every other byte are kept."""
    new, changed = profiles.stamp(text, dotted, value)
    if changed:
        return new, True
    lines = text.split("\n")
    lo, hi, indent = 0, len(lines), 0

    def end_of_block() -> int:   # back over blank lines / the NEXT section's leading comments
        j = hi
        while j > lo and (not lines[j - 1].strip() or
                          (lines[j - 1].lstrip().startswith("#") and profiles._indent(lines[j - 1]) < indent)):
            j -= 1
        return j

    for depth, key in enumerate(dotted[:-1]):
        i = profiles._find_key(lines, key, lo, hi, indent)
        if i < 0:
            if depth < 2:          # never invent a top-level section here (write_config's new_sections does)
                return text, False
            i = end_of_block()     # a nested block an older config lacks (e.g. programmatic.live)
            lines.insert(i, f"{' ' * indent}{key}:")
            hi += 1
        lo, hi = i + 1, profiles._block_end(lines, i, indent)
        indent += 2
    lines.insert(end_of_block(), f"{' ' * indent}{dotted[-1]}: {profiles._fmt(value)}")
    return "\n".join(lines), True


def set_executor_config(body: dict) -> tuple[dict, int]:
    """Executor settings (whitelisted, validated, all-or-nothing; confirmed and logged)."""
    if executor is None:
        return ctx.no_executor()
    if not body.get("confirm"):
        return {"error": "changing settings needs explicit confirm"}, 400
    updates, err = _parse(EXEC_CONFIG, body.get("changes"))
    err = err or write_config(updates)
    if err:
        return {"error": err}, 400
    parsed = {k: updates[tuple(EXEC_CONFIG[k][0])] for k in body["changes"]}
    ctx.pi_log({"action": "executor.config", "changes": parsed})
    attention.recheck_executor()   # re-probe (e.g. the new backend's CLI) on the next snapshot
    ctx.KICK.set()
    return {"ok": True, "changes": parsed, "note": f"saved {len(parsed)} setting(s) to lab/config.yaml"}, 200


PI_DOCS = {"system": "lab/SYSTEM.md", "open-questions": "lab/knowledge/OPEN-QUESTIONS.md"}


def doc_get(which: str) -> tuple[dict, int]:
    rel = PI_DOCS.get(which)
    if not rel:
        return {"error": "unknown document"}, 400
    p = ctx.HUB / rel
    text = ctx.read(p)
    if text is None and which == "system":
        text = ctx.read(ctx.labfiles.template(ctx.HUB, "SYSTEM.md")) or "# This machine\n"
        return {"ok": True, "rel": rel, "text": text, "exists": False}, 200
    return {"ok": True, "rel": rel, "text": text or "", "exists": text is not None}, 200


def doc_save(body: dict) -> tuple[dict, int]:
    rel = PI_DOCS.get(str(body.get("doc") or ""))
    if not rel:
        return {"error": "this document can't be edited here"}, 400
    text = body.get("text")
    if not isinstance(text, str) or len(text) > 200_000:
        return {"error": "text missing or too long"}, 400
    p = ctx.HUB / rel
    old = ctx.read(p) or ""
    p.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_keep_eol(p, old, text)
    ctx.pi_log({"action": "doc.save", "doc": rel, "chars": len(text)})
    return {"ok": True, "note": f"saved {rel}"}, 200


def lab_config_get() -> tuple[dict, int]:
    cfg = ctx.config()
    out = {}
    for k, (path, _p) in LAB_CONFIG.items():
        node = cfg
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        out[k] = node
    tier = None
    for line in (ctx.read(ctx.LAB / "config.yaml") or "").splitlines()[:40]:
        m = re.search(r"profile:\s*(low|medium|high)\b", line)
        if m:
            tier = m.group(1)
    out["budget_tier"] = tier
    out["name"] = out.get("name") or ctx.HUB.name
    out["keep_awake"] = "off" if out.get("keep_awake") is False else (out.get("keep_awake") or "auto")
    return {"ok": True, "config": out, "setup": setup_status()}, 200


def lab_config_set(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "changing lab settings needs explicit confirm"}, 400
    changes = dict(body.get("changes") or {})
    tier = changes.pop("budget_tier", None)
    updates, err = _parse(LAB_CONFIG, changes) if changes else ({}, None)
    if err or (tier is None and not updates):
        return {"error": err or "no changes"}, 400
    notes = []
    if tier is not None:
        if tier not in ("low", "medium", "high"):
            return {"error": "budget tier must be low, medium or high"}, 400
        r = subprocess.run([sys.executable, str(ctx.HUB / "tools" / "profiles.py"), "apply", tier],
                           cwd=str(ctx.HUB), capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return {"error": f"could not apply the {tier} budget profile: {(r.stderr or r.stdout)[-400:]}"}, 400
        notes.append(f"applied the {tier} budget profile")
    if updates:
        err = write_config(updates, new_sections=True)
        if err:
            return {"error": err}, 400
        notes.append(f"saved {len(updates)} setting(s)")
    parsed = {k: updates[tuple(LAB_CONFIG[k][0])] for k in changes}
    ctx.pi_log({"action": "lab.config", "changes": parsed, "budget_tier": tier})
    attention.recheck_executor()
    return {"ok": True, "changes": parsed, "note": "; ".join(notes) or "nothing changed"}, 200


# ── first-run setup ──────────────────────────────────────────────────────────

def setup_status() -> dict:
    cfg = ctx.config()
    done = (cfg.get("dashboard") or {}).get("setup_completed")
    rows = [r for r in sources.parse_registry() if r.get("id")]
    return {"completed": bool(done), "completed_at": str(done) if done else None,
            "fresh": not rows, "lab": {"name": lab_name(ctx.HUB), "path": str(ctx.HUB)}}


def setup_complete(body: dict) -> tuple[dict, int]:
    done = body.get("done", True)
    err = write_config({("dashboard", "setup_completed"): time.strftime("%Y-%m-%d") if done else None},
                       new_sections=True)
    if err:
        return {"error": err}, 400
    ctx.pi_log({"action": "setup.complete", "done": bool(done)})
    return {"ok": True}, 200
