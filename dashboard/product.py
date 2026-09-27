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
    """The checklist the Gate 3 sheet shows. `blocking` items must pass to sign."""
    row = _row(slug)
    paper = _paper(slug)
    state = (row or {}).get("state") or ""
    checks = []
    checks.append({"id": "state", "label": "Internal review is complete (state: internal-review)",
                   "ok": state == "internal-review", "blocking": True,
                   "detail": f"state is '{state or 'unknown'}'"})
    meta = ""
    for f in sorted(paper.glob("reviews/**/meta-review*.md")) if paper.is_dir() else []:
        meta = _read(f) or meta
    verdict = S._meta_verdict(meta) if meta else ""
    accept = bool(re.search(r"\baccept", verdict, re.I)) and not re.search(r"\breject|needs[- ]experiment", verdict, re.I)
    checks.append({"id": "meta", "label": "The meta-review recommends accepting", "ok": accept, "blocking": False,
                   "detail": (verdict[:300] or "no meta-review found")})
    pdf = paper / "main.pdf"
    checks.append({"id": "pdf", "label": "The paper compiles (main.pdf)", "ok": pdf.exists(), "blocking": False,
                   "detail": "studies/%s/paper/main.pdf" % slug})
    claims = paper / "claims.yaml"
    checks.append({"id": "claims", "label": "Every claim is mapped to an artifact (claims.yaml)", "ok": claims.exists(),
                   "blocking": False, "detail": "run the claims audit from the Paper tab" if claims.exists() else "no claims.yaml"})
    signed = (paper / "gate3-approval.md").exists()
    return {"ok": True, "idea": slug, "checks": checks, "signed": signed,
            "can_sign": all(c["ok"] for c in checks if c["blocking"]) and not signed}


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
    wall = str(f.get("wall_clock") or "").strip() or "—"
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
    t = t.replace("**Total compute:** ___", f"**Total compute:** {budget_total}")
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
    out = {"ok": True, "file": rel, "note": f"campaign signed: {rel}"}
    if body.get("launch"):
        rep = body.get("repeat_minutes")
        res, code = S.launch_run({"skill": "autopilot", "args": rel, "confirm": True, "backend": body.get("backend"),
                                  "repeat_minutes": rep or 30, "max_repeats": body.get("max_repeats") or 48},
                                 by="campaign")
        out["launch"] = res
        if code == 200:
            out["note"] = f"campaign signed and started ({rel})"
    return out, 200


# ── revive ───────────────────────────────────────────────────────────────────

REVIVE_TO = ("seed", "triaged", "lit-review", "scoping", "proposal", "active")


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
    if to not in REVIVE_TO:
        return {"error": f"revive into one of {', '.join(REVIVE_TO)}"}, 400
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
    return {"ok": True, "note": "the dashboard server is stopping — running agents keep going"}, 200
