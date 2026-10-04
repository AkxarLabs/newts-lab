"""The lab's half of running agents: everything the executor (tools/executor/) needs to know about THIS lab
— Newts' Lab's procedures, gates, campaigns, papers and hooks — in one module. The executor itself only
runs coding agents: sessions, the queue, caps, retries, the campaign keeper's mechanics. A different kind
of lab plugs in by replacing this file.

    NEVER, registry(hub)                  what a click / chain / campaign may launch (the skills' frontmatter)
    not_dispatchable(hub), campaign_driver(hub)   what a campaign may not dispatch; what runs its cycles
    validate_gated(lab, spec, skill)      the one exception (/finalize, under a valid Gate 3 signature)
    campaign_brief(lab, arg)              a campaign run's signed brief
    render_prompt(lab, v, cmd, native)    the run's user prompt
    preamble(lab, run_id, v, ask_tool)    the standing instructions every headless run gets (+ its stage brief)
    campaign_block(lab, spec, v, run_id)  the extra instructions for a campaign's cycle / dispatched run
    campaign_parallel(brief) · campaign_members(lab, st, brief) · wait_resolved(lab, slug, kind)
    after_cycle(lab, st, children, out, enqueue, keeper)   delegated Gate 3, after each keeper pass
    NEEDS_PI_TITLES                       the run footer's needs_pi, as Needs you shows it
    run_env(m, env)                       the lab's part of a run's environment (its Gate 3 lock)
    GUARD, TRACER, bus_script(), trace_script()   the hooks a run carries: the signature guard, the tracer, the bus
    NOTIFY_TITLE, NOTIFY_PATH             a phone notification's default title and the page it opens
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import markers   # (tools/ is on sys.path: the executor puts it there)
import workflow
from labfiles import read_jsonl

TOOLS = Path(__file__).resolve().parent
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")


def safe_id(s) -> str | None:
    return s if isinstance(s, str) and _SLUG.match(s) and ".." not in s else None

# ── what may run ─────────────────────────────────────────────────────────────────────────────────
NEVER = workflow.NEVER_LAUNCH   # never from a click / chain / campaign — only a Gate 3 signature launches it


def registry(hub=None) -> dict[str, dict]:
    """{skill: {level, mode, args, hint, in_project}} — what a click / chain / campaign may launch in this lab."""
    reg = workflow.launch_registry(hub or TOOLS.parent)
    for n in NEVER:
        reg.pop(n, None)
    return reg


def not_dispatchable(hub=None) -> set[str]:
    """What a campaign pass may not start as its own run (`dispatchable: false`, and finalize)."""
    return workflow.not_dispatchable(hub)


def campaign_driver(hub=None) -> str | None:
    """The procedure that runs one campaign cycle (its args are `campaign`): /autopilot here."""
    return workflow.campaign_driver(hub) or "autopilot"


def validate_gated(lab, spec, skill: str) -> dict:
    """A procedure the click allowlist never holds (finalize): allowed only under a recorded, valid Gate 3
    signature for its study (the dashboard's Gate 3 sheet or a campaign's delegation). Raises ValueError."""
    if skill != "finalize" or not spec.gate3:
        raise ValueError(f"/{skill} is Gate 3 territory — only the PI's Gate 3 signature (the dashboard's "
                         "Gate 3 sheet) launches it")
    target = (spec.target or "").strip()
    if not safe_id(target) or target == "hub":
        raise ValueError("/finalize needs the study it finalizes")
    note = lab.hub / "studies" / target / "paper" / "gate3-approval.md"
    try:
        text = note.read_text(encoding="utf-8-sig")
    except OSError:
        raise ValueError(f"Gate 3 is not signed for {target} (no studies/{target}/paper/gate3-approval.md)") from None
    if not re.search(r"gate ?3 approved", text, re.I):
        raise ValueError(f"studies/{target}/paper/gate3-approval.md is not a Gate 3 approval")
    import gate3 as _gate3  # noqa: PLC0415 — lazy: gate3 imports workflow, which is cheap, but not at import
    ok, why = _gate3.delegation_valid(lab.hub, target)
    if not ok:
        raise ValueError(f"Gate 3 for {target} is not validly signed: {why}")
    return {"skill": "finalize", "cfg": {"level": "hub", "mode": "headless", "args": "slug"},
            "workdir": lab.hub, "subject": target, "args": "", "level": "hub", "target": target,
            "gate3_signed": True}


def campaign_brief(lab, arg: str) -> Path:
    """A campaign run's argument: its signed brief, which must live in lab/campaigns/. Raises ValueError."""
    if not arg:
        raise ValueError("/autopilot needs a signed campaign brief (a file in lab/campaigns/)")
    p = Path(arg)
    base = (lab.lab / "campaigns").resolve()
    cand = (lab.hub / p).resolve() if not p.is_absolute() else p.resolve()
    if not cand.exists():
        cand = (base / p.name).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        raise ValueError("the campaign brief must live in lab/campaigns/") from None
    if not cand.is_file():
        raise ValueError(f"no campaign brief at lab/campaigns/{p.name}")
    return cand


