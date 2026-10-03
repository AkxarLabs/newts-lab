"""Settings written to lab/config.yaml: whitelisted keys, validated, stamped in place (comments kept),
and refused unless the file reads back with the new value.
"""

from __future__ import annotations


import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None (observe-and-sign only)


# key → (config path, parser). Parsers raise ValueError on a bad value.
def _enum(*allowed):
    def f(v):
        v = str(v).strip()
        if v not in allowed:
            raise ValueError(f"one of {', '.join(allowed)}")
        return v
    return f


def _num(lo, integer=False):
    def f(v):
        x = int(v) if integer else float(v)
        if x != x or x < lo:
            raise ValueError(f"a number ≥ {lo}")
        return int(x) if float(x).is_integer() else x
    return f


def _model_val(v):
    v = str(v).strip() or "inherit"
    if v != "inherit" and not executor.spec.MODEL_RE.match(v):
        raise ValueError("a model id or alias")
    return v


EXEC_CONFIG = {
    "backend": (["agents", "programmatic", "backend"], _enum(*(executor.backends.BACKENDS if executor else ("claude",)))),
    "model": (["agents", "programmatic", "model"], _model_val),
    # bypassPermissions is deliberately absent: it would remove the human-in-loop floor
    "permission_mode": (["agents", "programmatic", "permission_mode"],
                        _enum("auto", "acceptEdits", "default", "plan", "dontAsk")),
    "max_minutes": (["agents", "programmatic", "max_minutes"], _num(5)),
    "max_concurrent": (["agents", "programmatic", "max_concurrent"], _num(1, True)),
    "max_concurrent_total": (["agents", "programmatic", "max_concurrent_total"], _num(1, True)),
    "hub_max_concurrent": (["agents", "programmatic", "hub_max_concurrent"], _num(1, True)),
    "daily_max_runs": (["agents", "programmatic", "daily_max_runs"], _num(0, True)),
    "daily_max_minutes": (["agents", "programmatic", "daily_max_minutes"], _num(0)),
    "chain_max_steps": (["agents", "programmatic", "chain_max_steps"], _num(1, True)),
    "live": (["agents", "programmatic", "live", "enabled"],
             lambda v: v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")),
    "park_minutes": (["agents", "programmatic", "live", "park_minutes"], _num(1)),
    "permission_minutes": (["agents", "programmatic", "live", "permission_minutes"], _num(1)),
    "campaign_question_minutes": (["agents", "programmatic", "live", "campaign_question_minutes"], _num(1)),
    "linger_minutes": (["agents", "programmatic", "live", "linger_minutes"], _num(0)),
    "auto_spawn_on_gate1": (["dashboard", "auto_spawn_on_gate1"],
                            lambda v: v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")),
}


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
            if depth < 2:          # never invent a top-level section (agents / dashboard / …)
                return text, False
            i = end_of_block()     # a nested block an older config lacks (e.g. programmatic.live)
            lines.insert(i, f"{' ' * indent}{key}:")
            hi += 1
        lo, hi = i + 1, profiles._block_end(lines, i, indent)
        indent += 2
    lines.insert(end_of_block(), f"{' ' * indent}{dotted[-1]}: {profiles._fmt(value)}")
    return "\n".join(lines), True


def set_executor_config(body: dict) -> tuple[dict, int]:
    """Change executor settings in lab/config.yaml (comment-preserving stamp, the /configure writer).
    Whitelisted keys only, each validated; all-or-nothing; confirmed and logged."""
    if executor is None:
        return ctx.no_executor()
    if not body.get("confirm"):
        return {"error": "changing settings needs explicit confirm"}, 400
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        return {"error": "no changes"}, 400
    parsed = {}
    for k, v in changes.items():
        if k not in EXEC_CONFIG:
            return {"error": f"'{k}' can't be changed from the dashboard"}, 400
        try:
            parsed[k] = EXEC_CONFIG[k][1](v)
        except (TypeError, ValueError) as e:
            return {"error": f"{k}: must be {e}"}, 400
    profiles = ctx.tool("profiles")   # tools/profiles.stamp (the /configure writer)
    cfg = ctx.LAB / "config.yaml"
    try:
        text = cfg.read_text(encoding="utf-8-sig")
    except OSError:
        return {"error": "no lab/config.yaml"}, 400
    for k, v in parsed.items():
        text, changed = _stamp_or_insert(profiles, text, EXEC_CONFIG[k][0], v)
        if not changed:
            return {"error": f"lab/config.yaml has no '{EXEC_CONFIG[k][0][0]}' section to put "
                             f"{'.'.join(EXEC_CONFIG[k][0])} in"}, 400
    try:   # never write a config that no longer parses to the values we meant
        import yaml
        doc = yaml.safe_load(text) or {}
        for k, v in parsed.items():
            node = doc
            for part in EXEC_CONFIG[k][0]:
                node = node.get(part) if isinstance(node, dict) else None
            if node != v:
                raise ValueError(k)
    except Exception as e:  # noqa: BLE001
        return {"error": f"refused: the edited lab/config.yaml would not read back correctly ({e})"}, 400
    cfg.write_text(text, encoding="utf-8", newline="")
    ctx.pi_log({"action": "executor.config", "changes": parsed})
    sources._EXEC_CACHE["ts"] = 0   # re-probe (e.g. the new backend's CLI) on the next snapshot
    ctx.KICK.set()
    return {"ok": True, "changes": parsed, "note": f"saved {len(parsed)} setting(s) to lab/config.yaml"}, 200
