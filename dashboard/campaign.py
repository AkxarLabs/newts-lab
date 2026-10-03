"""Campaigns: write and sign lab/campaigns/<date>-<slug>.md from the form, the PI's controls on a running
one (pause, resume, stop, Gate 3 back, hold, answer), and the walk-away preflight.
"""

from __future__ import annotations

import re
import time

import ctx  # noqa: E402
import sources  # noqa: E402
import attention  # noqa: E402

executor = sources.executor   # tools/executor, or None


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
    tpl = ctx.read(ctx.HUB / "templates" / "loop" / "CAMPAIGN.md")
    if tpl is None:
        return {"error": "templates/loop/CAMPAIGN.md is missing"}, 500
    date, ts = time.strftime("%Y-%m-%d"), ctx.ts()
    slug = _slugify(str(f.get("name") or direction))
    name = f"{date}-{slug}.md"
    dest = ctx.LAB / "campaigns" / name
    i = 2
    while dest.exists():
        name = f"{date}-{slug}-{i}.md"
        dest = ctx.LAB / "campaigns" / name
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
    ctx.emit_hub("campaign_signed", detail=f"campaign {rel} signed (PI via dashboard)")
    ctx.pi_log({"action": "campaign.sign", "file": rel, "fields": f})
    out = {"ok": True, "file": rel, "note": f"campaign signed: {rel}", "gate3_auto": gate3_auto}
    if body.get("launch"):
        try:
            from executor import campaigns  # noqa: PLC0415 — tools/ is on sys.path via sources
            lab = sources.executor.Lab(ctx.HUB)
            sources.executor.check_enabled(lab)
            st = campaigns.create(lab, rel, hours=hours, agent_minutes=agent_hours * 60, cycle_minutes=cycle_minutes,
                                  repeat_minutes=repeat_minutes, gate3_auto=gate3_auto,
                                  backend=body.get("backend") or None)
        except Exception as e:  # noqa: BLE001 — the brief is signed either way; say why it didn't start
            out["note"] = f"campaign signed ({rel}) but not started: {e}"
            out["warnings"] = [str(e)]
            return out, 200
        ctx.pi_log({"action": "campaign.start", "file": rel, "hours": hours, "agent_hours": agent_hours,
                   "cycle_minutes": cycle_minutes, "repeat_minutes": repeat_minutes, "gate3_auto": gate3_auto})
        out.update(campaign=st["name"], note=f"campaign signed and started — the lab keeps it going until {deadline}")
    return out, 200


CAMPAIGN_ACTIONS = ("pause", "resume", "stop", "revoke_gate3", "hold", "unhold", "answer")


def campaign_control(body: dict) -> tuple[dict, int]:
    """The PI's controls on a running campaign (the campaign card)."""
    name, action = str(body.get("name") or ""), str(body.get("action") or "")
    if action not in CAMPAIGN_ACTIONS:
        return {"error": f"action must be one of {', '.join(CAMPAIGN_ACTIONS)}"}, 400
    if action in ("stop", "revoke_gate3") and not body.get("confirm"):
        return {"error": "confirm first"}, 400
    try:
        from executor import campaigns  # noqa: PLC0415
        st = campaigns.control(sources.executor.Lab(ctx.HUB), name, action, study=body.get("study") or None,
                               text=body.get("text"), index=body.get("index"))
    except (ValueError, OSError) as e:
        return {"error": str(e)}, 400
    ctx.pi_log({"action": f"campaign.{action}", "campaign": name, "study": body.get("study")})
    words = {"pause": "paused", "resume": "resumed", "stop": "stopping — it writes its final report",
             "revoke_gate3": "Gate 3 is yours again for this campaign", "hold": "held from auto-finalizing",
             "unhold": "released", "answer": "answered — the next pass gets it"}
    return {"ok": True, "note": words[action], "status": st.get("status")}, 200


def campaign_preflight(q: dict) -> tuple[dict, int]:
    """Can the lab run on its own right now? What a walk-away start needs, checked."""
    ex = sources.executor
    if ex is None:
        return {"ok": True, "ready": False, "checks": [{"id": "executor", "ok": False, "label": "The executor is available",
                                                        "detail": "tools/executor is missing"}]}, 200
    lab = ex.Lab(ctx.HUB)
    prog = lab.prog()
    status = attention.executor_status()
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
