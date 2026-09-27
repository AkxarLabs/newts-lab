"""The dashboard as an end-to-end product: PI actions beyond Gate 1/2 and the run launcher.

Pure functions returning (body, http_code), bound to the server module (`bind(serve)`) so they always
read its CURRENT hub (the lab picker re-points it) and share its writers. Every write here is a PI
action: explicit, validated, logged to lab/.bus/pi-actions.jsonl.

  labs        list / open / create / forget labs (~/.newts/labs.json — NEWTS_HOME overrides)
  terminal    open a visible console for a CLI's own login or install (fixed commands only)
  gate 3      readiness, typed-confirmation signature (studies/<slug>/paper/gate3-approval.md), revoke,
              and the one /finalize run that signature allows
  envelope    edit a project's gate2_envelope values, optionally (re)sign
  loop brief  authorize a project's LOOP_BRIEF.md (mode execute | explore)
  campaign    write + sign lab/campaigns/<date>-<slug>.md from a form
  revive      bring a parked / killed idea back (reason required)
  revoke      withdraw a Gate 1 / Gate 2 / Gate 3 / loop-brief signature
  docs        save a PI-authored document (lab/SYSTEM.md, lab/knowledge/OPEN-QUESTIONS.md)
  lab config  the Lab settings (budget tier, compute, venue, oversight, …)
  keys        research API keys → lab/.env.local (git-ignored; runs inherit it; values never read back)
  setup       first-run wizard state
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

S = None   # the serve module (bound at import)


def bind(serve_module) -> None:
    global S
    S = serve_module


def _hub() -> Path:
    return S.HUB


def _lab() -> Path:
    return S.LAB


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read(p: Path) -> str | None:
    try:
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            return f.read()
    except OSError:
        return None


def _write_keep_eol(p: Path, original: str, text: str) -> None:
    eol = "\r\n" if "\r\n" in original else "\n"
    with p.open("w", encoding="utf-8", newline="") as f:
        f.write(text.replace("\r\n", "\n").replace("\n", eol))


def _tools():
    sys.path.insert(0, str(Path(S.__file__).resolve().parents[1] / "tools"))


def _row(slug: str) -> dict | None:
    return next((r for r in S.sources.parse_registry() if r.get("id") == slug), None)


def _need_slug(body: dict, key: str = "idea") -> str | None:
    return S._safe_id(body.get(key) or "")


# ── labs ─────────────────────────────────────────────────────────────────────

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
    cfg = S.sources._load_yaml(hub / "lab" / "config.yaml")
    return str(((cfg.get("lab") or {}).get("name")) or hub.name)


def _lab_summary(hub: Path) -> dict:
    """Name + state counts for the picker, read cheaply from the registry file."""
    counts: dict[str, int] = {}
    reg = _read(hub / "lab" / "REGISTRY.md") or ""
    for line in reg.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in ("ID", "—", "") and not set(cells[0]) <= set("-"):
            counts[cells[2]] = counts.get(cells[2], 0) + 1
    return {"path": str(hub), "name": lab_name(hub), "counts": counts, "ideas": sum(counts.values()),
            "exists": (hub / "lab").is_dir()}


def remember_lab(hub: Path) -> None:
    labs = [d for d in _labs_load() if Path(d["path"]).resolve() != hub.resolve()]
    labs.insert(0, {"path": str(hub.resolve()), "opened": _ts()})
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
        s["current"] = p.resolve() == _hub().resolve()
        out.append(s)
    if not any(x.get("current") for x in out):
        cur = _lab_summary(_hub())
        cur["current"] = True
        out.insert(0, cur)
    return {"ok": True, "labs": out, "current": str(_hub()), "template": str(Path(S.__file__).resolve().parents[1])}, 200


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
    S.set_remote(None)
    S.switch_hub(hub)
    remember_lab(hub)
    S._pi_log({"action": "lab.open", "path": str(hub)})
    return {"ok": True, "lab": _lab_summary(hub), "note": f"opened {lab_name(hub)}"}, 200


def labs_create(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "creating a lab needs explicit confirm"}, 400
    name = str(body.get("name") or "").strip()[:80]
    where = str(body.get("path") or "").strip().strip('"')
    if not where:
        return {"error": "choose where the new lab should live"}, 400
    _tools()
    import new_lab   # noqa: E402
    res = new_lab.create_lab(where, name or None, (str(body.get("projects_root") or "").strip() or None),
                             template=Path(S.__file__).resolve().parents[1])
    if not res.get("ok"):
        return res, 400
    hub = Path(res["path"])
    remember_lab(hub)
    if body.get("open", True):
        S.set_remote(None)
        S.switch_hub(hub)
    S._pi_log({"action": "lab.create", "path": str(hub), "name": name})
    return {"ok": True, "lab": _lab_summary(hub), "git": res.get("git"),
            "note": f"created {res.get('name')} at {hub}"}, 200


def labs_forget(body: dict) -> tuple[dict, int]:
    raw = str(body.get("path") or "")
    labs = [d for d in _labs_load() if str(Path(d["path"])).lower() != str(Path(raw)).lower()]
    _labs_save(labs)
    return {"ok": True}, 200


# ── terminal (sign in / install) ─────────────────────────────────────────────

def terminal_open(body: dict) -> tuple[dict, int]:
    purpose, backend = str(body.get("purpose") or ""), str(body.get("backend") or "")
    _tools()
    import terminal   # noqa: E402
    if purpose == "shell":
        res = terminal.open_terminal("echo Newts' Lab — this is your lab folder", _hub())
    elif purpose in ("login", "install"):
        if backend not in ("claude", "codex", "opencode"):
            return {"error": "unknown backend"}, 400
        if purpose == "install":
            cmd = terminal.install_command(backend)
            if not cmd:
                return {"error": f"no install command known for {backend}"}, 400
            res = terminal.open_terminal(cmd, _hub())
        else:
            if S.executor is None:
                return S._no_executor()
            prog = (S.sources._load_yaml(_lab() / "config.yaml").get("agents") or {}).get("programmatic") or {}
            cli = S.executor.backends.resolve_cli(backend, (prog.get("backends") or {}).get(backend) or {})
            argv = terminal.login_argv(backend, cli or [])
            if not argv:
                return {"error": f"{backend} is not installed yet — install it first"}, 400
            res = terminal.open_terminal(argv, _hub())
    else:
        return {"error": "unknown purpose"}, 400
    if not res.get("ok"):
        return res, 500
    S.sources._EXEC_CACHE["ts"] = 0
    if S.executor is not None:
        try:
            S.executor.backends._AUTH_CACHE.clear()
        except AttributeError:
            pass
    S._pi_log({"action": f"terminal.{purpose}", "backend": backend or None})
    what = {"login": "sign-in", "install": "install", "shell": "shell"}[purpose]
    return {"ok": True, "note": f"opened {res['how']} for the {backend + ' ' if backend else ''}{what} — "
                                "finish there; this page updates by itself"}, 200


# ── Gate 3 ───────────────────────────────────────────────────────────────────

def _paper(slug: str) -> Path:
    return _hub() / "studies" / slug / "paper"


def gate3_readiness(slug: str) -> dict:
    """The checklist the Gate 3 sheet shows (tools/gate3.py — the keeper uses the same one). `blocking`
    items must pass to sign."""
    import gate3  # noqa: PLC0415 — tools/ is on sys.path via sources
    out = gate3.readiness(_hub(), slug)
    if out.get("signed"):
        out["valid"], out["valid_why"] = gate3.delegation_valid(_hub(), slug)
    return out


def gate3_sign(body: dict) -> tuple[dict, int]:
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "Gate 3 needs explicit confirm"}, 400
    if str(body.get("typed") or "").strip() != slug:
        return {"error": f"type the study name exactly ({slug}) to sign Gate 3"}, 400
    ready = gate3_readiness(slug)
    if ready["signed"]:
        return {"error": "Gate 3 is already signed for this study"}, 400
    if not ready["can_sign"]:
        why = "; ".join(c["detail"] for c in ready["checks"] if c["blocking"] and not c["ok"])
        return {"error": f"not ready to sign: {why}"}, 400
    paper = _paper(slug)
    paper.mkdir(parents=True, exist_ok=True)
    ts = _ts()
    pdf = paper / "main.pdf"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else None
    warn = [c["label"] for c in ready["checks"] if not c["ok"]]
    lines = [f"# Gate 3 approval — {slug}", "",
             "Gate 3 approved by the PI (signed in the Vivarium dashboard).", "",
             f"- signed_via: dashboard:{ts}",
             f"- state at signing: {(_row(slug) or {}).get('state')}",
             f"- paper: studies/{slug}/paper/main.pdf" + (f" (sha256 {digest})" if digest else " (not compiled)"),
             ]
    if warn:
        lines += ["- signed despite: " + "; ".join(warn)]
    note = str(body.get("note") or "").strip()[:1000]
    if note:
        lines += ["", "PI note:", "", note]
    (paper / "gate3-approval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    S._emit_hub("gate_resolved", idea=slug, detail="Gate 3 signed (PI via dashboard)")
    S._pi_log({"action": "approve_gate", "gate": 3, "idea": slug, "paper_sha256": digest, "warnings": warn or None})
    out = {"ok": True, "gate": 3, "idea": slug, "warnings": warn or None,
           "note": "Gate 3 signed. /finalize can now run for this study."}
    if body.get("launch"):
        res, code = S.launch_run({"skill": "finalize", "target": slug, "confirm": True,
                                  "backend": body.get("backend")}, by="gate3", gate3=True)
        out["launch"] = res
        if code == 200:
            out["note"] = f"Gate 3 signed; /finalize {slug} queued ({res.get('run_id')})."
    return out, 200


def finalize_start(body: dict) -> tuple[dict, int]:
    """Start /finalize for a study whose Gate 3 the PI already signed here (the signature is the
    authority; this is the PI's click to use it). Never reachable by an agent: only this endpoint and
    gate3_sign pass gate3=True, and the executor re-checks the signed note."""
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "starting /finalize needs explicit confirm"}, 400
    if not (_paper(slug) / "gate3-approval.md").exists():
        return {"error": "sign Gate 3 first"}, 400
    res, code = S.launch_run({"skill": "finalize", "target": slug, "confirm": True, "backend": body.get("backend")},
                             by="gate3", gate3=True)
    return res, code


# ── revoke ───────────────────────────────────────────────────────────────────

def gate_revoke(body: dict) -> tuple[dict, int]:
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "revoking a signature needs explicit confirm"}, 400
    what = str(body.get("what") or body.get("gate") or "")
    if what in ("1", "gate1"):
        prop = _hub() / "studies" / slug / "proposal.md"
        text = _read(prop)
        if text is None:
            return {"error": "no proposal"}, 400
        new = re.sub(r"\n*<!-- " + re.escape(S.sources.GATE1_MARK) + r"[^>]*-->\n?", "\n", text)
        if new == text:
            return {"error": "no dashboard Gate-1 signature on this proposal"}, 400
        _write_keep_eol(prop, text, new)
        row = _row(slug)
        warn = ["the project is already spawned — revoking Gate 1 does not undo that"] \
            if row and (row.get("state") or "") not in ("proposal", "scoping") else None
    elif what in ("2", "gate2"):
        pdir = S._pdir(slug)
        ctl = (pdir / "control.yaml") if pdir else None
        text = _read(ctl) if ctl else None
        if text is None:
            return {"error": "no control.yaml"}, 400
        new = _set_block(text.replace("\r\n", "\n"), "gate2_envelope", {"pi_signed": "false", "signed_via": "null"})
        if new == text.replace("\r\n", "\n"):
            return {"error": "the envelope is not signed"}, 400
        _write_keep_eol(ctl, text, new)
        warn = None
    elif what in ("3", "gate3"):
        note = _paper(slug) / "gate3-approval.md"
        if not note.exists():
            return {"error": "Gate 3 is not signed"}, 400
        if ((_row(slug) or {}).get("state") or "") == "final":
            return {"error": "already finalized — revoking now would not undo it"}, 400
        note.unlink()
        warn = None
    elif what == "loop":
        pdir = S._pdir(slug)
        brief = (pdir / "LOOP_BRIEF.md") if pdir else None
        text = _read(brief) if brief else None
        if text is None:
            return {"error": "no LOOP_BRIEF.md"}, 400
        new = re.sub(r"-\s*\[[xX]\]\s*Authorized as scoped above", "- [ ] Authorized as scoped above", text)
        if new == text:
            return {"error": "the loop brief is not authorized"}, 400
        _write_keep_eol(brief, text, new)
        warn = ["a running loop keeps going until you stop it"] if S.executor else None
    else:
        return {"error": "what must be gate1 | gate2 | gate3 | loop"}, 400
    S._emit_hub("gate_revoked", idea=slug, detail=f"{what} signature revoked (PI via dashboard)")
    S._pi_log({"action": "revoke", "what": what, "idea": slug})
    return {"ok": True, "warnings": warn, "note": "signature revoked"}, 200


# ── envelope editor ──────────────────────────────────────────────────────────

ENV_KEYS = ("full_runs", "per_run_max_minutes", "total_max_minutes", "expires")


def _set_block(text: str, block: str, values: dict) -> str:
    """Set `key: value` lines inside a top-level YAML block, keeping comments; adds missing keys at the
    block's end."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if re.match(rf"{re.escape(block)}:\s*(#.*)?$", ln)), None)
    if start is None:
        return text
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].strip() and not lines[j].startswith((" ", "\t")):
            end = j
            break
    todo = dict(values)
    for j in range(start + 1, end):
        m = re.match(r"(\s+)([A-Za-z_]+):(\s*)([^#\n]*?)(\s*#.*)?$", lines[j])
        if m and m.group(2) in todo:
            v = todo.pop(m.group(2))
            pad = m.group(3) or " "
            lines[j] = f"{m.group(1)}{m.group(2)}:{pad}{v}{m.group(5) or ''}"
    if todo:
        last = end
        while last > start + 1 and not lines[last - 1].strip():
            last -= 1
        for k, v in todo.items():
            lines.insert(last, f"  {k}: {v}")
            last += 1
    return "\n".join(lines)