# ── what a run is told ─────────────────────────────────────────────────────────────────────────────
def render_prompt(lab, v: dict, cmd: str, native_slash: bool) -> str:
    """The user prompt. Hub runs on a backend with native slash commands (claude expands them) use the
    command itself. Project runs — and every other backend — name the procedure file explicitly, because
    project repos don't ship the lifecycle skills (their AGENTS.md points at the hub's copies)."""
    if native_slash and v["level"] == "hub":
        return cmd
    skill_file = (lab.hub / ".claude" / "skills" / v["skill"] / "SKILL.md").as_posix()
    rest = cmd.split(" ", 1)[1] if " " in cmd else ""
    return (f"Run the Newts' Lab procedure `/{v['skill']}`" + (f" with arguments: {rest}" if rest else "")
            + f". Its procedure file is {skill_file} — read it and follow it step by step, exactly as if "
            f"the PI had typed `{cmd}` in a session.")


_AWAY = ("- The PI is away. Ask only what you can't decide within the brief, as ONE question with "
         "concrete options and your recommendation FIRST: if nobody answers in time the recommended option "
         "is taken (and shown to the PI as assumed). A permission request is denied while the PI is away.")


def _answers_block(spec) -> list[str]:
    """The PI's answers to questions earlier passes left on the campaign card."""
    ans = (spec.extra or {}).get("pi_answers") or []
    if not ans:
        return []
    return ["- The PI answered questions from earlier passes — act on them:"] + [
        f"  - Q: {a.get('question')}\n    A: {a.get('answer')}" for a in ans[:10]]


def campaign_block(lab, spec, v: dict, run_id: str) -> str:
    """Standing instructions for a run that belongs to a campaign kept by the executor (campaigns.py)."""
    bus = bus_script(lab.hub, "hub", lab.hub).as_posix()
    driver = (v.get("cfg") or {}).get("args") == "campaign"   # this run IS a campaign cycle
    brief = spec.args if driver else ""
    if driver:
        final = bool((spec.extra or {}).get("campaign_final"))
        lines = [
            f"CAMPAIGN CYCLE {spec.extra.get('campaign_cycle') or ''} of {spec.campaign} (brief {brief}), kept by the "
            "executor's campaign keeper. The PI is away; the keeper starts the next cycle after this one, however it ends.",
            "- This cycle is ONE portfolio pass (the /autopilot re-entry path): rebuild state from the written record, "
            "decide each idea's next step, and DISPATCH it — never run a long stage inline. Dispatch = run "
            f"`python {bus} emit campaign_dispatch --run-id {run_id} --data skill=<procedure> --data target=<study slug or hub> "
            "[--data args=\"<args>\"]`; the keeper validates and starts it as its own run (with retries). Dispatch "
            "only procedures that fit the next step; never /finalize (Gate 3 is recorded by the keeper itself, only "
            "if the brief delegates it) and never another campaign.",
            "- Before dispatching work for a NEW idea, append its Campaign Log row (the log is how the keeper knows "
            "which studies belong to this campaign).",
            _AWAY,
            "- A decision outside the brief's bounds is never yours to assume: that study waits for the PI "
            "(its own run reports needs_pi) and you move on to the others.",
            *_answers_block(spec),
            "- End with the run footer, adding `--data campaign=<continue|idle|done>` (done = every target idea is "
            "at internal-review / final / killed, or a stop condition holds).",
        ]
        if final:
            lines.append("- THIS IS THE FINAL CYCLE (a stop condition holds or the PI stopped the campaign): dispatch "
                         "nothing; write the morning report (the skill's §3) and end with `campaign=done`.")
        return "\n".join(lines)
    return "\n".join([
        f"CAMPAIGN RUN for {spec.campaign}: dispatched by its keeper. The PI is away.",
        _AWAY,
        "- A gate, or a decision outside the brief's bounds: stop at it and report it in the run footer "
        "(`needs_pi=<gate1|gate2|gate3|...>`) with `--data study=<slug>` — only this study waits.",
        "- Everything else is exactly the procedure as usual; its gates and hard rules bind.",
    ])


