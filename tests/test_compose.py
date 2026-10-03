"""Compose (dashboard/compose.py): the lab's definition edited as a draft — forms, files, copies, deletes —
checked, then published as one change (and undone). The lab and its runs never see a half-made edit."""

from __future__ import annotations

import shutil

import pytest
import yaml

from conftest import REPO, load


@pytest.fixture
def m(hub, monkeypatch, tmp_path):
    for rel in ("workflow", ".claude/skills", "agent-roles", "checks", "templates/project-types"):
        shutil.copytree(REPO / rel, hub.root / rel, dirs_exist_ok=True)
    (hub.root / "tools").mkdir(exist_ok=True)
    shutil.copy(REPO / "tools" / "role_sync.py", hub.root / "tools")
    shutil.copy(REPO / "tools" / "labfiles.py", hub.root / "tools")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    mod = load("dashboard/serve")
    monkeypatch.setattr(mod.ctx, "HUB", hub.root)
    monkeypatch.setattr(mod.ctx, "LAB", hub.lab)
    return mod


def _op(m, **body):
    out, code = m.compose.op(body)
    assert code == 200, out
    return out


def _stages(root):
    return yaml.safe_load((root / "workflow" / "stages.yaml").read_text(encoding="utf-8"))


def test_edits_go_to_a_draft_until_published_and_can_be_undone(m, hub):
    before = (hub.root / ".claude/skills/scope/SKILL.md").read_text(encoding="utf-8")
    assert not m.compose.view()[0]["draft"]["active"]
    _op(m, op="procedure", name="scope", fields={"title": "Scope it", "does": "Weighs the options."}, stages=["scoping", "proposal"])
    v = m.compose.view()[0]
    assert v["draft"]["active"] and v["procedures"]["scope"]["title"] == "Scope it"
    assert {c["path"] for c in v["draft"]["changes"]} == {".claude/skills/scope/SKILL.md", "workflow/stages.yaml"}
    assert v["draft"]["problems"] == []
    assert (hub.root / ".claude/skills/scope/SKILL.md").read_text(encoding="utf-8") == before   # the lab: untouched
    out, code = m.compose.op({"op": "publish", "note": "rename scope"})
    assert code == 200, out
    skill = (hub.root / ".claude/skills/scope/SKILL.md").read_text(encoding="utf-8")
    assert "title: Scope it" in skill and "<!-- newts:contract" in skill
    assert "scope" in next(s for s in _stages(hub.root)["stages"] if s["id"] == "proposal")["procedures"]
    v = m.compose.view()[0]
    assert not v["draft"]["active"] and v["history"][0]["note"] == "rename scope"
    out, code = m.compose.op({"op": "undo", "id": v["history"][0]["id"]})
    assert code == 200, out
    assert (hub.root / ".claude/skills/scope/SKILL.md").read_text(encoding="utf-8") == before
    assert "compose.publish" in (hub.lab / ".bus" / "pi-actions.jsonl").read_text(encoding="utf-8")


def test_copy_then_delete_a_procedure_and_discard(m, hub):
    _op(m, op="copy", kind="procedure", like="lit-review", name="quick-scan", title="A quick scan")
    v = m.compose.view()[0]
    p = v["procedures"]["quick-scan"]
    assert p["like"] == "lit-review" and p["title"] == "A quick scan" and "literature" in p["stages"]
    _op(m, op="instructions", kind="method", name="quick-scan", text="Skim the ten most-cited papers.")
    assert (m.compose._draft() / "lab/workflow/quick-scan.method.md").is_file()
    _op(m, op="delete", kind="procedure", name="quick-scan")
    v = m.compose.view()[0]
    assert "quick-scan" not in v["procedures"] and v["draft"]["problems"] == []
    _op(m, op="discard")
    assert not m.compose.active() and not (hub.root / ".claude/skills/quick-scan").exists()


def test_the_locks_and_the_problems_block_a_publish(m, hub):
    text = (hub.root / "workflow/stages.yaml").read_text(encoding="utf-8").replace("at: proposal,", "at: scoping,", 1)
    _op(m, op="write", path="workflow/stages.yaml", text=text)
    probs = m.compose.view()[0]["draft"]["problems"]
    assert any("gates are fixed" in p for p in probs)
    assert m.compose.op({"op": "publish"})[1] == 409
    _op(m, op="discard")
    _op(m, op="rule", id="seeds", remove=True)
    assert any("cited by number" in p for p in m.compose.problems())
    _op(m, op="discard")
    _op(m, op="delete", kind="procedure", name="advance")             # next_for_state still names it
    assert any("advance" in p for p in m.compose.problems())


def test_a_lab_change_after_the_draft_began_is_a_conflict(m, hub):
    _op(m, op="role", name="overseer", fields={"label": "The overseer"})
    (hub.root / "agent-roles" / "overseer.yaml").write_text("name: overseer\nlabel: Changed meanwhile\n", encoding="utf-8")
    out, code = m.compose.op({"op": "publish"})
    assert code == 409 and out["conflicts"] == ["agent-roles/overseer.yaml"]


def test_stages_states_and_rooms_without_yaml(m, hub):
    _op(m, op="stage-add", id="replication", title="Replication", after="analysis", state="replicating",
        state_label="Replicating", room="lab")
    d = _stages(m.compose._draft())
    ids = [s["id"] for s in d["states"]]
    assert ids.index("replicating") == ids.index("analysis") + 1
    assert [s["id"] for s in d["stages"]].index("replication") == [s["id"] for s in d["stages"]].index("analysis") + 1
    assert "replicating" in next(r for r in d["rooms"] if r["id"] == "lab")["states"]
    assert d["tracks"]["paper"].index("replicating") == d["tracks"]["paper"].index("analysis") + 1
    _op(m, op="copy", kind="room", like="lab", name="bench", plain=True)
    _op(m, op="state", id="replicating", fields={"room": "bench", "label": "Replication"})
    d = _stages(m.compose._draft())
    assert next(r for r in d["rooms"] if r["id"] == "bench")["states"] == ["replicating"]
    assert "replicating" not in next(r for r in d["rooms"] if r["id"] == "lab")["states"]
    _op(m, op="room", id="bench", fields={"title": "The Bench", "floor": 1, "order": 3})
    assert m.compose.problems() == []
    _op(m, op="delete", kind="room", name="bench", move_to="lab")
    _op(m, op="delete", kind="stage", name="replication")
    assert m.compose.problems() == []
    assert "# the PI's gates" in (m.compose._draft() / "workflow/stages.yaml").read_text(encoding="utf-8")   # comments kept


def test_rules_and_files(m, hub):
    _op(m, op="copy", kind="rule", name="no-tabs", text="**No tabs.** Indent with spaces.", list="project")
    _op(m, op="rule", id="no-tabs", text="**No tabs.** Indent with four spaces.", checks=[])
    rl = yaml.safe_load((m.compose._draft() / "workflow/rules.yaml").read_text(encoding="utf-8"))
    assert rl["project_rules"][-1] == {"id": "no-tabs", "text": "**No tabs.** Indent with four spaces."}
    _op(m, op="rule", id="no-tabs", remove=True)
    _op(m, op="rule", id="seeds", text="**Seeds.** Three of them.")
    assert m.compose.problems() == []
    for bad in ("../lab/config.yaml", "tools/guard.py", "workflow/../tools/x.md", "checks/x.exe"):
        assert m.compose.op({"op": "write", "path": bad, "text": "x"})[1] == 400, bad
    f, code = m.compose.file_get({"path": "agent-roles/overseer.md"})
    assert code == 200 and f["text"] == f["published"]