def envelope_set(body: dict) -> tuple[dict, int]:
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "changing the envelope needs explicit confirm"}, 400
    pdir = S._pdir(slug)
    ctl = (pdir / "control.yaml") if pdir else None
    text = _read(ctl) if ctl else None
    if text is None:
        return {"error": f"no control.yaml for {slug} (spawn the project first)"}, 400
    vals = body.get("values") or {}
    out = {}
    try:
        for k in ("full_runs", "per_run_max_minutes", "total_max_minutes"):
            if k in vals:
                x = int(vals[k])
                if x < 0 or x > 100000:
                    raise ValueError(k)
                out[k] = str(x)
        if "expires" in vals:
            e = str(vals.get("expires") or "").strip()
            if e and not re.match(r"^\d{4}-\d{2}-\d{2}$", e):
                raise ValueError("expires")
            if e and e < time.strftime("%Y-%m-%d"):
                return {"error": "the expiry date is in the past"}, 400
            out["expires"] = e or "null"
    except (TypeError, ValueError) as e:
        return {"error": f"{e}: must be a whole number ≥ 0 (expires: YYYY-MM-DD)"}, 400
    before = (S.sources._load_yaml(ctl).get("gate2_envelope") or {})
    sign = bool(body.get("sign"))
    ts = _ts()
    changed_values = any(str(before.get(k) if before.get(k) is not None else "null") != out[k] for k in out)
    if sign:
        out.update(pi_signed="true", signed_via=f"dashboard:{ts}")
    elif changed_values and before.get("pi_signed"):
        out.update(pi_signed="false", signed_via="null")   # new values are not what the PI signed
    new = _set_block(text.replace("\r\n", "\n"), "gate2_envelope", out)
    try:
        import yaml
        doc = yaml.safe_load(new) or {}
    except Exception as e:  # noqa: BLE001
        return {"error": f"refused: control.yaml would not parse ({e})"}, 400
    env = doc.get("gate2_envelope") or {}
    for k in ("full_runs", "per_run_max_minutes", "total_max_minutes"):
        if k in out and int(env.get(k) or 0) != int(out[k]):
            return {"error": "refused: the edited envelope does not read back correctly"}, 400
    _write_keep_eol(ctl, text, new)
    S._emit_hub("gate_resolved" if sign else "envelope_changed", idea=slug,
                detail="Gate 2 envelope " + ("signed" if sign else "updated") + " (PI via dashboard)")
    S._pi_log({"action": "envelope.set", "idea": slug, "before": before, "after": env, "signed": sign})
    note = ("envelope saved and signed — FULL runs within it are authorized" if sign else
            "envelope saved (not signed)" + (" — its old signature was withdrawn because the values changed"
                                             if changed_values and before.get("pi_signed") else ""))
    return {"ok": True, "envelope": env, "note": note}, 200