def stage_brief(lab, v: dict) -> tuple[str | None, str | None]:
    """The procedure's stage brief (tools/workflow.py): its method + the PI's instructions for it, lab-wide
    and for the run's study. None when there is nothing beyond SKILL.md (no method, no instructions) —
    and never for a free-form run."""
    skill = v.get("skill")
    if not skill or skill == "ask" or workflow.procedure(skill, lab.hub) is None:
        return None, None
    try:
        text, h = workflow.brief(skill, lab.hub, study=v.get("subject"))
    except (KeyError, ValueError, OSError):
        return None, None
    return (text, h) if "\n## " in text else (None, None)


def preamble(lab, run_id: str, v: dict, ask_tool: str | None) -> str:
    """The executor's standing instructions for a headless run (claude: --append-system-prompt-file;
    other backends: appended to the prompt), then the procedure's stage brief (its method + the PI's
    instructions) so a headless run can't skip it. Skill bodies stay untouched."""
    bus = bus_script(lab.hub, v["level"], Path(v["workdir"])).as_posix()
    interactive = v["cfg"].get("mode") == "interactive"
    ask = (f"ask it with your question tool ({ask_tool or 'if you have one'}): ONE call, concrete options, your recommended "
           "answer FIRST. The PI's answer comes back to you in this same session. If that tool isn't "
           "available, state the question as your final message and end your turn; the PI's reply "
           "resumes this session.")
    lines = [
        f"You are running HEADLESS under the Newts' Lab executor (run id {run_id}, target "
        f"{v['target']}, cwd {Path(v['workdir']).as_posix()}). There is no terminal: the PI watches and "
        "answers from the Vivarium dashboard.",
        "- Follow the lab protocol (AGENTS.md) exactly. Every gate and hard rule still binds you.",
        ("- The PI signed Gate 3 for this study in the dashboard: this run IS the finalization. Follow "
         "/finalize exactly; send nothing outside the lab beyond what it prescribes."
         if v.get("gate3_signed") else
         "- Gate 3 (finalization, sending anything outside the lab) is NEVER yours: stop at it and report."),
        "- Only the PI signs (gate approvals, envelopes, LOOP_BRIEF and campaign authorizations, Gate 3): "
        "a signature guard denies any attempt, so ask instead.",
        f"- When the procedure needs a PI decision, {ask}",
        "- Do everything the procedure allows without the PI; never idle waiting.",
        "- Background work dies with this session: a background shell job is killed as soon as your "
        "session ends. Never end your turn while a job or subagent you started is still running — "
        "stay in the turn and poll it (check its log / the compute slot on the procedure's cadence) "
        "until it finishes; the executor's watchdog bounds the run. Subagents cannot ask the PI: they "
        "return open questions in their result and you ask.",
        ("- This is the PI's own instruction (no procedure was named): do what it asks, using the lab's "
         "procedures when the work is one of them, and stop when it is done or needs a PI decision."
         if v["cfg"].get("kind") == "ask" else
         "- This is an interactive procedure: ask one question per turn and wait for the answer."
         if interactive else "- Keep going until the procedure's own stop point."),
        "- Before you end ANY turn in which the procedure finished or stopped, emit the run footer "
        f"(one line): python {bus} emit run_report --run-id {run_id} --data next=\"<the exact next "
        "command, e.g. /spawn-project my-idea, or empty>\" --data needs_pi=<none|gate1|gate2|gate3|"
        "kill_criteria|null_result|spawn_type|other> --data summary=\"<≤200 chars: what you did and "
        "what the PI should look at>\"",
    ]
    brief, _h = stage_brief(lab, v)
    if brief:
        lines += ["", "--- The stage brief for this procedure (its method and the PI's instructions; it is "
                  "already loaded, so skip the procedure's own step that prints it) ---", brief]
    return "\n".join(lines)


