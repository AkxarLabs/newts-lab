"""What a run IS: a whitelisted skill + validated arguments + where it executes.

`registry(hub)` is an explicit allowlist: only the lab's skills that say `launchable` (their SKILL.md
frontmatter `newts:` block) appear, each with its level (hub cwd vs project cwd), its mode, and an
argument schema. `finalize` is absent on purpose — Gate 3 is never delegated: the only way a
/finalize run exists is the PI signing Gate 3 in the dashboard, which launches exactly that one run
(`gate3=True`, checked against the signed studies/<slug>/paper/gate3-approval.md). Chains, repeats,
campaigns and free-form runs can never produce it.

A free-form run (`prompt=…`, the dashboard's "Ask Newt") is the PI's own instruction instead of a
procedure: skill "ask", the same preamble, the same hooks (tracing + the signature guard), no chaining.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import backends
from .lab import HUB_TARGET, Lab
from .manifest import safe_id

# level: where the session's cwd is — "hub" or "project" (the target must then be a spawned project).
# mode:  "headless"    — runs to completion; PI decisions arrive as AskUserQuestion / needs_pi footer
#        "interactive" — an interview; works through the question card + reply box, one turn at a time
# args:  "" (none) · "slug" · "slug?" · "text?" · "campaign" · "slug text?"
# The allowlist is DERIVED from the lab's skills (each SKILL.md's `newts:` block, `launchable`), read
# through tools/workflow.py; NEVER below is still enforced here regardless of what they say.
_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
import workflow as _workflow  # noqa: E402

NEVER = _workflow.NEVER_LAUNCH   # never from a click / chain / campaign — only a Gate 3 signature launches it


def registry(hub=None) -> dict[str, dict]:
    """{skill: {level, mode, args, hint}} — what a click / chain / campaign may launch in this lab."""
    reg = _workflow.launch_registry(hub or _TOOLS.parent)
    for n in NEVER:
        reg.pop(n, None)
    return reg


SKILL_REGISTRY = registry()   # this code's own lab (callers with a Lab use registry(lab.hub))
ASK = "ask"            # the free-form run's pseudo-skill
MAX_PROMPT = 8000

_TEXT_OK = re.compile(r"^[A-Za-z0-9 ._/=,:+#@()'\"-]*$")
MAX_TEXT = 400


@dataclass
class RunSpec:
    skill: str
    target: str = HUB_TARGET          # "hub" or an idea/project slug (the run's subject)
    args: str = ""                    # extra free text (sanitized)
    backend: str | None = None
    model: str | None = None
    effort: str | None = None
    permission_mode: str | None = None
    max_minutes: float | None = None
    max_turns: int | None = None
    role: str = "orchestrator"
    label: str | None = None
    parent: str | None = None
    campaign: str | None = None
    priority: int = 0
    chain: str = "off"                # off | next | loop
    repeat_minutes: float | None = None
    max_repeats: int | None = None
    created_by: str = "cli"
    prompt_override: str | None = None  # a full prompt (campaign worker prompts), bypassing /skill
    prompt: str | None = None           # the PI's free-form instruction (skill "ask")
    gate3: bool = False                 # set only by the dashboard's Gate-3 signature for /finalize
    extra: dict = field(default_factory=dict)


MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\[\]-]{0,119}$")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MIN_REPEAT_MINUTES = 5


class SpecError(ValueError):
    """A run request that must be refused, with a message fit to show the PI."""


def sanitize_text(text: str, *, allow_in_project: bool = False) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) > MAX_TEXT:
        raise SpecError(f"arguments too long (max {MAX_TEXT} chars)")
    if "\n" in text or "\r" in text:
        raise SpecError("arguments must be a single line")
    if not _TEXT_OK.match(text):
        raise SpecError("arguments contain characters outside the allowed set (letters, digits, spaces, ._/=,:+#@()'\"-)")
    first = text.split()[0]
    if first.startswith("-"):
        if allow_in_project and first == "--in-project" and len(text.split()) == 2 and safe_id(text.split()[1]):
            return text
        raise SpecError(f"arguments may not start with a flag ({first})")
    return text


def validate(lab: Lab, spec: RunSpec) -> dict:
    """Resolve and check a spec. Returns {skill_cfg, workdir, subject, level, target} or raises SpecError."""
    skill = (spec.skill or "").strip().lstrip("/")
    if spec.prompt is not None or skill == ASK:
        return _validate_ask(lab, spec)
    if skill in NEVER:
        if skill == "finalize" and spec.gate3:
            return _validate_finalize(lab, spec)
        raise SpecError(f"/{skill} is Gate 3 territory — only the PI's Gate 3 signature (the dashboard's "
                        "Gate 3 sheet) launches it")
    cfg = registry(lab.hub).get(skill)
    if not cfg and not spec.prompt_override:
        raise SpecError(f"unknown or non-launchable skill '/{skill}'")
    cfg = cfg or {"level": "project" if spec.target not in (HUB_TARGET, "", None) else "hub",
                  "mode": "headless", "args": "text?"}
    target = (spec.target or HUB_TARGET).strip()
    if target != HUB_TARGET and not safe_id(target):
        raise SpecError(f"invalid target '{target}' — 'hub' or a bare idea/project slug")
    subject = None if target == HUB_TARGET else target
    schema = cfg["args"]
    if cfg["level"] == "project":
        if not subject:
            raise SpecError(f"/{skill} runs inside a project — pick a project, not the hub")
        workdir = lab.project_dir(subject)
        if not workdir:
            raise SpecError(f"'{subject}' has no project repo yet (spawn it first)")
    else:
        workdir = lab.hub
    needs_slug = schema.startswith("slug") and not schema.startswith("slug?")
    if needs_slug and not subject:
        raise SpecError(f"/{skill} needs an idea/project — pick one as the target")
    args = sanitize_text(spec.args, allow_in_project=(skill == "ideate"))
    if schema == "" and args:
        raise SpecError(f"/{skill} takes no arguments")
    if schema == "campaign":
        brief = _campaign_path(lab, args)
        args = brief.relative_to(lab.hub).as_posix()
    if spec.chain not in ("off", "next", "loop"):
        raise SpecError("chain must be off | next | loop")
    _common_checks(spec)
    return {"skill": skill, "cfg": cfg, "workdir": workdir, "subject": subject, "args": args,
            "level": cfg["level"], "target": target}


def _common_checks(spec: RunSpec) -> None:
    if spec.model and spec.model != "inherit" and not MODEL_RE.match(spec.model):
        raise SpecError("model must be a model id/alias (letters, digits, . _ : / [ ] -), e.g. opus or "
                        "claude-opus-5-5 or openai/gpt-5.5")
    if spec.effort and spec.effort not in EFFORTS:
        raise SpecError(f"effort must be one of {', '.join(EFFORTS)}")
    if spec.repeat_minutes is not None and not (spec.repeat_minutes >= MIN_REPEAT_MINUTES):
        raise SpecError(f"repeat interval must be at least {MIN_REPEAT_MINUTES} minutes")


def _validate_ask(lab: Lab, spec: RunSpec) -> dict:
    """The PI's free-form instruction. Where it runs: the lab (hub), or a study — inside its project repo
    when one exists, else in the hub with the study as its subject."""
    text = (spec.prompt or "").replace("\r\n", "\n").strip()
    if not text:
        raise SpecError("write what you want done")
    if len(text) > MAX_PROMPT:
        raise SpecError(f"the instruction is too long (max {MAX_PROMPT} characters)")
    if "\x00" in text:
        raise SpecError("the instruction contains a NUL byte")
    target = (spec.target or HUB_TARGET).strip()
    if target != HUB_TARGET and not safe_id(target):
        raise SpecError(f"invalid target '{target}' — 'hub' or a bare idea/project slug")
    subject = None if target == HUB_TARGET else target
    pdir = lab.project_dir(subject) if subject else None
    if spec.chain not in ("off", None, ""):
        raise SpecError("a free-form run can't chain — its reported next step shows as a button instead")
    _common_checks(spec)
    level = "project" if pdir else "hub"
    return {"skill": ASK, "cfg": {"level": level, "mode": "headless", "args": "text?", "kind": ASK},
            "workdir": pdir or lab.hub, "subject": subject, "args": "", "level": level, "target": target,
            "prompt": text}


def _validate_finalize(lab: Lab, spec: RunSpec) -> dict:
    target = (spec.target or "").strip()
    if not safe_id(target) or target == HUB_TARGET:
        raise SpecError("/finalize needs the study it finalizes")
    note = lab.hub / "studies" / target / "paper" / "gate3-approval.md"
    try:
        text = note.read_text(encoding="utf-8-sig")
    except OSError:
        raise SpecError(f"Gate 3 is not signed for {target} (no studies/{target}/paper/gate3-approval.md)") from None
    if not re.search(r"gate ?3 approved", text, re.I):
        raise SpecError(f"studies/{target}/paper/gate3-approval.md is not a Gate 3 approval")
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    import gate3 as _gate3  # noqa: PLC0415
    ok, why = _gate3.delegation_valid(lab.hub, target)
    if not ok:
        raise SpecError(f"Gate 3 for {target} is not validly signed: {why}")
    _common_checks(spec)
    return {"skill": "finalize", "cfg": {"level": "hub", "mode": "headless", "args": "slug"},
            "workdir": lab.hub, "subject": target, "args": "", "level": "hub", "target": target,
            "gate3_signed": True}


def _campaign_path(lab: Lab, arg: str) -> Path:
    if not arg:
        raise SpecError("/autopilot needs a signed campaign brief (a file in lab/campaigns/)")
    p = Path(arg)
    base = (lab.lab / "campaigns").resolve()
    cand = (lab.hub / p).resolve() if not p.is_absolute() else p.resolve()
    if not cand.exists():
        cand = (base / p.name).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        raise SpecError("the campaign brief must live in lab/campaigns/") from None
    if not cand.is_file():
        raise SpecError(f"no campaign brief at lab/campaigns/{p.name}")
    return cand


def slash_command(v: dict) -> str:
    """The `/skill args` line exactly as the PI would type it in a session."""
    skill, subject, args, schema = v["skill"], v["subject"], v["args"], v["cfg"]["args"]
    parts = [f"/{skill}"]
    if skill == "autopilot":
        parts += ["continue", args]
    else:
        if schema.startswith("slug") and subject:
            parts.append(subject)
        if args:
            parts.append(args)
    return " ".join(parts)


def render_prompt(lab: Lab, v: dict, backend: str) -> str:
    """The user prompt. Hub runs on a backend with native slash commands (claude expands them) use the
    command itself. Project runs — and every other backend — name the procedure file explicitly, because
    project repos don't ship the lifecycle skills (their AGENTS.md points at the hub's copies)."""
    cmd = slash_command(v)
    if backends.get(backend).native_slash and v["level"] == "hub":
        return cmd
    skill_file = (lab.hub / ".claude" / "skills" / v["skill"] / "SKILL.md").as_posix()
    rest = cmd.split(" ", 1)[1] if " " in cmd else ""
    return (f"Run the Newts' Lab procedure `/{v['skill']}`" + (f" with arguments: {rest}" if rest else "")
            + f". Its procedure file is {skill_file} — read it and follow it step by step, exactly as if "
            f"the PI had typed `{cmd}` in a session.")


_AWAY = ("- The PI is away. Ask only what you can't decide within the brief, as ONE question with "
         "concrete options and your recommendation FIRST: if nobody answers in time the recommended option "
         "is taken (and shown to the PI as assumed). A permission request is denied while the PI is away.")


def _answers_block(spec: RunSpec) -> list[str]:
    """The PI's answers to questions earlier passes left on the campaign card."""
    ans = (spec.extra or {}).get("pi_answers") or []
    if not ans:
        return []
    return ["- The PI answered questions from earlier passes — act on them:"] + [
        f"  - Q: {a.get('question')}\n    A: {a.get('answer')}" for a in ans[:10]]


