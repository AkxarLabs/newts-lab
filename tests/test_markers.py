"""One definition of the PI's signatures (tools/markers.py), read the same way everywhere."""

from __future__ import annotations

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import markers  # noqa: E402


def test_every_gate1_spelling_counts_and_an_expired_envelope_does_not(tmp_path):
    (tmp_path / "studies" / "a").mkdir(parents=True)
    for text in ("PI Gate 1 approved via Vivarium dashboard", "gate1_approved: 2026-10-01", "Gate 1 approved by the PI"):
        (tmp_path / "studies" / "a" / "proposal.md").write_text(f"# p\n{text}\n", encoding="utf-8")
        assert markers.gate_signed(tmp_path, "a", 1)
    (tmp_path / "studies" / "a" / "proposal.md").write_text("# p\nno signature\n", encoding="utf-8")
    assert not markers.gate_signed(tmp_path, "a", 1)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "control.yaml").write_text("gate2_envelope:\n  pi_signed: true\n  expires: 2000-01-01\n", encoding="utf-8")
    assert not markers.gate_signed(tmp_path, "a", 2, proj)
    (proj / "control.yaml").write_text("gate2_envelope:\n  pi_signed: true\n  expires: null\n", encoding="utf-8")
    assert markers.gate_signed(tmp_path, "a", 2, proj)
    assert not markers.gate_signed(tmp_path, "a", 3)


def test_the_readers_share_the_definition():
    import gate3
    import guard
    import signature_guard
    assert guard.GATE1_RE is markers.GATE1_RE and signature_guard.GATE3_RE is markers.GATE3_RE
    assert gate3.AUTH_BOX_RE is markers.AUTH_BOX_RE is signature_guard.AUTH_BOX_RE
    assert markers.GATE1_RE.search(markers.GATE1_DASHBOARD_MARK)


def test_gate_waiting_is_word_bounded():
    m = markers
    assert m.gate_waiting("awaiting PI Gate 1") == 1
    assert m.gate_waiting("sign the Gate-2 envelope") == 2
    assert m.gate_waiting("investigate 3 baselines") is None    # not a gate
    assert m.gate_waiting("delegate 2 sweeps to runners") is None
    assert m.gate_waiting("mitigate the risk") is None
