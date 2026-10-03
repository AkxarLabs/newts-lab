"""Backends: one module per agent CLI (claude · codex · opencode), registered in REGISTRY.

A backend knows everything the executor needs about its CLI, so nothing outside this package
branches on a backend's name:

    prepare(a)    env and per-run sidecars (the tracer, the signature guard) for an Attempt
    command(a)    the argv for one attempt — a live session (live.py) or one-shot  → RunCommand
    session(a)    the live session speaking the CLI's own protocol (None: one-shot only)
    parse(obj)    one stream line → normalized events (start · text · action · tool_result · …)
    auth(out)     is the CLI signed in? (from `auth_args`)   · sign_in_hint, ask_tool, …

Adding a backend = one module here with a Backend subclass, plus its line in REGISTRY. The helpers
below are backend-neutral: finding a CLI, its version, why a run failed, when a limit lifts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..lab import profile   # the lab's hooks: its signature guard, tracer and bus (tools/lab_profile.py)

DEFAULT = "claude"
TOOLS = Path(__file__).resolve().parents[2]
TRACE_EVENTS = ("SessionStart", "SubagentStart", "PreToolUse", "PostToolUse", "SubagentStop", "SessionEnd")


@dataclass
class RunCommand:
    argv: list[str]
    stdin_text: str | None       # written to the child's stdin then closed; None = DEVNULL (or live)
    fires_hooks: bool            # the tracer runs inside the CLI (else the supervisor writes a worker log)
    notes: list[str] = field(default_factory=list)


@dataclass
class Attempt:
    """Everything one attempt of one run needs, built by the supervisor and filled in by its backend."""
    lab: object
    m: dict                      # the run's manifest
    workdir: Path
    rd: Path                     # <run>.d/ — sidecars
    prog: dict                   # agents.programmatic
    cli: list[str]
    prompt: str
    preamble: str
    resuming: bool
    live: bool
    env: dict
    python: str
    ver: tuple | None = None
    guard: Path | None = None    # tools/signature_guard.py, when present
    tracer: Path | None = None   # tools/trace_hook.py, when present
    # set by Backend.prepare:
    settings: Path | None = None
    system_prompt_file: Path | None = None
    add_dirs: list = field(default_factory=list)
    hooks: list | None = None
    traced: bool = False
    command: RunCommand | None = None   # Backend.command(self), once prepared

    @property
    def bcfg(self) -> dict:
        return (self.prog.get("backends") or {}).get(self.m.get("backend") or DEFAULT) or {}

    @property
    def model(self):
        """An explicit launch/global model wins; otherwise the backend's own default."""
        m = self.m.get("model") or self.prog.get("model")
        return m if (m and m != "inherit") else (self.bcfg.get("model") or None)

    @property
    def extra(self) -> str:
        return str(self.bcfg.get("extra_args") or "")

    @property
    def resume_sid(self) -> str | None:
        return self.m.get("session_id") if self.resuming else None

    @property
    def bus(self) -> Path:
        """The run's own lab_bus.py (hub-level → the hub's; project → the project's copy)."""
        return profile.bus_script(self.lab.hub, self.m.get("level") or "hub", self.workdir)