# ── campaigns: the lab's policy for the keeper ───────────────────────────────────────────────────
def campaign_parallel(brief: str) -> int:
    """The brief's `≤ N ideas in flight`: how many studies a campaign works at once."""
    m = re.search(r"≤\s*(\d+)\s*ideas in flight", brief)
    return max(1, int(m.group(1))) if m else 1


def campaign_members(lab, st: dict, brief: str) -> None:
    """Studies in this campaign: named in its Campaign Log, or projects whose envelope it signed."""
    studies = st.setdefault("studies", {})
    log = brief.split("## Campaign Log", 1)[1] if "## Campaign Log" in brief else ""
    found = set()
    for line in log.splitlines():
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and _SLUG.match(cells[1] or "") and cells[1] not in ("idea", "---"):
            found.add(cells[1])
    rows = {r.get("id"): r for r in lab.registry_rows()}
    for slug in rows:
        pdir = lab.project_dir(slug)
        if pdir and st["file"] in ((pdir / "control.yaml").read_text(encoding="utf-8", errors="replace")
                                   if (pdir / "control.yaml").is_file() else ""):
            found.add(slug)
    for slug in found:
        if slug in rows:
            studies.setdefault(slug, {})["member"] = True


def wait_resolved(lab, slug: str, kind: str) -> bool:
    """Has the PI resolved what this study was waiting for?"""
    if kind not in ("gate1", "gate2", "gate3"):
        return False
    return markers.gate_signed(lab.hub, slug, int(kind[-1]), lab.project_dir(slug))


def _open_escalation(lab, slug: str) -> bool:
    open_ = set()
    for e in read_jsonl(lab.lab / ".bus" / "events.jsonl", tail=6000):
        if e.get("idea") != slug:
            continue
        if e.get("kind") == "escalation":
            open_.add(e.get("ts"))
        elif e.get("kind") == "escalation_resolved":
            open_.clear()
    return bool(open_)


