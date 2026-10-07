"""Artifacts — what agents make for the PI to look at (tools/artifact.py), and the dashboard's side of them.

Publishing (kinds from the file, a question with choices, the run it came from, refusals), what the dashboard
lists and shows (Markdown text, a parsed table, a file served sandboxed), a question waiting in Needs you, the PI's
reply reaching the run that asked (or a note to its study when that run is gone), a run never writing the PI's
reply, and "what it wrote" on a run's sheet: only files its own transcript names.
"""

from __future__ import annotations

import json
import sys

import pytest

from conftest import REPO, load

FAKE = REPO / "tests" / "fake_claude.py"


@pytest.fixture
def art(hub, monkeypatch):
    t = load("artifact")
    monkeypatch.setenv("NEWTS_HUB", str(hub.root))
    for k in ("NEWTS_RUN_ID", "NEWTS_RUN_SKILL", "NEWTS_RUN_SUBJECT"):
        monkeypatch.delenv(k, raising=False)
    return t


def _serve(hub, monkeypatch):
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\ndashboard:\n  port: 8787\n'
        "agents:\n  programmatic:\n    enabled: true\n    backend: claude\n    max_depth: 1\n"
        f"    backends:\n      claude:\n        command: {json.dumps([sys.executable, str(FAKE)])}\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    m = load("dashboard/serve")
    monkeypatch.setattr(m.ctx, "HUB", hub.root)
    monkeypatch.setattr(m.ctx, "LAB", hub.lab)
    return m