class Backend:
    name = ""
    ask_tool = ""                # the question tool the preamble names
    native_slash = False         # runs hub procedures as /slash commands (else: "read SKILL.md and follow it")
    probe_version = False        # `--version` gates flags
    preassign_session = False    # the executor picks the session id before the first attempt
    waits_for_background = False  # the CLI waits for background subagents before it exits
    env_auth = ()                # env vars that sign the CLI in without an interactive login
    auth_args: list | None = None
    sign_in_hint = ""
    forbid: tuple = ()           # flags extra_args may not set (the executor's or the PI's to decide)

    def prepare(self, a: Attempt) -> None:
        pass

    def command(self, a: Attempt) -> RunCommand:
        raise NotImplementedError

    def session(self, a: Attempt):
        return None

    @property
    def has_live(self) -> bool:
        return type(self).session is not Backend.session

    def parse(self, obj: dict) -> list[dict]:
        return []

    def auth(self, out: subprocess.CompletedProcess) -> dict | None:
        return None

    def check_extra(self, a: Attempt) -> None:
        """extra_args is a PI-owned advanced knob; it must NOT silently negate the human-in-loop
        permission/sandbox defaults or the executor's own wiring. Refuse rather than override. Match the
        `=`-joined form too (`--sandbox=danger-full-access`), which bare-token equality would miss."""
        toks = a.extra.split()
        hit = sorted({f for f in self.forbid for tok in toks if tok == f or tok.startswith(f + "=")})
        if hit:
            raise SystemExit(f"[executor] backends.{self.name}.extra_args may not set {hit} — that "
                             "would defeat the human-in-loop default; set the dedicated config key instead")


class Dummy(Backend):
    """Tests: the configured command is the whole argv; the prompt (+ preamble) goes to stdin, the resume
    session id rides the env; lines are parsed as codex `exec --json`."""
    name = "_dummy"

    def prepare(self, a: Attempt) -> None:
        a.env["NEWTS_RESUME_SID"] = a.resume_sid or a.m.get("session_id") or ""
        a.env["NEWTS_RESUME_MODE"] = (a.m.get("resume") or {}).get("mode") or ""

    def command(self, a: Attempt) -> RunCommand:
        return RunCommand(list(a.cli), with_preamble(a) or None, False)

    def parse(self, obj: dict) -> list[dict]:
        return REGISTRY["codex"].parse(obj)


def with_preamble(a: Attempt) -> str:
    """The prompt with the executor's standing instructions after it (for CLIs without a system-prompt
    flag in one-shot mode)."""
    text = a.prompt or ""
    return f"{text}\n\n---\n{a.preamble}" if (a.preamble and text) else text


def toml_str(v) -> str:
    """A `-c key=value` value is parsed as TOML: quote strings so `medium` isn't a TOML error."""
    return json.dumps(str(v))


# ── finding the CLI ───────────────────────────────────────────────────────────

