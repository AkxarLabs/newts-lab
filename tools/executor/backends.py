"""Backends: argv builders, CLI resolution, and stream parsing for claude / codex / opencode.

`build_command` keeps the exact legacy contract agent_runner.py has always exposed (argv starting
with the bare CLI name, prompt as argv). `build_run_command` is the executor's builder: resolved CLI
path, prompt via stdin (dodges the ~32K Windows command-line limit), session pre-assignment / resume,
the per-run settings + MCP permission host, and hub skill access for project runs.
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

BACKENDS = ("claude", "codex", "opencode")
_VERSION_CACHE: dict[tuple, tuple[float, tuple | None]] = {}

# claude flags newer than some installs; only passed when the resolved CLI is at least this version.
CLAUDE_MIN = {
    "--forward-subagent-text": (2, 1, 211),
}


def _guard_extra(backend: str, extra: str, forbidden: tuple[str, ...]) -> None:
    """extra_args is a PI-owned advanced knob; it must NOT silently negate the human-in-loop
    permission/sandbox defaults or the executor's own wiring. Refuse rather than override. Match the
    `=`-joined form too (`--sandbox=danger-full-access`), which bare-token equality would miss."""
    toks = extra.split()
    hit = sorted({f for f in forbidden for tok in toks if tok == f or tok.startswith(f + "=")})
    if hit:
        raise SystemExit(f"[agent_runner] backends.{backend}.extra_args may not set {hit} — that "
                         "would defeat the human-in-loop default; set the dedicated config key instead")


_CLAUDE_FORBID = ("--permission-mode", "--dangerously-skip-permissions")
_CLAUDE_EXECUTOR_OWNED = ("--settings", "--mcp-config", "--permission-prompt-tool", "--resume", "--input-format",
                          "--replay-user-messages",
                          "--session-id", "--add-dir", "--continue", "--fork-session",
                          "--append-system-prompt", "--append-system-prompt-file",
                          "--allow-dangerously-skip-permissions")
_CODEX_FORBID = ("--sandbox", "-s", "-a", "--ask-for-approval", "--dangerously-bypass-approvals-and-sandbox",
                 "--yolo", "--full-auto", "--approve-for-me", "--not-so-yolo", "resume", "fork")
_OPENCODE_FORBID = ("--dangerously-skip-permissions", "--dir", "--format")


def _eff_model(model, bcfg: dict):
    # An explicit launch/global model wins; otherwise the backend's own default.
    return model if (model and model != "inherit") else (bcfg.get("model") or "inherit")


def _toml_str(v) -> str:
    """A `-c key=value` value is parsed as TOML: quote strings so `medium` isn't a TOML error."""
    return json.dumps(str(v))


def _codex_opts(bcfg: dict, workdir, eff_model) -> list[str]:
    """`codex exec` options shared by a fresh run and a resume (they go BEFORE the `resume`
    subcommand: -s / -C are exec-level flags the resume inherits).

    `codex exec` has no -a/--ask-for-approval flag (that is the interactive TUI's); exec already
    runs with approval_policy=never — a blocked op fails back to the model, never prompts. A PI who
    sets `approval` to something stricter gets it as a config override (approvals are then rejected
    in exec, i.e. the op fails)."""
    opts = ["--json", "--sandbox", str(bcfg.get("sandbox") or "workspace-write"),
            "--skip-git-repo-check", "-C", str(workdir)]
    appr = str(bcfg.get("approval") or "never")
    if appr != "never":
        opts += ["-c", f"approval_policy={_toml_str(appr)}"]
    if bcfg.get("network_access"):   # workspace-write disables network by default; opt-in per genuine need
        opts += ["-c", "sandbox_workspace_write.network_access=true"]
    if bcfg.get("reasoning_effort"):   # codex has no --effort flag; it's a config override
        opts += ["-c", f"model_reasoning_effort={_toml_str(bcfg['reasoning_effort'])}"]
    if eff_model and eff_model != "inherit":
        opts += ["-m", str(eff_model)]
    return opts


