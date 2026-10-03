"""Settings: whitelisted keys of lab/config.yaml written in place (comments kept, refused unless the file
reads back), research keys and notification addresses (lab/.env.local), the PI's documents, and what
this machine offers (the System page, compute.scheduler), and first-run setup.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402
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


def _reads_back(text: str, updates: dict) -> str | None:
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
    err = _reads_back(new, updates)
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
    sources.recheck_executor()   # re-probe (e.g. the new backend's CLI) on the next snapshot
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
        text = ctx.read(ctx.HUB / "templates" / "SYSTEM.md") or "# This machine\n"
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
    sources.recheck_executor()
    return {"ok": True, "changes": parsed, "note": "; ".join(notes) or "nothing changed"}, 200


KNOWN_KEYS = {"S2_API_KEY": "Semantic Scholar", "OPENALEX_API_KEY": "OpenAlex"}


_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")


def _env_path() -> Path:
    return ctx.LAB / ".env.local"


def _env_read() -> dict:
    return ctx.labfiles.read_env(_env_path())


def keys_status() -> tuple[dict, int]:
    have = {k: v for k, v in _env_read().items() if not k.startswith("NEWTS_")}   # (notifications: their own form)
    keys = [{"key": k, "label": KNOWN_KEYS.get(k, k), "set": bool(have.get(k)) or bool(os.environ.get(k)),
             "where": ("lab" if have.get(k) else ("environment" if os.environ.get(k) else None))}
            for k in list(KNOWN_KEYS) + [k for k in have if k not in KNOWN_KEYS]]
    return {"ok": True, "keys": keys, "file": ".env.local (git-ignored)"}, 200


def keys_set(body: dict) -> tuple[dict, int]:
    key = str(body.get("key") or "").strip()
    if not _KEY_RE.match(key) or key.startswith(("NEWTS_", "AUTOSCIENTIST_", "CLAUDE_", "OPENCODE_", "CODEX_", "PATH")):
        return {"error": "a key name like S2_API_KEY"}, 400
    value = body.get("value")
    if value is not None and (not isinstance(value, str) or "\n" in value or len(value) > 500):
        return {"error": "the value must be one line"}, 400
    have = _env_read()
    if value:
        have[key] = value.strip()
    else:
        have.pop(key, None)
    _env_write(have)
    ctx.pi_log({"action": "keys.set", "key": key, "set": bool(value)})   # never the value
    return {"ok": True, "note": f"{key} {'saved' if value else 'removed'}"}, 200


def _env_write(have: dict) -> None:
    lines = ["# This lab's keys — written by the dashboard. Research keys are inherited by runs; NEWTS_* lines",
             "# (notifications) never are. Never commit."]
    lines += [f"{k}={v}" for k, v in have.items()]
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ensure_gitignored()


_URL_RE = re.compile(r"^https?://[^\s\"'<>]{3,400}$")


def _mask(url: str) -> str:
    return (url[:url.find("/", 8) + 1] + "…" + url[-4:]) if url and url.count("/") > 2 else ("set" if url else "")


def notify_status() -> tuple[dict, int]:
    from executor import notify   # noqa: PLC0415
    cfg = notify.config(sources.executor.Lab(ctx.HUB))
    return {"ok": True, "ntfy": _mask(cfg.get("ntfy", "")), "webhook": _mask(cfg.get("webhook", "")),
            "link": cfg.get("link", "")}, 200


def notify_set(body: dict) -> tuple[dict, int]:
    """Set or clear (empty) the ntfy topic URL, the webhook URL and the dashboard link."""
    from executor import notify   # noqa: PLC0415
    if not body.get("confirm"):
        return {"error": "confirm first"}, 400
    have = _env_read()
    changed = []
    for k, env in notify.KEYS.items():
        if k not in body:
            continue
        v = str(body.get(k) or "").strip()
        if v and not _URL_RE.match(v):
            return {"error": f"{k}: a web address starting with https:// (or http://)"}, 400
        if v:
            have[env] = v
        else:
            have.pop(env, None)
        changed.append(k)
    if not changed:
        return {"error": "nothing to change"}, 400
    _env_write(have)
    ctx.pi_log({"action": "notify.set", "changed": changed})   # never the URLs
    return {"ok": True, "note": "saved — new items that need you are sent from now on"}, 200


def notify_test(body: dict) -> tuple[dict, int]:
    from executor import notify   # noqa: PLC0415
    cfg = notify.config(sources.executor.Lab(ctx.HUB))
    if not (cfg.get("ntfy") or cfg.get("webhook")):
        return {"error": "set an ntfy topic or a webhook first"}, 400
    failed = notify.send(cfg, {"title": "Newts' Lab: notifications work", "kind": "test",
                               "body": "Questions, approvals and gates that need you will arrive here."})
    if failed:
        return {"error": f"could not reach {', '.join(failed)} — check the address"}, 400
    return {"ok": True, "note": "sent — check your phone"}, 200


def _ensure_gitignored() -> None:
    gi = ctx.HUB / ".gitignore"
    text = ctx.read(gi) or ""
    if "lab/.env.local" not in text:
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n# Research API keys (dashboard → Settings → Research keys)\nlab/.env.local\n")


_SYS_CACHE: dict = {"hub": None, "at": 0.0, "facts": None}


_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.,:=+@/%-]{0,120}$")


def system_info(q: dict) -> tuple[dict, int]:
    """tools/system_probe.py run on the machine this lab lives on (cached 10 min) + the scheduler block."""
    fresh = bool(q.get("fresh"))
    if fresh or _SYS_CACHE["hub"] != str(ctx.HUB) or time.time() - _SYS_CACHE["at"] > 600 or not _SYS_CACHE["facts"]:
        r = subprocess.run([sys.executable, str(ctx.TOOLS / "system_probe.py"),
                            "--hub", str(ctx.HUB)], capture_output=True, text=True, timeout=90)
        try:
            _SYS_CACHE.update(hub=str(ctx.HUB), at=time.time(), facts=json.loads(r.stdout))
        except ValueError:
            return {"error": f"the system probe failed: {(r.stderr or r.stdout)[-300:]}"}, 500
    cfg = ctx.config()
    sched = ((cfg.get("compute") or {}).get("scheduler")) or {"kind": "local"}
    return {"ok": True, "facts": _SYS_CACHE["facts"], "scheduler": sched,
            "system_md": (ctx.LAB / "SYSTEM.md").exists()}, 200


def _clean_scheduler(sc: dict) -> dict:
    """Validate the form into a compute.scheduler block (raises ValueError with a PI-readable message)."""
    kind = str(sc.get("kind") or "local")
    if kind not in ("local", "slurm", "custom"):
        raise ValueError("kind must be local, slurm or custom")
    stages = [str(x).upper() for x in (sc.get("stages") or ["PILOT", "FULL"])]
    if not set(stages) <= {"SMOKE", "PILOT", "FULL"}:
        raise ValueError("stages are SMOKE, PILOT, FULL")
    out: dict = {"kind": kind, "stages": stages,
                 "poll_seconds": int(sc.get("poll_seconds") or 30), "max_queue_hours": float(sc.get("max_queue_hours") or 48)}
    if not (5 <= out["poll_seconds"] <= 3600):
        raise ValueError("poll_seconds must be 5–3600")

    def lines(v, what, maxn=20):
        v = v if isinstance(v, list) else [x for x in str(v or "").splitlines()]
        v = [str(x).rstrip() for x in v if str(x).strip()]
        if len(v) > maxn or any("\n" in x or len(x) > 400 for x in v):
            raise ValueError(f"{what}: at most {maxn} lines of ≤400 characters")
        return v
    s = sc.get("slurm") or {}
    slurm: dict = {}
    for k in ("partition", "account", "qos", "constraint", "mem", "gres"):
        v = str(s.get(k) or "").strip()
        if v and not _SAFE_WORD.match(v):
            raise ValueError(f"slurm.{k} has characters a SLURM value can't have")
        slurm[k] = v or None
    for k, hi in (("gpus_per_run", 64), ("cpus_per_task", 512), ("time_grace_minutes", 1440)):
        v = s.get(k)
        slurm[k] = int(v) if v not in (None, "") else (10 if k == "time_grace_minutes" else None)
        if slurm[k] is not None and not (0 <= slurm[k] <= hi):
            raise ValueError(f"slurm.{k} must be 0–{hi}")
    slurm["extra_args"] = lines(s.get("extra_args"), "slurm.extra_args")
    if any(not a.startswith("--") for a in slurm["extra_args"]):
        raise ValueError("each extra sbatch argument starts with --, e.g. --exclusive")
    slurm["setup"] = lines(s.get("setup"), "slurm.setup")
    out["slurm"] = slurm
    c = sc.get("custom") or {}
    out["custom"] = {"submit": str(c.get("submit") or "").strip() or None, "state": str(c.get("state") or "").strip() or None,
                     "cancel": str(c.get("cancel") or "").strip() or None, "header": lines(c.get("header"), "custom.header"),
                     "setup": lines(c.get("setup"), "custom.setup")}
    if kind == "custom" and (not out["custom"]["submit"] or "{script}" not in out["custom"]["submit"]):
        raise ValueError("a custom scheduler needs a submit command containing {script}")
    return out


def _replace_block(text: str, parent: str, key: str, block: dict) -> str:
    """Replace (or add) `parent:\n  key: …` with a freshly rendered block; everything else is kept."""
    import yaml
    body = yaml.safe_dump({key: block}, sort_keys=False, default_flow_style=False).rstrip("\n").split("\n")
    body = ["  " + ln for ln in body]
    body[0] = body[0] + "                    # how training runs on this machine — Settings → System (docs/compute.md)"
    lines = text.replace("\r\n", "\n").split("\n")
    pi = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(parent)}:\s*(#.*)?$", ln)), None)
    if pi is None:
        return text.rstrip("\n") + f"\n\n{parent}:\n" + "\n".join(body) + "\n"
    end = len(lines)
    for j in range(pi + 1, len(lines)):
        if lines[j].strip() and not lines[j].startswith((" ", "\t")):
            end = j
            break
    ki = next((j for j in range(pi + 1, end) if re.match(rf"  {re.escape(key)}:", lines[j])), None)
    if ki is None:
        ins = end
        while ins > pi + 1 and not lines[ins - 1].strip():
            ins -= 1
        return "\n".join(lines[:ins] + body + lines[ins:])
    kend = end
    for j in range(ki + 1, end):
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= 2 and not ln.lstrip().startswith("#"):
            kend = j
            break
    while kend > ki + 1 and not lines[kend - 1].strip():
        kend -= 1
    return "\n".join(lines[:ki] + body + lines[kend:])


def system_scheduler_set(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "changing how training runs needs explicit confirm"}, 400
    try:
        block = _clean_scheduler(body.get("scheduler") or {})
    except (TypeError, ValueError) as e:
        return {"error": str(e)}, 400
    cfg = ctx.LAB / "config.yaml"
    text = ctx.read(cfg)
    if text is None:
        return {"error": "no lab/config.yaml"}, 400
    new = _replace_block(text, "compute", "scheduler", block)
    err = _reads_back(new, {("compute", "scheduler"): block})
    if err:
        return {"error": err}, 400
    ctx.write_keep_eol(cfg, text, new)
    ctx.pi_log({"action": "system.scheduler", "scheduler": block})
    return {"ok": True, "scheduler": block,
            "note": "training runs locally" if block["kind"] == "local" else f"PILOT/FULL runs now go through {block['kind']}"}, 200


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