# ── loop brief ───────────────────────────────────────────────────────────────

def loopbrief_sign(body: dict) -> tuple[dict, int]:
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "authorizing the loop needs explicit confirm"}, 400
    mode = str(body.get("mode") or "execute")
    if mode not in ("execute", "explore"):
        return {"error": "mode must be execute or explore"}, 400
    pdir = S._pdir(slug)
    brief = (pdir / "LOOP_BRIEF.md") if pdir else None
    text = _read(brief) if brief else None
    if text is None:
        return {"error": f"{slug} has no LOOP_BRIEF.md yet — the loop's first step writes it (Start loop)"}, 400
    if re.search(r"-\s*\[[xX]\]\s*Authorized as scoped above", text):
        return {"error": "this loop brief is already authorized"}, 400
    ts = _ts()
    new = re.sub(r"-\s*\[ \]\s*Authorized as scoped above", "- [x] Authorized as scoped above", text, count=1)
    if new == text:
        return {"error": "LOOP_BRIEF.md has no '- [ ] Authorized as scoped above' line — unexpected format"}, 400
    new = re.sub(r"\*\*PI:\*\*\s*_+\s*·\s*\*\*Date:\*\*\s*_+",
                 f"**PI:** signed in the dashboard (signed_via: dashboard:{ts}) · **Date:** {ts[:10]}", new, count=1)
    new = re.sub(r"(\*\*Mode:\*\*\s*)`(execute|explore)`", rf"\1`{mode}`", new, count=1)
    _write_keep_eol(brief, text, new)
    S._emit_hub("gate_resolved", idea=slug, detail=f"LOOP_BRIEF authorized, mode {mode} (PI via dashboard)")
    S._pi_log({"action": "loopbrief.sign", "idea": slug, "mode": mode})
    out = {"ok": True, "note": f"loop authorized ({mode})"}
    if body.get("launch"):
        res, code = S.launch_run({"skill": "research-loop", "target": slug, "confirm": True,
                                  "backend": body.get("backend")}, by="loopbrief")
        out["launch"] = res
        if code == 200:
            out["note"] = f"loop authorized ({mode}); /research-loop {slug} queued"
    return out, 200