def build_command(backend: str, prompt: str, pdir: Path, model: str,
                  permission_mode: str, prog: dict) -> tuple[list[str], bool]:
    """Legacy builder → (argv, fires_claude_hooks). The launcher only synthesizes a worker log when
    the backend does NOT fire Claude Code hooks (claude does; codex / opencode / test backends don't)."""
    bcfg = (prog.get("backends") or {}).get(backend) or {}
    extra = str(bcfg.get("extra_args") or "")
    eff_model = _eff_model(model, bcfg)

    if backend == "claude":
        _guard_extra(backend, extra, _CLAUDE_FORBID)
        mode = bcfg.get("permission_mode") or permission_mode   # per-backend key overrides the launch default
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose"]
        if eff_model and eff_model != "inherit":
            cmd += ["--model", str(eff_model)]
        if mode:
            cmd += ["--permission-mode", str(mode)]
        if bcfg.get("effort"):
            cmd += ["--effort", str(bcfg["effort"])]   # claude --effort: low|medium|high|xhigh|max
        if extra:
            cmd += extra.split()
        return cmd, True
    if backend == "codex":
        _guard_extra(backend, extra, _CODEX_FORBID)
        cmd = ["codex", "exec", prompt, *_codex_opts(bcfg, pdir, eff_model)]
        if extra:
            cmd += extra.split()
        return cmd, False
    if backend == "opencode":
        # `opencode run <prompt> --format json` streams NDJSON and exits when idle. Autonomy rides the
        # OPENCODE_PERMISSION env (set by the launcher), not a flag.
        _guard_extra(backend, extra, _OPENCODE_FORBID)
        cmd = ["opencode", "run", prompt, "--format", "json", "--dir", str(pdir)]
        if eff_model and eff_model != "inherit":
            cmd += ["--model", str(eff_model)]   # MUST be provider/model form, e.g. anthropic/claude-...
        if bcfg.get("variant"):
            cmd += ["--variant", str(bcfg["variant"])]
        if bcfg.get("agent"):
            cmd += ["--agent", str(bcfg["agent"])]
        if bcfg.get("skip_permissions"):   # version-dependent flag; the stable control is the env
            cmd += ["--dangerously-skip-permissions"]
        if extra:
            cmd += extra.split()
        return cmd, False
    if backend == "_dummy":  # test backend: a portable JSONL emitter configured in lab/config.yaml
        c = bcfg.get("command")
        if not c:
            raise SystemExit("_dummy backend needs agents.programmatic.backends._dummy.command")
        return (list(c) if isinstance(c, list) else str(c).split()), False
    raise SystemExit(f"[agent_runner] unknown backend {backend!r} (claude | codex | opencode)")


# ── CLI resolution ────────────────────────────────────────────────────────────

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
        out = []
        for r in roots:
            out += [r / f"{name}.exe", r / f"{name}.cmd"]
        return out
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
        hits = list(pf.glob("OpenAI.Codex_*/app/resources/codex.exe"))

        def ver(p: Path) -> tuple:
            v = p.parts[-4].split("_")[1] if "_" in p.parts[-4] else ""
            return tuple(int(x) for x in v.split(".") if x.isdigit())
        return sorted(hits, key=ver, reverse=True)
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
    bcfg = bcfg or {}
    explicit = bcfg.get("command")
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
                             encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", (out.stdout or "") + (out.stderr or ""))
        if m:
            ver = tuple(int(x) for x in m.groups())
    except (OSError, subprocess.SubprocessError):
        ver = None
    _VERSION_CACHE[key] = (time.time(), ver)
    return ver


def version_str(v) -> str | None:
    return ".".join(str(x) for x in v) if v else None


_AUTH_CACHE: dict[tuple, tuple[float, dict | None]] = {}


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_AUTH_ARGS = {"claude": ["auth", "status"], "codex": ["login", "status"], "opencode": ["providers", "list"]}


