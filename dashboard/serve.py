"""Vivarium — the Newts' Lab, rendered as a living terrarium. Optional, local-only.

    uv run --with pyyaml python dashboard/serve.py [--port 8787]

A tiny stdlib HTTP server that READS the lab's files (registry, run records, the event
bus, slots, in-flight liveness) and serves a no-build single-page scene. It is the PI's
control surface — but it stays honest about what it can and can't do:

  WRITES (the only ones):
    POST /api/directive   free-text note to an agent's inbox      -> directives.jsonl
    POST /api/command     a STRUCTURED command (start_loop, …)    -> directives.jsonl
                          the running agent executes it at its next checkpoint, in-protocol
    POST /api/gate        record a PI gate approval (Gate 1 or 2) -> proposal / control.yaml
                          local-only, explicit-confirm, logged. GATE 3 IS NEVER OFFERED.
  RUNS (safe, read-only subprocesses, on demand):
    POST /api/tool        a whitelisted read-only tool (check_lab/show_config/status/…)
  READS (safe, read-only file views, on demand):
    POST /api/read        a small whitelisted text view (lab knowledge; a gate's proposal/
                          claims/envelope) from fixed roots + a sanitized slug. Never writes.

It cannot run an agent skill (that's the Claude session) and it never signs Gate 3 or
fakes a result. Binds 127.0.0.1 only. Delete the dashboard/ folder and the lab is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
HUB = HERE.parent
LAB = HUB / "lab"
STATIC = HERE / "static"
sys.path.insert(0, str(HERE))

import sources  # noqa: E402

# Structured command actions the dashboard may issue (the agent executes them in-protocol).
COMMAND_ACTIONS = {
    "start_loop", "stop_loop", "set_mode", "run_smoke", "request_run",
    "prioritize", "park", "kill", "analyze", "ideate",
}
# Read-only / safe tools the dashboard may run directly. Never anything that trains or writes.
# audit_claims runs tools/audit_claims.py (reads claims.yaml + artifacts, prints PASS/FAIL/MANUAL — writes nothing).
SAFE_TOOLS = {"check_lab", "show_config", "status", "compare", "inbox", "slots", "audit_claims"}


# ── bus writers (directives, commands) ──────────────────────────────────────
# ThreadingHTTPServer serves each POST on its own thread; serialize id-compute + append so two
# concurrent directives can't read the same max id and write a duplicate d-NNN (which would mis-route
# later acks/withdraws onto the wrong directive).
_BUS_LOCK = threading.Lock()


def _next_id(directives_path: Path) -> str:
    # max(existing d-NNN) + 1 — NOT a line count: a withdrawn/edited/missing row must never
    # cause a reissued id (which would collide and mis-route acks/withdraws onto a live directive).
    hi = 0
    if directives_path.exists():
        for line in directives_path.read_text(encoding="utf-8-sig").splitlines():
            for m in re.findall(r'"id"\s*:\s*"d-(\d+)"', line):
                hi = max(hi, int(m))
    return f"d-{hi + 1:03d}"


def _bus_dir(target: str) -> Path:
    if target in ("hub", "", None):
        return LAB / ".bus"
    pdir = sources._project_path({"id": target, "project": ""})
    return (pdir / ".bus") if pdir else (LAB / ".bus")


def _append(target: str, rec: dict) -> dict:
    bus = _bus_dir(target)
    bus.mkdir(parents=True, exist_ok=True)
    path = bus / "directives.jsonl"
    with _BUS_LOCK:
        rec.setdefault("id", _next_id(path))
        rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        rec.setdefault("from", "PI via dashboard")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    return rec


def append_directive(target: str, text: str) -> dict:
    return _append(target, {"text": text})


def append_command(target: str, action: str, args: dict, text: str) -> dict:
    return _append(target, {"kind": "command", "action": action, "args": args or {},
                            "text": text or action.replace("_", " ")})


def append_withdraw(target: str, ref: str) -> None:
    _append(target, {"kind": "withdraw", "ref": ref})


def _pi_log(rec: dict) -> None:
    """Append-only audit trail of PI actions taken through the dashboard. `default=str` keeps it
    robust to YAML-parsed values (e.g. an `expires:` date) that aren't natively JSON-serializable."""
    (LAB / ".bus").mkdir(parents=True, exist_ok=True)
    rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (LAB / ".bus" / "pi-actions.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def _emit_hub(kind: str, **fields) -> None:
    (LAB / ".bus").mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "hub", "kind": kind}
    rec.update(fields)
    with (LAB / ".bus" / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# ── gate approval (PI-only, local, explicit) ─────────────────────────────────

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


def approve_gate(idea: str, gate: int) -> dict:
    """Record a PI gate approval. Gate 1: sign the proposal + leave the follow-through
    command for the agent. Gate 2: flip control.yaml gate2_envelope.pi_signed. Gate 3 is
    never handled here — finalization/sending outside the lab is always done in a session."""
    if gate == 3:
        return {"error": "Gate 3 (finalization) is never approved from the dashboard — do it in a session."}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    if gate == 1:
        proposal = HUB / "studies" / idea / "proposal.md"
        if not proposal.exists():
            return {"error": f"no proposal at studies/{idea}/proposal.md"}
        with proposal.open("a", encoding="utf-8") as f:
            f.write(f"\n\n<!-- PI Gate 1 approved via Vivarium dashboard {ts} -->\n")
        append_command(idea, "gate1_approved", {}, "Gate 1 approved (PI via dashboard) — proceed to /spawn-project")
        _emit_hub("gate_resolved", idea=idea, detail="Gate 1 approved (PI via dashboard)")
        _pi_log({"action": "approve_gate", "gate": 1, "idea": idea})
        return {"ok": True, "gate": 1, "idea": idea,
                "note": "Proposal signed; the agent will transition the registry and spawn the project at its next checkpoint."}
    # gate 2 — sign the project's control.yaml gate2_envelope (the canonical machine-readable
    # signature). READ via YAML to VALIDATE the envelope; WRITE via a targeted regex so the
    # file's comments/formatting survive.
    pdir = sources._project_path({"id": idea, "project": ""})
    control = (pdir / "control.yaml") if pdir else None
    if not control or not control.exists():
        return {"error": f"no control.yaml for {idea} (spawn the project first)"}
    text = control.read_text(encoding="utf-8-sig")
    if "pi_signed:" not in text:
        return {"error": "control.yaml has no gate2_envelope.pi_signed field"}
    env = sources._load_yaml(control).get("gate2_envelope") or {}
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
    control.write_text(new_text, encoding="utf-8")
    env_after = sources._load_yaml(control).get("gate2_envelope") or {}
    if not env_after.get("pi_signed"):   # verify the write actually parsed to signed — never report a phantom ok
        return {"error": "gate2_envelope.pi_signed did not take effect after write — check control.yaml format"}
    _emit_hub("gate_resolved", idea=idea, detail="Gate 2 envelope signed (PI via dashboard)")
    _pi_log({"action": "approve_gate", "gate": 2, "idea": idea, "control": str(control),
             "envelope_before": env, "envelope_after": env_after})
    return {"ok": True, "gate": 2, "idea": idea, "warnings": warnings or None,
            "note": "gate2_envelope.pi_signed set true (signed_via: dashboard). FULL runs within the envelope are now authorized."}


# ── safe tool runner (read-only subprocesses) ────────────────────────────────

def run_tool(name: str, idea: str | None = None) -> dict:
    if name not in SAFE_TOOLS:
        return {"error": f"tool '{name}' is not in the read-only whitelist"}
    py = sys.executable
    pdir = sources._project_path({"id": idea, "project": ""}) if idea else None
    cmd, cwd = None, HUB
    if name == "check_lab":
        cmd = [py, str(HUB / "tools" / "check_lab.py")]
    elif name == "show_config":
        cmd = [py, str(HUB / "tools" / "show_config.py")] + ([str(pdir)] if pdir else [])
    elif name == "slots":
        cmd = [py, str(HUB / "tools" / "run_slots.py"), "status"]
    elif name == "audit_claims":
        s = _slug(idea or "")
        if not s:
            return {"error": "audit_claims needs an idea slug"}
        rel_tol = (sources._load_yaml(LAB / "config.yaml").get("critique") or {}).get("claim_rel_tol", 1e-3)
        cmd = [py, str(HUB / "tools" / "audit_claims.py"), f"studies/{s}/paper", "--rel-tol", str(rel_tol)]
    elif name == "inbox":
        if pdir:
            cmd, cwd = [py, str(pdir / "scripts" / "lab_bus.py"), "inbox"], pdir
        else:
            cmd = [py, str(HUB / "tools" / "lab_bus.py"), "inbox"]
    elif name in ("status", "compare"):
        if not pdir:
            return {"error": f"'{name}' needs a project (pass idea)"}
        script = pdir / "scripts" / f"{name}.py"
        # compare.py requires a subcommand (`list`); status.py takes none.
        cmd, cwd = [py, str(script)] + (["list", "--last", "20"] if name == "compare" else []), pdir
    try:
        out = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
        return {"ok": True, "tool": name, "exit": out.returncode,
                "output": (out.stdout or "") + (("\n[stderr]\n" + out.stderr) if out.stderr.strip() else "")}
    except subprocess.TimeoutExpired:
        return {"error": f"{name} timed out"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{name} failed: {e}"}


# ── read-only document viewer (lab knowledge · a gate's proposal/claims) ─────
#
# Surfaces a few SMALL, READ-ONLY text files so the PI can read context in-dashboard
# (the lab's learning; a proposal/claims at a gate). Reads only from fixed roots with a
# sanitized slug — never writes, never executes. Gate 3 stays non-signable; this only
# *shows* the draft + claims so a finalization decision can be made in a session.

import re as _re

_SLUG_RE = _re.compile(r"[^A-Za-z0-9._-]")
_DOC_CLIP = 16000   # never stream a whole repo — clip each file


def _slug(s: str) -> str:
    return _SLUG_RE.sub("", (s or "").strip())[:80]


def _read_clip(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    txt = path.read_text(encoding="utf-8-sig", errors="replace")
    return txt if len(txt) <= _DOC_CLIP else txt[:_DOC_CLIP] + "\n\n… (clipped — open the file for the rest)"


def _filesec(title: str, f: Path, fallback: str = "") -> dict:
    """A doc-viewer section for a real file: its clipped text plus an absolute `path` (when the file
    exists) so the frontend can offer an 'open in editor' deep-link. The dashboard is local-only."""
    sec = {"title": title, "text": _read_clip(f) or fallback}
    if f.exists() and f.is_file():
        sec["path"] = str(f.resolve())
    return sec


def _read_full(path: Path) -> str:
    """Unclipped read — for parsing/extraction where a 16 KB clip could cut a section mid-way (the
    extracted section itself is small, so this never streams much). Empty string if absent."""
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _md_section(text: str, pattern) -> str:
    """Return one markdown section (heading + body) whose HEADING TEXT matches `pattern` (a compiled
    regex). Body runs until the next heading of equal-or-shallower level (## stops at ##/#). '' if
    not found. Used to lift the decision-critical bits out of proposal.md / lit-review.md / a
    meta-review — tolerant of the numbered ('## 5. Budget') and suffixed ('Kill criteria (…)') headings."""
    lines = text.split("\n")
    heads = [(i, len(m.group(1)), m.group(2)) for i, ln in enumerate(lines)
             for m in (_HEADING.match(ln),) if m]
    for n, (i, level, htext) in enumerate(heads):
        if pattern.search(htext):
            end = len(lines)
            for (j, lvl, _h) in heads[n + 1:]:
                if lvl <= level:
                    end = j
                    break
            return "\n".join(lines[i:end]).strip()
    return ""


# ── gate review bundles — everything the PI needs to decide a gate, in one view ───────────────────
#
# Each gate gets a COMPOSED read-only view instead of a single file: Gate 1 = the lit-review's
# novelty verdict + the proposal's budget/kill/success sections + the full proposal; Gate 2 = the
# FULL-run envelope + the completed PILOT runs that justify scaling; Gate 3 = claims + the
# meta-review verdict + every review/response (the PDF itself opens in the paper viewer). Every
# section that maps to a real file still carries its `path`, so the editor deep-links keep working.

def _gate1_bundle(slug: str) -> dict:
    prop = HUB / "studies" / slug / "proposal.md"
    lit = HUB / "studies" / slug / "lit-review.md"
    secs = []
    nov = _md_section(_read_full(lit), re.compile(r"Novelty verdict", re.I))
    if nov:
        secs.append({"title": "Novelty verdict (lit-review)", "text": nov, "path": str(lit.resolve())})
    prop_full = _read_full(prop)
    if prop_full:
        crit = [s for s in (_md_section(prop_full, re.compile(pat, re.I))
                            for pat in (r"\bBudget\b(?![-\w])", r"Kill criteria", r"Success criteria")) if s]
        if crit:
            secs.append({"title": "Decision-critical — budget · kill criteria · success criteria",
                         "text": "\n\n".join(crit), "path": str(prop.resolve())})
        secs.append(_filesec(f"studies/{slug}/proposal.md", prop))
    else:
        secs.append(_filesec(f"studies/{slug}/proposal.md", prop, f"no proposal at studies/{slug}/proposal.md"))
    return {"ok": True, "title": f"Gate 1 · {slug} · proposal + novelty", "sections": secs}


def _pilot_evidence(pdir: Path | None) -> dict:
    """The completed PILOT runs — the evidence that justifies signing a FULL-run envelope."""
    if not pdir:
        return {"title": "Pilot evidence", "text": "project not reachable — no runs to show"}
    reg = pdir / "runs" / "registry.jsonl"
    rows = sources._read_jsonl(reg) if reg.exists() else []
    pilots = [r for r in rows if r.get("status") == "completed" and str(r.get("stage", "")).upper() == "PILOT"]
    sec = {"title": f"Pilot evidence — {len(pilots)} completed PILOT run(s)"}
    if reg.exists():
        sec["path"] = str(reg.resolve())
    if not pilots:
        sec["text"] = ("no completed PILOT runs yet — pilots are the evidence that justifies a "
                       "FULL-scale launch (Gate 2 should usually wait for them)")
        return sec
    lines = []
    for r in pilots[-12:]:
        m = r.get("metrics") or {}
        mtxt = " · ".join(f"{k}={v}" for k, v in list(m.items())[:4] if isinstance(v, (int, float)))
        lines.append(f"{str(r.get('run_id', '?')):<34}  seed={r.get('seed', '?')}  {mtxt}")
    sec["text"] = "\n".join(lines)
    return sec


def _gate2_bundle(slug: str) -> dict:
    pdir = sources._project_path({"id": slug, "project": ""})
    ctrl = (pdir / "control.yaml") if pdir else None
    env = (sources._load_yaml(ctrl).get("gate2_envelope") if ctrl and ctrl.exists() else None)
    secs = [{"title": "gate2_envelope (control.yaml)",
             "text": json.dumps(env, indent=2, default=str) if env else "no gate2_envelope found — spawn the project first"}]
    secs.append(_pilot_evidence(pdir))
    if ctrl and ctrl.exists():
        secs.append(_filesec("control.yaml", ctrl))
    return {"ok": True, "title": f"Gate 2 · {slug} · envelope + pilot evidence", "sections": secs}


def _find_review_files(paper: Path, pattern: str) -> list:
    """Reviews live under studies/<slug>/paper/reviews/[critique-<date>/], so search RECURSIVELY
    (a plain glob — what the old gate-3 view used — finds none of them). Bounded."""
    if not paper.is_dir():
        return []
    return [f for f in sorted(paper.rglob(pattern)) if f.is_file()][:30]


def _meta_verdict(text: str) -> str:
    """Lift the headline decision + Overall-score row out of a meta-review.md."""
    if not text:
        return ""
    out = []
    for ln in text.split("\n"):
        if re.search(r"\|\s*\*{0,2}Overall", ln, re.I):
            out.append(ln.strip())
            break
    dec = _md_section(text, re.compile(r"^Decision\b", re.I))
    if dec:
        out.append(dec)
    return "\n\n".join(out).strip()


def _gate3_bundle(slug: str) -> dict:
    paper = HUB / "studies" / slug / "paper"
    secs = [_filesec(f"studies/{slug}/paper/claims.yaml", paper / "claims.yaml", "no claims.yaml yet")]
    metas = _find_review_files(paper, "*meta*.md")
    if metas:
        verdict = _meta_verdict(_read_full(metas[-1]))
        if verdict:
            secs.append({"title": "Meta-review verdict", "text": verdict, "path": str(metas[-1].resolve())})
    seen = set()
    for f in _find_review_files(paper, "*review*.md") + metas + _find_review_files(paper, "*response*.md"):
        if f in seen:
            continue
        seen.add(f)
        secs.append(_filesec(f"paper/{f.relative_to(paper).as_posix()}", f))
    return {"ok": True, "title": f"Gate 3 · {slug} · claims + review (read-only)", "sections": secs,
            "note": "Gate 3 is never signed from the dashboard — read here (use “view paper ▸” for the PDF), then /finalize in a session."}


# ── claims ↔ artifact map — hard rule 1, made visible ─────────────────────────────────────────────
#
# Renders studies/<slug>/paper/claims.yaml as a structured list: every claimed number, its metric /
# location / derivation, and the artifact file(s) it traces to — each resolved on disk so the PI can
# OPEN the artifact (a run peek + an editor link) and see the number is real. It reports artifact
# *linkage* (file present / missing), NOT a numeric audit — the mechanical PASS/FAIL/MANUAL audit is
# tools/audit_claims.py, runnable from the same view via the read-only tool runner.

def _as_list(v) -> list:
    """Coerce a YAML scalar to a one-item list — so a hand-edited `artifacts: foo` / `numbers: "0.9"`
    (a string written where a list belongs) isn't iterated character-by-character."""
    if isinstance(v, list):
        return v
    return [v] if v not in (None, "") else []


def _within(base: Path | None, target: Path) -> bool:
    """True iff `target` resolves to inside `base` — a cheap containment guard so a claim artifact
    like `../../x` can't surface an out-of-project absolute path as an openable editor link."""
    if not base:
        return False
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def _claim_project_dir(c: dict, slug: str) -> Path | None:
    # project_path is a documented override for /adopt or oddly-located projects, so it is NOT
    # contained to projects_root — it points wherever the PI's project actually lives.
    pp = str(c.get("project_path") or "").strip()
    if pp:
        p = Path(pp)
        return p if p.is_absolute() else (HUB / p).resolve()
    return sources._project_path({"id": c.get("project") or slug, "project": ""})


def claims_map(idea: str | None = None) -> dict:
    slug = _slug(idea or "")
    if not slug:
        return {"error": "no idea given"}
    cfile = HUB / "studies" / slug / "paper" / "claims.yaml"
    if not cfile.exists():
        return {"error": f"no claims.yaml at studies/{slug}/paper/claims.yaml"}
    doc = sources._load_yaml(cfile)
    if not isinstance(doc, dict):        # a malformed top-level scalar/list → empty map, never a 500
        doc = {}
    claims_in = doc.get("claims")
    if not isinstance(claims_in, list):  # the schema's top-level `claims:` is a list; anything else → none
        claims_in = []
    archive = HUB / "studies" / slug / "paper" / "artifacts"
    out = []
    for c in claims_in:
        if not isinstance(c, dict):      # count parity: sources._claims_count also counts dict items only
            continue
        proj = str(c.get("project") or slug)
        pdir = _claim_project_dir(c, slug)
        arts = []
        for rel in _as_list(c.get("artifacts")):
            rel = str(rel).replace("\\", "/")
            info = {"rel": rel, "exists": False}
            target = None
            live = (pdir / rel) if pdir else None
            if live and live.exists() and _within(pdir, live):                  # must stay inside its project
                target = live
            elif (archive / rel).exists() and _within(archive, archive / rel):  # hub archive (locked at /finalize)
                target = archive / rel
            if target:
                info.update(exists=True, abs=str(target.resolve()))
                mm = re.match(r"runs/([^/]+)/", rel)                            # a run artifact → peekable in the doc viewer
                if mm and mm.group(1) not in ("..", "."):
                    info.update(project=proj, run_id=mm.group(1))
            arts.append(info)
        out.append({
            "id": str(c.get("id") or ""), "claim": str(c.get("claim") or ""),
            "numbers": [str(n) for n in _as_list(c.get("numbers"))],
            "metric": str(c.get("metric") or ""), "location": str(c.get("location") or ""),
            "derivation": str(c.get("derivation") or ""), "project": proj,
            "has_hashes": bool(c.get("artifact_sha256")), "artifacts": arts,
            "linked": bool(arts) and all(a["exists"] for a in arts),
        })
    return {"ok": True, "title": f"{slug} · claims ↔ artifacts", "n": len(out),
            "claims_path": str(cfile.resolve()), "claims": out}


def read_doc(what: str, idea: str | None = None, gate: int | None = None, run: str | None = None) -> dict:
    if what == "run":
        slug, rid = _slug(idea or ""), _slug(run or "")
        if not slug or not rid:
            return {"error": "need a project + run id"}
        pdir = sources._project_path({"id": slug, "project": ""})
        if not pdir:
            return {"error": f"no project dir for {slug}"}
        rdir = pdir / "runs" / rid
        secs = []
        for fn in ("metrics.json", "meta.json", "config.yaml"):
            f = rdir / fn
            if f.exists():
                secs.append(_filesec(f"runs/{rid}/{fn}", f))
        stream = rdir / "metrics.jsonl"
        if stream.exists():
            lines = [ln for ln in _read_clip(stream).splitlines() if ln.strip()]
            if lines:
                secs.append({"title": f"runs/{rid}/metrics.jsonl · last {min(8, len(lines))} of {len(lines)}",
                             "text": "\n".join(lines[-8:]), "path": str(stream.resolve())})
        if not secs:
            return {"error": f"no artifacts under {slug}/runs/{rid} (runs are gitignored; the project may be elsewhere)"}
        return {"ok": True, "title": f"{slug} · {rid}", "sections": secs}

    if what == "knowledge":
        secs = []
        for name in ("FINDINGS", "FAILURES", "OPEN-QUESTIONS", "REFERENCES"):
            secs.append(_filesec(name.replace("-", " ").title(),
                                 LAB / "knowledge" / f"{name}.md", "(none recorded yet)"))
        nb_dir = LAB / "notebook"
        entries = sorted(nb_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True) if nb_dir.exists() else []
        dated = [f for f in entries if f.name.lower() != "readme.md"]
        latest = (dated or entries)[0] if (dated or entries) else None
        if latest:
            secs.append(_filesec("Latest notebook entry · " + latest.name, latest))
        return {"ok": True, "title": "Lab knowledge", "sections": secs}

    if what == "gate":
        slug = _slug(idea or "")
        if not slug:
            return {"error": "no idea given"}
        try:
            gate = int(gate or 0)
        except (TypeError, ValueError):
            gate = 0
        if gate == 1:
            return _gate1_bundle(slug)
        if gate == 2:
            return _gate2_bundle(slug)
        if gate == 3:
            return _gate3_bundle(slug)
        return {"error": f"unknown gate {gate}"}
    return {"error": f"unknown document '{what}'"}


# ── paper artifacts (compiled PDF + figures) — read-only binary views ─────────
#
# A back-half session compiles studies/<slug>/paper/main.pdf (the /write-paper latexmk gate) and
# syncs figures into studies/<slug>/paper/figures/. We stream those bytes so the PI can read the
# paper IN the dashboard and watch it refresh on each recompile. Read-only; fixed root + sanitized
# slug; figure names are reduced to a basename and re-confirmed under the figures dir (no traversal).

_FIG_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp", ".pdf"}
_FIG_CTYPE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml",
              ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}


def _paper_dir(idea: str) -> Path | None:
    slug = _slug(idea or "")
    return (HUB / "studies" / slug / "paper") if slug else None


def paper_pdf(idea: str) -> Path | None:
    pdir = _paper_dir(idea)
    f = (pdir / "main.pdf") if pdir else None
    return f if (f and f.is_file()) else None


def figure_list(idea: str) -> list[str]:
    pdir = _paper_dir(idea)
    fdir = (pdir / "figures") if pdir else None
    if not fdir or not fdir.is_dir():
        return []
    return sorted(f.name for f in fdir.iterdir() if f.is_file() and f.suffix.lower() in _FIG_EXTS)


def figure_file(idea: str, name: str) -> Path | None:
    pdir = _paper_dir(idea)
    fdir = (pdir / "figures") if pdir else None
    if not fdir or not fdir.is_dir():
        return None
    target = (fdir / Path(name or "").name).resolve()   # basename only — strips any path components
    if fdir.resolve() not in target.parents:            # re-confirm it lands inside figures/
        return None
    if not target.is_file() or target.suffix.lower() not in _FIG_EXTS:
        return None
    return target


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    # Demo mode is a debugging/showcase world, NOT a user-facing dashboard feature. It is OFF unless
    # the server is started with `--demo` (or VIVARIUM_DEMO=1); only then is window.__VIV_DEMO__ injected
    # so a `?demo` URL activates the synthetic lab. There is no in-dashboard control to enable it.
    demo = False

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        length = max(0, min(length, 1 << 20))   # ignore a non-numeric/absurd Content-Length; cap at 1 MB
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return {}

    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

    def _local_only(self) -> bool:
        """True iff this is a same-origin localhost request. Guards state-changing POSTs (the
        dashboard can sign Gate 1/2) against DNS-rebinding from a malicious page the PI visits:
        a rebound request still carries the attacker's Host header, which is rejected here."""
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):            # [::1]:port -> ::1
            host = host.split("]", 1)[0].lstrip("[")
        elif host.count(":") == 1:          # 127.0.0.1:port -> 127.0.0.1
            host = host.rsplit(":", 1)[0]
        if host and host not in self._LOCAL_HOSTS:
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "null":
            from urllib.parse import urlparse
            if (urlparse(origin).hostname or "") not in self._LOCAL_HOSTS:
                return False
        return True

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index.html") or self.path.startswith("/?"):
            return self._serve_index()
        if self.path.startswith("/api/state"):
            try:
                return self._json(sources.snapshot())
            except Exception as e:  # noqa: BLE001
                return self._json({"error": str(e)}, 500)
        if self.path.startswith("/api/events"):
            return self._serve_sse()
        if self.path.startswith("/api/paper"):
            return self._serve_paper()
        if self.path.startswith("/api/figs"):
            return self._serve_figs()
        if self.path.startswith("/api/figure"):
            return self._serve_figure()
        if self.path.startswith("/static/") or self.path.count("/") == 1:
            return self._serve_static(self.path.lstrip("/"))
        self._send(404, b"not found", "text/plain")

    def _query(self) -> dict:
        from urllib.parse import parse_qs, urlparse
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def _serve_bytes(self, f: Path, ctype: str) -> None:
        try:
            self._send(200, f.read_bytes(), ctype)
        except OSError:
            self._send(404, b"unreadable", "text/plain")

    def _serve_paper(self) -> None:
        f = paper_pdf(self._query().get("idea", ""))
        if not f:
            return self._send(404, b"no compiled paper (studies/<slug>/paper/main.pdf)", "text/plain")
        self._serve_bytes(f, "application/pdf")

    def _serve_figs(self) -> None:
        self._json({"figures": figure_list(self._query().get("idea", ""))})

    def _serve_figure(self) -> None:
        q = self._query()
        f = figure_file(q.get("idea", ""), q.get("name", ""))
        if not f:
            return self._send(404, b"no such figure", "text/plain")
        self._serve_bytes(f, _FIG_CTYPE.get(f.suffix.lower(), "application/octet-stream"))

    def _serve_index(self) -> None:
        try:
            html = (STATIC / "index.html").read_text(encoding="utf-8")
        except OSError:
            return self._send(500, b"dashboard assets missing (dashboard/static/index.html)", "text/plain")
        try:
            seed = json.dumps(sources.snapshot())
        except Exception:  # noqa: BLE001
            seed = "null"
        demo = "true" if self.demo else "false"
        html = html.replace(
            "</head>", f"<script>window.__STATE__={seed};window.__VIV_DEMO__={demo};</script></head>", 1)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static(self, rel: str) -> None:
        rel = rel.split("?")[0].replace("static/", "")
        target = (STATIC / rel).resolve()
        if (STATIC not in target.parents and target != STATIC) or not target.exists():
            return self._send(404, b"not found", "text/plain")
        ctype = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                 ".svg": "image/svg+xml"}.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), f"{ctype}; charset=utf-8")

    def _serve_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = None
        try:
            while True:
                try:
                    payload = json.dumps(sources.snapshot())
                except Exception:  # noqa: BLE001
                    payload = json.dumps({"error": "snapshot failed"})
                if payload != last:
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last = payload
                else:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        if not self._local_only():
            return self._json({"error": "refused: cross-origin/non-localhost POST"}, 403)
        body = self._body()
        p = self.path
        if p.startswith("/api/directive"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._json({"error": "empty directive"}, 400)
            return self._json({"ok": True, "directive": append_directive(body.get("target", "hub"), text)})
        if p.startswith("/api/command"):
            action = body.get("action")
            if action not in COMMAND_ACTIONS:
                return self._json({"error": f"unknown action (allowed: {sorted(COMMAND_ACTIONS)})"}, 400)
            rec = append_command(body.get("target", "hub"), action, body.get("args") or {}, body.get("text") or "")
            return self._json({"ok": True, "command": rec})
        if p.startswith("/api/gate"):
            if not body.get("confirm"):
                return self._json({"error": "gate approval needs explicit confirm"}, 400)
            try:
                gate = int(body.get("gate", 0))
            except (TypeError, ValueError):
                return self._json({"error": "gate must be 1 or 2"}, 400)
            if gate not in (1, 2):
                return self._json({"error": "dashboard signs only Gate 1 or Gate 2"}, 400)
            res = approve_gate(body.get("idea", ""), gate)
            return self._json(res, 200 if res.get("ok") else 400)
        if p.startswith("/api/tool"):
            return self._json(run_tool(body.get("name", ""), body.get("idea")))
        if p.startswith("/api/read"):
            return self._json(read_doc(body.get("what", ""), body.get("idea"), body.get("gate"), body.get("run")))
        if p.startswith("/api/claims"):
            return self._json(claims_map(body.get("idea")))
        if p.startswith("/api/withdraw"):
            append_withdraw(body.get("target", "hub"), body.get("id", ""))
            return self._json({"ok": True})
        self._send(404, b"not found", "text/plain")


def main() -> int:
    cfg = sources._load_yaml(LAB / "config.yaml").get("dashboard") or {}
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(cfg.get("port", 8787)))
    parser.add_argument("--demo", action="store_true",
                        help="enable the synthetic demo world (debugging/showcase; visit /?demo). "
                             "Off by default; also enabled by VIVARIUM_DEMO=1.")
    args = parser.parse_args()
    Handler.demo = bool(args.demo) or os.environ.get("VIVARIUM_DEMO", "").lower() in ("1", "true", "yes")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Vivarium — the living lab · http://127.0.0.1:{args.port}  (Ctrl-C to stop)")
    if Handler.demo:
        print(f"  demo mode ENABLED (debugging) · synthetic world at http://127.0.0.1:{args.port}/?demo")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nlights out in the vivarium.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
