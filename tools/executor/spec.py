"""What a run IS: a whitelisted skill + validated arguments + where it executes.

`SKILL_REGISTRY` is an explicit allowlist, not "whatever is in .claude/skills": only procedures that
are safe to launch from a click appear, each with its level (hub cwd vs project cwd), its mode, and
an argument schema. `finalize` is absent on purpose — Gate 3 is never delegated.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .lab import HUB_TARGET, Lab
from .manifest import safe_id

# level: where the session's cwd is — "hub" or "project" (the target must then be a spawned project).
# mode:  "headless"    — runs to completion; PI decisions arrive as AskUserQuestion / needs_pi footer
#        "interactive" — an interview; works through the question card + reply box, one turn at a time
# args:  "" (none) · "slug" · "slug?" · "text?" · "campaign" · "slug text?"
SKILL_REGISTRY: dict[str, dict] = {
    "lab-status":     {"level": "hub", "mode": "headless", "args": "", "hint": "orient: registry, inboxes, next action"},
    "ideate":         {"level": "hub", "mode": "headless", "args": "text?", "hint": "research direction, or --in-project <slug>"},
    "lit-review":     {"level": "hub", "mode": "headless", "args": "slug", "hint": "idea slug"},
    "scope":          {"level": "hub", "mode": "headless", "args": "slug", "hint": "idea slug"},
    "propose":        {"level": "hub", "mode": "headless", "args": "slug", "hint": "idea slug (stops at Gate 1)"},
    "spawn-project":  {"level": "hub", "mode": "headless", "args": "slug", "hint": "idea slug (needs Gate 1)"},
    "advance":        {"level": "hub", "mode": "headless", "args": "slug?", "hint": "optional idea slug"},
    "analyze":        {"level": "hub", "mode": "headless", "args": "slug", "hint": "project slug"},
    "make-figures":   {"level": "hub", "mode": "headless", "args": "slug", "hint": "project slug"},
    "write-paper":    {"level": "hub", "mode": "headless", "args": "slug", "hint": "study slug"},
    "critique-paper": {"level": "hub", "mode": "headless", "args": "slug", "hint": "study slug"},
    "review-paper":   {"level": "hub", "mode": "headless", "args": "slug", "hint": "study slug (stops at Gate 3)"},
    "adopt":          {"level": "hub", "mode": "headless", "args": "text?", "hint": "what exists: idea, design, or repo path"},
    "autopilot":      {"level": "hub", "mode": "headless", "args": "campaign", "hint": "signed campaign brief in lab/campaigns/"},
    "experiment":     {"level": "project", "mode": "headless", "args": "slug text?", "hint": "optional exp-id"},
    "improve":        {"level": "project", "mode": "headless", "args": "slug text?", "hint": "optional operator/notes"},
    "research-loop":  {"level": "project", "mode": "headless", "args": "slug", "hint": "needs a signed LOOP_BRIEF.md"},
    "discuss":        {"level": "hub", "mode": "interactive", "args": "text?", "hint": "purpose [target], e.g. direction"},
    "compete":        {"level": "hub", "mode": "interactive", "args": "text?", "hint": "slug or task"},
    "setup-lab":      {"level": "hub", "mode": "interactive", "args": "", "hint": "first-run interview"},
    "configure":      {"level": "hub", "mode": "interactive", "args": "text?", "hint": "e.g. <slug> or set key=value"},
}
NEVER = {"finalize"}   # Gate 3 is never delegated to a headless run

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
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


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
    if skill in NEVER:
        raise SpecError(f"/{skill} is Gate 3 territory — never launched headless; run it in a session")
    cfg = SKILL_REGISTRY.get(skill)
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
    if spec.model and spec.model != "inherit" and not MODEL_RE.match(spec.model):
        raise SpecError("model must be a model id/alias (letters, digits, . _ : / [ ] -), e.g. opus or "
                        "claude-opus-5-5 or openai/gpt-5.5")
    if spec.effort and spec.effort not in EFFORTS:
        raise SpecError(f"effort must be one of {', '.join(EFFORTS)}")
    if spec.repeat_minutes is not None and not (spec.repeat_minutes >= MIN_REPEAT_MINUTES):
        raise SpecError(f"repeat interval must be at least {MIN_REPEAT_MINUTES} minutes")
    return {"skill": skill, "cfg": cfg, "workdir": workdir, "subject": subject, "args": args,
            "level": cfg["level"], "target": target}


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
    """The user prompt. Hub runs on claude use the native slash command (Claude Code expands it in
    -p). Project runs — and every non-claude backend — name the procedure file explicitly, because
    project repos don't ship the lifecycle skills (their AGENTS.md points at the hub's copies)."""
    cmd = slash_command(v)
    if backend == "claude" and v["level"] == "hub":
        return cmd
    skill_file = (lab.hub / ".claude" / "skills" / v["skill"] / "SKILL.md").as_posix()
    rest = cmd.split(" ", 1)[1] if " " in cmd else ""
    return (f"Run the Newts' Lab procedure `/{v['skill']}`" + (f" with arguments: {rest}" if rest else "")
            + f". Its procedure file is {skill_file} — read it and follow it step by step, exactly as if "
            f"the PI had typed `{cmd}` in a session.")


def preamble(lab: Lab, run_id: str, v: dict, backend: str) -> str:
    """The executor's standing instructions for a headless run (claude: --append-system-prompt-file;
    other backends: appended to the prompt). Skill bodies stay untouched."""
    bus = (lab.hub / "tools" / "lab_bus.py") if v["level"] == "hub" else (Path(v["workdir"]) / "scripts" / "lab_bus.py")
    bus = bus.as_posix()
    interactive = v["cfg"].get("mode") == "interactive"
    ask = ("ask it with ONE AskUserQuestion call (concrete options, your recommended answer first) as "
           "the ONLY tool call in that turn — the run pauses and you are resumed with the PI's answer. "
           "If the question has no discrete options, ask it in plain prose as your final message and "
           "stop; the PI's reply resumes this session."
           if backend == "claude" else
           f"run `python {bus} escalate --detail \"<the question>\"`, state the question as your final "
           "message, and end the session; the PI's reply resumes it.")
    lines = [
        f"You are running HEADLESS under the Newts' Lab executor (run id {run_id}, target "
        f"{v['target']}, cwd {Path(v['workdir']).as_posix()}). There is no terminal: the PI watches and "
        "answers from the Vivarium dashboard.",
        "- Follow the lab protocol (AGENTS.md) exactly. Every gate and hard rule still binds you.",
        "- Gate 3 (finalization, sending anything outside the lab) is NEVER yours: stop at it and report.",
        f"- When the procedure needs a PI decision, {ask}",
        "- Do everything the procedure allows without the PI; never idle waiting.",
        "- Background work dies with this session: a background shell job is killed as soon as your "
        "session ends. Never end your turn while a job or subagent you started is still running — "
        "stay in the turn and poll it (check its log / the compute slot on the procedure's cadence) "
        "until it finishes; the executor's watchdog bounds the run. Subagents cannot ask the PI: they "
        "return open questions in their result and you ask.",
        ("- This is an interactive procedure: ask one question per turn and wait for the answer."
         if interactive else "- Keep going until the procedure's own stop point."),
        "- Before you end ANY turn in which the procedure finished or stopped, emit the run footer "
        f"(one line): python {bus} emit run_report --run-id {run_id} --data next=\"<the exact next "
        "command, e.g. /spawn-project my-idea, or empty>\" --data needs_pi=<none|gate1|gate2|gate3|"
        "kill_criteria|null_result|spawn_type|other> --data summary=\"<≤200 chars: what you did and "
        "what the PI should look at>\"",
    ]
    return "\n".join(lines)
