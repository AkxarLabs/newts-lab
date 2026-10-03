"""Labs on this computer (list / open / create / forget — ~/.newts/labs.json, NEWTS_HOME overrides), the
consoles for a CLI's own sign-in or install, and stopping the server.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor   # tools/executor, or None


def _labs_file() -> Path:
    home = Path(os.environ.get("NEWTS_HOME") or (Path.home() / ".newts"))
    return home / "labs.json"


def _labs_load() -> list[dict]:
    try:
        data = json.loads(_labs_file().read_text(encoding="utf-8"))
        return [d for d in data.get("labs", []) if isinstance(d, dict) and d.get("path")]
    except (OSError, json.JSONDecodeError, AttributeError):
        return []


def _labs_save(labs: list[dict]) -> None:
    f = _labs_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"labs": labs}, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def lab_name(hub: Path) -> str:
    cfg = ctx.labfiles.config(hub)
    return str(((cfg.get("lab") or {}).get("name")) or hub.name)


def _lab_summary(hub: Path) -> dict:
    """Name + state counts for the picker, read cheaply from the registry file."""
    counts: dict[str, int] = {}
    reg = ctx.read(hub / "lab" / "REGISTRY.md") or ""
    for line in reg.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in ("ID", "—", "") and not set(cells[0]) <= set("-"):
            counts[cells[2]] = counts.get(cells[2], 0) + 1
    return {"path": str(hub), "name": lab_name(hub), "counts": counts, "ideas": sum(counts.values()),
            "exists": (hub / "lab").is_dir()}


def remember_lab(hub: Path) -> None:
    labs = [d for d in _labs_load() if Path(d["path"]).resolve() != hub.resolve()]
    labs.insert(0, {"path": str(hub.resolve()), "opened": ctx.ts()})
    _labs_save(labs[:30])


def labs_list() -> tuple[dict, int]:
    out = []
    seen = set()
    for d in _labs_load():
        p = Path(d["path"])
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        s = _lab_summary(p) if (p / "lab").is_dir() else {"path": str(p), "name": p.name, "exists": False}
        s["opened"] = d.get("opened")
        s["current"] = p.resolve() == ctx.HUB.resolve()
        out.append(s)
    if not any(x.get("current") for x in out):
        cur = _lab_summary(ctx.HUB)
        cur["current"] = True
        out.insert(0, cur)
    return {"ok": True, "labs": out, "current": str(ctx.HUB), "template": str(ctx.ROOT)}, 200


def labs_open(body: dict) -> tuple[dict, int]:
    raw = str(body.get("path") or "").strip().strip('"')
    if not raw:
        return {"error": "choose a lab folder"}, 400
    hub = Path(raw).expanduser()
    try:
        hub = hub.resolve()
    except OSError:
        return {"error": f"can't read {raw}"}, 400
    if not (hub / "lab").is_dir() or not (hub / "lab" / "config.yaml").exists():
        return {"error": f"{hub} is not a Newts' Lab (no lab/config.yaml there)"}, 400
    ctx.set_remote(None)
    ctx.switch_hub(hub)
    remember_lab(hub)
    ctx.pi_log({"action": "lab.open", "path": str(hub)})
    return {"ok": True, "lab": _lab_summary(hub), "note": f"opened {lab_name(hub)}"}, 200


def labs_create(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "creating a lab needs explicit confirm"}, 400
    name = str(body.get("name") or "").strip()[:80]
    where = str(body.get("path") or "").strip().strip('"')
    if not where:
        return {"error": "choose where the new lab should live"}, 400
    ctx.tool("workflow")   # tools/ on sys.path for the imports below
    import new_lab   # noqa: E402
    res = new_lab.create_lab(where, name or None, (str(body.get("projects_root") or "").strip() or None),
                             template=ctx.ROOT)
    if not res.get("ok"):
        return res, 400
    hub = Path(res["path"])
    remember_lab(hub)
    if body.get("open", True):
        ctx.set_remote(None)
        ctx.switch_hub(hub)
    ctx.pi_log({"action": "lab.create", "path": str(hub), "name": name})
    return {"ok": True, "lab": _lab_summary(hub), "git": res.get("git"),
            "note": f"created {res.get('name')} at {hub}"}, 200


def labs_forget(body: dict) -> tuple[dict, int]:
    raw = str(body.get("path") or "")
    labs = [d for d in _labs_load() if str(Path(d["path"])).lower() != str(Path(raw)).lower()]
    _labs_save(labs)
    return {"ok": True}, 200


def terminal_open(body: dict) -> tuple[dict, int]:
    purpose, backend = str(body.get("purpose") or ""), str(body.get("backend") or "")
    ctx.tool("workflow")   # tools/ on sys.path for the imports below
    import terminal   # noqa: E402
    if purpose == "shell":
        res = terminal.open_terminal("echo Newts' Lab — this is your lab folder", ctx.HUB)
    elif purpose in ("login", "install"):
        if backend not in sources.executor.backends.BACKENDS if sources.executor else ("claude", "codex", "opencode"):
            return {"error": "unknown backend"}, 400
        if purpose == "install":
            cmd = terminal.install_command(backend)
            if not cmd:
                return {"error": f"no install command known for {backend}"}, 400
            res = terminal.open_terminal(cmd, ctx.HUB)
        else:
            if sources.executor is None:
                return ctx.no_executor()
            prog = (ctx.config().get("agents") or {}).get("programmatic") or {}
            cli = sources.executor.backends.resolve_cli(backend, (prog.get("backends") or {}).get(backend) or {})
            argv = terminal.login_argv(backend, cli or [])
            if not argv:
                return {"error": f"{backend} is not installed yet — install it first"}, 400
            res = terminal.open_terminal(argv, ctx.HUB)
    else:
        return {"error": "unknown purpose"}, 400
    if not res.get("ok"):
        return res, 500
    sources.recheck_executor(cli=True)
    ctx.pi_log({"action": f"terminal.{purpose}", "backend": backend or None})
    what = {"login": "sign-in", "install": "install", "shell": "shell"}[purpose]
    return {"ok": True, "note": f"opened {res['how']} for the {backend + ' ' if backend else ''}{what} — "
                                "finish there; this page updates by itself"}, 200


def server_stop(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "stopping the server needs explicit confirm"}, 400
    srv = ctx.SERVER
    if srv is None:
        return {"error": "no server handle"}, 500
    ctx.pi_log({"action": "server.stop"})
    threading.Timer(0.5, srv.shutdown).start()
    note = "the dashboard server is stopping — running agents keep going"
    try:
        from executor import campaigns  # noqa: PLC0415
        live = [c for c in campaigns.all_states(sources.executor.Lab(ctx.HUB)) if c.get("status") in ("active", "finishing")]
        if live:
            note += f", and a background scheduler keeps {len(live)} campaign(s) going"
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "note": note}, 200
