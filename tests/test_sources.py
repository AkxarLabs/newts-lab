"""Tests for dashboard/sources.py — the read-only world model the dashboard renders."""

from __future__ import annotations

import json

from conftest import load


def _mod(hub, monkeypatch):
    m = load("dashboard/sources")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def test_parse_registry_reads_rows(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", title="Demo", state="active", project="../projects/demo")
    rows = m.parse_registry()
    assert len(rows) == 1
    assert rows[0]["id"] == "demo"
    assert rows[0]["state"] == "active"
    assert rows[0]["title"] == "Demo"


def test_parse_registry_skips_header_and_divider(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # empty registry (header only) -> no rows
    assert m.parse_registry() == []


def test_snapshot_cold_when_registry_empty(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    snap = m.snapshot()
    assert snap["cold"] is True
    # documented keys present
    for key in ("items", "events", "workers", "slots", "directives", "gates_waiting", "cold"):
        assert key in snap


def test_snapshot_not_cold_with_a_row(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    snap = m.snapshot()
    assert snap["cold"] is False
    assert len(snap["items"]) == 1
    assert snap["items"][0]["id"] == "demo"
    assert snap["items"][0]["has_project"] is True


def test_snapshot_gates_waiting_counts_gate_next_action(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", project="-", next="awaiting PI Gate 1")
    snap = m.snapshot()
    assert snap["gates_waiting"] == 1


def test_project_path_prefers_explicit_column(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", in_root=False)
    p = m._project_path({"id": "demo", "project": str(proj)})
    assert p == proj.resolve()


def test_project_path_falls_back_to_projects_root(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")  # under projects_root
    p = m._project_path({"id": "demo", "project": "-"})
    assert p == proj.resolve()


def test_project_path_unreachable_returns_none(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # no such project anywhere
    assert m._project_path({"id": "ghost", "project": "-"}) is None


# ── workers feed ──────────────────────────────────────────────────────────────

def _worker_log(bus_dir, name, lines):
    wdir = bus_dir / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    with (wdir / name).open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def test_workers_marks_done(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    _worker_log(bus, "w1.jsonl", [
        {"ts": "2026-06-19T10:00:00", "role": "experiment-runner", "event": "start"},
        {"ts": "2026-06-19T10:01:00", "event": "action", "tool": "Read", "summary": "Read: x",
         "kind": "read"},
        {"ts": "2026-06-19T10:02:00", "event": "stop"},
    ])
    workers = m._workers(bus, None)
    assert len(workers) == 1
    w = workers[0]
    assert w["role"] == "experiment-runner"
    assert w["status"] == "done"  # saw a stop event
    assert w["n_actions"] == 1


def test_workers_marks_working(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    # fresh activity, no stop -> working (file mtime is now)
    _worker_log(bus, "w2.jsonl", [
        {"ts": "2026-06-19T10:00:00", "role": "orchestrator", "event": "start"},
        {"ts": "2026-06-19T10:01:00", "event": "action", "tool": "Edit", "summary": "Edit: y",
         "kind": "edit"},
    ])
    workers = m._workers(bus, None)
    assert workers[0]["status"] == "working"


# ── editor deep-links + paper status ───────────────────────────────────────────

def test_snapshot_includes_editor_scheme(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    # the fixture config has no `editor` key -> the documented default
    assert m.snapshot()["editor"] == "vscode"


def test_editor_scheme_reads_config(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    (hub.lab / "config.yaml").write_text("dashboard:\n  editor: cursor\n", encoding="utf-8")
    assert m.editor_scheme() == "cursor"


def test_paper_status_none_without_pdf(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m._paper_status("demo") is None


def test_paper_status_reports_pdf_and_tex(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    pdir = hub.root / "studies" / "demo" / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "main.pdf").write_bytes(b"%PDF-1.5")
    (pdir / "main.tex").write_text("x", encoding="utf-8")
    st = m._paper_status("demo")
    assert st and st["pdf"] is True and isinstance(st["mtime"], int)
    assert st["tex"].endswith("main.tex")


def test_snapshot_item_carries_paper(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    pdir = hub.root / "studies" / "demo" / "paper"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "main.pdf").write_bytes(b"%PDF")
    it = m.snapshot()["items"][0]
    assert it["paper"] and it["paper"]["pdf"] is True


def test_claims_count(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m._claims_count("demo") == 0                  # no file
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n  - id: C002\n", encoding="utf-8")
    assert m._claims_count("demo") == 2


def test_claims_count_counts_only_dict_items(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    # a bare-string list item must NOT be counted — parity with serve.claims_map's dict filter,
    # so the "claims (N)" button never disagrees with the rendered rows
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n  - just a string\n  - id: C002\n", encoding="utf-8")
    assert m._claims_count("demo") == 2


def test_snapshot_item_carries_claims_count(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    paper = hub.root / "studies" / "demo" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    (paper / "claims.yaml").write_text("claims:\n  - id: C001\n", encoding="utf-8")
    assert m.snapshot()["items"][0]["claims"] == 1


# ── H2: dirty (non-UTF-8) bytes must never crash the snapshot ──────────────────

def test_read_text_tolerates_non_utf8_bytes(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    f = hub.lab / "dirty.txt"
    f.write_bytes(b"ok \xff\xfe not utf8\n")   # invalid UTF-8 — read_text(utf-8-sig) would raise
    assert "not utf8" in m._read_text(f)         # errors='replace' → no UnicodeDecodeError


def test_snapshot_survives_non_utf8_event_line(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    bus = proj / ".bus"
    bus.mkdir(parents=True, exist_ok=True)
    (bus / "events.jsonl").write_bytes(b'{"ts":"2026-06-19T10:00:00","kind":"note","detail":"\xff\xfe"}\n')
    snap = m.snapshot()                          # a cp1252 byte in a tailed file used to 500 the whole snapshot
    assert snap["cold"] is False


# ── M1: gate detection is word-bounded (no phantom gates from "investigate"/"delegate") ──

def test_gate_of_word_bounded(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m._gate_of("awaiting PI Gate 1") == 1
    assert m._gate_of("sign the Gate-2 envelope") == 2
    assert m._gate_of("investigate 3 baselines") is None    # not a gate
    assert m._gate_of("delegate 2 sweeps to runners") is None
    assert m._gate_of("mitigate the risk") is None


def test_gates_waiting_matches_parsed_gate_items(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("a", state="active", project="-", next="investigate 3 leads")   # NOT a gate
    hub.add_registry_row("b", state="proposal", project="-", next="awaiting PI Gate 1")   # a gate
    snap = m.snapshot()
    assert snap["gates_waiting"] == 1                        # badge == "Needs you" panel (items with a gate)
    assert sum(1 for it in snap["items"] if it["gate"]) == 1


# ── L3: stale compute slots are flagged (read-only, never reclaimed here) ──────

def test_slots_flag_stale_by_mtime(hub, monkeypatch):
    import json
    import os
    import time
    m = _mod(hub, monkeypatch)
    sdir = hub.lab / ".slots"
    sdir.mkdir(parents=True, exist_ok=True)
    fresh = sdir / "s-fresh.json"
    fresh.write_text(json.dumps({"project": "demo", "label": "full", "acquired": time.time()}), encoding="utf-8")
    old = sdir / "s-old.json"
    old.write_text(json.dumps({"project": "demo", "label": "sweep", "acquired": time.time()}), encoding="utf-8")
    # config stale_slot_minutes is 360 (6h); backdate the old slot's mtime past it
    past = time.time() - 400 * 60
    os.utime(old, (past, past))
    got = {s["slot_id"]: s for s in m.slots()}
    assert got["s-fresh"]["stale"] is False
    assert got["s-old"]["stale"] is True and got["s-old"]["age_min"] >= 360


# ── envelope accounting (shared source of truth) + M4 authorizes-nothing ───────

def test_envelope_accounting_authorizes_nothing_when_all_caps_zero(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    a = m.envelope_accounting(proj, {"pi_signed": True, "expires": None,
                                     "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0})
    assert a["signed"] is True and a["authorizes"] is False
    assert a["status"] == "authorizes nothing"              # NOT "active ∞" — guard.py refuses these


def test_envelope_accounting_tolerates_non_numeric_caps(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    a = m.envelope_accounting(proj, {"pi_signed": True, "full_runs": "six", "total_max_minutes": "45 min"})
    assert a["full_cap"] == 0 and a["total_cap"] == 0.0     # bad values coerce, never raise


def test_snapshot_item_carries_envelope(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={"pi_signed": True, "expires": "2099-01-01",
                                           "full_runs": 4, "per_run_max_minutes": 30, "total_max_minutes": 120})
    hub.add_registry_row("demo", state="active", project=str(proj))
    it = m.snapshot()["items"][0]
    assert it["envelope"] and it["envelope"]["status"] == "active" and it["envelope"]["full_cap"] == 4


# ── L4: directive terminal acks are sticky (parity with lab_bus.unresolved_directives) ──

def test_directive_threads_terminal_ack_is_sticky(hub, monkeypatch):
    import json
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    bus.mkdir(parents=True, exist_ok=True)
    (bus / "directives.jsonl").write_text(json.dumps({"id": "d-001", "text": "do x"}) + "\n", encoding="utf-8")
    # done THEN a later out-of-order 'seen' must not reopen the directive
    (bus / "events.jsonl").write_text(
        json.dumps({"ts": "2026-06-19T10:00:00", "kind": "directive_done", "data": {"ref": "d-001"}}) + "\n"
        + json.dumps({"ts": "2026-06-19T10:05:00", "kind": "directive_seen", "data": {"ref": "d-001"}}) + "\n",
        encoding="utf-8")
    th = next(t for t in m._directive_threads(bus) if t["id"] == "d-001")
    assert th["state"] == "done"


def test_directive_threads_carry_record_target(hub, monkeypatch):
    import json
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    bus.mkdir(parents=True, exist_ok=True)
    # a directive aimed at 'spark-1' that landed on the hub bus (pre-spawn) keeps its target
    (bus / "directives.jsonl").write_text(json.dumps({"id": "d-001", "text": "park", "target": "spark-1"}) + "\n", encoding="utf-8")
    th = m._directive_threads(bus)[0]
    assert th["target"] == "spark-1"


# ── escalation lifecycle: an escalation_resolved event clears it ───────────────

def test_escalations_unresolved_and_resolved(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    evs = [
        {"ts": "2026-06-19T10:00:00", "source": "p1", "kind": "escalation", "detail": "need env bump", "data": {"id": "e-aaa"}},
        {"ts": "2026-06-19T10:01:00", "source": "p2", "kind": "escalation", "detail": "blocked", "data": {"id": "e-bbb"}},
        {"ts": "2026-06-19T10:02:00", "source": "p1", "kind": "escalation_resolved", "data": {"ref": "e-aaa"}},
    ]
    out = m._escalations(evs)
    ids = {e["id"] for e in out}
    assert ids == {"e-bbb"}                               # e-aaa resolved → dropped


def test_snapshot_includes_escalations_and_notebook(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    snap = m.snapshot()
    assert "escalations" in snap and isinstance(snap["escalations"], list)
    assert "notebook" in snap


# ── hardening from the adversarial verification pass ──────────────────────────

def test_load_yaml_non_mapping_returns_empty_dict(hub, monkeypatch):
    # a valid-YAML but non-mapping file must not make _load_yaml(...).get(...) raise AttributeError
    m = _mod(hub, monkeypatch)
    for content in ("42\n", "- a\n- b\n", "just a bare string\n"):
        f = hub.lab / "x.yaml"
        f.write_text(content, encoding="utf-8")
        assert m._load_yaml(f) == {}


def test_snapshot_survives_non_mapping_control_yaml(hub, monkeypatch):
    # a project whose control.yaml is valid YAML but a scalar/list must not blank the whole snapshot
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    (proj / "control.yaml").write_text("42\n", encoding="utf-8")
    hub.add_registry_row("demo", state="active", project=str(proj))
    snap = m.snapshot()
    assert snap["cold"] is False and snap["items"][0]["envelope"] is None


def test_notebook_age_from_dated_filename_not_mtime(hub, monkeypatch):
    # age comes from the ISO-dated filename (git-stable), not st_mtime which git ops reset
    import os
    import time
    m = _mod(hub, monkeypatch)
    old = hub.lab / "notebook" / "2020-01-01-ancient.md"
    old.write_text("# old\n", encoding="utf-8")
    os.utime(old, None)   # mtime = now, but the filename says 2020 → should read as very old
    nb = m._notebook_status()
    assert nb["latest"] == "2020-01-01-ancient.md"
    assert nb["age_hours"] > 24 * 365 * 3   # >3 years by the dated name, regardless of fresh mtime


def test_notebook_status_picks_latest_dated_and_ignores_readme(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    for name in ("2026-06-01-a.md", "2026-07-02-b.md", "README.md"):
        (hub.lab / "notebook" / name).write_text("x\n", encoding="utf-8")
    assert m._notebook_status()["latest"] == "2026-07-02-b.md"


# ── gate detection: registry-text is the signal; on-disk signature is the 'signed, waiting' state ─

def test_registry_text_gate_detected(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", next="awaiting PI Gate 1")
    it = m.snapshot()["items"][0]
    assert it["gate"] == 1 and it["gate_signed"] is False


def test_no_phantom_gate_from_plain_next_action(hub, monkeypatch):
    # a plain slash-command / next-action with no gate word yields no gate (no phantom Approve card)
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", next="run pilot exp-003")
    hub.add_registry_row("two", state="active", next="/spawn-project")
    items = {it["id"]: it for it in m.snapshot()["items"]}
    assert items["demo"]["gate"] is None and items["two"]["gate"] is None


def test_gate1_signed_state_and_badge_exclusion(hub, monkeypatch):
    # once the dashboard marker is on the proposal, the card flips to 'signed — waiting for the
    # agent' and the badge stops counting it (the PI already acted; the wait is the agent's).
    # Detection still rides on the registry text, which stays 'Gate 1' until the agent transitions.
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", next="awaiting PI Gate 1")
    prop = hub.root / "studies" / "demo" / "proposal.md"
    prop.parent.mkdir(parents=True, exist_ok=True)
    prop.write_text("# P\n", encoding="utf-8")
    snap = m.snapshot()
    assert snap["items"][0]["gate_signed"] is False and snap["gates_waiting"] == 1
    prop.write_text(f"# P\n\n<!-- {m.GATE1_MARK} 2026-07-04 -->\n", encoding="utf-8")
    snap = m.snapshot()
    assert snap["items"][0]["gate_signed"] is True and snap["gates_waiting"] == 0


def test_gate2_signed_state_from_control_yaml(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.make_project("demo", gate2={"pi_signed": True, "signed_via": "dashboard:x",
                                    "expires": None, "full_runs": 2,
                                    "per_run_max_minutes": 30, "total_max_minutes": 60})
    hub.add_registry_row("demo", state="active", project="../projects/demo", next="awaiting Gate 2 envelope")
    it = m.snapshot()["items"][0]
    assert it["gate"] == 2 and it["gate_signed"] is True


def test_gate2_expired_signed_envelope_is_not_signed_state(hub, monkeypatch):
    # an EXPIRED but pi_signed envelope must NOT read as 'signed — waiting for the agent' — the
    # PI has to re-authorize (guard.py full-run + approve_gate both refuse it), so it stays an
    # actionable gate the badge counts.
    m = _mod(hub, monkeypatch)
    hub.make_project("demo", gate2={"pi_signed": True, "signed_via": "dashboard:x",
                                    "expires": "2026-01-01", "full_runs": 2,
                                    "per_run_max_minutes": 30, "total_max_minutes": 60})
    hub.add_registry_row("demo", state="active", project="../projects/demo", next="awaiting Gate 2 envelope")
    snap = m.snapshot()
    assert snap["items"][0]["gate"] == 2 and snap["items"][0]["gate_signed"] is False
    assert snap["gates_waiting"] == 1


# ── subagent visibility: tree, liveness, results, attribution, run join ──────────

def _wlog(bus, wid, lines):
    import time as _t
    wdir = bus / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    ts = _t.strftime("%Y-%m-%dT%H:%M:%S")
    (wdir / f"{wid}.jsonl").write_text(
        "\n".join(json.dumps({"ts": ts, "worker_id": wid, **ln}) for ln in lines) + "\n", encoding="utf-8")


def test_worker_tree_links_spawn_to_child_with_label_and_result(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    _wlog(bus, "SESS", [
        {"role": "orchestrator", "event": "start", "session_id": "SESS"},
        {"role": "orchestrator", "event": "spawn", "session_id": "SESS", "tool_use_id": "tuA",
         "spawns": "ideation-critic", "summary": "Agent: ideation-critic: Novelty skeptic: sparse attn"},
        {"role": "orchestrator", "event": "return", "session_id": "SESS", "tool_use_id": "tuA",
         "result": "verdict: bruised — closest work is X"},
    ])
    _wlog(bus, "agent-1", [
        {"role": "ideation-critic", "event": "start", "session_id": "SESS"},
        {"role": "ideation-critic", "event": "action", "session_id": "SESS", "tool": "WebSearch", "summary": "q"},
    ])
    ws = {w["worker_id"]: w for w in m._link_workers(m._workers(bus, None))}
    child, parent = ws["agent-1"], ws["SESS"]
    assert child["is_subagent"] and child["parent"] == "SESS" and parent["children"] == ["agent-1"]
    assert child["label"] == "Novelty skeptic: sparse attn" and child["spawn_id"] == "tuA"
    assert child["result"].startswith("verdict: bruised")          # from the parent's return line
    assert parent["n_actions"] == 1                                 # the Post(Agent) 'return' isn't double-counted


def test_worker_inside_long_tool_stays_working(hub, monkeypatch):
    import os
    import time as _t
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    _wlog(bus, "agent-2", [
        {"role": "experiment-runner", "event": "start", "session_id": "S"},
        {"role": "experiment-runner", "event": "begin", "session_id": "S", "tool": "Bash",
         "summary": "Bash: uv run scripts/run.py", "kind": "run"},
    ])
    old = _t.time() - 1500                                          # 25 min into a PILOT run
    os.utime(bus / "workers" / "agent-2.jsonl", (old, old))
    w = m._workers(bus, None)[0]
    assert w["status"] == "working" and w["in_tool"]["tool"] == "Bash"   # not idle, not dropped


def test_done_worker_lingers_with_result_and_resume_reopens(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    bus = hub.lab / ".bus"
    _wlog(bus, "agent-3", [{"role": "overseer", "event": "start", "session_id": "S"},
                           {"role": "overseer", "event": "stop", "session_id": "S", "result": "SUPPORTED"}])
    w = m._workers(bus, None)[0]
    assert w["status"] == "done" and w["result"] == "SUPPORTED"
    _wlog(bus, "S", [{"event": "start", "session_id": "S"}, {"event": "stop", "session_id": "S"},
                     {"event": "start", "session_id": "S", "source": "resume"}])
    w = next(x for x in m._workers(bus, None) if x["worker_id"] == "S")
    assert w["status"] != "done"                                    # a resumed session is live again


def test_hub_worker_promoted_to_project_from_worktree(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    hub.add_registry_row("demo", state="active", project=str(proj))
    _wlog(hub.lab / ".bus", "agent-4", [
        {"role": "experiment-runner", "event": "action", "session_id": "S", "project": "demo",
         "variant": "exp-004", "summary": "Bash: uv run x"}])
    snap = m.snapshot()
    w = next(x for x in snap["workers"] if x["worker_id"] == "agent-4")
    assert w["project"] == "demo" and w["variant"] == "exp-004"
    assert next(it for it in snap["items"] if it["id"] == "demo")["n_workers"] == 1


def test_snapshot_joins_headless_run_to_its_session_worker(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    adir = hub.lab / ".bus" / "agents"
    adir.mkdir(parents=True)
    (adir / "hub-propose-x-1.json").write_text(json.dumps({
        "schema": 2, "run_id": "hub-propose-x-1", "agent_id": "hub-propose-x-1", "status": "running",
        "session_id": "SID9", "command": "/propose x", "level": "hub", "target": "x", "backend": "claude",
        "started": "2026-01-01T00:00:00", "attempts": [{"started": "2026-01-01T00:00:00"}]}), encoding="utf-8")
    _wlog(hub.lab / ".bus", "SID9", [{"event": "start", "session_id": "SID9"}])
    snap = m.snapshot()
    assert snap["runs"][0]["run_id"] == "hub-propose-x-1" and snap["hub_agents"]
    w = next(x for x in snap["workers"] if x["worker_id"] == "SID9")
    assert w["run_id"] == "hub-propose-x-1" and w["label"] == "/propose x"
    for key in ("runs", "attention", "executor", "skills"):
        assert key in snap
    assert snap["executor"]["available"] is True and "propose" in snap["skills"]


def test_attention_includes_gates_and_escalations(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("idea-g", state="proposal", next="Gate 1: approve the proposal")
    (hub.lab / ".bus").mkdir(parents=True, exist_ok=True)
    (hub.lab / ".bus" / "events.jsonl").write_text(json.dumps(
        {"ts": "2026-01-01T00:00:00", "source": "hub", "kind": "escalation", "detail": "need FULL run",
         "data": {"id": "e-1"}}) + "\n", encoding="utf-8")
    kinds = {it["kind"]: it for it in m.snapshot()["attention"]}
    assert kinds["gate"]["sev"] == "block" and kinds["gate"]["detail"]["gate"] == 1
    assert kinds["escalation"]["detail"]["id"] == "e-1"
