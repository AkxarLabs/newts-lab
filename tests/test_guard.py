"""Tests for tools/guard.py — the mechanical lifecycle guards.

Each c_* function returns an exit code: 0 OK · 1 BLOCKED · 2 WARN. We call them directly with
a tiny SimpleNamespace args object and assert the code.
"""

from __future__ import annotations

import time
import types

from conftest import load


def _mod(hub, monkeypatch):
    m = load("guard")
    monkeypatch.setattr(m, "HUB", hub.root)
    monkeypatch.setattr(m, "LAB", hub.lab)
    return m


def _proposal(hub, slug, text):
    p = hub.root / "studies" / slug / "proposal.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ── spawn (Gate 1) ────────────────────────────────────────────────────────────

def test_spawn_blocked_without_proposal(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    assert m.c_spawn(types.SimpleNamespace(slug="x")) == 1


def test_spawn_blocked_without_gate1_marker(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _proposal(hub, "demo", "# Proposal\nNo approval here.\n")
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_spawn(types.SimpleNamespace(slug="demo")) == 1


def test_spawn_ok_with_gate1_marker(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _proposal(hub, "demo", "# Proposal\n\nPI Gate 1 approved.\n")
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_spawn(types.SimpleNamespace(slug="demo")) == 0


# ── full-run (Gate 2 envelope) ────────────────────────────────────────────────

def _future():
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400 * 30))


def _past():
    return time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 30))