# ── campaign brief ───────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s[:40] or "campaign").strip("-")


def campaign_create(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "signing a campaign needs explicit confirm"}, 400
    f = body.get("fields") or {}
    direction = str(f.get("direction") or "").strip()
    if not direction:
        return {"error": "describe the research direction"}, 400
    try:
        n = lambda k, lo=0, d=None: max(lo, int(f.get(k) if f.get(k) not in (None, "") else d))  # noqa: E731
        ideas, parallel = n("ideas", 1, 3), n("parallel", 1, 1)
        budget_total = str(f.get("compute_total") or "").strip() or "—"
        full_runs, full_min = n("full_runs", 0, 3), n("full_minutes", 0, 60)
        open_q = n("max_open_questions", 0, 2)
        rounds, lines_per = n("explore_rounds", 0, 1), n("explore_lines", 0, 2)
    except (TypeError, ValueError):
        return {"error": "numbers must be whole numbers"}, 400
    try:
        hours = float(f.get("hours") if f.get("hours") not in (None, "") else 12)
        agent_hours = float(f.get("agent_hours") if f.get("agent_hours") not in (None, "") else 0)
        cycle_minutes = float(f.get("cycle_minutes") if f.get("cycle_minutes") not in (None, "") else 90)
        repeat_minutes = float(f.get("repeat_minutes") if f.get("repeat_minutes") not in (None, "") else 20)
    except (TypeError, ValueError):
        return {"error": "hours and minutes must be numbers"}, 400
    if not (0 < hours <= 24 * 30) or agent_hours < 0 or not (10 <= cycle_minutes <= 24 * 60) or not (5 <= repeat_minutes <= 24 * 60):
        return {"error": "wall-clock 0–720 h; each cycle 10–1440 min; a pass every 5–1440 min"}, 400
    gate3_auto = bool(f.get("gate3"))
    if gate3_auto and str(body.get("gate3_typed") or "").strip().lower() != "finalize":
        return {"error": "to let papers finalize without you, type finalize to confirm"}, 400
    deadline = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + hours * 3600))
    wall = str(f.get("wall_clock") or "").strip() or f"{hours:g} h (until {deadline})"
    mode = str(f.get("mode") or "execute")
    if mode not in ("execute", "explore"):
        return {"error": "loop mode must be execute or explore"}, 400
    for v in (direction, budget_total, wall):
        if len(v) > 600 or "\n## " in v:
            return {"error": "keep each field short (no section headings)"}, 400
    tpl = _read(_hub() / "templates" / "loop" / "CAMPAIGN.md")
    if tpl is None:
        return {"error": "templates/loop/CAMPAIGN.md is missing"}, 500
    date, ts = time.strftime("%Y-%m-%d"), _ts()
    slug = _slugify(str(f.get("name") or direction))
    name = f"{date}-{slug}.md"
    dest = _lab() / "campaigns" / name
    i = 2
    while dest.exists():
        name = f"{date}-{slug}-{i}.md"
        dest = _lab() / "campaigns" / name
        i += 1
    t = tpl.replace("{{date}}-{{slug}}", name[:-3])
    t = t.replace("**Research direction(s):** <!-- from the PI -->", f"**Research direction(s):** {direction}")
    t = t.replace("carry up to ___ ideas", f"carry up to {ideas} ideas")
    t = t.replace("≤ ___ ideas in flight", f"≤ {parallel} ideas in flight")
    t = t.replace("- [ ] Compute budget ≤ ___ total, FULL runs ≤ ___ × ___ min",
                  f"- [x] Compute budget ≤ {budget_total} total, FULL runs ≤ {full_runs} × {full_min} min")
    t = t.replace("- [ ] Kill criteria + frozen eval", "- [x] Kill criteria + frozen eval")
    t = t.replace("- [ ] Novelty verdict", "- [x] Novelty verdict")
    t = t.replace("- [ ] Scoping value re-verification passed with ≤ ___ open questions",
                  f"- [x] Scoping value re-verification passed with ≤ {open_q} open questions")
    t = re.sub(r"\*\*Loop mode for spawned projects:\*\* `execute`", f"**Loop mode for spawned projects:** `{mode}`", t)
    t = t.replace("caps: ___ expansion rounds, ___ new lines/round", f"caps: {rounds} expansion rounds, {lines_per} new lines/round")
    t = re.sub(r"\*\*Total wall-clock:\*\* ___ \([^)]*\)", f"**Total wall-clock:** {wall}", t)
    t = t.replace("**Total compute:** ___", f"**Total compute:** {budget_total}"
                  + (f" · agent time ≤ {agent_hours:g} h" if agent_hours else ""))
    if gate3_auto:
        t = t.replace("- [ ] Papers may finalize without me", "- [x] Papers may finalize without me")
    t = t.replace("- [ ] Authorized as scoped above · **PI:** ______ · **Date/time:** ______",
                  f"- [x] Authorized as scoped above · **PI:** signed in the dashboard (signed_via: dashboard:{ts}) "
                  f"· **Date/time:** {ts}")
    t = t.replace("*Created by `/autopilot`", "*Created in the Vivarium dashboard (the PI's campaign form)")
    if "- [x] Authorized as scoped above" not in t:
        return {"error": "the campaign template's authorization line has an unexpected format"}, 500
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(t, encoding="utf-8")
    rel = f"lab/campaigns/{name}"
    S._emit_hub("campaign_signed", detail=f"campaign {rel} signed (PI via dashboard)")
    S._pi_log({"action": "campaign.sign", "file": rel, "fields": f})
    out = {"ok": True, "file": rel, "note": f"campaign signed: {rel}", "gate3_auto": gate3_auto}
    if body.get("launch"):
        try:
            from executor import campaigns  # noqa: PLC0415 — tools/ is on sys.path via sources
            lab = S.sources.executor.Lab(_hub())
            S.sources.executor.check_enabled(lab)
            st = campaigns.create(lab, rel, hours=hours, agent_minutes=agent_hours * 60, cycle_minutes=cycle_minutes,
                                  repeat_minutes=repeat_minutes, gate3_auto=gate3_auto,
                                  backend=body.get("backend") or None)
        except Exception as e:  # noqa: BLE001 — the brief is signed either way; say why it didn't start
            out["note"] = f"campaign signed ({rel}) but not started: {e}"
            out["warnings"] = [str(e)]
            return out, 200
        S._pi_log({"action": "campaign.start", "file": rel, "hours": hours, "agent_hours": agent_hours,
                   "cycle_minutes": cycle_minutes, "repeat_minutes": repeat_minutes, "gate3_auto": gate3_auto})
        out.update(campaign=st["name"], note=f"campaign signed and started — the lab keeps it going until {deadline}")
    return out, 200


