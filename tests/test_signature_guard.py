"""tools/signature_guard.py — in a headless run, only the PI signs.

The allow/deny matrix across tool shapes (claude Edit/Write/MultiEdit/Bash, codex apply_patch, opencode
edit), the delegation paths that must keep working (a PI-signed campaign brief, an envelope the PI
approved with Gate 1), before-vs-after comparison (unsigned placeholders are fine), and the hook
contract (exit 2 + reason on stderr, the denial logged to the run's permissions.jsonl).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from conftest import REPO, load

MARK = "<!-- PI Gate 1 approved via Vivarium dashboard 2026-09-01T10:00:00 -->"


@pytest.fixture
def g(hub, monkeypatch):
    mod = load("signature_guard")
    monkeypatch.setattr(mod, "HUB", hub.root.resolve())
    monkeypatch.delenv("NEWTS_RUN_SKILL", raising=False)
    (hub.root / "studies" / "idea-a").mkdir(parents=True)
    (hub.root / "studies" / "idea-a" / "proposal.md").write_text("# Proposal\n\n## Gate\n\npending\n", encoding="utf-8")
    return mod


def edit(path, old, new):
    return {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(path.parent),
            "tool_input": {"file_path": str(path), "old_string": old, "new_string": new}}


def write(path, content):
    return {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": str(path.parent),
            "tool_input": {"file_path": str(path), "content": content}}


def bash(cmd, cwd="."):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": cmd}}


def _campaign(hub, name="2026-09-01-x.md", signed=True):
    d = hub.lab / "campaigns"
    d.mkdir(parents=True, exist_ok=True)
    box = "- [x] Authorized as scoped above · **PI:** me" if signed else "- [ ] Authorized as scoped above · **PI:** ______"
    (d / name).write_text(f"# Campaign\n\n## Direction\n\nx\n\n## PI authorization\n\n{box}\n\n## Campaign Log\n", encoding="utf-8")
    return f"lab/campaigns/{name}"


# ── Gate 1 ────────────────────────────────────────────────────────────────────

def test_gate1_marker_is_denied(g, hub):
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    assert g.decide(edit(p, "pending", MARK))
    assert g.decide(write(p, "# Proposal\n" + MARK))
    assert g.decide(edit(p, "pending", "gate1_approved"))


def test_proposal_edits_without_a_signature_are_fine(g, hub):
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    assert g.decide(edit(p, "pending", "pending — waiting for the PI at Gate 1")) is None
    assert g.decide(write(hub.root / "studies" / "idea-b" / "proposal.md", "# New proposal\n")) is None


def test_gate1_under_a_signed_campaign_is_delegated(g, hub):
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    ok = _campaign(hub, signed=True)
    assert g.decide(edit(p, "pending", f"Gate 1 approved (self-approved within {ok})")) is None
    bad = _campaign(hub, "2026-09-02-y.md", signed=False)
    assert g.decide(edit(p, "pending", f"Gate 1 approved (self-approved within {bad})"))


def test_keeping_an_existing_marker_is_fine(g, hub):
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    p.write_text("# Proposal\n" + MARK + "\n\nnotes\n", encoding="utf-8")
    assert g.decide(edit(p, "notes", "notes, revised")) is None


# ── Gate 2 envelope ───────────────────────────────────────────────────────────

ENV = "gate2_envelope:\n  full_runs: {n}\n  per_run_max_minutes: 60\n  total_max_minutes: 300\n  expires: null\n  pi_signed: {s}\n  signed_via: {v}\n"


def test_new_control_yaml_unsigned_is_fine_signed_is_not(g, hub):
    pdir = hub.make_project("idea-a", control=False)
    c = pdir / "control.yaml"
    assert g.decide(write(c, "eval_frozen: true\n" + ENV.format(n=0, s="false", v="null"))) is None
    assert g.decide(write(c, "eval_frozen: true\n" + ENV.format(n=3, s="true", v="null")))
    assert g.decide(write(c, ENV.format(n=3, s="false", v="dashboard:2026-09-01T10:00:00")))


def test_envelope_signed_at_spawn_when_the_pi_approved_it_with_gate1(g, hub):
    (hub.root / "studies" / "idea-a" / "proposal.md").write_text(
        "# P\n<!-- PI Gate 1 approved via Vivarium dashboard 2026-09-01T10:00:00 · envelope approved -->\n", encoding="utf-8")
    pdir = hub.make_project("idea-a", control=False)
    assert g.decide(write(pdir / "control.yaml", ENV.format(n=3, s="true", v="null"))) is None


def test_envelope_signed_via_a_signed_campaign(g, hub):
    ok = _campaign(hub)
    pdir = hub.make_project("idea-a", control=False)
    assert g.decide(write(pdir / "control.yaml", ENV.format(n=3, s="true", v=ok))) is None
    bad = _campaign(hub, "2026-09-03-z.md", signed=False)
    assert g.decide(write(pdir / "control.yaml", ENV.format(n=3, s="true", v=bad)))


def test_a_signed_envelope_is_frozen(g, hub):
    pdir = hub.make_project("idea-a", control=False)
    c = pdir / "control.yaml"
    c.write_text("eval_frozen: true\n" + ENV.format(n=3, s="true", v="dashboard:2026-09-01T10:00:00"), encoding="utf-8")
    assert g.decide(edit(c, "full_runs: 3", "full_runs: 30"))
    assert g.decide(edit(c, "eval_frozen: true", "eval_frozen: true  # still")) is None


# ── Gate 3, registry, loop brief, campaign ────────────────────────────────────

def test_gate3_is_the_pis(g, hub):
    paper = hub.root / "studies" / "idea-a" / "paper"
    assert g.decide(write(paper / "gate3-approval.md", "Gate 3 approved"))
    rv = paper / "reviews" / "meta-review.md"
    rv.parent.mkdir(parents=True)
    rv.write_text("# Meta\nDecision: accept\n", encoding="utf-8")
    assert g.decide(edit(rv, "Decision: accept", "Decision: accept\n\nGate 3 approved"))
    assert g.decide(edit(rv, "Decision: accept", "Decision: accept (minor)")) is None


def test_registry_final_needs_the_dashboard_signature(g, hub):
    hub.add_registry_row("idea-a", state="internal-review")
    reg = hub.lab / "REGISTRY.md"
    row = "| idea-a | T | internal-review |"
    assert g.decide(edit(reg, row, "| idea-a | T | final |"))
    note = hub.root / "studies" / "idea-a" / "paper" / "gate3-approval.md"
    note.parent.mkdir(parents=True)
    note.write_text("Gate 3 approved by the PI\n- signed_via: dashboard:2026-09-01T10:00:00\n", encoding="utf-8")
    assert g.decide(edit(reg, row, "| idea-a | T | final |")) is None
    assert g.decide(edit(reg, "| idea-a | T | internal-review |", "| idea-a | T | writing |")) is None


def test_loop_brief_authorization(g, hub):
    pdir = hub.make_project("idea-a")
    b = pdir / "LOOP_BRIEF.md"
    b.write_text("## PI authorization\n\n- [ ] Authorized as scoped above\n- **PI:** ______\n", encoding="utf-8")
    assert g.decide(edit(b, "- [ ] Authorized", "- [x] Authorized"))
    ok = _campaign(hub)
    assert g.decide(edit(b, "- [ ] Authorized as scoped above\n- **PI:** ______",
                         f"- [x] Authorized as scoped above\n- **PI:** PI via campaign brief {ok}")) is None


def test_campaign_brief_signature(g, hub):
    d = hub.lab / "campaigns"
    d.mkdir(parents=True)
    f = d / "2026-09-04-new.md"
    draft = "# C\n\n## PI authorization\n\n- [ ] Authorized as scoped above · **PI:** ______\n\n## Campaign Log\n"
    assert g.decide(write(f, draft)) is None                                   # the agent drafts it
    f.write_text(draft, encoding="utf-8")
    assert g.decide(edit(f, "- [ ] Authorized", "- [x] Authorized"))           # but never signs it
    signed = _campaign(hub, "2026-09-05-s.md")
    sf = hub.root / signed
    assert g.decide(edit(sf, "x\n", "a much bigger direction\n"))              # a signed brief is frozen
    assert g.decide(edit(sf, "## Campaign Log\n", "## Campaign Log\n| t | a | b | c | d | e |\n")) is None


# ── lab config + the PI-action log ────────────────────────────────────────────

CFG = "compute:\n  max_concurrent_runs: 1\nideation:\n  candidates: 8\nagents:\n  programmatic:\n    enabled: false\n"


def test_lab_config_owner_rules(g, hub, monkeypatch):
    c = hub.lab / "config.yaml"
    c.write_text(CFG, encoding="utf-8")
    assert g.decide(edit(c, "enabled: false", "enabled: true"))
    assert g.decide(edit(c, "max_concurrent_runs: 1", "max_concurrent_runs: 8"))      # PI-owned
    assert g.decide(edit(c, "candidates: 8", "candidates: 12")) is None                # agent-owned
    monkeypatch.setenv("NEWTS_RUN_SKILL", "setup-lab")                                 # the PI's interview
    assert g.decide(edit(c, "max_concurrent_runs: 1", "max_concurrent_runs: 8")) is None
    assert g.decide(edit(c, "enabled: false", "enabled: true"))                        # still dashboard-only
    assert g.decide(write(hub.lab / ".bus" / "pi-actions.jsonl", "{}"))


# ── shell ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "AUTOSCIENTIST_GATE2_OK=1 uv run python scripts/run.py --stage FULL",
    "python tools/spawn_project.py idea-a --skip-guard",
    "unset AUTOSCIENTIST_NO_GATE3 && python tools/guard.py finalization idea-a",
    "python tools/configure.py set compute.max_concurrent_runs 4 --pi-approved",
    "echo '<!-- PI Gate 1 approved -->' >> studies/idea-a/proposal.md",
    "sed -i 's/pi_signed: false/pi_signed: true/' ../projects/idea-a/control.yaml",
    "python -c \"open('studies/idea-a/paper/gate3-approval.md','w').write('ok')\"",
    "Set-Content studies/idea-a/paper/gate3-approval.md 'Gate 3 approved'",
])
def test_shell_denials(g, cmd):
    assert g.decide(bash(cmd))


@pytest.mark.parametrize("cmd", [
    "grep -n 'PI Gate 1' studies/idea-a/proposal.md",
    "uv run python tools/guard.py spawn idea-a 2>&1",
    "cat ../projects/idea-a/control.yaml | grep pi_signed",
    "uv run python scripts/run.py --stage PILOT > runs/log.txt 2>&1",
    "ls lab/.bus",
])
def test_shell_reads_are_fine(g, cmd):
    assert g.decide(bash(cmd)) is None


# ── other tool shapes ─────────────────────────────────────────────────────────

def test_codex_apply_patch_and_opencode_edit(g, hub):
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    patch = f"*** Begin Patch\n*** Update File: {p}\n@@\n-pending\n+{MARK}\n*** End Patch\n"
    assert g.decide({"tool_name": "apply_patch", "cwd": str(hub.root), "tool_input": {"command": patch}})
    ok_patch = f"*** Begin Patch\n*** Update File: {p}\n@@\n-pending\n+still pending\n*** End Patch\n"
    assert g.decide({"tool_name": "apply_patch", "cwd": str(hub.root), "tool_input": {"command": ok_patch}}) is None
    assert g.decide({"tool_name": "edit", "cwd": str(hub.root),
                     "tool_input": {"filePath": str(p), "oldString": "pending", "newString": MARK}})
    assert g.decide({"tool_name": "MultiEdit", "cwd": str(hub.root), "tool_input": {
        "file_path": str(p), "edits": [{"old_string": "pending", "new_string": MARK}]}})


def test_hook_contract_exit_2_and_logged(hub, tmp_path):
    (hub.root / "studies" / "idea-a").mkdir(parents=True)
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    p.write_text("pending\n", encoding="utf-8")
    rd = tmp_path / "run.d"
    rd.mkdir()
    env = {**__import__("os").environ, "NEWTS_HUB": str(hub.root), "NEWTS_RUN_DIR": str(rd)}
    r = subprocess.run([sys.executable, str(REPO / "tools" / "signature_guard.py")], input=json.dumps(edit(p, "pending", MARK)),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "signature guard" in r.stderr
    rec = json.loads((rd / "permissions.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["decision"] == "deny" and rec["by"] == "signature-guard"
    ok = subprocess.run([sys.executable, str(REPO / "tools" / "signature_guard.py")], input=json.dumps(edit(p, "pending", "later")),
                        capture_output=True, text=True, env=env, timeout=60)
    assert ok.returncode == 0
    junk = subprocess.run([sys.executable, str(REPO / "tools" / "signature_guard.py")], input="not json",
                          capture_output=True, text=True, env=env, timeout=60)
    assert junk.returncode == 0


NODE = __import__("shutil").which("node")


@pytest.mark.skipif(not NODE, reason="node is needed to load the opencode plugin")
def test_opencode_guard_plugin_blocks_under_node(hub, tmp_path):
    sys.path.insert(0, str(REPO / "tools"))
    from executor.backends import opencode
    (hub.root / "studies" / "idea-a").mkdir(parents=True)
    p = hub.root / "studies" / "idea-a" / "proposal.md"
    p.write_text("pending\n", encoding="utf-8")
    d = opencode.guard_dir(tmp_path / "run.d", REPO / "tools" / "signature_guard.py", sys.executable)
    plugin = (d / "plugins" / "newts-guard.js").as_uri()
    js = f"""
