"""How the PI's signatures are recognised — one definition for every reader: the lifecycle guard, the
signature guard, Gate 3 delegation, the campaign keeper and the dashboard. Stdlib only (pyyaml is used
when present, for the Gate-2 envelope's expiry).

    GATE1_RE      a Gate-1 approval in studies/<slug>/proposal.md
    GATE3_RE      a Gate-3 approval (a review file, or studies/<slug>/paper/gate3-approval.md)
    AUTH_BOX_RE   a ticked "Authorized" box in a LOOP_BRIEF / campaign brief
    GATE3_BOX_RE  a ticked "Papers may finalize without me" box in a campaign brief
    gate_signed(hub, slug, gate, project_dir)   is that gate's signature on disk and still valid?
"""

from __future__ import annotations

import re
import time
from pathlib import Path

GATE1_RE = re.compile(r"gate ?1 approved|PI Gate 1|gate1_approved", re.I)
GATE3_RE = re.compile(r"gate ?3 approved|PI Gate 3|gate3_approved|Gate 3:\s*approved", re.I)
AUTH_BOX_RE = re.compile(r"-\s*\[[xX]\]\s*Authorized", re.I)
GATE3_BOX_RE = re.compile(r"-\s*\[[xX]\]\s*Papers may finalize without me", re.I)
GATE1_DASHBOARD_MARK = "PI Gate 1 approved via Vivarium dashboard"   # what the dashboard writes


def _text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def envelope(control_yaml: Path) -> dict:
    """The project's gate2_envelope block ({} when absent or unreadable)."""
    text = _text(control_yaml)
    try:
        import yaml   # noqa: PLC0415
        return (yaml.safe_load(text) or {}).get("gate2_envelope") or {}
    except ImportError:
        m = re.search(r"^gate2_envelope:\s*\n((?:[ \t]+.*\n?)*)", text, re.M)
        if not m:
            return {}
        out = {}
        for k, v in re.findall(r"^[ \t]+(pi_signed|expires):\s*(\S+)", m.group(1), re.M):
            out[k] = (v.lower() == "true") if k == "pi_signed" else v.strip("'\"")
        return out
    except Exception:  # noqa: BLE001 — a malformed control.yaml is "not signed"
        return {}


def envelope_valid(env: dict) -> bool:
    """Signed, and not past its `expires` date."""
    if not env.get("pi_signed"):
        return False
    expires = str(env.get("expires") or "").strip().lower()
    return not (expires and expires not in ("null", "none", "~") and expires < time.strftime("%Y-%m-%d"))


def gate_signed(hub, slug: str, gate: int, project_dir=None) -> bool:
    hub = Path(hub)
    if gate == 1:
        return bool(GATE1_RE.search(_text(hub / "studies" / slug / "proposal.md")))
    if gate == 2:
        return bool(project_dir) and envelope_valid(envelope(Path(project_dir) / "control.yaml"))
    if gate == 3:
        return bool(GATE3_RE.search(_text(hub / "studies" / slug / "paper" / "gate3-approval.md")))
    return False
