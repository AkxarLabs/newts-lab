"""What a run IS: a whitelisted skill + validated arguments + where it executes.

`registry(hub)` — the lab profile's (tools/lab_profile.py) — is an explicit allowlist, each entry with its
level (hub cwd vs project cwd), its mode and an argument schema. What is in `NEVER` launches only through
the profile's `validate_gated` (for Newts' Lab: /finalize, under a valid Gate 3 signature); chains,
repeats, campaigns and free-form runs can never produce it. What the run is TOLD (its prompt, the
preamble, the stage brief) is the profile's too.

A free-form run (`prompt=…`, the dashboard's "Ask Newt") is the PI's own instruction instead of a
procedure: skill "ask", the same preamble, the same hooks (tracing + the signature guard), no chaining.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import backends  # noqa: F401 — (callers reach backends.get through here)
from .lab import HUB_TARGET, Lab, profile
from .manifest import safe_id

# level: where the session's cwd is — "hub" or "project" (the target must then be a spawned project).
# mode:  "headless"    — runs to completion; PI decisions arrive as AskUserQuestion / needs_pi footer
#        "interactive" — an interview; works through the question card + reply box, one turn at a time
# args:  "" (none) · "slug" · "slug?" · "text?" · "campaign" · "slug text?"
NEVER = profile.NEVER
registry = profile.registry      # registry(hub) → {skill: {level, mode, args, hint, in_project}}
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
    if skill in NEVER:   # only the lab's own exception path (a Gate 3 signature for /finalize)
        try:
            v = profile.validate_gated(lab, spec, skill)
        except ValueError as e:
            raise SpecError(str(e)) from None
        _common_checks(spec)
        return v
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
    args = sanitize_text(spec.args, allow_in_project=bool(cfg.get("in_project")))
    if schema == "" and args:
        raise SpecError(f"/{skill} takes no arguments")
    if schema == "campaign":
        try:
            brief = profile.campaign_brief(lab, args)
        except ValueError as e:
            raise SpecError(str(e)) from None
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


def slash_command(v: dict) -> str:
    """The `/skill args` line exactly as the PI would type it in a session."""
    skill, subject, args, schema = v["skill"], v["subject"], v["args"], v["cfg"]["args"]
    parts = [f"/{skill}"]
    if schema == "campaign":
        parts += ["continue", args]
    else:
        if schema.startswith("slug") and subject:
            parts.append(subject)
        if args:
            parts.append(args)
    return " ".join(parts)


def ask_label(text: str) -> str:
    first = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
    return (first[:57] + "…") if len(first) > 58 else first