def test_full_run_ok_signed_unexpired_nonzero(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _future(), "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 0


def test_full_run_blocked_unsigned(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={"pi_signed": False, "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


def test_full_run_blocked_expired(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _past(), "full_runs": 4})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


def test_full_run_blocked_all_zero_caps(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", gate2={
        "pi_signed": True, "expires": _future(),
        "full_runs": 0, "per_run_max_minutes": 0, "total_max_minutes": 0})
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_full_run(types.SimpleNamespace(slug="demo")) == 1


# ── frozen ────────────────────────────────────────────────────────────────────

def test_frozen_ok(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", eval_frozen=True)
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 0


def test_frozen_blocked_when_unfrozen(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", eval_frozen=False)
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 1


def test_frozen_blocked_when_block_missing(hub, monkeypatch):
    import yaml
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo", control=False)
    # control.yaml with eval_frozen but no budgets/seeds/gate2_envelope
    (proj / "control.yaml").write_text(yaml.safe_dump({"eval_frozen": True}), encoding="utf-8")
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_frozen(types.SimpleNamespace(slug="demo")) == 1


# ── state transitions ─────────────────────────────────────────────────────────

def _ns(slug, frm, to):
    return types.SimpleNamespace(slug=slug, frm=frm, to=to)


def test_state_legal_forward(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="proposal", project="-")
    assert m.c_state(_ns("demo", "proposal", "active")) == 0


def test_state_documented_back_edge(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="writing", project="-")
    assert m.c_state(_ns("demo", "writing", "active")) == 0


def test_state_blocked_wrong_from_state(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    # row says active, but we claim from=proposal
    assert m.c_state(_ns("demo", "proposal", "active")) == 1


def test_state_blocked_illegal_edge(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="seed", project="-")
    assert m.c_state(_ns("demo", "seed", "final")) == 1


def test_state_park_kill_from_anywhere(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    assert m.c_state(_ns("demo", "active", "parked")) == 0
    hub.add_registry_row("demo2", state="seed", project="-")
    assert m.c_state(_ns("demo2", "seed", "killed")) == 0


# ── append-only ───────────────────────────────────────────────────────────────

def _ledger_project(hub, slug, lines):
    proj = hub.make_project(slug)
    (proj / "EXPERIMENT_LOG.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hub.add_registry_row(slug, state="active", project=str(proj))
    return proj


def test_append_only_baseline_then_append_ok(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0  # records baseline
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1\nentry 2\nentry 3\n", encoding="utf-8")
    assert m.c_append_only(a) == 0  # pure append -> OK


def test_append_only_rewrite_violation(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0
    # rewrite an earlier line -> violation
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1 TAMPERED\nentry 2\n", encoding="utf-8")
    assert m.c_append_only(a) == 1


def test_append_only_removed_line_violation(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = _ledger_project(hub, "demo", ["entry 1", "entry 2", "entry 3"])
    a = types.SimpleNamespace(target=str(proj))
    assert m.c_append_only(a) == 0
    (proj / "EXPERIMENT_LOG.md").write_text("entry 1\nentry 2\n", encoding="utf-8")  # shrank
    assert m.c_append_only(a) == 1


# ── writeback ─────────────────────────────────────────────────────────────────

def test_writeback_ok_with_dated_notebook_naming_slug(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    today = time.strftime("%Y-%m-%d")
    hub.notebook_entry(f"{today}-demo.md", "# Notebook — demo\nworked on demo today\n")
    assert m.c_writeback(types.SimpleNamespace(slug="demo")) == 0


def test_writeback_warn_when_nothing(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="active", project="-")
    assert m.c_writeback(types.SimpleNamespace(slug="demo")) == 2


# ── evolve (triggered write-back operators) ───────────────────────────────────

_NOTES_TEMPLATE = """\
# NOTES — distilled memory

## Gotchas & fixes (environment / data / infra)

<!-- One line each: the trap -> the fix, with evidence.
     e.g.  - data path stalls -> stage to scratch (exp-004) -->

{gotchas}

## Tried & abandoned (approaches that didn't work — do not re-try blindly)

<!-- approach -> where -> why it failed -> "don't retry unless <cond>".
     e.g.  - label smoothing 0.1: exp-006, no gain, reverted -->

{abandoned}

## What worked / settled here (keepers + key results)

<!-- decisions/results that HOLD, with run-id evidence. -->

{worked}
"""


def _make_notes(pdir, *, abandoned="*(none yet)*", worked="*(none yet)*", gotchas="*(none yet)*"):
    (pdir / "NOTES.md").write_text(
        _NOTES_TEMPLATE.format(gotchas=gotchas, abandoned=abandoned, worked=worked), encoding="utf-8")


def test_evolve_kill_blocked_without_correction(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj)  # all placeholders
    hub.add_registry_row("demo", state="killed", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 1


def test_evolve_kill_ok_with_notes_correction(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj, abandoned="- curriculum LR: exp-005, diverged, reverted; skip unless data shifts")
    hub.add_registry_row("demo", state="killed", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 0


def test_evolve_kill_ok_with_hub_failure(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj)  # placeholders, but the hub FAILURES.md carries the correction
    (hub.lab / "knowledge" / "FAILURES.md").write_text(
        "# Failures\n\n- [2026-06-26] (demo) approach X diverged — wrong scale\n", encoding="utf-8")
    hub.add_registry_row("demo", state="killed", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 0


def test_evolve_triage_kill_without_project_not_blocked(hub, monkeypatch):
    # A kill at triage (no project — non-novel / out of scope) is recorded in IDEA.md/OPEN-QUESTIONS,
    # NOT FAILURES.md; the guard must not demand a correction it would be wrong to file.
    m = _mod(hub, monkeypatch)
    hub.add_registry_row("demo", state="killed", project="-")  # never spawned a project
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 0


def test_evolve_results_stage_warns_without_recipe(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj)
    hub.add_registry_row("demo", state="writing", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 2


def test_evolve_results_stage_ok_with_recipe(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj, worked="- cosine LR is the keeper: +0.6% val (exp-007)")
    hub.add_registry_row("demo", state="writing", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 0


def test_evolve_active_state_is_ok_operators_optional(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj)  # nothing recorded yet, but mid-flight nothing is forced
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_evolve(types.SimpleNamespace(slug="demo")) == 0


def test_evolve_placeholder_and_comment_dont_count_as_filled(hub, monkeypatch):
    # The example in the HTML comment + the *(none yet)* placeholder must NOT register as a real line.
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    _make_notes(proj)
    assert m._notes_section_filled(proj, "abandoned") is False
    assert m._notes_section_filled(proj, "worked") is False


# ── decisions (Revisit-predicate lint) ────────────────────────────────────────

def _write_decisions(hub, slug, decisions):
    """decisions: list of (D-NNN, status, headline, predicate|None)."""
    idx = ["## Decision index", "", "| ID | Decision | Status | Headline | Choice |",
           "|----|----------|--------|----------|--------|"]
    for d, status, headline, _ in decisions:
        idx.append(f"| {d} | area | {status} | {headline} | choice |")
    blocks = []
    for d, status, headline, pred in decisions:
        b = [f"## {d}: area", "", f"**Headline:** {headline}", "", "**Revisit if:** something"]
        if pred is not None:
            b.append(f"**Revisit predicate:** `{pred}`")
        blocks.append("\n".join(b))
    doc = "\n".join(idx) + "\n\n---\n\n" + "\n\n---\n\n".join(blocks) + "\n"
    f = hub.root / "studies" / slug / "decisions.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(doc, encoding="utf-8")
    return f


def _dec_ns(slug, strict=False):
    return types.SimpleNamespace(slug=slug, strict=strict)


def test_decisions_ok_well_formed_predicate(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "settled", "no",
                                    "metric(exp-003, val_acc) within seed_noise of best(baseline)")])
    assert m.c_decisions(_dec_ns("demo")) == 0


def test_decisions_warn_missing_predicate(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "settled", "no", None)])
    assert m.c_decisions(_dec_ns("demo")) == 2


def test_decisions_strict_blocks_missing(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "settled", "no", None)])
    assert m.c_decisions(_dec_ns("demo", strict=True)) == 1


def test_decisions_blocked_malformed_predicate(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "settled", "no", "just some prose, no function call")])
    assert m.c_decisions(_dec_ns("demo")) == 1


def test_decisions_headline_yes_exempt(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "settled", "yes", None)])
    assert m.c_decisions(_dec_ns("demo")) == 0


def test_decisions_open_exempt(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _write_decisions(hub, "demo", [("D-001", "OPEN", "no", None)])
    assert m.c_decisions(_dec_ns("demo")) == 0


# ── plan-trace (PLAN.md row provenance) ───────────────────────────────────────

def _plan_project(hub, slug, rows, replan_events=None, decisions_text=None):
    """rows: list of (id, question, criterion). Writes PLAN.md (+ optional hub decisions.md)."""
    proj = hub.make_project(slug)
    body = ["# Experiment Plan", "", "## Experiments", "",
            "| ID | Question | Stage | Status | Promotion/success criterion | Result (run ids) |",
            "|----|----------|-------|--------|------------------------------|------------------|"]
    for rid, q, crit in rows:
        body.append(f"| {rid} | {q} | SMOKE | todo | {crit} | |")
    body += ["", "## Re-planning log", "", "| date | event | detail | evidence |", "|---|---|---|---|"]
    for ev in (replan_events or []):
        body.append(f"| 2026-06-20 | {ev} | round 1 | exp-009 |")
    (proj / "PLAN.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    hub.add_registry_row(slug, state="active", project=str(proj))
    if decisions_text is not None:
        f = hub.root / "studies" / slug / "decisions.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(decisions_text, encoding="utf-8")
    return proj


def test_plan_trace_ok_seed_only(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo", [("exp-001", "pipeline end-to-end", "runs clean")])
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 0


def test_plan_trace_ok_row_cites_decision(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo",
                  [("exp-001", "smoke", "clean"), ("exp-002", "test D-003 dataset choice", "beats base")],
                  decisions_text="## D-003: dataset\n**Headline:** no\n")
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 0


def test_plan_trace_ok_expand_row_with_log(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo",
                  [("exp-001", "smoke", "clean"), ("exp-007", "curriculum (expand R1)", "beats base")],
                  replan_events=["frontier_expand"])
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 0


def test_plan_trace_warn_untraceable_row(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo",
                  [("exp-001", "smoke", "clean"), ("exp-002", "some new idea", "beats base")])
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 2


def test_plan_trace_blocked_headline_change_row(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo",
                  [("exp-001", "smoke", "clean"),
                   ("exp-002", "swap the objective — Headline-change: yes", "beats base")])
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 1


def test_plan_trace_headline_change_not_smuggled_by_decision_cite(hub, monkeypatch):
    # A Headline-change:yes row must be BLOCKED even when it cites a real D-NNN — a decisions.md
    # decision is not a /propose origin, so it cannot smuggle a headline change past the gate.
    m = _mod(hub, monkeypatch)
    _plan_project(hub, "demo",
                  [("exp-001", "smoke", "clean"),
                   ("exp-002", "rework objective per D-003 — Headline-change: yes", "beats base")],
                  decisions_text="## D-003: objective\n**Headline:** no\n")
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 1


def test_plan_trace_blocked_no_plan(hub, monkeypatch):
    m = _mod(hub, monkeypatch)
    proj = hub.make_project("demo")
    (proj / "PLAN.md").unlink(missing_ok=True)
    hub.add_registry_row("demo", state="active", project=str(proj))
    assert m.c_plan_trace(types.SimpleNamespace(slug="demo")) == 1