def campaign_block(lab: Lab, spec: RunSpec, v: dict, run_id: str) -> str:
    """Standing instructions for a run that belongs to a campaign kept by the executor (campaigns.py)."""
    bus = (lab.hub / "tools" / "lab_bus.py").as_posix()
    brief = spec.args if v.get("skill") == "autopilot" else ""
    if v.get("skill") == "autopilot":
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


def ask_label(text: str) -> str:
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return (first[:57] + "…") if len(first) > 58 else first


def stage_brief(lab: Lab, v: dict) -> tuple[str | None, str | None]:
    """The procedure's stage brief (tools/workflow.py): its method + the PI's instructions for it, lab-wide
    and for the run's study. None when there is nothing beyond SKILL.md (no method, no instructions) —
    and never for a free-form run."""
    skill = v.get("skill")
    if not skill or skill == ASK or _workflow.procedure(skill, lab.hub) is None:
        return None, None
    try:
        text, h = _workflow.brief(skill, lab.hub, study=v.get("subject"))
    except (KeyError, ValueError, OSError):
        return None, None
    return (text, h) if "\n## " in text else (None, None)


def preamble(lab: Lab, run_id: str, v: dict, backend: str) -> str:
    """The executor's standing instructions for a headless run (claude: --append-system-prompt-file;
    other backends: appended to the prompt), then the procedure's stage brief (its method + the PI's
    instructions) so a headless run can't skip it. Skill bodies stay untouched."""
    bus = (lab.hub / "tools" / "lab_bus.py") if v["level"] == "hub" else (Path(v["workdir"]) / "scripts" / "lab_bus.py")
    bus = bus.as_posix()
    interactive = v["cfg"].get("mode") == "interactive"
    ask = (f"ask it with your question tool ({backends.get(backend).ask_tool or 'if you have one'}): ONE call, concrete options, your recommended "
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
         if v["cfg"].get("kind") == ASK else
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
