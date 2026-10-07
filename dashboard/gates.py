"""The PI's signatures in the dashboard: Gates 1 and 2, Gate 3 (typed confirmation) and the one /finalize
run it allows, revoking any of them, the Gate-2 envelope, a loop brief, reviving an idea. What the PI
reads to sign is review.py."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

import ctx  # noqa: E402
import sources  # noqa: E402
from bus import append_command  # noqa: E402
import runops  # noqa: E402
from runops import launch_run  # noqa: E402


executor = sources.executor   # tools/executor, or None (observe-and-sign only)


def _wf():
    return ctx.tool("workflow")   # the lab's states, gates and procedures (workflow/stages.yaml)


def _sign_gate2_block(text: str, ts: str) -> tuple[str, bool]:
    """Flip pi_signed -> true and signed_via -> dashboard:<ts> WITHIN the gate2_envelope block only,
    tolerating YAML's `False`/`no`/`off` and an empty/`null`/`~` signed_via. Block-scoped so it can't
    flip a different envelope's pi_signed (e.g. a /compete target.score_envelope earlier in the file).
    Comment/format preserving. Returns (new_text, pi_signed_changed)."""
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines)
                  if re.match(r"\s*gate2_envelope:\s*(#.*)?$", ln)), None)
    if start is None:
        return text, False
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= base_indent:
            end = j
            break
    pi_changed = sv_set = False
    for j in range(start + 1, end):
        if not pi_changed:
            m = re.match(r"(\s*pi_signed:\s*)(\S+)(.*)$", lines[j], re.I)
            if m and m.group(2).lower() in ("false", "no", "off"):
                lines[j] = f"{m.group(1)}true{m.group(3)}"
                pi_changed = True
                continue
        if not sv_set:
            m = re.match(r"(\s*signed_via:\s*)(\S*)(.*)$", lines[j], re.I)
            if m and m.group(2).lower() in ("null", "~", "none", ""):
                lines[j] = f"{m.group(1)}dashboard:{ts}{m.group(3)}"
                sv_set = True
    return "\n".join(lines), pi_changed


def approve_gate(idea: str, gate: int, envelope: bool = False) -> dict:
    """Record a PI gate approval. Gate 1: sign the proposal + leave the follow-through
    command for the agent. Gate 2: flip control.yaml gate2_envelope.pi_signed. Gate 3 is
    handled here — it is gates.gate3_sign (typed confirmation; the one /finalize run it allows)."""
    if gate == 3:
        return {"error": "Gate 3 is signed with gates.gate3_sign (typed confirmation), not here."}
    idea = ctx.safe_id(idea) or ""
    if not idea:
        return {"error": "invalid idea slug"}   # the raw id becomes a path under studies/ — never trust it
    ts = ctx.ts()
    _MARK = sources.GATE1_MARK
    if gate == 1:
        proposal = ctx.HUB / "studies" / idea / "proposal.md"
        if not proposal.exists():
            return {"error": f"no proposal at studies/{idea}/proposal.md"}
        if _MARK in proposal.read_text(encoding="utf-8-sig", errors="replace"):
            # idempotent: a second click would append a duplicate marker AND queue a second
            # gate1_approved command (the Approve card lingers until the agent next runs).
            return {"error": "Gate 1 is already approved on this proposal — nothing to do "
                             "(the agent applies it at its next checkpoint)."}
        row = next((r for r in sources.parse_registry() if r["id"] == idea), None)
        at = _wf().gate_state(1, ctx.HUB)
        warnings = ([] if (row and (row.get("state") or "").strip() == at)
                    else [f"idea is not in state '{at}' — approving anyway, but confirm this is the "
                          "right idea before the agent spawns it"])
        # `envelope approved`: the PI also approved the proposal's Gate-2 envelope (§5) — /spawn-project
        # may then write it into control.yaml signed (tools/signature_guard.py checks for this marker)
        with proposal.open("a", encoding="utf-8") as f:
            f.write(f"\n\n<!-- {_MARK} {ts}" + (" · envelope approved" if envelope else "") + " -->\n")
        then = _wf().after_gate(1, ctx.HUB) or "spawn-project"
        append_command(idea, "gate1_approved", {"idea": idea},
                       f"Gate 1 approved (PI via dashboard) — proceed to /{then}")
        ctx.emit_hub("gate_resolved", idea=idea, detail="Gate 1 approved (PI via dashboard)")
        ctx.pi_log({"action": "approve_gate", "gate": 1, "idea": idea, "envelope": bool(envelope)})
        exec_on = executor is not None and bool(
            ((ctx.config().get("agents") or {}).get("programmatic") or {}).get("enabled"))
        res = {"ok": True, "gate": 1, "idea": idea, "warnings": warnings or None,
               "note": (f"Proposal signed — launch /{then} {idea} from the Activity tab when you're ready."
                        if exec_on else
                        "Proposal signed; the agent will transition the registry and spawn the project at its next checkpoint.")}
        if (ctx.config().get("dashboard") or {}).get("auto_spawn_on_gate1"):
            out, code = launch_run({"skill": then, "target": idea, "confirm": True}, by="gate1-auto")
            res["launch"] = out
            if code == 200:
                res["note"] = f"Proposal signed; /{then} {idea} queued ({out.get('run_id')})."
        return res
    # gate 2 — sign the project's control.yaml gate2_envelope (the canonical machine-readable
    # signature). READ via YAML to VALIDATE the envelope; WRITE via a targeted regex so the
    # file's comments/formatting survive.
    pdir = ctx.pdir(idea)
    control = (pdir / "control.yaml") if pdir else None
    if not control or not control.exists():
        return {"error": f"no control.yaml for {idea} (spawn the project first)"}
    with control.open("r", encoding="utf-8-sig", newline="") as f:
        raw = f.read()                                  # newline="" preserves the file's own EOLs
    eol = "\r\n" if "\r\n" in raw else "\n"             # so we can write them back unchanged (no CRLF churn)
    text = raw.replace("\r\n", "\n")
    if "pi_signed:" not in text:
        return {"error": "control.yaml has no gate2_envelope.pi_signed field"}
    env = ctx.labfiles.load_yaml(control).get("gate2_envelope") or {}
    if env.get("pi_signed"):
        return {"error": "gate2_envelope is already signed (pi_signed: true) — nothing to do"}
    expires = str(env.get("expires") or "").strip()
    if expires and expires.lower() not in ("null", "none") and expires < time.strftime("%Y-%m-%d"):
        return {"error": f"gate2_envelope expired ({expires}) — update the envelope in control.yaml before signing"}
    warnings = []
    if not any(env.get(k) for k in ("full_runs", "per_run_max_minutes", "total_max_minutes")):
        warnings.append("envelope authorizes nothing (all caps are 0/null) — signing it is a no-op; every FULL run will still need fresh PI approval")
    new_text, pi_changed = _sign_gate2_block(text, ts)
    if not pi_changed:
        return {"error": "could not set gate2_envelope.pi_signed (unexpected format) — sign via /configure"}
    with control.open("w", encoding="utf-8", newline="") as f:
        f.write(new_text.replace("\n", eol))            # restore the original EOL — a clean one-line diff
    env_after = ctx.labfiles.load_yaml(control).get("gate2_envelope") or {}
    if not env_after.get("pi_signed"):   # verify the write actually parsed to signed — never report a phantom ok
        return {"error": "gate2_envelope.pi_signed did not take effect after write — check control.yaml format"}
    ctx.emit_hub("gate_resolved", idea=idea, detail="Gate 2 envelope signed (PI via dashboard)")
    ctx.pi_log({"action": "approve_gate", "gate": 2, "idea": idea, "control": str(control),
             "envelope_before": env, "envelope_after": env_after})
    return {"ok": True, "gate": 2, "idea": idea, "warnings": warnings or None,
            "note": "gate2_envelope.pi_signed set true (signed_via: dashboard). FULL runs within the envelope are now authorized."}


def _paper(slug: str) -> Path:
    return ctx.HUB / "studies" / slug / "paper"


def gate3_readiness(slug: str) -> dict:
    """The checklist the Gate 3 sheet shows (tools/gate3.py — the keeper uses the same one). `blocking`
    items must pass to sign."""
    ctx.tool("workflow")   # tools/ on sys.path for the imports below
    import gate3  # noqa: PLC0415
    out = gate3.readiness(ctx.HUB, slug)
    if out.get("signed"):
        out["valid"], out["valid_why"] = gate3.delegation_valid(ctx.HUB, slug)
    return out


def gate3_sign(body: dict) -> tuple[dict, int]:
    slug = ctx.need_slug(body)
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
    ts = ctx.ts()
    pdf = paper / "main.pdf"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else None
    warn = [c["label"] for c in ready["checks"] if not c["ok"]]
    lines = [f"# Gate 3 approval — {slug}", "",
             "Gate 3 approved by the PI (signed in the Vivarium dashboard).", "",
             f"- signed_via: dashboard:{ts}",
             f"- state at signing: {(ctx.row(slug) or {}).get('state')}",
             f"- paper: studies/{slug}/paper/main.pdf" + (f" (sha256 {digest})" if digest else " (not compiled)"),
             ]
    if warn:
        lines += ["- signed despite: " + "; ".join(warn)]
    note = str(body.get("note") or "").strip()[:1000]
    if note:
        lines += ["", "PI note:", "", note]
    (paper / "gate3-approval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.emit_hub("gate_resolved", idea=slug, detail="Gate 3 signed (PI via dashboard)")
    ctx.pi_log({"action": "approve_gate", "gate": 3, "idea": slug, "paper_sha256": digest, "warnings": warn or None})
    out = {"ok": True, "gate": 3, "idea": slug, "warnings": warn or None,
           "note": "Gate 3 signed. /finalize can now run for this study."}
    if body.get("launch"):
        res, code = runops.launch_run({"skill": "finalize", "target": slug, "confirm": True,
                                  "backend": body.get("backend")}, by="gate3", gate3=True)
        out["launch"] = res
        if code == 200:
            out["note"] = f"Gate 3 signed; /finalize {slug} queued ({res.get('run_id')})."
    return out, 200


def finalize_start(body: dict) -> tuple[dict, int]:
    """Start /finalize for a study whose Gate 3 the PI already signed here (the signature is the
    authority; this is the PI's click to use it). Never reachable by an agent: only this endpoint and
    gate3_sign pass gate3=True, and the executor re-checks the signed note."""
    slug = ctx.need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "starting /finalize needs explicit confirm"}, 400
    if not (_paper(slug) / "gate3-approval.md").exists():
        return {"error": "sign Gate 3 first"}, 400
    res, code = runops.launch_run({"skill": "finalize", "target": slug, "confirm": True, "backend": body.get("backend")},
                             by="gate3", gate3=True)
    return res, code


def gate_revoke(body: dict) -> tuple[dict, int]:
    slug = ctx.need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "revoking a signature needs explicit confirm"}, 400
    what = str(body.get("what") or body.get("gate") or "")
    if what in ("1", "gate1"):
        prop = ctx.HUB / "studies" / slug / "proposal.md"
        text = ctx.read(prop)
        if text is None:
            return {"error": "no proposal"}, 400
        new = re.sub(r"\n*<!-- " + re.escape(sources.GATE1_MARK) + r"[^>]*-->\n?", "\n", text)
        if new == text:
            return {"error": "no dashboard Gate-1 signature on this proposal"}, 400
        ctx.write_keep_eol(prop, text, new)
        row = ctx.row(slug)
        life, opened = _wf().lifecycle(ctx.HUB), _wf().gate_before(1, ctx.HUB)
        state = (row or {}).get("state") or ""
        warn = ["the project is already spawned — revoking Gate 1 does not undo that"]\
            if state in life and opened in life and life.index(state) >= life.index(opened) else None
    elif what in ("2", "gate2"):
        pdir = ctx.pdir(slug)
        ctl = (pdir / "control.yaml") if pdir else None
        text = ctx.read(ctl) if ctl else None
        if text is None:
            return {"error": "no control.yaml"}, 400
        new = _set_block(text.replace("\r\n", "\n"), "gate2_envelope", {"pi_signed": "false", "signed_via": "null"})
        if new == text.replace("\r\n", "\n"):
            return {"error": "the envelope is not signed"}, 400
        ctx.write_keep_eol(ctl, text, new)
        warn = None
    elif what in ("3", "gate3"):
        note = _paper(slug) / "gate3-approval.md"
        if not note.exists():
            return {"error": "Gate 3 is not signed"}, 400
        if ((ctx.row(slug) or {}).get("state") or "") == _wf().gate_before(3, ctx.HUB):
            return {"error": "already finalized — revoking now would not undo it"}, 400
        note.unlink()
        warn = None
    elif what == "loop":
        pdir = ctx.pdir(slug)
        brief = (pdir / "LOOP_BRIEF.md") if pdir else None
        text = ctx.read(brief) if brief else None
        if text is None:
            return {"error": "no LOOP_BRIEF.md"}, 400
        new = re.sub(r"-\s*\[[xX]\]\s*Authorized as scoped above", "- [ ] Authorized as scoped above", text)
        if new == text:
            return {"error": "the loop brief is not authorized"}, 400
        ctx.write_keep_eol(brief, text, new)
        warn = ["a running loop keeps going until you stop it"] if sources.executor else None
    else:
        return {"error": "what must be gate1 | gate2 | gate3 | loop"}, 400
    ctx.emit_hub("gate_revoked", idea=slug, detail=f"{what} signature revoked (PI via dashboard)")
    ctx.pi_log({"action": "revoke", "what": what, "idea": slug})
    return {"ok": True, "warnings": warn, "note": "signature revoked"}, 200


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
    slug = ctx.need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "changing the envelope needs explicit confirm"}, 400
    pdir = ctx.pdir(slug)
    ctl = (pdir / "control.yaml") if pdir else None
    text = ctx.read(ctl) if ctl else None
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
    before = (ctx.labfiles.load_yaml(ctl).get("gate2_envelope") or {})
    sign = bool(body.get("sign"))
    ts = ctx.ts()
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
    ctx.write_keep_eol(ctl, text, new)
    ctx.emit_hub("gate_resolved" if sign else "envelope_changed", idea=slug,
                detail="Gate 2 envelope " + ("signed" if sign else "updated") + " (PI via dashboard)")
    ctx.pi_log({"action": "envelope.set", "idea": slug, "before": before, "after": env, "signed": sign})
    note = ("envelope saved and signed — FULL runs within it are authorized" if sign else
            "envelope saved (not signed)" + (" — its old signature was withdrawn because the values changed"
                                             if changed_values and before.get("pi_signed") else ""))
    return {"ok": True, "envelope": env, "note": note}, 200


def loopbrief_sign(body: dict) -> tuple[dict, int]:
    slug = ctx.need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "authorizing the loop needs explicit confirm"}, 400
    mode = str(body.get("mode") or "execute")
    if mode not in ("execute", "explore"):
        return {"error": "mode must be execute or explore"}, 400
    pdir = ctx.pdir(slug)
    brief = (pdir / "LOOP_BRIEF.md") if pdir else None
    text = ctx.read(brief) if brief else None
    if text is None:
        return {"error": f"{slug} has no LOOP_BRIEF.md yet — the loop's first step writes it (Start loop)"}, 400
    if re.search(r"-\s*\[[xX]\]\s*Authorized as scoped above", text):
        return {"error": "this loop brief is already authorized"}, 400
    ts = ctx.ts()
    new = re.sub(r"-\s*\[ \]\s*Authorized as scoped above", "- [x] Authorized as scoped above", text, count=1)
    if new == text:
        return {"error": "LOOP_BRIEF.md has no '- [ ] Authorized as scoped above' line — unexpected format"}, 400
    new = re.sub(r"\*\*PI:\*\*\s*_+\s*·\s*\*\*Date:\*\*\s*_+",
                 f"**PI:** signed in the dashboard (signed_via: dashboard:{ts}) · **Date:** {ts[:10]}", new, count=1)
    new = re.sub(r"(\*\*Mode:\*\*\s*)`(execute|explore)`", rf"\1`{mode}`", new, count=1)
    ctx.write_keep_eol(brief, text, new)
    ctx.emit_hub("gate_resolved", idea=slug, detail=f"LOOP_BRIEF authorized, mode {mode} (PI via dashboard)")
    ctx.pi_log({"action": "loopbrief.sign", "idea": slug, "mode": mode})
    out = {"ok": True, "note": f"loop authorized ({mode})"}
    if body.get("launch"):
        res, code = runops.launch_run({"skill": "research-loop", "target": slug, "confirm": True,
                                  "backend": body.get("backend")}, by="loopbrief")
        out["launch"] = res
        if code == 200:
            out["note"] = f"loop authorized ({mode}); /research-loop {slug} queued"
    return out, 200


def _revive_to() -> tuple:
    return tuple(sources.workflow.revivable_states(ctx.HUB))   # workflow/stages.yaml `revivable: true`


def revive(body: dict) -> tuple[dict, int]:
    slug = ctx.need_slug(body)
    if not slug:
        return {"error": "invalid idea slug"}, 400
    if not body.get("confirm"):
        return {"error": "reviving needs explicit confirm"}, 400
    reason = str(body.get("reason") or "").strip().replace("|", "/").replace("\n", " ")[:300]
    if not reason:
        return {"error": "say why it comes back (it is recorded)"}, 400
    to = str(body.get("to") or _wf().revive_default(ctx.HUB))
    if to not in _revive_to():
        return {"error": f"revive into one of {', '.join(_revive_to())}"}, 400
    reg = ctx.LAB / "REGISTRY.md"
    text = ctx.read(reg)
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
    if was not in _wf().side_states(ctx.HUB):
        return {"error": f"{slug} is '{was}', not parked or killed"}, 400
    cells[2] = f" {to} "
    cells[6] = f" {time.strftime('%Y-%m-%d')} "
    cells[7] = f" revived by the PI: {reason} "
    lines[i] = "|" + "|".join(cells) + "|"
    ctx.write_keep_eol(reg, text, "\n".join(lines))
    idea = ctx.HUB / "studies" / slug / "IDEA.md"
    it = ctx.read(idea)
    if it is not None:
        new = re.sub(r"^(state:\s*)\S+", rf"\g<1>{to}", it, count=1, flags=re.M)
        new = new.rstrip("\n") + f"\n- {time.strftime('%Y-%m-%d')}: {was} → {to} — revived by the PI (dashboard): {reason}\n"
        ctx.write_keep_eol(idea, it, new)
    ctx.emit_hub("state_change", idea=slug, detail=f"{was} → {to} (revived by the PI: {reason})")
    ctx.pi_log({"action": "revive", "idea": slug, "from": was, "to": to, "reason": reason})
    return {"ok": True, "note": f"{slug} is back in {to}"}, 200


def gate_post(body: dict) -> tuple[dict, int]:
    """Sign a gate: 1 (a proposal) and 2 (an envelope) here, 3 through gate3_sign (typed confirmation)."""
    if not body.get("confirm"):
        return {"error": "gate approval needs explicit confirm"}, 400
    try:
        gate = int(body.get("gate", 0))
    except (TypeError, ValueError):
        return {"error": "gate must be 1, 2 or 3"}, 400
    if gate == 3:
        return gate3_sign(body)
    if gate not in (1, 2):
        return {"error": "gate must be 1, 2 or 3"}, 400
    res = approve_gate(body.get("idea", ""), gate, envelope=bool(body.get("envelope")))
    return res, 200 if res.get("ok") else 400
