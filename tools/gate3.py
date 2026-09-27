"""Gate 3 — the final sign-off — in one place: the readiness checklist, the paper audits, and delegation.

Gate 3 is the PI's. It is recorded in `studies/<slug>/paper/gate3-approval.md` in exactly one of two ways:

  signed_via: dashboard:<ts>                    the PI signed it in the dashboard (typed confirmation)
  signed_via: campaign:lab/campaigns/<f>.md     the PI's signed campaign brief delegates Gate 3 (its
                                                "Papers may finalize without me" box is ticked) and the
                                                executor's campaign keeper — never an agent — recorded
                                                it after re-running the paper audits itself

A delegated note stays valid only while its campaign still delegates: `delegation_valid()` re-checks the
brief (signed, box ticked, unchanged since the note was written), the keeper's campaign state (not
revoked) and the study (still in the campaign, not held). The executor (`/finalize` launch), guard.py
(finalization) and the signature guard (a registry row moving to `final`) all ask it, so revoking the
delegation in the dashboard takes effect even after a note exists.

Import-safe (stdlib + optional yaml); the audits run as subprocesses of this interpreter.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HUB = Path(__file__).resolve().parents[1]
NOTE = "gate3-approval.md"
AUTH_BOX_RE = re.compile(r"-\s*\[[xX]\]\s*Authorized", re.I)
GATE3_BOX_RE = re.compile(r"-\s*\[[xX]\]\s*Papers may finalize without me", re.I)
AUDITS = [
    ("claims", ["audit_claims.py", "{paper}", "--scan-novelty"]),
    ("multiseed", ["audit_multiseed.py", "{paper}"]),
    ("ablations", ["audit_ablation_coverage.py", "{paper}"]),
    ("eval", ["audit_eval_discipline.py", "{paper}"]),
]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig")
    except OSError:
        return ""


def paper_dir(hub: Path, slug: str) -> Path:
    return Path(hub) / "studies" / slug / "paper"


def note_path(hub: Path, slug: str) -> Path:
    return paper_dir(hub, slug) / NOTE


def registry_state(hub: Path, slug: str) -> str:
    for line in _read(Path(hub) / "lab" / "REGISTRY.md").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] == slug:
            return cells[2].lower()
    return ""


# ── the meta-review verdict ──────────────────────────────────────────────────────────────────────
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def _section(text: str, pattern: re.Pattern) -> str:
    lines = text.split("\n")
    heads = [(i, len(m.group(1)), m.group(2)) for i, ln in enumerate(lines) for m in (_HEADING.match(ln),) if m]
    for n, (i, level, h) in enumerate(heads):
        if pattern.search(h):
            end = next((j for (j, lvl, _h) in heads[n + 1:] if lvl <= level), len(lines))
            return "\n".join(lines[i:end]).strip()
    return ""


def meta_verdict(text: str) -> str:
    if not text:
        return ""
    out = [ln.strip() for ln in text.split("\n") if re.search(r"\|\s*\*{0,2}Overall", ln, re.I)][:1]
    dec = _section(text, re.compile(r"^Decision\b", re.I))
    if dec:
        out.append(dec)
    return "\n\n".join(out).strip()


def accepts(verdict: str) -> bool:
    return bool(re.search(r"\baccept", verdict, re.I)) and not re.search(r"\breject|needs[- ]experiment", verdict, re.I)


# ── the checklist the Gate 3 sheet (and the keeper) use ──────────────────────────────────────────
def readiness(hub: Path, slug: str) -> dict:
    hub = Path(hub)
    paper = paper_dir(hub, slug)
    state = registry_state(hub, slug)
    meta = ""
    for f in sorted(paper.glob("reviews/**/meta-review*.md")) if paper.is_dir() else []:
        meta = _read(f) or meta
    verdict = meta_verdict(meta)
    checks = [
        {"id": "state", "label": "Internal review is complete (state: internal-review)", "ok": state == "internal-review",
         "blocking": True, "detail": f"state is '{state or 'unknown'}'"},
        {"id": "meta", "label": "The meta-review recommends accepting", "ok": accepts(verdict), "blocking": False,
         "detail": (verdict[:300] or "no meta-review found")},
        {"id": "pdf", "label": "The paper compiles (main.pdf)", "ok": (paper / "main.pdf").exists(), "blocking": False,
         "detail": f"studies/{slug}/paper/main.pdf"},
        {"id": "claims", "label": "Every claim is mapped to an artifact (claims.yaml)", "ok": (paper / "claims.yaml").exists(),
         "blocking": False, "detail": "run the claims audit from the Paper tab" if (paper / "claims.yaml").exists() else "no claims.yaml"},
    ]
    signed = note_path(hub, slug).exists()
    return {"ok": True, "idea": slug, "checks": checks, "signed": signed,
            "signed_via": signed_via(hub, slug) if signed else None,
            "can_sign": all(c["ok"] for c in checks if c["blocking"]) and not signed}


def run_audits(hub: Path, slug: str, timeout: float = 600) -> dict:
    """The four paper audits, run by the caller (the keeper) itself: {name: exit code} (0 = clean,
    1 = FAIL, 2 = MANUAL — anything but 0 blocks a delegated Gate 3)."""
    hub = Path(hub)
    paper = paper_dir(hub, slug).as_posix()
    out = {}
    for name, argv in AUDITS:
        tool = hub / "tools" / argv[0]
        if not tool.is_file():
            out[name] = 127
            continue
        try:
            r = subprocess.run([sys.executable, str(tool), *[a.format(paper=paper) for a in argv[1:]]], cwd=str(hub),
                               capture_output=True, text=True, timeout=timeout)
            out[name] = r.returncode
        except (OSError, subprocess.TimeoutExpired):
            out[name] = 124
    return out


# ── delegation ───────────────────────────────────────────────────────────────────────────────────
def brief_sha(text: str) -> str:
    """The signed part of a campaign brief (everything above its append-only Campaign Log)."""
    head = (text or "").replace("\r\n", "\n").split("## Campaign Log", 1)[0]
    return hashlib.sha256(head.encode("utf-8")).hexdigest()


def campaign_state(hub: Path, name: str) -> dict:
    try:
        return json.loads((Path(hub) / "lab" / ".bus" / "campaigns" / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def campaign_delegates(hub: Path, brief_rel: str) -> tuple[bool, str]:
    """Does this campaign (still) delegate Gate 3? Its brief is signed by the PI with the Gate-3 box ticked,
    and its state (kept by the executor) has not been revoked."""
    rel = str(brief_rel or "").strip()
    if not re.match(r"^lab/campaigns/[A-Za-z0-9][A-Za-z0-9._-]*\.md$", rel):
        return False, f"not a campaign brief: {rel!r}"
    text = _read(Path(hub) / rel)
    if not text:
        return False, f"{rel} is missing"
    if not AUTH_BOX_RE.search(text) or "signed_via: dashboard:" not in text:
        return False, f"{rel} is not signed by the PI"
    if not GATE3_BOX_RE.search(text.split("## Campaign Log", 1)[0]):
        return False, f"{rel} does not delegate Gate 3"
    st = campaign_state(hub, Path(rel).stem)
    if not st.get("gate3_auto"):
        return False, "the PI revoked Gate-3 delegation for this campaign" if st else "no campaign state"
    return True, "ok"


def signed_via(hub: Path, slug: str) -> str | None:
    m = re.search(r"signed_via:\s*(\S+)", _read(note_path(hub, slug)))
    return m.group(1) if m else None


def delegation_valid(hub: Path, slug: str) -> tuple[bool, str]:
    """Is the study's Gate-3 note a valid signature? The PI's own (dashboard) always is; a delegated one only
    while its campaign still delegates, the brief is unchanged, and the study is still in it and not held."""
    hub = Path(hub)
    text = _read(note_path(hub, slug))
    if not text:
        return False, "no Gate 3 note"
    via = signed_via(hub, slug) or ""
    if via.startswith("dashboard:"):
        return True, "signed by the PI in the dashboard"
    if not via.startswith("campaign:"):
        return False, f"unrecognised signature {via!r}"
    rel = via[len("campaign:"):]
    ok, why = campaign_delegates(hub, rel)
    if not ok:
        return False, why
    m = re.search(r"brief_sha256:\s*([0-9a-f]{64})", text)
    if not m or m.group(1) != brief_sha(_read(hub / rel)):
        return False, "the campaign brief changed after Gate 3 was recorded"
    st = campaign_state(hub, Path(rel).stem)
    study = (st.get("studies") or {}).get(slug) or {}
    if study.get("hold"):
        return False, "the PI is holding this study from auto-finalizing"
    if not study.get("member"):
        return False, "this study is not part of the campaign"
    return True, f"delegated by {rel}"


def sign_delegated(hub: Path, slug: str, brief_rel: str, audits: dict, by: str) -> Path:
    """Write the delegated Gate-3 note. Called ONLY by the executor's campaign keeper after its checks."""
    hub = Path(hub)
    paper = paper_dir(hub, slug)
    pdf = paper / "main.pdf"
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest() if pdf.exists() else None
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    lines = [f"# Gate 3 approval — {slug}", "",
             "Gate 3 approved by delegation (the PI's signed campaign brief delegates it).", "",
             f"- signed_via: campaign:{brief_rel}",
             f"- brief_sha256: {brief_sha(_read(hub / brief_rel))}",
             f"- delegated_by: {by} at {ts}",
             f"- audits: " + ", ".join(f"{k}={v}" for k, v in audits.items()),
             f"- state at signing: {registry_state(hub, slug)}",
             f"- paper: studies/{slug}/paper/main.pdf" + (f" (sha256 {digest})" if digest else " (not compiled)"),
             "", "The PI can revoke this in the dashboard (the campaign card) until /finalize has run."]
    paper.mkdir(parents=True, exist_ok=True)
    p = paper / NOTE
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