CAMPAIGN_ACTIONS = ("pause", "resume", "stop", "revoke_gate3", "hold", "unhold")


def campaign_control(body: dict) -> tuple[dict, int]:
    """The PI's controls on a running campaign (the campaign card)."""
    name, action = str(body.get("name") or ""), str(body.get("action") or "")
    if action not in CAMPAIGN_ACTIONS:
        return {"error": f"action must be one of {', '.join(CAMPAIGN_ACTIONS)}"}, 400
    if action in ("stop", "revoke_gate3") and not body.get("confirm"):
        return {"error": "confirm first"}, 400
    try:
        from executor import campaigns  # noqa: PLC0415
        st = campaigns.control(S.sources.executor.Lab(_hub()), name, action, study=body.get("study") or None)
    except (ValueError, OSError) as e:
        return {"error": str(e)}, 400
    S._pi_log({"action": f"campaign.{action}", "campaign": name, "study": body.get("study")})
    words = {"pause": "paused", "resume": "resumed", "stop": "stopping — it writes its final report",
             "revoke_gate3": "Gate 3 is yours again for this campaign", "hold": "held from auto-finalizing",
             "unhold": "released"}
    return {"ok": True, "note": words[action], "status": st.get("status")}, 200


def campaign_preflight(q: dict) -> tuple[dict, int]:
    """Can the lab run on its own right now? What a walk-away start needs, checked."""
    ex = S.sources.executor
    if ex is None:
        return {"ok": True, "ready": False, "checks": [{"id": "executor", "ok": False, "label": "The executor is available",
                                                        "detail": "tools/executor is missing"}]}, 200
    lab = ex.Lab(_hub())
    prog = lab.prog()
    status = S.sources.executor_status()
    backend = prog.get("backend") or "claude"
    cli = (status.get("clis") or {}).get(backend) or {}
    checks = [{"id": "launch", "ok": bool(prog.get("enabled")), "label": "Agents may be started from the dashboard",
               "detail": "Settings → Autonomy & limits → Launching agents", "fix": "settings/autonomy"},
              {"id": "cli", "ok": bool(cli.get("found") or cli.get("path") or cli.get("version")),
               "label": f"The {backend} CLI is installed", "detail": cli.get("version") or cli.get("error") or "",
               "fix": "settings/agents"}]
    li = cli.get("logged_in")
    checks.append({"id": "auth", "ok": li is not False, "label": f"{backend} is signed in",
                   "detail": "" if li else ("not signed in — Settings → Agents → Sign in…" if li is False else
                                            "can't tell from here — checked on the first run"), "fix": "settings/agents"})
    pm = str(prog.get("permission_mode") or "auto")
    checks.append({"id": "perm", "ok": pm in ("auto", "acceptEdits", "dontAsk"),
                   "label": "Agents won't stop to ask for tool permissions", "detail": f"permission mode: {pm}",
                   "fix": "settings/autonomy"})
    root = lab.projects_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".newts-write-test"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        writable = True
    except OSError:
        writable = False
    checks.append({"id": "projects", "ok": writable, "label": "The projects folder is writable", "detail": str(root),
                   "fix": "settings/lab"})
    import shutil as _sh  # noqa: PLC0415
    tex = bool(_sh.which("latexmk") or _sh.which("pdflatex") or _sh.which("tectonic"))
    checks.append({"id": "latex", "ok": tex, "warn_only": True, "label": "LaTeX is installed (papers compile to PDF)",
                   "detail": "" if tex else "without it papers stay .tex and Gate 3 can't be delegated"})
    try:
        from executor import awake  # noqa: PLC0415
        aw = awake.status()
    except Exception:  # noqa: BLE001
        aw = {"available": False, "detail": ""}
    checks.append({"id": "awake", "ok": bool(aw.get("available")), "warn_only": True,
                   "label": "The computer stays awake while agents work", "detail": aw.get("detail") or ""})
    return {"ok": True, "checks": checks, "ready": all(c["ok"] for c in checks if not c.get("warn_only"))}, 200