const {{ NewtsGuard }} = await import({json.dumps(plugin)})
const hooks = await NewtsGuard({{ directory: {json.dumps(str(hub.root))} }})
const call = (a) => hooks["tool.execute.before"]({{ tool: "edit", sessionID: "s", callID: "c" }}, {{ args: a }})
let denied = false
try {{ await call({{ filePath: {json.dumps(str(p))}, oldString: "pending", newString: {json.dumps(MARK)} }}) }} catch (e) {{ denied = /signature guard/.test(e.message) }}
await call({{ filePath: {json.dumps(str(p))}, oldString: "pending", newString: "later" }})
console.log(JSON.stringify({{ denied }}))
"""
    env = {**__import__("os").environ, "NEWTS_HUB": str(hub.root)}
    r = subprocess.run([NODE, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60, env=env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"denied": True}


# ── procedures, roles and the PI's stage instructions ─────────────────────────

@pytest.mark.parametrize("rel", [".claude/skills/experiment/SKILL.md", ".claude/skills/experiment/METHOD.md",
                                 "agent-roles/overseer.md", ".claude/agents/overseer.md", "workflow/stages.yaml",
                                 "lab/workflow/experiment.add.md", "studies/idea-a/workflow/propose.method.md"])
def test_agents_cannot_edit_procedures_or_their_own_instructions(g, hub, rel):
    p = hub.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    why = g.decide(write(p, "be sloppier"))
    assert why and "workflow.py propose" in why
    assert g.decide(bash(f"echo x > {rel}", hub.root))


def test_proposing_an_instruction_change_is_allowed(g, hub):
    assert g.decide(bash("uv run --with pyyaml python tools/workflow.py propose --proc experiment --mode add "
                         "--file /tmp/draft.md", hub.root)) is None
    assert g.decide(write(hub.root / "studies" / "idea-a" / "notes.md", "fine")) is None


def test_the_rules_the_manuals_and_the_checks_are_the_pis(g, hub):
    """workflow/rules.yaml's protected_paths: a run can't rewrite the lab's rules, its manuals, its checks or
    its templates (it proposes instead); ordinary work files stay writable."""
    for rel in ("workflow/rules.yaml", "AGENTS.md", "CLAUDE.md", "checks/evolve.py", "templates/idea/proposal.md",
                "lab/templates/idea/proposal.md", ".claude/skills/propose/SKILL.md"):
        assert g.decide(write(hub.root / rel, "x\n")), rel
    assert g.decide(write(hub.root / "studies" / "idea-a" / "notes.md", "fine\n")) is None
    assert g.decide({"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(hub.root),
                     "tool_input": {"command": "echo '14. new rule' >> AGENTS.md"}})