def _candidates(name: str) -> list[Path]:
    home = Path.home()
    if os.name == "nt":
        env = os.environ.get
        roots = [home / ".local" / "bin",
                 Path(env("APPDATA", str(home / "AppData" / "Roaming"))) / "npm",
                 Path(env("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Programs" / name,
                 Path(env("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Microsoft" / "WinGet" / "Links",
                 Path(env("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin",
                 home / ".bun" / "bin", home / f".{name}" / "bin"]
        return [r / f"{name}{ext}" for r in roots for ext in (".exe", ".cmd")]
    roots = [home / ".local" / "bin", home / ".claude" / "local", home / ".npm-global" / "bin",
             home / ".bun" / "bin", home / f".{name}" / "bin", Path("/opt/homebrew/bin"),
             Path("/usr/local/bin"), Path("/usr/bin")]
    return [r / name for r in roots]


def _app_bundled(name: str) -> list[Path]:
    """CLIs that ship inside a desktop app (the Codex app carries the full `codex` CLI, signed in with
    the app's account). Newest app version first — the path changes with every app update."""
    if name != "codex":
        return []
    if os.name == "nt":
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"

        def ver(p: Path) -> tuple:
            v = p.parts[-4].split("_")[1] if "_" in p.parts[-4] else ""
            return tuple(int(x) for x in v.split(".") if x.isdigit())
        return sorted(pf.glob("OpenAI.Codex_*/app/resources/codex.exe"), key=ver, reverse=True)
    if sys.platform == "darwin":
        return [Path(r) / "Codex.app" / "Contents" / "Resources" / "codex"
                for r in ("/Applications", str(Path.home() / "Applications"))]
    return []


def resolve_cli(backend: str, bcfg: dict | None = None) -> list[str] | None:
    """The argv PREFIX that runs a backend CLI, or None if it can't be found.

    `backends.<b>.command` wins: a string is one executable path (never split — Windows paths have
    spaces), a list is a full prefix (e.g. [python, fake_cli.py] in tests). Then PATH, then the usual
    per-platform install locations (the Claude installer puts claude.exe in ~/.local/bin, which is
    often not on a GUI-launched process's PATH), then a desktop app's bundled copy (the Codex app).
    `.exe` beats a `.cmd` shim on Windows.
    """
    explicit = (bcfg or {}).get("command")
    if explicit:
        if isinstance(explicit, list):
            return [str(x) for x in explicit] if explicit else None
        p = Path(str(explicit)).expanduser()
        if p.exists():
            return [str(p)]
        w = shutil.which(str(explicit))
        return [w] if w else None
    if backend not in BACKENDS:
        return None
    found = shutil.which(backend)
    if found and os.name == "nt" and found.lower().endswith((".cmd", ".bat")):
        exe = Path(found).with_suffix(".exe")
        found = str(exe) if exe.exists() else found
    if found:
        return [found]
    for c in _candidates(backend) + _app_bundled(backend):
        if c.is_file():
            return [str(c)]
    return None


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_VERSION_CACHE: dict[tuple, tuple[float, tuple | None]] = {}
_AUTH_CACHE: dict[tuple, tuple[float, dict | None]] = {}


def forget_checks() -> None:
    """Re-probe every CLI's version and sign-in next time (after an install or a sign-in)."""
    _VERSION_CACHE.clear()
    _AUTH_CACHE.clear()


def cli_version(prefix: list[str] | None) -> tuple | None:
    """(major, minor, patch) from `<cli> --version`, cached per prefix for 10 minutes (so an upgrade
    shows without restarting the dashboard). None if unknown."""
    if not prefix:
        return None
    key = tuple(prefix)
    hit = _VERSION_CACHE.get(key)
    if hit is not None and time.time() - hit[0] < 600:
        return hit[1]
    ver = None
    try:
        out = subprocess.run([*prefix, "--version"], capture_output=True, text=True, timeout=20,
                             encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", (out.stdout or "") + (out.stderr or ""))
        ver = tuple(int(x) for x in m.groups()) if m else None
    except (OSError, subprocess.SubprocessError):
        ver = None
    _VERSION_CACHE[key] = (time.time(), ver)
    return ver


def version_str(v) -> str | None:
    return ".".join(str(x) for x in v) if v else None


def cli_auth(prefix: list[str] | None, ttl: float = 60.0, backend: str = DEFAULT) -> dict | None:
    """Is the backend CLI signed in? → {"logged_in": bool, "method": str}, cached `ttl` s; None if
    unknown. Read-only: it never touches credentials."""
    b = REGISTRY.get(backend)
    if not prefix or not b or not b.auth_args:
        return None
    key = (backend, *prefix)
    hit = _AUTH_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        out = subprocess.run([*prefix, *b.auth_args], capture_output=True, text=True, timeout=20,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        info = b.auth(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        info = None
    _AUTH_CACHE[key] = (time.time(), info)
    return info


ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


trace_script = profile.trace_script   # the lab's tracer for a run's workdir (tools/lab_profile.py)


# ── why a run failed: "try again later" or "something is wrong" ───────────────

_USAGE_RE = re.compile(r"usage limit|rate limit|quota|too many requests|\b429\b|limit (?:reached|exceeded)|"
                       r"out of (?:credits|messages)|resets? (?:at|in)", re.I)
_TRANSIENT_RE = re.compile(r"overloaded|\b5\d\d\b|internal server error|bad gateway|service unavailable|"
                           r"econnreset|econnrefused|etimedout|timed out|network|connection (?:reset|closed|error)|"
                           r"temporar(?:y|ily)|try again", re.I)
_AUTH_RE = re.compile(r"not logged in|/login|authentication_failed|failed to authenticate|oauth session expired|"
                      r"unauthorized|\b401\b|codex login|no provider|api key|providermodelnotfound", re.I)


def failure_kind(text: str) -> str:
    """usage_limit | auth | transient | logic — how to treat a failed attempt (a campaign retries the first
    three with backoff; `logic` counts as a real failure)."""
    t = str(text or "")
    if _USAGE_RE.search(t):
        return "usage_limit"
    if _AUTH_RE.search(t):
        return "auth"
    if _TRANSIENT_RE.search(t):
        return "transient"
    return "logic"


def limit_reset(text: str, now: float | None = None) -> float | None:
    """When a usage limit lifts, as an epoch — from the CLI's own message when it says (claude:
    `usage limit reached|<epoch>` or "resets 3pm"; codex: "try again in 2h 13m"; a Retry-After of N
    seconds). None when the message doesn't say."""
    now = time.time() if now is None else now
    t = str(text or "")
    m = re.search(r"limit reached\|(\d{9,11})", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(?:try again|retry|resets?) in\s+(?:(\d+)\s*h(?:ours?)?)?\s*(?:(\d+)\s*m(?:in(?:utes?)?)?)?\s*"
                  r"(?:(\d+)\s*s(?:ec(?:onds?)?)?)?", t, re.I)
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        return now + h * 3600 + mi * 60 + s
    m = re.search(r"retry[- ]after[\"':\s]+(\d+)", t, re.I)
    if m:
        return now + int(m.group(1))
    m = re.search(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t, re.I)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and hh < 12:
            hh += 12
        if ap == "am" and hh == 12:
            hh = 0
        if hh < 24 and mm < 60:
            lt = time.localtime(now)
            cand = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
            return cand if cand > now else cand + 86400
    return None


# ── stream parsing: one vocabulary for every backend ──────────────────────────

_SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "url", "query", "description", "skill", "prompt")


def summarize_input(tool: str | None, inp) -> str:
    if not isinstance(inp, dict):
        return str(inp or "")[:400]
    if tool in ("Agent", "Task"):
        st = inp.get("subagent_type") or "general-purpose"
        return f"{st}: {inp.get('description') or inp.get('prompt') or ''}"[:400]
    if tool == "AskUserQuestion":
        qs = [q.get("question") for q in (inp.get("questions") or []) if isinstance(q, dict) and q.get("question")]
        return (" · ".join(qs) or "a question for the PI")[:400]
    for k in _SUMMARY_KEYS:
        if inp.get(k):
            return str(inp[k])[:400]
    return str(inp)[:400]


def parse_events(backend: str, obj: dict) -> list[dict]:
    """Every activity in one stream object, normalized:
      start{session_id} · text{text,parent} · action{tool,tool_use_id,summary,parent,spawn?}
      tool_result{tool_use_id,text,is_error,parent} · begin{tool,summary} · denied{tool}
      usage{usage,cost_delta?} · result{last_message,session_id,stop_reason,cost_usd,usage,is_error}
    `parent` is the tool_use_id of the Agent/Task call that spawned the subagent the message came
    from (None = the main thread) — a hook-free source for the run → subagent tree."""
    b = REGISTRY.get(backend)
    return b.parse(obj) if (b and isinstance(obj, dict)) else []


def get(name: str | None) -> Backend:
    b = REGISTRY.get(name or DEFAULT)
    if b is None:
        raise SystemExit(f"[executor] unknown backend {name!r} ({' | '.join(BACKENDS)})")
    return b


from .claude import Claude  # noqa: E402 — the modules subclass Backend above
from .codex import Codex  # noqa: E402
from .opencode import Opencode  # noqa: E402

REGISTRY: dict[str, Backend] = {b.name: b for b in (Claude(), Codex(), Opencode(), Dummy())}
BACKENDS = tuple(n for n in REGISTRY if not n.startswith("_"))