# ── revive ───────────────────────────────────────────────────────────────────

def _revive_to() -> tuple:
    return tuple(S.sources.workflow.revivable_states(_hub()))   # workflow/stages.yaml `revivable: true`


def revive(body: dict) -> tuple[dict, int]:
    slug = _need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "reviving needs explicit confirm"}, 400
    reason = str(body.get("reason") or "").strip().replace("|", "/").replace("\n", " ")[:300]
    if not reason:
        return {"error": "say why it comes back (it is recorded)"}, 400
    to = str(body.get("to") or "triaged")
    if to not in _revive_to():
        return {"error": f"revive into one of {', '.join(_revive_to())}"}, 400
    reg = _lab() / "REGISTRY.md"
    text = _read(reg)
    if text is None:
        return {"error": "no lab/REGISTRY.md"}, 400
    lines = text.replace("\r\n", "\n").split("\n")
    hit = None
    for i, ln in enumerate(lines):
        cells = ln.strip().strip("|").split("|")
        if len(cells) >= 8 and cells[0].strip() == slug:
            hit = (i, cells)
            break
    if not hit:
        return {"error": f"{slug} is not in the registry"}, 400
    i, cells = hit
    was = cells[2].strip()
    if was not in ("parked", "killed"):
        return {"error": f"{slug} is '{was}', not parked or killed"}, 400
    cells[2] = f" {to} "
    cells[6] = f" {time.strftime('%Y-%m-%d')} "
    cells[7] = f" revived by the PI: {reason} "
    lines[i] = "|" + "|".join(cells) + "|"
    _write_keep_eol(reg, text, "\n".join(lines))
    idea = _hub() / "studies" / slug / "IDEA.md"
    it = _read(idea)
    if it is not None:
        new = re.sub(r"^(state:\s*)\S+", rf"\g<1>{to}", it, count=1, flags=re.M)
        new = new.rstrip("\n") + f"\n- {time.strftime('%Y-%m-%d')}: {was} → {to} — revived by the PI (dashboard): {reason}\n"
        _write_keep_eol(idea, it, new)
    S._emit_hub("state_change", idea=slug, detail=f"{was} → {to} (revived by the PI: {reason})")
    S._pi_log({"action": "revive", "idea": slug, "from": was, "to": to, "reason": reason})
    return {"ok": True, "note": f"{slug} is back in {to}"}, 200


# ── PI documents ─────────────────────────────────────────────────────────────

PI_DOCS = {"system": "lab/SYSTEM.md", "open-questions": "lab/knowledge/OPEN-QUESTIONS.md"}


def doc_get(which: str) -> tuple[dict, int]:
    rel = PI_DOCS.get(which)
    if not rel:
        return {"error": "unknown document"}, 400
    p = _hub() / rel
    text = _read(p)
    if text is None and which == "system":
        text = _read(_hub() / "templates" / "SYSTEM.md") or "# This machine\n"
        return {"ok": True, "rel": rel, "text": text, "exists": False}, 200
    return {"ok": True, "rel": rel, "text": text or "", "exists": text is not None}, 200


def doc_save(body: dict) -> tuple[dict, int]:
    rel = PI_DOCS.get(str(body.get("doc") or ""))
    if not rel:
        return {"error": "this document can't be edited here"}, 400
    text = body.get("text")
    if not isinstance(text, str) or len(text) > 200_000:
        return {"error": "text missing or too long"}, 400
    p = _hub() / rel
    old = _read(p) or ""
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_keep_eol(p, old, text)
    S._pi_log({"action": "doc.save", "doc": rel, "chars": len(text)})
    return {"ok": True, "note": f"saved {rel}"}, 200


# ── The workflow: the PI's instructions per procedure / stage / role (tools/workflow.py) ─────────

def _wf():
    return S.sources.workflow


def _study_arg(v) -> str | None:
    v = str(v or "").strip()
    if not v or v == "lab":
        return None
    if not re.match(r"^[a-z0-9][a-z0-9._-]{0,79}$", v) or not (_hub() / "studies" / v).is_dir():
        raise ValueError(f"no study '{v}'")
    return v


def _strip_fm(text: str) -> str:
    return _wf().split_frontmatter(text or "")[1].strip()


def workflow_item(q: dict) -> tuple[dict, int]:
    """Everything the Workflow page shows for one procedure, stage or role — at lab level, or one study's."""
    wf, hub = _wf(), _hub()
    kind = str(q.get("kind") or "procedure")
    name = str(q.get("name") or "")
    try:
        study = _study_arg(q.get("study"))
        m = wf.load(hub)
        if kind == "procedure":
            p = (m.get("procedures") or {}).get(name)
            if not p:
                return {"error": f"unknown procedure '{name}'"}, 404
            skill = _read(hub / ".claude" / "skills" / name / "SKILL.md") or ""
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
                    "contract": (_read(hub / "agent-roles" / f"{name}.md") or "").strip(),
                    "lab": {"add": wf.read_custom("role", name, hub)[1].strip()}}, 200
    except ValueError as e:
        return {"error": str(e)}, 400
    return {"error": "kind must be procedure | stage | role"}, 400


def workflow_save(body: dict) -> tuple[dict, int]:
    """Save (empty text = remove) one layer: kind add | method | stage | role, lab-wide or for one study."""
    wf, hub = _wf(), _hub()
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
    S._pi_log({"action": "workflow.save", "kind": kind, "name": name, "study": study, "chars": len(text.strip()),
               "file": rel})
    where = f"for {study}" if study else "lab-wide"
    return {"ok": True, "note": (f"saved {where}" if path else f"reset to the default ({where})"), "file": rel,
            "warnings": warnings}, 200