def _auth_from(backend: str, out: subprocess.CompletedProcess) -> dict | None:
    if backend == "claude":   # JSON: {"loggedIn": bool, "authMethod": ...}
        data = json.loads((out.stdout or "").strip() or "null")
        if isinstance(data, dict) and "loggedIn" in data:
            return {"logged_in": bool(data.get("loggedIn")), "method": data.get("authMethod")}
        return None
    text = _ANSI_RE.sub("", (out.stdout or "") + "\n" + (out.stderr or ""))
    if backend == "codex":    # exit 0 + "Logged in using …" on stderr; exit 1 + "Not logged in"
        if "not logged in" in text.lower():
            return {"logged_in": False, "method": None}
        if out.returncode == 0:
            m = re.search(r"Logged in using ([^\n-]+)", text)
            return {"logged_in": True, "method": (m.group(1).strip() if m else None)}
        return None
    if backend == "opencode":  # "N credentials" (auth.json) + "N environment variables" (provider keys)
        nums = [int(n) for n in re.findall(r"(\d+)\s+(?:credentials?|environment variables?)", text)]
        if not nums:
            return None
        return {"logged_in": sum(nums) > 0, "method": "providers" if sum(nums) else None}
    return None


def cli_auth(prefix: list[str] | None, ttl: float = 60.0, backend: str = "claude") -> dict | None:
    """Is the backend CLI signed in? → {"logged_in": bool, "method": str}, cached `ttl` s; None if
    unknown. claude: `auth status` (JSON). codex: `login status` (exit code; note CODEX_API_KEY in
    the env also works for exec although `login status` ignores it). opencode: `providers list`
    (stored credentials + detected provider env keys). Read-only: it never touches credentials."""
    if not prefix or backend not in _AUTH_ARGS:
        return None
    key = (backend, *prefix)
    hit = _AUTH_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    info = None
    try:
        out = subprocess.run([*prefix, *_AUTH_ARGS[backend]], capture_output=True, text=True, timeout=20,
                             encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        info = _auth_from(backend, out)
    except (OSError, subprocess.SubprocessError, ValueError):
        info = None
    _AUTH_CACHE[key] = (time.time(), info)
    return info


# ── subagent tracing for codex / opencode (the same trace_hook.py the claude hooks call) ──────

TRACE_EVENTS = ("SessionStart", "SubagentStart", "PreToolUse", "PostToolUse", "SubagentStop", "SessionEnd")


def trace_script(workdir) -> Path | None:
    """The lab's tracer for a run's workdir: the hub's tools/trace_hook.py or a project's
    scripts/trace_hook.py (a git worktree of a project has its own copy)."""
    w = Path(workdir)
    for rel in (("tools", "trace_hook.py"), ("scripts", "trace_hook.py")):
        f = w.joinpath(*rel)
        if f.is_file():
            return f
    return None


def codex_hook_overrides(workdir, bcfg: dict | None = None, python: str | None = None,
                         guard=None) -> list[str] | None:
    """codex exec flags that register trace_hook.py on every hook event for THIS invocation.

    Why flags and not the repo's .codex/hooks.json: codex loads a repo's .codex/ layer only when
    the project is marked trusted, and every non-managed hook (repo, user, or -c session flags)
    runs only once its hash was reviewed in the TUI's /hooks — neither holds for a headless run in
    a fresh project. So the executor passes the hooks as `-c hooks.<Event>=[…]` session flags plus
    `--dangerously-bypass-hook-trust` ("enabled hooks may run without review for this invocation";
    it applies to the user's own ~/.codex hooks too). The payload matches Claude Code's: root
    `session_id` (= the exec thread id), `agent_id`/`agent_type` inside a subagent.
    `backends.codex.trace_hooks: false` turns tracing off (subagents then show from the stream only).
    `guard` (tools/signature_guard.py) is added to PreToolUse either way: it denies a tool call that
    would forge a PI signature (exit 2)."""
    bcfg = bcfg or {}
    import sys as _sys
    py = python or _sys.executable or "python"
    script = trace_script(workdir) if bcfg.get("trace_hooks") is not False else None
    if not script and not guard:
        return None
    trace = ("{type=\"command\",command=" + _toml_str(f'"{py}" "{script}"') + ",timeout=10}") if script else None
    guard_h = ("{type=\"command\",command=" + _toml_str(f'"{py}" "{guard}"') + ",timeout=15}") if guard else None
    out = ["--dangerously-bypass-hook-trust"]
    for ev in TRACE_EVENTS:
        handlers = [h for h in ([trace, guard_h] if ev == "PreToolUse" else [trace]) if h]
        if not handlers:
            continue
        group = "{" + ('matcher="*",' if ev in ("PreToolUse", "PostToolUse") else "") + \
            f"hooks=[{','.join(handlers)}]" + "}"
        out += ["-c", f"hooks.{ev}=[{group}]"]
    return out


OPENCODE_GUARD_PLUGIN = Path(__file__).resolve().parent / "opencode_guard.js"


def opencode_guard_dir(run_dir, guard, python: str) -> Path | None:
    """A per-run OPENCODE_CONFIG_DIR holding only the signature-guard plugin. opencode searches that dir
    for plugins like a .opencode/ dir, in addition to the global and project config."""
    if not OPENCODE_GUARD_PLUGIN.is_file():
        return None
    d = Path(run_dir) / "opencode-config"
    (d / "plugins").mkdir(parents=True, exist_ok=True)
    src = OPENCODE_GUARD_PLUGIN.read_text(encoding="utf-8")
    src = src.replace("__GUARD__", json.dumps(str(guard))).replace("__PYTHON__", json.dumps(str(python)))
    (d / "plugins" / "newts-guard.js").write_text(src, encoding="utf-8")
    return d


def opencode_traced(workdir) -> bool:
    """opencode loads plugins from every .opencode/ dir between the cwd and the git worktree root;
    the lab's tracer plugin there feeds the same worker logs as the claude/codex hooks."""
    w = Path(workdir).resolve()
    for d in [w, *w.parents]:
        if (d / ".opencode" / "plugins" / "newts-trace.js").is_file():
            return True
        if (d / ".git").exists():
            break
    return False


# ── executor run command ──────────────────────────────────────────────────────

@dataclass
class RunCommand:
    argv: list[str]
    stdin_text: str | None       # written to the child's stdin then closed; None = DEVNULL
    fires_hooks: bool            # claude fires Claude Code hooks (worker logs come from trace_hook)
    notes: list[str] = field(default_factory=list)


def build_run_command(backend: str, *, prompt: str | None, workdir: Path, prog: dict,
                      cli: list[str], model: str | None = None, permission_mode: str | None = None,
                      effort: str | None = None, session_id: str | None = None,
                      resume_sid: str | None = None, max_turns: int | None = None,
                      add_dirs: list[Path] | None = None, settings_path: Path | None = None,
                      mcp_config_path: Path | None = None, permission_tool: str | None = None,
                      system_prompt_file: Path | None = None, preamble: str | None = None,
                      cli_ver: tuple | None = None, codex_hooks: list[str] | None = None,
                      opencode_traced: bool = False, live: bool = False) -> RunCommand:
    """The executor's argv for one attempt. `prompt=None` on a claude resume means "continue the
    deferred turn" (the answer rides the AskUserQuestion hook, not a new user message). `live`: the
    session stays open on stdin (tools/executor/live.py sends the prompt and everything after it)."""
    bcfg = (prog.get("backends") or {}).get(backend) or {}
    extra = str(bcfg.get("extra_args") or "")
    eff_model = _eff_model(model or prog.get("model"), bcfg)
    via = str(bcfg.get("prompt_via") or "stdin").lower()
    notes: list[str] = []

    if backend == "claude":
        _guard_extra(backend, extra, _CLAUDE_FORBID + _CLAUDE_EXECUTOR_OWNED)
        mode = bcfg.get("permission_mode") or permission_mode or prog.get("permission_mode") or "auto"
        argv = [*cli, "-p"]
        stdin_text = None
        if live:
            argv += ["--input-format", "stream-json", "--replay-user-messages",
                     "--permission-prompt-tool", "stdio"]
        elif prompt:
            if via == "argv":
                argv.append(prompt)   # MUST sit right after -p: --add-dir/--mcp-config are variadic
            else:
                stdin_text = prompt
        argv += ["--output-format", "stream-json", "--verbose"]
        if resume_sid:
            argv += ["--resume", resume_sid]   # permission mode is NOT restored on a -p resume
        elif session_id:
            argv += ["--session-id", session_id]
        if eff_model and eff_model != "inherit":
            argv += ["--model", str(eff_model)]
        argv += ["--permission-mode", str(mode)]
        eff = effort or bcfg.get("effort")
        if eff:
            argv += ["--effort", str(eff)]
        if max_turns:
            argv += ["--max-turns", str(int(max_turns))]
        if system_prompt_file:
            argv += ["--append-system-prompt-file", str(system_prompt_file)]
        if settings_path:
            argv += ["--settings", str(settings_path)]
        if mcp_config_path and permission_tool and not live:
            argv += ["--mcp-config", str(mcp_config_path), "--permission-prompt-tool", permission_tool]
        for d in add_dirs or []:
            argv += ["--add-dir", str(d)]
        for flag, minv in CLAUDE_MIN.items():
            if cli_ver and cli_ver >= minv:
                argv.append(flag)
            elif not cli_ver:
                notes.append(f"{flag} skipped (CLI version unknown)")
        if extra:
            argv += extra.split()
        return RunCommand(argv, stdin_text, True, notes)

    # codex / opencode / _dummy have no system-prompt flag: the executor preamble rides the prompt.
    text = prompt or ""
    if preamble and text:
        text = f"{text}\n\n---\n{preamble}"
    if backend == "codex":
        # codex exec [opts] [resume <thread_id>] <prompt|->   (`-` = the prompt is stdin; resume ≥0.35)
        _guard_extra(backend, extra, _CODEX_FORBID)
        argv = [*cli, "exec", *_codex_opts(bcfg, workdir, eff_model), *(codex_hooks or [])]
        if extra:
            argv += extra.split()
        if resume_sid:
            argv += ["resume", resume_sid]
        argv.append("-" if via != "argv" else text)
        traced = any("trace_hook" in str(x) for x in (codex_hooks or []))   # the guard alone logs nothing
        return RunCommand(argv, text if via != "argv" else None, traced, notes)
    if backend == "opencode":
        _guard_extra(backend, extra, _OPENCODE_FORBID)
        # opencode keeps the prompt on argv: with a live stdin its --format json mode can block on
        # the first readline (seen in practice), so its stdin is always DEVNULL.
        argv = [*cli, "run", text, "--format", "json", "--dir", str(workdir)]
        if resume_sid:
            argv += ["-s", resume_sid]
        if eff_model and eff_model != "inherit":
            argv += ["--model", str(eff_model)]
        if bcfg.get("variant"):
            argv += ["--variant", str(bcfg["variant"])]
        if bcfg.get("agent"):
            argv += ["--agent", str(bcfg["agent"])]
        if bcfg.get("skip_permissions"):
            argv += ["--dangerously-skip-permissions"]
        if extra:
            argv += extra.split()
        return RunCommand(argv, None, opencode_traced, notes)
    if backend == "_dummy":
        # Tests: the configured command is the whole argv; the prompt goes to stdin, and the resume
        # session id rides the env (the supervisor sets NEWTS_RESUME_SID).
        return RunCommand(list(cli), text or None, False, notes)
    raise SystemExit(f"[executor] unknown backend {backend!r} (claude | codex | opencode)")


# ── why a run failed: the difference between "try again later" and "something is wrong" ─────────

_USAGE_RE = re.compile(r"usage limit|rate limit|quota|too many requests|\b429\b|limit (?:reached|exceeded)|"
                       r"out of (?:credits|messages)|resets? (?:at|in)", re.I)
_TRANSIENT_RE = re.compile(r"overloaded|\b5\d\d\b|internal server error|bad gateway|service unavailable|"
                           r"econnreset|econnrefused|etimedout|timed out|network|connection (?:reset|closed|error)|"
                           r"temporar(?:y|ily)|try again", re.I)
_AUTH_RE = re.compile(r"not logged in|/login|authentication_failed|failed to authenticate|oauth session expired|"
                      r"unauthorized|\b401\b|codex login|no provider|api key", re.I)


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
    import time as _t   # noqa: PLC0415
    now = _t.time() if now is None else now
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
            lt = _t.localtime(now)
            cand = _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, hh, mm, 0, 0, 0, -1))
            return cand if cand > now else cand + 86400
    return None


