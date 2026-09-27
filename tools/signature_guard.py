"""Signature guard — in a headless run, only the PI signs.

A PreToolUse hook the executor installs in every launched run (claude: the run's sidecar settings;
codex: `-c hooks.PreToolUse` session flags; opencode: a plugin loaded through OPENCODE_CONFIG_DIR). It
reads one Claude-shaped hook payload on stdin and DENIES (exit 2, the reason on stderr) a tool call
that would create or change a PI signature:

  * a Gate-1 approval marker added to a study's proposal.md
  * `pi_signed: true` / a non-null `signed_via` appearing in a control.yaml envelope, or the values of an
    already-signed envelope changing
  * any write to paper/gate3-approval.md, or a Gate-3 approval marker added under studies/*/paper/
  * a LOOP_BRIEF.md "Authorized" box ticked, or a campaign brief's PI-authorization line filled
  * a registry row moved to `final` without a dashboard-signed gate3-approval.md
  * PI-owned keys of lab/config.yaml changing (tools/configure.py's owner table; `agents.programmatic.*`
    and `dashboard.*` always), and any write to lab/.bus/pi-actions.jsonl
  * the lab's procedures and roles (.claude/skills, agent-roles, the rendered role files), the workflow
    definition (workflow/) and the PI's stage instructions (lab/workflow/, studies/*/workflow/) — an agent
    proposes a change instead (`tools/workflow.py propose`), the PI accepts it in the dashboard
  * shell commands that do any of the above (best effort: signature tokens or protected files together
    with a write, plus the escape hatches AUTOSCIENTIST_GATE2_OK / --pi-approved / --skip-guard and
    clearing AUTOSCIENTIST_NO_GATE3)

Delegation is honoured, not bypassed: under a PI-signed /autopilot campaign brief the procedures sign
"via lab/campaigns/<file>" — allowed when that brief exists and its PI-authorization box is ticked (the
brief itself can only be signed by the PI). An envelope signed at spawn is allowed when the proposal's
PI Gate-1 marker also approved the envelope. Everything is compared BEFORE vs AFTER, so writing a
template's unsigned placeholder, or keeping an existing signature, is fine.

Interactive sessions never load this (the PI is present). Denials are logged to the run's
permissions.jsonl, so they surface in the dashboard's "Needs you".
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover — the executor always has pyyaml
    yaml = None

HERE = Path(__file__).resolve().parent
HUB = Path(os.environ.get("NEWTS_HUB") or HERE.parent).resolve()

GATE1_RE = re.compile(r"gate ?1 approved|PI Gate 1|gate1_approved", re.I)
GATE3_RE = re.compile(r"gate ?3 approved|PI Gate 3|gate3_approved|Gate 3:\s*approved", re.I)
AUTH_BOX_RE = re.compile(r"-\s*\[[xX]\]\s*Authorized", re.I)
FINAL_ROW_RE = re.compile(r"^\|\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*\|[^|\n]*\|\s*final\s*\|", re.M | re.I)
CAMPAIGN_REF_RE = re.compile(r"lab/campaigns/([A-Za-z0-9][A-Za-z0-9._-]*\.md)")
ENVELOPE_OK_RE = re.compile(r"PI Gate 1 approved[^>\n]*envelope", re.I)

SHELL_ALWAYS = [
    (re.compile(r"AUTOSCIENTIST_GATE2_OK"), "setting AUTOSCIENTIST_GATE2_OK bypasses the Gate-2 envelope check"),
    (re.compile(r"--skip-guard\b"), "--skip-guard bypasses the lifecycle guard"),
    (re.compile(r"(unset\s+AUTOSCIENTIST_NO_GATE3|AUTOSCIENTIST_NO_GATE3\s*=|Env:AUTOSCIENTIST_NO_GATE3|"
                r"environ\s*(\.pop|\[)\s*\(?\s*['\"]AUTOSCIENTIST_NO_GATE3)"),
     "AUTOSCIENTIST_NO_GATE3 must stay set — Gate 3 is signed by the PI"),
]
SIG_TOKENS = re.compile(r"pi_signed|signed_via|gate ?1 approved|PI Gate 1|gate1_approved|gate ?3 approved|"
                        r"PI Gate 3|gate3_approved|\[x\]\s*Authorized", re.I)
PROTECTED_NAMES = re.compile(r"gate3-approval\.md|pi-actions\.jsonl|\.claude/(?:skills|agents)/|agent-roles/|"
                             r"\.(?:codex|opencode)/agents/|"
                             r"lab/workflow/|/workflow/[\w.-]+\.(?:add|method)\.md|workflow/stages\.yaml", re.I)
WRITE_HINT = re.compile(r"(?<![0-9&])>(?!&)|\btee\b|sed\s+-i|perl\s+-\w*i|Set-Content|Add-Content|Out-File|"
                        r"\.write\(|write_text|write_bytes|open\([^)]*['\"][wa+]|\bcp\s|\bmv\s|\brm\s|"
                        r"Copy-Item|Move-Item|Remove-Item|New-Item|yaml\.(safe_)?dump", re.I)
REDIRECT_NOISE = re.compile(r"\d?>\s*&\s*\d|\d?>\s*/dev/null|\d?>\s*\$null|\d?>\s*nul\b|->|=>|>=", re.I)

EDIT_TOOLS = {"edit", "multiedit", "write", "notebookedit", "create", "patch", "apply_patch", "str_replace",
              "str_replace_based_edit_tool"}
SHELL_TOOLS = {"bash", "shell", "exec_command", "local_shell", "powershell"}


# ── helpers ──────────────────────────────────────────────────────────────────

def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _yaml(text: str | None):
    if text is None or yaml is None:
        return None
    try:
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 — a half-written file is just "unknown"
        return None


def _count(rx: re.Pattern, text: str | None) -> int:
    return len(rx.findall(text or ""))


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(HUB).as_posix()
    except ValueError:
        return p.as_posix()


def _campaign_signed(name: str) -> bool:
    """A campaign brief carries PI authority only once the PI ticked its authorization box."""
    text = _read(HUB / "lab" / "campaigns" / name)
    if not text:
        return False
    sec = text.split("## PI authorization", 1)
    return len(sec) == 2 and bool(AUTH_BOX_RE.search(sec[1].split("\n## ", 1)[0]))


def _via_signed_campaign(text: str) -> bool:
    return any(_campaign_signed(n) for n in CAMPAIGN_REF_RE.findall(text or ""))


def _added(old: str | None, new: str) -> str:
    """The lines of `new` that were not in `old` (a multiset diff — enough to read a new marker)."""
    from collections import Counter
    have = Counter((old or "").splitlines())
    out = []
    for ln in new.splitlines():
        if have[ln] > 0:
            have[ln] -= 1
        else:
            out.append(ln)
    return "\n".join(out)


def _flat(d, prefix="") -> dict:
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}{k}"
            if isinstance(v, dict):
                out.update(_flat(v, key + "."))
            else:
                out[key] = v
    return out


def _is_pi_owned(key: str) -> bool:
    try:
        sys.path.insert(0, str(HERE))
        from configure import is_pi_owned   # the single owner table (docs/configuration.md)
        return is_pi_owned(key)
    except Exception:  # noqa: BLE001
        return key.startswith(("agents.", "lab.", "compute.", "budgets.", "oversight."))


# ── per-file rules: (path, text before, text after) → reason or None ─────────

def _rule_proposal(path: Path, old: str | None, new: str) -> str | None:
    if path.name != "proposal.md":
        return None
    if _count(GATE1_RE, new) > _count(GATE1_RE, old):
        if _via_signed_campaign(_added(old, new)):
            return None
        return ("a Gate-1 approval can only be recorded by the PI (the dashboard's Sign button), or under a "
                "PI-signed campaign brief that is referenced in the marker")
    return None


def _envelopes(doc) -> dict:
    """{name: envelope dict} for gate2_envelope and target.score_envelope."""
    out = {}
    if isinstance(doc, dict):
        if isinstance(doc.get("gate2_envelope"), dict):
            out["gate2_envelope"] = doc["gate2_envelope"]
        tgt = doc.get("target")
        if isinstance(tgt, dict) and isinstance(tgt.get("score_envelope"), dict):
            out["target.score_envelope"] = tgt["score_envelope"]
    return out


def _signed(env: dict) -> bool:
    return env.get("pi_signed") is True or str(env.get("pi_signed")).lower() in ("true", "yes", "on")


def _proposal_approved_envelope(control: Path) -> bool:
    slug = control.parent.name
    cands = [HUB / "studies" / slug / "proposal.md"]
    reg = _read(HUB / "lab" / "REGISTRY.md") or ""
    for line in reg.splitlines():   # an adopted repo's dir name can differ from its slug
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 5 and cells[4] and Path(cells[4]).name == control.parent.name:
            cands.append(HUB / "studies" / cells[0] / "proposal.md")
    return any(ENVELOPE_OK_RE.search(_read(c) or "") for c in cands)


def _rule_control(path: Path, old: str | None, new: str) -> str | None:
    if path.name != "control.yaml":
        return None
    before, after = _envelopes(_yaml(old) or {}), _envelopes(_yaml(new))
    if _yaml(new) is None and new.strip():
        # unparseable result: fall back to a token check so a broken file can't smuggle a signature in
        if _count(re.compile(r"pi_signed:\s*(true|yes|on)\b", re.I), new) > \
                _count(re.compile(r"pi_signed:\s*(true|yes|on)\b", re.I), old):
            return "an envelope can only be signed by the PI"
        return None
    for name, env in after.items():
        prev = before.get(name) or {}
        if _signed(prev):
            if {k: v for k, v in env.items()} != {k: v for k, v in prev.items()}:
                return (f"{name} is PI-signed — its values and signature are frozen; a change needs a fresh "
                        "PI signature (the dashboard's envelope editor)")
            continue
        via = str(env.get("signed_via") or "").strip()
        newly_signed = _signed(env)
        new_via = via.lower() not in ("", "null", "none", "~") and via != str(prev.get("signed_via") or "").strip()
        if not (newly_signed or new_via):
            continue
        if via and CAMPAIGN_REF_RE.search(via) and _via_signed_campaign(via):
            continue
        if newly_signed and via.lower() in ("", "null", "none", "~") and _proposal_approved_envelope(path):
            continue
        return (f"{name}: only the PI signs an envelope (the dashboard), or a PI-signed campaign brief via "
                "signed_via: lab/campaigns/<file>")
    return None


def _rule_gate3(path: Path, old: str | None, new: str) -> str | None:
    rel = _rel(path)
    if path.name == "gate3-approval.md":
        return "Gate 3 is signed by the PI only (the dashboard's Gate 3 sheet)"
    if rel.startswith("studies/") and "/paper/" in rel and _count(GATE3_RE, new) > _count(GATE3_RE, old):
        return "a Gate-3 approval marker can only be recorded by the PI"
    return None


def _rule_loop_brief(path: Path, old: str | None, new: str) -> str | None:
    if path.name != "LOOP_BRIEF.md":
        return None
    if _count(AUTH_BOX_RE, new) > _count(AUTH_BOX_RE, old) and not _via_signed_campaign(_added(old, new)):
        return ("LOOP_BRIEF.md is authorized by the PI (the dashboard's Sign button), or \"PI via campaign "
                "brief lab/campaigns/<file>\" under a PI-signed campaign")
    return None


def _rule_campaign(path: Path, old: str | None, new: str) -> str | None:
    rel = _rel(path)
    if not (rel.startswith("lab/campaigns/") and path.suffix == ".md"):
        return None
    sec_old = (old or "").split("## PI authorization", 1)
    sec_new = new.split("## PI authorization", 1)
    tail = lambda s: s[1].split("\n## ", 1)[0] if len(s) == 2 else ""   # noqa: E731
    if old is not None and _campaign_signed(path.name) and new.split("## Campaign Log", 1)[0] != \
            old.split("## Campaign Log", 1)[0]:
        return "this campaign brief is PI-signed — everything above the Campaign Log is frozen"
    if tail(sec_new) != tail(sec_old) and (AUTH_BOX_RE.search(tail(sec_new)) or
                                           re.search(r"\*\*PI:\*\*\s*(?!_)\S", tail(sec_new))):
        return "a campaign brief is signed by the PI only (the dashboard)"
    return None


def _rule_registry(path: Path, old: str | None, new: str) -> str | None:
    if _rel(path) != "lab/REGISTRY.md":
        return None
    had = set(FINAL_ROW_RE.findall(old or ""))
    for slug in set(FINAL_ROW_RE.findall(new)) - had:
        note = _read(HUB / "studies" / slug / "paper" / "gate3-approval.md") or ""
        if not re.search(r"signed_via:\s*dashboard:", note):
            return f"{slug} can only become 'final' after the PI signs Gate 3"
    return None


def _rule_config(path: Path, old: str | None, new: str) -> str | None:
    rel = _rel(path)
    if rel == "lab/.bus/pi-actions.jsonl":
        return "the PI-action log is written by the dashboard only"
    if rel != "lab/config.yaml":
        return None
    a, b = _flat(_yaml(old) or {}), _yaml(new)
    if b is None:
        return None if not new.strip() else "lab/config.yaml would no longer parse"
    b = _flat(b)
    interview = os.environ.get("NEWTS_RUN_SKILL") in ("setup-lab", "configure")
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key):
            continue
        if key.startswith(("agents.programmatic.", "dashboard.")):
            return f"{key} is a dashboard setting — change it in Settings, not from a run"
        if not interview and _is_pi_owned(key):
            return f"{key} is PI-owned — change it in the dashboard's Settings (or ask for it in /configure)"
    return None


PROCEDURE_PATHS = re.compile(r"^(?:\.claude/skills/|\.claude/agents/|\.codex/agents/|\.opencode/agents/|"
                             r"agent-roles/|workflow/|lab/workflow/|studies/[^/]+/workflow/)")


def _rule_procedures(path: Path, old: str | None, new: str) -> str | None:
    """The lab's procedures, roles, workflow definition and the PI's stage instructions are not a run's to
    change — an agent that wants them different files a proposal the PI accepts in the dashboard."""
    if PROCEDURE_PATHS.match(_rel(path)):
        return ("procedures, roles and the PI's stage instructions are PI-owned — suggest a change with "
                "`python tools/workflow.py propose --proc <procedure> --mode add|replace --file <draft.md>`")
    return None


RULES = [_rule_proposal, _rule_control, _rule_gate3, _rule_loop_brief, _rule_campaign, _rule_registry, _rule_config,
         _rule_procedures]


def check_write(path: Path, old: str | None, new: str) -> str | None:
    for rule in RULES:
        why = rule(path, old, new)
        if why:
            return why
    return None


# ── tool inputs → (path, before, after) ──────────────────────────────────────

PATCH_FILE_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.M)


def _abs(fp: str, cwd: str) -> Path:
    p = Path(fp)
    return (p if p.is_absolute() else Path(cwd or ".") / p).resolve()


def _patch_writes(patch: str, cwd: str):
    """codex apply_patch: per file, the removed text vs the added text (enough for the count rules;
    the envelope-values rule sees the added lines too)."""
    parts = PATCH_FILE_RE.split(patch)
    # parts = [pre, kind, file, body, kind, file, body, ...]
    for i in range(1, len(parts) - 2, 3):
        kind, fp, body = parts[i], parts[i + 1].strip(), parts[i + 2]
        path = _abs(fp, cwd)
        cur = _read(path)
        if kind == "Add":
            new = "\n".join(ln[1:] for ln in body.splitlines() if ln.startswith("+"))
            yield path, None, new
        elif kind == "Delete":
            yield path, cur, ""
        else:
            removed = "\n".join(ln[1:] for ln in body.splitlines() if ln.startswith("-"))
            added = "\n".join(ln[1:] for ln in body.splitlines() if ln.startswith("+"))
            if cur is not None and removed and removed in cur:
                yield path, cur, cur.replace(removed, added, 1)
            elif cur is not None:
                yield path, cur, cur + "\n" + added          # hunks with context: treat as additions
            else:
                yield path, None, added


def writes_of(tool: str, ti: dict, cwd: str):
    t = (tool or "").lower()
    if not isinstance(ti, dict):
        return
    if t == "apply_patch" or (t == "patch" and "patch" not in ti and "command" in ti):
        yield from _patch_writes(str(ti.get("command") or ti.get("input") or ""), cwd)
        return
    if t == "patch":
        yield from _patch_writes(str(ti.get("patch") or ti.get("patchText") or ""), cwd)
        return
    fp = ti.get("file_path") or ti.get("filePath") or ti.get("path") or ti.get("notebook_path")
    if not fp:
        return
    path = _abs(str(fp), cwd)
    cur = _read(path)
    if t in ("write", "create"):
        yield path, cur, str(ti.get("content") or ti.get("file_text") or "")
    elif t in ("edit", "str_replace", "str_replace_based_edit_tool"):
        old_s = str(ti.get("old_string") or ti.get("oldString") or ti.get("old_str") or "")
        new_s = str(ti.get("new_string") or ti.get("newString") or ti.get("new_str") or ti.get("file_text") or "")
        if cur is None:
            yield path, None, new_s
        elif old_s and old_s in cur:
            yield path, cur, (cur.replace(old_s, new_s) if ti.get("replace_all") or ti.get("replaceAll")
                              else cur.replace(old_s, new_s, 1))
        else:
            yield path, cur, cur + "\n" + new_s
    elif t == "multiedit":
        text = cur or ""
        for e in ti.get("edits") or []:
            if not isinstance(e, dict):
                continue
            o, n = str(e.get("old_string") or e.get("oldString") or ""), str(e.get("new_string") or e.get("newString") or "")
            text = text.replace(o, n) if (e.get("replace_all") and o) else (text.replace(o, n, 1) if o and o in text else text + "\n" + n)
        yield path, cur, text
    elif t == "notebookedit":
        yield path, cur, (cur or "") + "\n" + str(ti.get("new_source") or "")


def check_shell(cmd: str) -> str | None:
    for rx, why in SHELL_ALWAYS:
        if rx.search(cmd):
            return why
    interview = os.environ.get("NEWTS_RUN_SKILL") in ("setup-lab", "configure")
    if "--pi-approved" in cmd and not interview:
        return "--pi-approved is the PI's own flag — the PI approves in the dashboard"
    quiet = REDIRECT_NOISE.sub(" ", cmd)
    if WRITE_HINT.search(quiet) and (SIG_TOKENS.search(cmd) or PROTECTED_NAMES.search(cmd)):
        return ("this command writes a signature or a PI-only file — signatures are made by the PI in the "
                "dashboard")
    return None


def decide(payload: dict) -> str | None:
    """The deny reason for one PreToolUse payload, or None to allow."""
    tool = str(payload.get("tool_name") or payload.get("tool") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else (payload.get("args") or {})
    cwd = str(payload.get("cwd") or os.getcwd())
    t = tool.lower()
    if t in SHELL_TOOLS:
        cmd = ti.get("command") if isinstance(ti, dict) else ""
        cmd = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd or "")
        return check_shell(cmd)
    if t in EDIT_TOOLS:
        for path, old, new in writes_of(t, ti, cwd):
            why = check_write(path, old, new)
            if why:
                return f"{_rel(path)}: {why}"
    return None


def _log_denial(tool: str, why: str) -> None:
    rd = os.environ.get("NEWTS_RUN_DIR")
    if not rd:
        return
    try:
        with (Path(rd) / "permissions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool, "decision": "deny",
                                "by": "signature-guard", "summary": why[:300]}) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except (json.JSONDecodeError, OSError):
        return 0     # never block on a malformed payload — the tracer and the CLI's own checks remain
    if not isinstance(payload, dict) or (payload.get("hook_event_name") not in (None, "PreToolUse")):
        return 0
    try:
        why = decide(payload)
    except Exception:  # noqa: BLE001 — a guard bug must not wedge a run; it fails open, loudly
        return 0
    if not why:
        return 0
    _log_denial(str(payload.get("tool_name") or ""), why)
    sys.stderr.write(f"Denied by the Newts' Lab signature guard: {why}. Ask the PI instead (they sign from "
                     "the dashboard); do not try another way around it.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