def workflow_proposal(body: dict) -> tuple[dict, int]:
    """Accept or decline an agent's suggested instruction change."""
    wf = _wf()
    pid, accept = str(body.get("id") or ""), body.get("accept")
    if not isinstance(accept, bool):
        return {"error": "accept must be true or false"}, 400
    try:
        rec = wf.resolve_proposal(pid, accept, _hub())
    except (OSError, ValueError) as e:
        return {"error": str(e)}, 400
    if rec["kind"] == "role" and accept:
        subprocess.run([sys.executable, str(_hub() / "tools" / "role_sync.py"), "render"], cwd=str(_hub()),
                       capture_output=True, timeout=120)
    S._emit_hub("instruction_resolved", idea=rec.get("study"), detail=f"{rec['status']}: {rec['kind']} {rec['name']}")
    S._pi_log({"action": "workflow.proposal", "id": pid, "accept": accept, "kind": rec["kind"], "name": rec["name"],
               "study": rec.get("study")})
    return {"ok": True, "note": "added to the instructions" if accept else "declined"}, 200


def workflow_proposal_get(q: dict) -> tuple[dict, int]:
    pid = str(q.get("id") or "")
    for r in _wf().proposals(_hub(), pending_only=False):
        if r.get("id") == pid:
            return {"ok": True, **r}, 200
    return {"error": "no such proposal"}, 404


# ── Lab settings ─────────────────────────────────────────────────────────────

def _intv(lo, hi):
    def f(v):
        x = int(v)
        if not (lo <= x <= hi):
            raise ValueError(f"a whole number {lo}–{hi}")
        return x
    return f


def _strv(maxlen, rx=None):
    def f(v):
        v = str(v).strip()
        if not v or len(v) > maxlen or (rx and not re.match(rx, v)):
            raise ValueError("a short text value")
        return v
    return f


LAB_CONFIG = {
    "name": (["lab", "name"], _strv(80)),
    "projects_root": (["lab", "projects_root"], _strv(300, r"^[^\n\"]+$")),
    "max_concurrent_runs": (["compute", "max_concurrent_runs"], _intv(1, 64)),
    "oversight": (["oversight", "level"], lambda v: _enum_s(v, ("standard", "strict"))),
    "venue": (["writing", "venue"], _strv(40, r"^[A-Za-z0-9 ._-]+$")),
    "page_limit": (["writing", "page_limit"], _intv(1, 100)),
    "max_concurrent_projects": (["autopilot", "max_concurrent_projects"], _intv(1, 16)),
    "loop_mode": (["loop", "mode"], lambda v: _enum_s(v, ("execute", "explore"))),
    "explore_rounds": (["loop", "explore_max_expansion_rounds"], _intv(0, 20)),
    "in_project_approval": (["ideation", "in_project_approval"], lambda v: _enum_s(v, ("pi", "campaign_auto"))),
    "keep_awake": (["lab", "keep_awake"], lambda v: _enum_s("off" if v is False else v, ("auto", "off"))),
}


def _enum_s(v, allowed):
    v = str(v).strip()
    if v not in allowed:
        raise ValueError("one of " + ", ".join(allowed))
    return v


def lab_config_get() -> tuple[dict, int]:
    cfg = S.sources._load_yaml(_lab() / "config.yaml")
    out = {}
    for k, (path, _p) in LAB_CONFIG.items():
        node = cfg
        for part in path:
            node = node.get(part) if isinstance(node, dict) else None
        out[k] = node
    tier = None
    for line in (_read(_lab() / "config.yaml") or "").splitlines()[:40]:
        m = re.search(r"profile:\s*(low|medium|high)\b", line)
        if m:
            tier = m.group(1)
    out["budget_tier"] = tier
    out["name"] = out.get("name") or _hub().name
    out["keep_awake"] = "off" if out.get("keep_awake") is False else (out.get("keep_awake") or "auto")
    return {"ok": True, "config": out, "setup": setup_status()}, 200


