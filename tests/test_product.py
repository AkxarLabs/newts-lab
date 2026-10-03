"""The dashboard as an end-to-end product (dashboard/labs.py, gates.py, campaign.py, settings.py, instructions.py + the serve.py wiring).

Free-form runs, Gate 3 (typed confirmation → the one /finalize run it allows; chains never finalize),
revoke, the envelope editor, LOOP_BRIEF and campaign signing, revive, research keys, lab settings,
labs (create / open / switch), setup state, and the HTTP protection (session cookie, JSON-only,
Origin: null). Launches only ENQUEUE (the scheduler thread is never started).
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import threading

import pytest

from conftest import REPO, load

FAKE = REPO / "tests" / "fake_claude.py"


@pytest.fixture
def m(hub, monkeypatch, tmp_path):
    (hub.lab / "config.yaml").write_text(
        'lab:\n  projects_root: "../projects"\n'
        "compute:\n  max_concurrent_runs: 1\n"
        "dashboard:\n  port: 8787\n"
        "agents:\n  programmatic:\n    enabled: true\n    backend: claude\n    max_depth: 1\n"
        "    backends:\n      claude:\n"
        f"        command: {json.dumps([sys.executable, str(FAKE)])}\n", encoding="utf-8")
    (hub.root / "templates" / "loop").mkdir(parents=True)
    shutil.copy(REPO / "templates" / "loop" / "CAMPAIGN.md", hub.root / "templates" / "loop")
    monkeypatch.setenv("NEWTS_HOME", str(tmp_path / "home"))
    monkeypatch.syspath_prepend(str(REPO / "dashboard"))
    mod = load("dashboard/serve")
    monkeypatch.setattr(mod.ctx, "HUB", hub.root)
    monkeypatch.setattr(mod.ctx, "LAB", hub.lab)
    return mod


def _pi(hub):
    f = hub.lab / ".bus" / "pi-actions.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


def _manifest(m, hub, rid):
    return m.executor.find_run(m.executor.Lab(hub.root), rid)[3]


# ── free-form runs ────────────────────────────────────────────────────────────

def test_free_form_run(m, hub):
    out, code = m.runops.launch_run({"prompt": "Summarize the open questions\nand suggest two ideas.", "confirm": True})
    assert code == 200, out
    man = _manifest(m, hub, out["run_id"])
    assert man["skill"] == "ask" and man["kind"] == "ask" and man["command"] is None
    assert man["label"].startswith("Summarize the open questions")
    rd = hub.lab / ".bus" / "agents" / f"{out['run_id']}.d"
    assert (rd / "prompt.md").read_text(encoding="utf-8").startswith("Summarize")
    assert "PI's own instruction" in (rd / "preamble.md").read_text(encoding="utf-8")
    assert _pi(hub)[-1]["prompt"].startswith("Summarize")
    assert m.runops.launch_run({"prompt": "   ", "confirm": True})[1] == 400
    assert m.runops.launch_run({"prompt": "x" * 9000, "confirm": True})[1] == 400
    assert m.runops.launch_run({"prompt": "go", "chain": "loop", "confirm": True})[1] == 400


def test_free_form_run_inside_a_project(m, hub):
    hub.add_registry_row("idea-p", state="active")
    pdir = hub.make_project("idea-p")
    out, code = m.runops.launch_run({"prompt": "check the last pilot", "target": "idea-p", "confirm": True})
    assert code == 200
    assert _manifest(m, hub, out["run_id"])["cwd"] == str(pdir)


# ── Gate 3 ────────────────────────────────────────────────────────────────────

def _ready_paper(hub, slug="idea-g"):
    hub.add_registry_row(slug, state="internal-review")
    paper = hub.root / "studies" / slug / "paper"
    (paper / "reviews").mkdir(parents=True)
    (paper / "reviews" / "meta-review.md").write_text("# Meta\n\n## Decision\n\nAccept.\n", encoding="utf-8")
    (paper / "main.pdf").write_bytes(b"%PDF-1.4 fake")
    return paper


def test_finalize_never_launches_without_the_signature(m, hub):
    _ready_paper(hub)
    out, code = m.runops.launch_run({"skill": "finalize", "target": "idea-g", "confirm": True})
    assert code == 400 and "Gate 3" in out["error"]
    out, code = m.runops.launch_run({"skill": "finalize", "target": "idea-g", "confirm": True}, gate3=True)
    assert code == 400 and "not signed" in out["error"]


def test_gate3_sign_then_finalize(m, hub):
    paper = _ready_paper(hub)
    r = m.gates.gate3_readiness("idea-g")
    assert r["can_sign"] and all(c["ok"] for c in r["checks"] if c["id"] in ("state", "meta", "pdf"))
    out, code = m.gates.gate3_sign({"idea": "idea-g", "confirm": True, "typed": "idea-x"})
    assert code == 400 and "type the study name" in out["error"]
    out, code = m.gates.gate3_sign({"idea": "idea-g", "confirm": True, "typed": "idea-g", "launch": True})
    assert code == 200, out
    note = (paper / "gate3-approval.md").read_text(encoding="utf-8")
    assert "signed_via: dashboard:" in note and "Gate 3 approved" in note and "sha256" in note
    man = _manifest(m, hub, out["launch"]["run_id"])
    assert man["skill"] == "finalize" and man["gate3_signed"] is True
    assert "this run IS the finalization" in (hub.lab / ".bus" / "agents" / f"{man['run_id']}.d" / "preamble.md").read_text(encoding="utf-8")
    assert _pi(hub)[-2]["gate"] == 3
    assert m.gates.gate3_sign({"idea": "idea-g", "confirm": True, "typed": "idea-g"})[1] == 400   # once
    # revoke (not yet final) removes the note
    assert m.gates.gate_revoke({"idea": "idea-g", "what": "gate3", "confirm": True})[1] == 200
    assert not (paper / "gate3-approval.md").exists()


def test_gate3_refuses_before_internal_review(m, hub):
    hub.add_registry_row("idea-w", state="writing")
    out, code = m.gates.gate3_sign({"idea": "idea-w", "confirm": True, "typed": "idea-w"})
    assert code == 400 and "not ready" in out["error"]


def test_chains_never_reach_finalize(m):
    from executor.scheduler import parse_next   # noqa: E402 — the executor on sys.path via sources
    assert parse_next("/finalize idea-g") is None
    assert parse_next("/ask do anything") is None


# ── Gate 1 with the envelope, revoke ──────────────────────────────────────────

def test_gate1_with_envelope_marker_and_revoke(m, hub):
    hub.add_registry_row("idea-1", state="proposal")
    (hub.root / "studies" / "idea-1").mkdir(parents=True)
    prop = hub.root / "studies" / "idea-1" / "proposal.md"
    prop.write_text("# P\n", encoding="utf-8")
    assert m.gates.approve_gate("idea-1", 1, envelope=True)["ok"]
    assert "· envelope approved -->" in prop.read_text(encoding="utf-8")
    out, code = m.gates.gate_revoke({"idea": "idea-1", "what": "gate1", "confirm": True})
    assert code == 200 and "Gate 1 approved" not in prop.read_text(encoding="utf-8")


# ── envelope editor ───────────────────────────────────────────────────────────

def test_envelope_edit_sign_and_resign(m, hub):
    hub.add_registry_row("idea-e", state="active")
    pdir = hub.make_project("idea-e")
    out, code = m.gates.envelope_set({"idea": "idea-e", "confirm": True, "sign": True,
                                        "values": {"full_runs": 4, "per_run_max_minutes": 90, "total_max_minutes": 360,
                                                   "expires": "2099-01-01"}})
    assert code == 200, out
    env = m.ctx.labfiles.load_yaml(pdir / "control.yaml")["gate2_envelope"]
    assert env["full_runs"] == 4 and env["pi_signed"] is True and str(env["signed_via"]).startswith("dashboard:")
    # changing values without re-signing withdraws the signature
    out, code = m.gates.envelope_set({"idea": "idea-e", "confirm": True, "values": {"full_runs": 8}})
    env = m.ctx.labfiles.load_yaml(pdir / "control.yaml")["gate2_envelope"]
    assert code == 200 and env["full_runs"] == 8 and env["pi_signed"] is False and "withdrawn" in out["note"]
    assert m.gates.envelope_set({"idea": "idea-e", "confirm": True, "values": {"expires": "2001-01-01"}})[1] == 400
    assert m.gates.envelope_set({"idea": "idea-e", "confirm": True, "values": {"full_runs": -1}})[1] == 400


# ── loop brief, campaign ──────────────────────────────────────────────────────

def test_loop_brief_sign(m, hub):
    hub.add_registry_row("idea-l", state="active")
    pdir = hub.make_project("idea-l")
    shutil.copy(REPO / "templates" / "loop" / "LOOP_BRIEF.md", pdir / "LOOP_BRIEF.md")
    out, code = m.gates.loopbrief_sign({"idea": "idea-l", "mode": "explore", "confirm": True})
    assert code == 200, out
    text = (pdir / "LOOP_BRIEF.md").read_text(encoding="utf-8")
    assert "- [x] Authorized as scoped above" in text and "signed_via: dashboard:" in text and "`explore`" in text
    assert m.gates.loopbrief_sign({"idea": "idea-l", "confirm": True})[1] == 400      # already signed
    assert m.gates.gate_revoke({"idea": "idea-l", "what": "loop", "confirm": True})[1] == 200


def test_campaign_form_writes_a_signed_brief_the_guard_accepts(m, hub, monkeypatch):
    out, code = m.campaign.campaign_create({"confirm": True, "fields": {
        "direction": "sparse routing for small MoEs", "ideas": 2, "parallel": 1, "compute_total": "8 GPU-h",
        "full_runs": 3, "full_minutes": 60, "wall_clock": "tonight, 8h", "mode": "execute"}})
    assert code == 200, out
    f = hub.root / out["file"]
    text = f.read_text(encoding="utf-8")
    assert "sparse routing for small MoEs" in text and "carry up to 2 ideas" in text and "___" not in text.split("## Campaign Log")[0]
    g = load("signature_guard")
    monkeypatch.setattr(g, "HUB", hub.root.resolve())
    assert g._campaign_signed(f.name)
    spec_out, code = m.runops.launch_run({"skill": "autopilot", "args": out["file"], "confirm": True})
    assert code == 200, spec_out


# ── revive ────────────────────────────────────────────────────────────────────

def test_revive(m, hub):
    hub.add_registry_row("idea-k", state="killed")
    (hub.root / "studies" / "idea-k").mkdir(parents=True)
    (hub.root / "studies" / "idea-k" / "IDEA.md").write_text("---\nstate: killed\n---\n# Idea\n", encoding="utf-8")
    assert m.gates.revive({"idea": "idea-k", "confirm": True})[1] == 400                 # a reason is required
    out, code = m.gates.revive({"idea": "idea-k", "confirm": True, "reason": "new data", "to": "triaged"})
    assert code == 200
    row = next(r for r in m.sources.parse_registry() if r["id"] == "idea-k")
    assert row["state"] == "triaged"
    assert "state: triaged" in (hub.root / "studies" / "idea-k" / "IDEA.md").read_text(encoding="utf-8")


# ── keys, settings, setup, docs ───────────────────────────────────────────────

def test_keys_are_stored_but_never_read_back(m, hub):
    assert m.settings.keys_set({"key": "S2_API_KEY", "value": "secret-123"})[1] == 200
    assert "S2_API_KEY=secret-123" in (hub.lab / ".env.local").read_text(encoding="utf-8")
    st, _ = m.settings.keys_status()
    assert "secret-123" not in json.dumps(st) and next(k for k in st["keys"] if k["key"] == "S2_API_KEY")["set"]
    assert "lab/.env.local" in (hub.root / ".gitignore").read_text(encoding="utf-8")
    assert "secret-123" not in json.dumps(_pi(hub))
    assert m.settings.keys_set({"key": "NEWTS_RUN_ID", "value": "x"})[1] == 400
    sup = load("tools/executor/supervise.py") if False else None   # noqa: F841 — _env_local is tested below
    from executor.supervise import _env_local
    assert _env_local(m.executor.Lab(hub.root))["S2_API_KEY"] == "secret-123"


def test_lab_settings_and_setup(m, hub):
    out, code = m.settings.lab_config_set({"confirm": True, "changes": {"name": "Moe lab", "max_concurrent_runs": 2,
                                                                        "venue": "neurips"}})
    assert code == 200, out
    cfg = m.ctx.labfiles.load_yaml(hub.lab / "config.yaml")
    assert cfg["lab"]["name"] == "Moe lab" and cfg["compute"]["max_concurrent_runs"] == 2 and cfg["writing"]["venue"] == "neurips"
    assert m.settings.lab_config_set({"confirm": True, "changes": {"agents.x": 1}})[1] == 400
    assert not m.settings.setup_status()["completed"]
    assert m.settings.setup_complete({})[1] == 200
    assert m.settings.setup_status()["completed"]
    assert m.settings.doc_save({"doc": "system", "text": "# This machine\n1 GPU\n"})[1] == 200
    assert m.settings.doc_get("system")[0]["text"].startswith("# This machine")
    assert m.settings.doc_save({"doc": "../../etc", "text": "x"})[1] == 400


def test_programmatic_switch_inserts_a_missing_key(m, hub):
    (hub.lab / "config.yaml").write_text("agents:\n  programmatic:\n    backend: claude\n", encoding="utf-8")
    out, code = m.runops.set_programmatic({"enabled": True, "confirm": True})
    assert code == 200 and m.ctx.labfiles.load_yaml(hub.lab / "config.yaml")["agents"]["programmatic"]["enabled"] is True


# ── labs ──────────────────────────────────────────────────────────────────────

def test_create_open_and_switch_labs(m, hub, tmp_path):
    dest = tmp_path / "labs" / "second"
    out, code = m.labs.labs_create({"confirm": True, "name": "Second lab", "path": str(dest), "open": False})
    assert code == 200, out
    assert (dest / "lab" / "config.yaml").exists() and not (dest / ".github").exists()
    assert m.ctx.labfiles.load_yaml(dest / "lab" / "config.yaml")["lab"]["name"] == "Second lab"
    listed, _ = m.labs.labs_list()
    assert any(l["path"] == str(dest) for l in listed["labs"])
    out, code = m.labs.labs_open({"path": str(dest)})
    assert code == 200 and m.ctx.HUB == dest.resolve()
    assert m.labs.labs_open({"path": str(tmp_path)})[1] == 400                     # not a lab
    assert m.labs.labs_create({"confirm": True, "path": str(dest)})[1] == 400      # not empty


# ── HTTP protection ───────────────────────────────────────────────────────────

@pytest.fixture
def server(m):
    srv = m.LabServer(("127.0.0.1", 0), m.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def _req(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


def test_session_cookie_and_json_only(server):
    port = server
    assert _req(port, "GET", "/api/state")[0] == 403                                       # no session
    st, hd, _ = _req(port, "GET", "/")
    assert st == 200
    cookie = hd.get("Set-Cookie", "").split(";", 1)[0]
    assert cookie.startswith(f"newts_{port}=") and "SameSite=Strict" in hd["Set-Cookie"] and "HttpOnly" in hd["Set-Cookie"]
    assert _req(port, "GET", "/api/state", headers={"Cookie": cookie})[0] == 200
    assert _req(port, "GET", "/api/ping")[0] == 200                                        # the launcher's probe
    body = json.dumps({"target": "hub", "text": "hi"})
    assert _req(port, "POST", "/api/directive", body, {"Cookie": cookie, "Content-Type": "text/plain"})[0] == 415
    assert _req(port, "POST", "/api/directive", body, {"Content-Type": "application/json"})[0] == 403
    assert _req(port, "POST", "/api/directive", body, {"Cookie": cookie, "Content-Type": "application/json",
                                                       "Origin": "null"})[0] == 403
    assert _req(port, "POST", "/api/directive", body, {"Cookie": cookie, "Content-Type": "application/json"})[0] == 200


# ── terminal (sign-in / install) — fixed commands only ────────────────────────

def test_terminal_opens_only_fixed_commands(m, hub, monkeypatch):
    sys.path.insert(0, str(REPO / "tools"))
    import terminal
    calls = []
    monkeypatch.setattr(terminal.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(terminal.shutil, "which", lambda exe: exe if exe == "xterm" else None)
    out, code = m.labs.terminal_open({"purpose": "login", "backend": "claude"})
    assert code == 200, out
    argv = calls[-1][0][0]
    flat = " ".join(map(str, argv))
    assert "auth login" in flat and "fake_claude.py" in flat          # the configured CLI, its own login
    assert m.labs.terminal_open({"purpose": "login", "backend": "rm -rf /"})[1] == 400
    assert m.labs.terminal_open({"purpose": "exec", "backend": "claude"})[1] == 400
    out, code = m.labs.terminal_open({"purpose": "install", "backend": "codex"})
    assert code == 200 and "@openai/codex" in " ".join(map(str, calls[-1][0][0]))
    assert _pi(hub)[-1]["action"] == "terminal.install"


# ── System & compute ──────────────────────────────────────────────────────────

def test_system_probe_and_scheduler_block(m, hub):
    out, code = m.settings.system_info({"fresh": "1"})
    assert code == 200 and out["facts"]["cpus"] and "suggested_scheduler" in out["facts"]
    assert out["scheduler"]["kind"] == "local"
    sc = {"kind": "slurm", "stages": ["PILOT", "FULL"], "slurm": {"partition": "gpu", "gpus_per_run": 2, "mem": "32G",
                                                                   "setup": ["module load cuda/12.4"], "extra_args": ["--exclusive"]}}
    out, code = m.settings.system_scheduler_set({"scheduler": sc, "confirm": True})
    assert code == 200, out
    cfg = m.ctx.labfiles.load_yaml(hub.lab / "config.yaml")
    got = cfg["compute"]["scheduler"]
    assert got["kind"] == "slurm" and got["slurm"]["gpus_per_run"] == 2 and got["slurm"]["setup"] == ["module load cuda/12.4"]
    assert cfg["compute"]["max_concurrent_runs"] == 1 and cfg["agents"]["programmatic"]["enabled"] is True   # the rest kept
    # a second save replaces the block in place (no duplicate key)
    assert m.settings.system_scheduler_set({"scheduler": {"kind": "local"}, "confirm": True})[1] == 200
    text = (hub.lab / "config.yaml").read_text(encoding="utf-8")
    assert text.count("scheduler:") == 1 and m.ctx.labfiles.load_yaml(hub.lab / "config.yaml")["compute"]["scheduler"]["kind"] == "local"
    bad = [{"kind": "pbs"}, {"kind": "slurm", "slurm": {"partition": "gpu; rm -rf /"}},
           {"kind": "slurm", "slurm": {"extra_args": ["exclusive"]}}, {"kind": "custom", "custom": {"submit": "qsub"}}]
    for b in bad:
        assert m.settings.system_scheduler_set({"scheduler": b, "confirm": True})[1] == 400, b


# ── the workflow: the PI's instructions per procedure / stage / role ──────────

def _wf_hub(hub):
    import shutil
    (hub.root / "workflow").mkdir(exist_ok=True)
    shutil.copy(REPO / "workflow" / "stages.yaml", hub.root / "workflow" / "stages.yaml")
    d = hub.root / ".claude" / "skills" / "propose"
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text("---\nname: propose\n---\n# Propose\n0. brief\n", encoding="utf-8")
    (d / "METHOD.md").write_text("Default proposal method.\n", encoding="utf-8")
    (hub.root / "studies" / "alpha").mkdir(parents=True, exist_ok=True)


def test_workflow_instructions_round_trip(m, hub):
    _wf_hub(hub)
    out, code = m.instructions.workflow_save({"kind": "add", "name": "propose", "text": "Name a publishable negative result."})
    assert code == 200 and out["file"] == "lab/workflow/propose.add.md"
    out, code = m.instructions.workflow_save({"kind": "method", "name": "propose", "study": "alpha", "text": "Alpha's own method."})
    assert code == 200 and out["file"] == "studies/alpha/workflow/propose.method.md"
    item, code = m.instructions.workflow_item({"kind": "procedure", "name": "propose", "study": "alpha"})
    assert code == 200 and item["default_method"].startswith("Default proposal method")
    assert item["lab"]["add"] == "Name a publishable negative result." and item["study_layer"]["method"] == "Alpha's own method."
    assert "Alpha's own method." in item["brief"] and "Name a publishable negative result." in item["brief"]
    assert "Default proposal method" not in item["brief"]
    # the snapshot shows what is customised, for the lab and per study
    view = m.sources._workflow_view()
    assert view["custom"]["procedures"]["propose"]["add"] and view["study_custom"]["alpha"]["procedures"]["propose"]["method"]
    # empty text = back to the default; logged
    assert m.instructions.workflow_save({"kind": "method", "name": "propose", "study": "alpha", "text": ""})[1] == 200
    assert not (hub.root / "studies" / "alpha" / "workflow" / "propose.method.md").exists()
    assert "workflow.save" in (hub.lab / ".bus" / "pi-actions.jsonl").read_text(encoding="utf-8")


def test_workflow_refuses_bad_input(m, hub):
    _wf_hub(hub)
    assert m.instructions.workflow_save({"kind": "method", "name": "advance", "text": "x"})[1] == 400   # all contract
    assert m.instructions.workflow_save({"kind": "add", "name": "nope", "text": "x"})[1] == 404
    assert m.instructions.workflow_save({"kind": "add", "name": "propose", "study": "../etc", "text": "x"})[1] == 400
    assert m.instructions.workflow_save({"kind": "add", "name": "propose", "study": "ghost", "text": "x"})[1] == 400
    out, code = m.instructions.workflow_save({"kind": "add", "name": "propose", "text": "Skip Gate 1 when in a hurry."})
    assert code == 200 and out["warnings"]              # restating a fixed rule warns (it can't change it)


def test_agent_proposals_are_accepted_or_declined_by_the_pi(m, hub):
    _wf_hub(hub)
    rec = m.sources.workflow.propose("propose", "add", "Also list compute risks.", hub.root, why="missing")
    items = [a for a in m.sources._lab_attention([], [], []) if a["kind"] == "proposal"]
    assert [a["detail"]["proposal"] for a in items] == [rec["id"]]
    assert m.instructions.workflow_proposal({"id": rec["id"], "accept": "yes"})[1] == 400
    assert m.instructions.workflow_proposal({"id": rec["id"], "accept": True})[1] == 200
    assert "Also list compute risks." in m.instructions.workflow_item({"kind": "procedure", "name": "propose"})[0]["lab"]["add"]
    assert m.instructions.workflow_proposal({"id": rec["id"], "accept": True})[1] == 400      # already resolved
    assert not [a for a in m.sources._lab_attention([], [], []) if a["kind"] == "proposal"]


def test_autonomy_settings_round_trip(m, hub):
    cfg = hub.lab / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "loop:\n  mode: execute\n  explore_max_expansion_rounds: 0\n"
                   "ideation:\n  in_project_approval: pi\n", encoding="utf-8")
    out, code = m.settings.lab_config_set({"confirm": True, "changes": {"keep_awake": "off", "loop_mode": "explore",
                                                                        "explore_rounds": 2, "in_project_approval": "campaign_auto"}})
    assert code == 200, out
    got = m.settings.lab_config_get()[0]["config"]
    assert (got["keep_awake"], got["loop_mode"], got["explore_rounds"], got["in_project_approval"]) == ("off", "explore", 2, "campaign_auto")
    assert m.settings.lab_config_set({"confirm": True, "changes": {"keep_awake": "auto"}})[1] == 200
    assert m.settings.lab_config_get()[0]["config"]["keep_awake"] == "auto"
    assert m.settings.lab_config_set({"confirm": True, "changes": {"loop_mode": "yolo"}})[1] == 400


# ── phone notifications (Settings → Notifications) ─────────────────────────────

def test_notifications_are_stored_outside_config_and_masked(m, hub, inbox):
    settings = m.settings
    out, code = settings.notify_set({"confirm": True, "ntfy": "not a url"})
    assert code == 400
    base, got = inbox
    out, code = settings.notify_set({"confirm": True, "ntfy": f"{base}/secret-topic-123", "link": "http://pc:8787"})
    assert code == 200, out
    st, _ = settings.notify_status()
    assert "secret-topic" not in st["ntfy"] and st["link"] == "http://pc:8787" and not st["webhook"]
    assert "secret-topic" not in (hub.lab / "config.yaml").read_text(encoding="utf-8")
    assert [k["key"] for k in settings.keys_status()[0]["keys"] if k["key"].startswith("NEWTS_")] == []
    out, code = settings.notify_test({})
    assert code == 200 and got and got[0]["path"] == "/secret-topic-123"


def test_read_side_slugs_never_step_out_of_a_folder(m):
    assert m.ctx.slug("..") == "" and m.ctx.slug("../x") == "" and m.ctx.slug(".hidden") == "" and m.ctx.slug("a..b") == ""
    assert m.ctx.slug("idea-1") == "idea-1" and m.ctx.slug("my idea!") == "myidea"