def test_publish_takes_its_kind_from_the_file_and_its_run_from_the_environment(art, hub, tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTS_RUN_ID", "r-1")
    monkeypatch.setenv("NEWTS_RUN_SKILL", "analyze")
    monkeypatch.setenv("NEWTS_RUN_SUBJECT", "idea-a")
    f = tmp_path / "pilot.md"
    f.write_text("# Pilot\n\nIt worked.\n", encoding="utf-8")
    m = art.publish("Pilot results", str(f), note="2 of 3 seeds")
    assert (m["kind"], m["run_id"], m["skill"], m["study"], m["question"]) == ("md", "r-1", "analyze", "idea-a", None)
    d = hub.lab / ".bus" / "artifacts" / m["id"]
    assert (d / "content.md").read_text(encoding="utf-8").startswith("# Pilot") and (d / "artifact.json").is_file()
    ev = json.loads((hub.lab / ".bus" / "events.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ev["kind"] == "artifact" and ev["run_id"] == "r-1" and ev["data"]["id"] == m["id"]
    q = art.publish("Which eval set?", question="A or B?", choices=["A", " B ", ""])
    assert q["kind"] == "choice" and q["choices"] == ["A", "B"] and q["file"] is None
    assert art.publish("Pick one", choices=["x", "y"])["question"] == "Pick one"     # choices alone ask the title
    loaded = art.load(m["id"])
    assert loaded["reply"] is None and loaded["seen"] is False
    assert [x["id"] for x in art.all_artifacts()][:1] == [art.all_artifacts()[0]["id"]]


def test_publish_refuses_what_it_cannot_show(art, tmp_path):
    with pytest.raises(art.ArtifactError):
        art.publish("", question="?")
    with pytest.raises(art.ArtifactError):
        art.publish("Nothing")                                        # no file, no question
    exe = tmp_path / "x.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(art.ArtifactError, match="can't show"):
        art.publish("A binary", str(exe))
    with pytest.raises(art.ArtifactError, match="no file"):
        art.publish("Missing", str(tmp_path / "nope.md"))
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (art.MAX_BYTES + 1))
    with pytest.raises(art.ArtifactError, match="MB"):
        art.publish("Too big", str(big))
    assert art.main(["publish", "--title", "t"]) == 2


def test_the_dashboard_shows_text_tables_and_files(art, hub, tmp_path, monkeypatch):
    m = _serve(hub, monkeypatch)
    (tmp_path / "t.csv").write_text("variant,loss\ndense,1.40\nours,1.31\n", encoding="utf-8")
    (tmp_path / "p.html").write_text("<h1>hi</h1><script>fetch('/api/state')</script>", encoding="utf-8")
    tab = art.publish("Ablation", str(tmp_path / "t.csv"))
    page = art.publish("Explorer", str(tmp_path / "p.html"))
    out, code = m.artifacts.get({"id": tab["id"]})
    assert code == 200 and out["table"]["rows"] == [["variant", "loss"], ["dense", "1.40"], ["ours", "1.31"]]
    assert m.artifacts.get({"id": "a-../../etc"})[1] == 404
    path, ctype = m.artifacts.file_route({"id": page["id"]})
    assert path.name == "content.html" and ctype.startswith("text/html")
    lst, _ = m.artifacts.list_artifacts({})
    assert {x["id"] for x in lst["artifacts"]} == {tab["id"], page["id"]}
    assert m.artifacts.seen({"ids": [tab["id"], "bogus"]})[0]["seen"] == 1 and art.load(tab["id"])["seen"]
    snap = m.sources.snapshot()
    assert {a["id"] for a in snap["artifacts"]} == {tab["id"], page["id"]}


def test_an_agents_page_is_served_sandboxed(art, hub, tmp_path, monkeypatch):
    """HTML and SVG from a run get a CSP sandbox (an opaque origin, even opened directly), never the dashboard's."""
    m = _serve(hub, monkeypatch)
    sent = {}

    class H(m.Handler):
        def __init__(self):        # no socket: just the method under test
            pass

        def _send(self, code, body, ctype, headers=None):
            sent.update(code=code, ctype=ctype, headers=headers or {})
    (tmp_path / "p.html").write_text("<p>x</p>", encoding="utf-8")
    H()._serve_bytes(tmp_path / "p.html", "text/html; charset=utf-8")
    assert sent["headers"]["Content-Security-Policy"].startswith("sandbox") and sent["headers"]["X-Content-Type-Options"] == "nosniff"
    (tmp_path / "f.png").write_bytes(b"\x89PNG")
    H()._serve_bytes(tmp_path / "f.png", "image/png")
    assert "Content-Security-Policy" not in sent["headers"]


def test_a_question_waits_in_needs_you_and_the_reply_reaches_the_run(art, hub, monkeypatch):
    m = _serve(hub, monkeypatch)
    out, _ = m.runops.launch_run({"skill": "spawn-project", "target": "idea-q", "confirm": True})
    rid = out["run_id"]
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, rid)
    m.executor.manifest.transition(lab, path, man, "completed", by="test", session_id="S1")
    monkeypatch.setenv("NEWTS_RUN_ID", rid)
    a = art.publish("Which eval set?", question="A or B?", choices=["A", "B"], study="idea-q")
    items = [x for x in m.runops.attention.collect([], [], [], []) if x["kind"] == "artifact"]
    assert [x["detail"]["artifact"] for x in items] == [a["id"]]
    assert m.artifacts.reply({"id": a["id"], "choice": "C"})[1] == 400           # not one of its options
    assert m.artifacts.reply({"id": a["id"]})[1] == 400
    res, code = m.artifacts.reply({"id": a["id"], "choice": "B", "text": "and keep A for pilots"})
    assert code == 200 and res["reply"]["delivered"] == f"run {rid}"
    run = m.runops.run_detail(rid)[0]["run"]
    assert run["status"] == "queued"                                              # resumes with the reply
    assert art.load(a["id"])["reply"]["choice"] == "B"
    assert not [x for x in m.runops.attention.collect([], [], [], []) if x["kind"] == "artifact"]   # answered
    assert any(x.get("action") == "artifact.reply" for x in map(json.loads, (hub.lab / ".bus" / "pi-actions.jsonl").read_text(encoding="utf-8").splitlines()))


def test_a_reply_to_a_run_that_is_gone_becomes_a_note_to_its_study(art, hub, monkeypatch):
    m = _serve(hub, monkeypatch)
    monkeypatch.setenv("NEWTS_RUN_ID", "r-gone")
    a = art.publish("Plan", question="Go?", choices=["Yes"], study="idea-a")
    res, code = m.artifacts.reply({"id": a["id"], "choice": "Yes"})
    assert code == 200 and res["reply"]["delivered"] == "a note to idea-a" and res["reply"]["delivered_error"]
    notes = (hub.lab / ".bus" / "directives.jsonl").read_text(encoding="utf-8")
    assert a["id"] in notes and "Chosen: Yes" in notes


def test_a_run_can_publish_but_never_write_the_pis_reply(hub, monkeypatch):
    g = load("signature_guard")
    monkeypatch.setattr(g, "HUB", hub.root.resolve())
    d = hub.lab / ".bus" / "artifacts" / "a-20260101-000000-abcd"
    d.mkdir(parents=True)
    w = lambda p, c: {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": str(hub.root), "tool_input": {"file_path": str(p), "content": c}}  # noqa: E731
    assert g.decide(w(d / "reply.json", '{"choice": "Yes"}'))
    assert g.decide(w(d / "seen", ""))
    assert g.decide({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(hub.root),
                     "tool_input": {"command": f"echo x > lab/.bus/artifacts/{d.name}/reply.json"}})
    assert g.decide(w(d / "artifact.json", "{}")) is None                       # its own artifact is the run's


def test_a_runs_sheet_opens_only_the_files_its_transcript_says_it_wrote(hub, tmp_path, monkeypatch):
    m = _serve(hub, monkeypatch)
    out, _ = m.runops.launch_run({"skill": "lab-status", "confirm": True})
    rid = out["run_id"]
    lab = m.executor.Lab(hub.root)
    _t, _w, path, man = m.executor.find_run(lab, rid)
    plan = tmp_path / "PLAN.md"
    plan.write_text("# The plan\n", encoding="utf-8")
    secret = tmp_path / "secret.md"
    secret.write_text("not this", encoding="utf-8")
    lines = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": str(plan), "content": "# The plan\n"}},
        {"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": f"cat {secret}"}}]}}]
    (path.parent / man["stream"]).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    files, code = m.runops.run_files({"run_id": rid})
    assert code == 200 and [(f["name"], f["kind"]) for f in files["files"]] == [("PLAN.md", "md")]
    got, code = m.runops.run_file({"run_id": rid, "path": str(plan)})
    assert code == 200 and got["text"] == "# The plan\n"
    assert m.runops.run_file({"run_id": rid, "path": str(secret)})[1] == 404
    assert m.runops.run_file_raw({"run_id": rid, "path": str(secret)}) is None