def lab_config_set(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "changing lab settings needs explicit confirm"}, 400
    changes = body.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        return {"error": "no changes"}, 400
    tier = changes.pop("budget_tier", None)
    parsed = {}
    for k, v in changes.items():
        if k not in LAB_CONFIG:
            return {"error": f"'{k}' can't be changed here"}, 400
        try:
            parsed[k] = LAB_CONFIG[k][1](v)
        except (TypeError, ValueError) as e:
            return {"error": f"{k}: must be {e}"}, 400
    notes = []
    if tier is not None:
        if tier not in ("low", "medium", "high"):
            return {"error": "budget tier must be low, medium or high"}, 400
        r = subprocess.run([sys.executable, str(_hub() / "tools" / "profiles.py"), "apply", tier],
                           cwd=str(_hub()), capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return {"error": f"could not apply the {tier} budget profile: {(r.stderr or r.stdout)[-400:]}"}, 400
        notes.append(f"applied the {tier} budget profile")
    if parsed:
        _tools()
        import profiles   # noqa: E402
        cfg = _lab() / "config.yaml"
        text = cfg.read_text(encoding="utf-8-sig")
        for k, v in parsed.items():
            text, ok = S._stamp_or_insert(profiles, text, LAB_CONFIG[k][0], v)
            if not ok:
                text = _insert_section(text, LAB_CONFIG[k][0], v)
        try:
            import yaml
            doc = yaml.safe_load(text) or {}
            for k, v in parsed.items():
                node = doc
                for part in LAB_CONFIG[k][0]:
                    node = node.get(part) if isinstance(node, dict) else None
                if node != v:
                    raise ValueError(k)
        except Exception as e:  # noqa: BLE001
            return {"error": f"refused: lab/config.yaml would not read back correctly ({e})"}, 400
        cfg.write_text(text, encoding="utf-8", newline="")
        notes.append(f"saved {len(parsed)} setting(s)")
    S._pi_log({"action": "lab.config", "changes": parsed, "budget_tier": tier})
    S.sources._EXEC_CACHE["ts"] = 0
    return {"ok": True, "changes": parsed, "note": "; ".join(notes) or "nothing changed"}, 200


def _insert_section(text: str, dotted: list, value) -> str:
    """A section missing entirely (e.g. autopilot:) — append it at the end."""
    _tools()
    import profiles   # noqa: E402
    out = text.rstrip("\n") + "\n\n"
    for depth, key in enumerate(dotted[:-1]):
        out += "  " * depth + f"{key}:\n"
    out += "  " * (len(dotted) - 1) + f"{dotted[-1]}: {profiles._fmt(value)}\n"
    return out


# ── research keys (lab/.env.local) ───────────────────────────────────────────

KNOWN_KEYS = {"S2_API_KEY": "Semantic Scholar", "OPENALEX_API_KEY": "OpenAlex"}
_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")


def _env_path() -> Path:
    return _lab() / ".env.local"


def _env_read() -> dict:
    out = {}
    for line in (_read(_env_path()) or "").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def keys_status() -> tuple[dict, int]:
    have = _env_read()
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
    lines = ["# Research API keys for this lab — written by the dashboard, inherited by runs. Never commit."]
    lines += [f"{k}={v}" for k, v in have.items()]
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ensure_gitignored()
    S._pi_log({"action": "keys.set", "key": key, "set": bool(value)})   # never the value
    return {"ok": True, "note": f"{key} {'saved' if value else 'removed'}"}, 200


def _ensure_gitignored() -> None:
    gi = _hub() / ".gitignore"
    text = _read(gi) or ""
    if "lab/.env.local" not in text:
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n# Research API keys (dashboard → Settings → Research keys)\nlab/.env.local\n")


# ── first-run setup ──────────────────────────────────────────────────────────

def setup_status() -> dict:
    cfg = S.sources._load_yaml(_lab() / "config.yaml")
    done = (cfg.get("dashboard") or {}).get("setup_completed")
    rows = [r for r in S.sources.parse_registry() if r.get("id")]
    return {"completed": bool(done), "completed_at": str(done) if done else None,
            "fresh": not rows, "lab": {"name": lab_name(_hub()), "path": str(_hub())}}


def setup_complete(body: dict) -> tuple[dict, int]:
    _tools()
    import profiles   # noqa: E402
    cfg = _lab() / "config.yaml"
    text = cfg.read_text(encoding="utf-8-sig")
    stamp = time.strftime("%Y-%m-%d")
    new, ok = S._stamp_or_insert(profiles, text, ["dashboard", "setup_completed"], stamp if body.get("done", True) else None)
    if not ok:
        new = _insert_section(text, ["dashboard", "setup_completed"], stamp)
    cfg.write_text(new, encoding="utf-8", newline="")
    S._pi_log({"action": "setup.complete", "done": bool(body.get("done", True))})
    return {"ok": True}, 200


# ── server ───────────────────────────────────────────────────────────────────

def server_stop(body: dict) -> tuple[dict, int]:
    if not body.get("confirm"):
        return {"error": "stopping the server needs explicit confirm"}, 400
    srv = getattr(S, "SERVER", None)
    if srv is None:
        return {"error": "no server handle"}, 500
    S._pi_log({"action": "server.stop"})
    threading.Timer(0.5, srv.shutdown).start()
    note = "the dashboard server is stopping — running agents keep going"
    try:
        from executor import campaigns  # noqa: PLC0415
        live = [c for c in campaigns.all_states(S.sources.executor.Lab(_hub())) if c.get("status") in ("active", "finishing")]
        if live:
            note += f", and a background scheduler keeps {len(live)} campaign(s) going"
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "note": note}, 200


# ── System: what this machine offers + how training runs here (compute.scheduler) ──────────────

_SYS_CACHE: dict = {"hub": None, "at": 0.0, "facts": None}
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.,:=+@/%-]{0,120}$")


def system_info(q: dict) -> tuple[dict, int]:
    """tools/system_probe.py run on the machine this lab lives on (cached 10 min) + the scheduler block."""
    fresh = bool(q.get("fresh"))
    if fresh or _SYS_CACHE["hub"] != str(_hub()) or time.time() - _SYS_CACHE["at"] > 600 or not _SYS_CACHE["facts"]:
        r = subprocess.run([sys.executable, str(Path(S.__file__).resolve().parents[1] / "tools" / "system_probe.py"),
                            "--hub", str(_hub())], capture_output=True, text=True, timeout=90)
        try:
            _SYS_CACHE.update(hub=str(_hub()), at=time.time(), facts=json.loads(r.stdout))
        except ValueError:
            return {"error": f"the system probe failed: {(r.stderr or r.stdout)[-300:]}"}, 500
    cfg = S.sources._load_yaml(_lab() / "config.yaml")
    sched = ((cfg.get("compute") or {}).get("scheduler")) or {"kind": "local"}
    return {"ok": True, "facts": _SYS_CACHE["facts"], "scheduler": sched,
            "system_md": (_lab() / "SYSTEM.md").exists()}, 200


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
    cfg = _lab() / "config.yaml"
    text = _read(cfg)
    if text is None:
        return {"error": "no lab/config.yaml"}, 400
    new = _replace_block(text, "compute", "scheduler", block)
    try:
        import yaml
        got = ((yaml.safe_load(new) or {}).get("compute") or {}).get("scheduler")
        if got != block:
            raise ValueError("mismatch")
    except Exception as e:  # noqa: BLE001
        return {"error": f"refused: lab/config.yaml would not read back correctly ({e})"}, 400
    _write_keep_eol(cfg, text, new)
    S._pi_log({"action": "system.scheduler", "scheduler": block})
    return {"ok": True, "scheduler": block,
            "note": "training runs locally" if block["kind"] == "local" else f"PILOT/FULL runs now go through {block['kind']}"}, 200