def after_cycle(lab, st: dict, children: list, out: dict, enqueue, keeper) -> None:
    """After each keeper pass: record Gate 3 by delegation for every member study whose paper passed review
    and the keeper's own run of the paper audits — only if the PI's signed brief delegates it — then start
    /finalize. `keeper` is tools/executor/campaigns.py (its event log, keeper.save, keeper.RunSpec)."""
    if not st.get("gate3_auto"):
        return
    import gate3  # noqa: PLC0415
    ok, why = gate3.campaign_delegates(lab.hub, st["file"])
    if not ok:
        return
    for slug, s in (st.get("studies") or {}).items():
        if not s.get("member") or s.get("hold") or s.get("gate3_done") or s.get("waiting") not in (None, "gate3"):
            continue
        if gate3.registry_state(lab.hub, slug) != workflow.gate_state(3, lab.hub) or gate3.note_path(lab.hub, slug).exists():
            continue
        pdir = lab.project_dir(slug)
        if pdir and re.search(r"^target:\s*\n(?:[ \t].*\n)*?[ \t]+active:\s*true",
                              (pdir / "control.yaml").read_text(encoding="utf-8", errors="replace")
                              if (pdir / "control.yaml").is_file() else "", re.M):
            continue   # a target-driven project: the PI picks the final output
        stopper = (workflow.load(lab.hub).get("next_for_state") or {}).get(workflow.gate_state(3, lab.hub))   # stops at Gate 3
        review = [m for *_x, m in children if m.get("skill") == stopper and m.get("subject") == slug
                  and m.get("status") == "completed" and (m.get("report") or {}).get("needs_pi") == "gate3"]
        if not review:
            continue
        paper = gate3.paper_dir(lab.hub, slug)
        stamp = "|".join(str(int(p.stat().st_mtime)) for p in (paper / "main.pdf", paper / "claims.yaml") if p.exists())
        if s.get("gate3_checked") == stamp:
            continue   # same paper already failed the checks — wait for a revision
        s["gate3_checked"] = stamp
        ready = gate3.readiness(lab.hub, slug)
        fails = [c["label"] for c in ready["checks"] if not c["ok"]]
        if _open_escalation(lab, slug):
            fails.append("an escalation is still open")
        audits = {} if fails else gate3.run_audits(lab.hub, slug)
        bad = [f"{k} audit exit {v}" for k, v in audits.items() if v != 0]
        entry = {"ts": keeper.now(), "study": slug, "audits": audits}
        if fails or bad:
            entry["result"] = "not yet: " + "; ".join(fails + bad)
            st.setdefault("gate3_log", []).append(entry)
            keeper._event(st, f"{slug}: Gate 3 not recorded — {entry['result'][9:]}")
            continue
        keeper.save(lab, st)   # gate3.delegation_valid reads the saved state (membership, hold)
        gate3.sign_delegated(lab.hub, slug, st["file"], audits, by=f"campaign keeper pid {os.getpid()}")
        spec = keeper.RunSpec(skill="finalize", target=slug, gate3=True, backend=st.get("backend"), model=st.get("model"),
                       campaign=st["name"], parent=review[-1]["run_id"], created_by="campaign-gate3")
        try:
            child = enqueue(lab, spec)
            entry.update(result="recorded Gate 3 by delegation; /finalize started", run_id=child["run_id"])
            s["gate3_done"] = True
            out["gate3"].append(slug)
        except keeper.SpecError as ex:
            entry["result"] = f"recorded, but /finalize could not start: {ex}"
        st.setdefault("gate3_log", []).append(entry)
        st["gate3_log"] = st["gate3_log"][-40:]
        keeper._event(st, f"{slug}: Gate 3 recorded by delegation")


NEEDS_PI_TITLES = {   # the run footer's needs_pi → what Needs you says
    "gate1": "Gate 1 — a proposal awaits your approval",
    "gate2": "Gate 2 — a FULL run needs a signed envelope",
    "gate3": "Gate 3 — a paper awaits final sign-off (in a session)",
    "kill_criteria": "Kill criteria fired — kill or park?",
    "null_result": "Null / negative result — how to proceed?",
    "spawn_type": "Confirm the project type before spawning",
    "other": "The agent needs your decision",
}

def run_env(m: dict, env: dict) -> None:
    """The lab's part of one run's environment: AUTOSCIENTIST_NO_GATE3 on every run except the one /finalize
    a Gate 3 signature started (guard.py finalization hard-stops the rest)."""
    if m.get("skill") == "finalize" and m.get("gate3_signed"):
        env.pop("AUTOSCIENTIST_NO_GATE3", None)
    else:
        env["AUTOSCIENTIST_NO_GATE3"] = "1"


# ── the hooks every run carries ──────────────────────────────────────────────────────────────────
GUARD = TOOLS / "signature_guard.py"     # only the PI signs (a PreToolUse hook; tools/signature_guard.py)
TRACER = TOOLS / "trace_hook.py"         # the per-agent action tracer


def bus_script(hub: Path, level: str, workdir: Path) -> Path:
    """The run's own lab_bus.py: hub-level → the hub's; a project run → the project's copy."""
    return (Path(hub) / "tools" / "lab_bus.py") if level == "hub" else (Path(workdir) / "scripts" / "lab_bus.py")


def trace_script(workdir: Path) -> Path | None:
    """The tracer for a run's workdir: the hub's tools/trace_hook.py or a project's scripts/trace_hook.py (a
    git worktree of a project has its own copy)."""
    for rel in (("tools", "trace_hook.py"), ("scripts", "trace_hook.py")):
        p = Path(workdir).joinpath(*rel)
        if p.is_file():
            return p
    return None


# ── notifications ────────────────────────────────────────────────────────────────────────────────
NOTIFY_TITLE = "Newts' Lab needs you"
NOTIFY_PATH = "#/studies"