# ── stream parsing ────────────────────────────────────────────────────────────

_SUMMARY_KEYS =("command", "file_path", "path", "pattern", "url", "query", "description", "skill", "prompt")


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


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(str(c.get("text") or ""))
            elif isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)
    return str(content or "")


def parse_events(backend: str, obj: dict) -> list[dict]:
    """Every activity in one stream object, normalized:
      start{session_id} · text{text,parent} · action{tool,tool_use_id,summary,parent,spawn?}
      tool_result{tool_use_id,text,is_error,parent} · begin{tool,summary} · denied{tool}
      result{last_message,session_id,stop_reason,deferred_tool_use,cost_usd,usage,is_error}
    `parent` is the tool_use_id of the Agent/Task call that spawned the subagent the message came
    from (None = the main thread) — a hook-free source for the run → subagent tree."""
    if not isinstance(obj, dict):
        return []
    t = obj.get("type")
    if backend == "claude":
        parent = obj.get("parent_tool_use_id")
        if t == "system":
            st = obj.get("subtype")
            if st == "init":
                return [{"event": "start", "status": "working", "session_id": obj.get("session_id"),
                         "model": obj.get("model")}]
            if st == "permission_denied":
                return [{"event": "denied", "tool": obj.get("tool_name"), "tool_use_id": obj.get("tool_use_id")}]
            return []
        if t == "assistant":
            out = []
            for b in ((obj.get("message") or {}).get("content") or []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text"):
                    out.append({"event": "text", "text": str(b["text"]), "parent": parent})
                elif b.get("type") == "tool_use":
                    name, inp = b.get("name"), b.get("input") or {}
                    ev = {"event": "action", "tool": name, "kind": "tool", "tool_use_id": b.get("id"),
                          "summary": summarize_input(name, inp)[:200], "parent": parent}
                    if name in ("Agent", "Task") and isinstance(inp, dict):
                        ev["spawn"] = {"subagent_type": inp.get("subagent_type") or "general-purpose",
                                       "description": str(inp.get("description") or "")[:200],
                                       "background": bool(inp.get("run_in_background"))}
                    if name == "AskUserQuestion":
                        ev["question"] = inp
                    out.append(ev)
            return out
        if t == "user":
            out = []
            content = (obj.get("message") or {}).get("content")
            for b in (content if isinstance(content, list) else []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append({"event": "tool_result", "tool_use_id": b.get("tool_use_id"),
                                "is_error": bool(b.get("is_error")), "parent": parent,
                                "text": _result_text(b.get("content"))[:2000]})
            return out
        if t == "result":
            return [{"event": "result", "last_message": obj.get("result"), "session_id": obj.get("session_id"),
                     "stop_reason": obj.get("stop_reason"), "deferred_tool_use": obj.get("deferred_tool_use"),
                     "cost_usd": obj.get("total_cost_usd"), "usage": obj.get("usage"),
                     "num_turns": obj.get("num_turns"), "is_error": obj.get("is_error"),
                     "subtype": obj.get("subtype"),
                     "denials": len(obj.get("permission_denials") or [])}]
        return []
    if backend == "opencode":
        return _parse_opencode(obj)
    return _parse_codex(obj)


_TASK_RESULT_RE = re.compile(r"<task_result>(.*?)</task_result>", re.S)


def _parse_opencode(obj: dict) -> list[dict]:
    """opencode `run --format json` (1.18): {type, timestamp, sessionID, part}. Types: step_start,
    step_finish (cost + tokens), text (a finished text part), reasoning (--thinking only), tool_use
    (emitted once the tool is completed|error — no pending/running lines), error. No init / result
    envelope: sessionID rides every line; the final message is the LAST text part (finalize on EOF).

    Only the ROOT session's parts are printed: a subagent (`task` tool) shows up once, when it
    returns, with its child session id in state.metadata.sessionId and its final answer inside
    <task_result>. Live child activity comes from the .opencode/plugins/newts-trace.js plugin."""
    t = obj.get("type")
    sid = obj.get("sessionID")
    part = obj.get("part") or {}
    if t == "tool_use":
        state = part.get("state") or {}
        tool, inp = part.get("tool"), state.get("input") or {}
        err = state.get("status") == "error"
        if tool == "task" and isinstance(inp, dict):
            call = part.get("callID") or part.get("id")
            meta = state.get("metadata") or {}
            out = str(state.get("output") or state.get("error") or "")
            m = _TASK_RESULT_RE.search(out)
            desc = str(inp.get("description") or inp.get("prompt") or "")[:200]
            return [{"event": "action", "tool": "task", "kind": "tool", "tool_use_id": call,
                     "summary": f"{inp.get('subagent_type') or 'general'}: {desc}"[:200], "session_id": sid,
                     "spawn": {"subagent_type": inp.get("subagent_type") or "general", "description": desc,
                               "child_session": meta.get("sessionId")}},
                    {"event": "tool_result", "tool_use_id": call, "is_error": err,
                     "text": (m.group(1) if m else out).strip()[:2000]}]
        summary = state.get("title") or summarize_input(tool, inp) or tool
        ev = {"event": "action", "tool": tool, "kind": "tool", "summary": str(summary or "")[:200],
              "session_id": sid, "tool_use_id": part.get("callID")}
        return [ev] + ([{"event": "tool_result", "tool_use_id": part.get("callID"), "is_error": True,
                         "text": str(state.get("error") or "")[:2000]}] if err else [])
    if t == "text" and part.get("text"):
        return [{"event": "result", "last_message": str(part["text"]), "session_id": sid},
                {"event": "text", "text": str(part["text"]), "parent": None}]
    if t == "step_finish":
        tok = part.get("tokens") or {}
        usage = {k: tok[k] for k in ("input", "output", "reasoning") if isinstance(tok.get(k), (int, float))}
        cache = tok.get("cache") or {}
        if isinstance(cache.get("read"), (int, float)):
            usage["cache_read"] = cache["read"]
        return [{"event": "usage", "usage": usage, "cost_delta": part.get("cost"), "session_id": sid},
                {"event": "start", "status": "working", "session_id": sid}]
    if t == "error":
        err = obj.get("error") or {}
        msg = (err.get("data") or {}).get("message") or err.get("name") or "opencode error"
        return [{"event": "result", "last_message": f"[error] {msg}", "session_id": sid, "is_error": True}]
    return [{"event": "start", "status": "working", "session_id": sid}] if sid else []


def _parse_codex(obj: dict) -> list[dict]:
    """codex `exec --json` ThreadEvents (the _dummy test backend mimics this shape): thread.started
    {thread_id} · turn.started · turn.completed {usage} · turn.failed {error} · item.started /
    item.updated (todo_list only) / item.completed {item} · error. Only the PRIMARY thread's items
    stream; subagents appear as `collab_tool_call` items (spawn_agent / send_input / wait /
    close_agent) with receiver_thread_ids + agents_states — their own tool calls come from the codex
    hooks (.codex/hooks.json → trace_hook.py), not from this stream."""
    t = obj.get("type")
    if t == "thread.started":
        return [{"event": "start", "status": "working",
                 "session_id": obj.get("thread_id") or obj.get("session_id")}]
    if t in ("item.started", "item.completed"):
        it = obj.get("item") or {}
        itype = it.get("type")
        if itype in ("collab_tool_call", "collab_agent_tool_call"):
            return _codex_collab(t, it)
        # codex has emitted both singular and plural item type names across versions
        if itype in ("command_execution", "mcp_tool_call", "mcp_tool_calls", "web_search",
                     "web_searches", "file_change", "file_changes"):
            tool = itype
            if itype.startswith("mcp_tool_call") and it.get("tool"):
                tool = f"mcp__{it.get('server') or 'mcp'}__{it['tool']}"
            summary = it.get("command") or it.get("query")
            if not summary and isinstance(it.get("changes"), list):
                summary = ", ".join(str((c or {}).get("path") or "") for c in it["changes"][:4])
            summary = str(summary or it.get("status") or itype)[:200]
            if t == "item.started":
                return [{"event": "begin", "tool": tool, "summary": summary}]
            out = [{"event": "action", "tool": tool, "kind": "tool", "summary": summary, "tool_use_id": it.get("id")}]
            if it.get("status") == "declined":
                out.append({"event": "denied", "tool": tool, "tool_use_id": it.get("id")})
            return out
        if itype == "agent_message" and t == "item.completed":
            return [{"event": "result", "last_message": str(it.get("text") or "")[:2000]},
                    {"event": "text", "text": str(it.get("text") or "")[:800], "parent": None}]
    if t == "turn.completed" and isinstance(obj.get("usage"), dict):
        return [{"event": "usage", "usage": obj["usage"]}]
    if t == "turn.failed":
        msg = (obj.get("error") or {}).get("message") or "turn failed"
        return [{"event": "result", "last_message": f"[error] {msg}", "is_error": True}]
    if t == "error":
        return [{"event": "result", "last_message": f"[error] {obj.get('message') or 'codex error'}"}]
    return []


def _codex_collab(t: str, it: dict) -> list[dict]:
    """A codex multi-agent call → the executor's subagent events, keyed by the child thread id."""
    tool = it.get("tool") or "collab"
    states = it.get("agents_states") if isinstance(it.get("agents_states"), dict) else {}
    receivers = [r for r in (it.get("receiver_thread_ids") or []) if r] or list(states)
    out: list[dict] = []
    if tool == "spawn_agent":
        if t != "item.completed":
            return [{"event": "begin", "tool": "spawn_agent", "summary": str(it.get("prompt") or "")[:200]}]
        desc = str(it.get("prompt") or "")[:200]
        for tid in receivers:
            out.append({"event": "action", "tool": "spawn_agent", "kind": "tool", "tool_use_id": tid,
                        "summary": f"subagent: {desc}"[:200],
                        "spawn": {"subagent_type": str(it.get("agent_type") or it.get("agent_name") or "subagent"),
                                  "description": desc, "child_session": tid}})
    elif t == "item.completed":
        out.append({"event": "action", "tool": tool, "kind": "tool",
                    "summary": f"{tool} {', '.join(r[:8] for r in receivers)}"[:200]})
    for tid, stt in states.items():
        status = (stt or {}).get("status") if isinstance(stt, dict) else None
        if t == "item.completed" and status in ("completed", "errored", "interrupted", "shutdown", "not_found"):
            out.append({"event": "tool_result", "tool_use_id": tid, "is_error": status != "completed",
                        "text": str((stt or {}).get("message") or status)[:2000]})
    return out


def parse_activity(backend: str, obj: dict) -> dict | None:
    """Legacy single-activity view (agent_runner.py): the first action/result/start in the object."""
    for ev in parse_events(backend, obj):
        if ev.get("event") in ("action", "result", "start"):
            return ev
    return None
