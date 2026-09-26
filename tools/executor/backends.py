"""Backends: argv builders, CLI resolution, and stream parsing for claude / codex / opencode.

`build_command` keeps the exact legacy contract agent_runner.py has always exposed (argv starting
with the bare CLI name, prompt as argv). `build_run_command` is the executor's builder: resolved CLI
path, prompt via stdin (dodges the ~32K Windows command-line limit), session pre-assignment / resume,
the per-run settings + MCP permission host, and hub skill access for project runs.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

BACKENDS = ("claude", "codex", "opencode")
_VERSION_CACHE: dict[tuple, tuple | None] = {}

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
_CLAUDE_EXECUTOR_OWNED = ("--settings", "--mcp-config", "--permission-prompt-tool", "--resume",
                          "--session-id", "--add-dir", "--continue", "--fork-session",
                          "--append-system-prompt", "--append-system-prompt-file",
                          "--allow-dangerously-skip-permissions")
_CODEX_FORBID = ("--sandbox", "-a", "--ask-for-approval", "--dangerously-bypass-approvals-and-sandbox", "--yolo")
_OPENCODE_FORBID = ("--dangerously-skip-permissions", "--dir", "--format")


def _eff_model(model, bcfg: dict):
    # An explicit launch/global model wins; otherwise the backend's own default.
    return model if (model and model != "inherit") else (bcfg.get("model") or "inherit")


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
        cmd = ["codex", "exec", prompt, "--json",
               "--sandbox", str(bcfg.get("sandbox") or "workspace-write"),
               "-a", str(bcfg.get("approval") or "never"),
               "--skip-git-repo-check", "-C", str(pdir)]
        if bcfg.get("network_access"):   # workspace-write disables network by default; opt-in per genuine need
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if bcfg.get("reasoning_effort"):   # codex has no --effort flag; it's a config override
            cmd += ["-c", f"model_reasoning_effort={bcfg['reasoning_effort']}"]
        if eff_model and eff_model != "inherit":
            cmd += ["-m", str(eff_model)]
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


def resolve_cli(backend: str, bcfg: dict | None = None) -> list[str] | None:
    """The argv PREFIX that runs a backend CLI, or None if it can't be found.

    `backends.<b>.command` wins: a string is one executable path (never split — Windows paths have
    spaces), a list is a full prefix (e.g. [python, fake_cli.py] in tests). Then PATH, then the usual
    per-platform install locations (the Claude installer puts claude.exe in ~/.local/bin, which is
    often not on a GUI-launched process's PATH). `.exe` beats a `.cmd` shim on Windows.
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
    for c in _candidates(backend):
        if c.is_file():
            return [str(c)]
    return None


def cli_version(prefix: list[str] | None) -> tuple | None:
    """(major, minor, patch) from `<cli> --version`, cached per prefix. None if unknown."""
    if not prefix:
        return None
    key = tuple(prefix)
    if key in _VERSION_CACHE:
        return _VERSION_CACHE[key]
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
    _VERSION_CACHE[key] = ver
    return ver


def version_str(v) -> str | None:
    return ".".join(str(x) for x in v) if v else None


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
                      cli_ver: tuple | None = None) -> RunCommand:
    """The executor's argv for one attempt. `prompt=None` on a claude resume means "continue the
    deferred turn" (the answer rides the AskUserQuestion hook, not a new user message)."""
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
        if prompt:
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
        if mcp_config_path and permission_tool:
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
        if resume_sid:
            raise SystemExit("[executor] resuming a codex session is not supported yet — start a new run")
        _guard_extra(backend, extra, _CODEX_FORBID)
        argv = [*cli, "exec", "-" if via != "argv" else text, "--json",
                "--sandbox", str(bcfg.get("sandbox") or "workspace-write"),
                "-a", str(bcfg.get("approval") or "never"), "--skip-git-repo-check", "-C", str(workdir)]
        if bcfg.get("network_access"):
            argv += ["-c", "sandbox_workspace_write.network_access=true"]
        if bcfg.get("reasoning_effort"):
            argv += ["-c", f"model_reasoning_effort={bcfg['reasoning_effort']}"]
        if eff_model and eff_model != "inherit":
            argv += ["-m", str(eff_model)]
        if extra:
            argv += extra.split()
        return RunCommand(argv, text if via != "argv" else None, False, notes)
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
        return RunCommand(argv, None, False, notes)
    if backend == "_dummy":
        # Tests: the configured command is the whole argv; the prompt goes to stdin, and the resume
        # session id rides the env (the supervisor sets NEWTS_RESUME_SID).
        return RunCommand(list(cli), text or None, False, notes)
    raise SystemExit(f"[executor] unknown backend {backend!r} (claude | codex | opencode)")


# ── stream parsing ────────────────────────────────────────────────────────────

_SUMMARY_KEYS = ("command", "file_path", "path", "pattern", "url", "query", "description", "skill", "prompt")


def summarize_input(tool: str | None, inp) -> str:
    if not isinstance(inp, dict):
        return str(inp or "")[:400]
    if tool in ("Agent", "Task"):
        st = inp.get("subagent_type") or "general-purpose"
        return f"{st}: {inp.get('description') or inp.get('prompt') or ''}"[:400]
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
                                       "description": str(inp.get("description") or "")[:200]}
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
        # NDJSON: {type, timestamp, sessionID, part{…}}; no init event, no single result envelope —
        # sessionID rides every line and the final message is the LAST `text` part (finalize on EOF).
        sid = obj.get("sessionID")
        part = obj.get("part") or {}
        if t == "tool_use":
            state = part.get("state") or {}
            summary = state.get("title") or state.get("input") or part.get("tool")
            return [{"event": "action", "tool": part.get("tool"), "kind": "tool",
                     "summary": str(summary or "")[:200], "session_id": sid}]
        if t == "text" and part.get("text"):
            return [{"event": "result", "last_message": str(part["text"]), "session_id": sid}]
        if t == "error":
            err = obj.get("error") or {}
            msg = (err.get("data") or {}).get("message") or err.get("name") or "opencode error"
            return [{"event": "result", "last_message": f"[error] {msg}", "session_id": sid}]
        return [{"event": "start", "status": "working", "session_id": sid}] if sid else []
    # codex (and the _dummy test backend mimics codex's ThreadEvent JSONL shape)
    if t == "thread.started":
        return [{"event": "start", "status": "working",
                 "session_id": obj.get("thread_id") or obj.get("session_id")}]
    if t in ("item.started", "item.completed"):
        it = obj.get("item") or {}
        itype = it.get("type")
        # codex has emitted both singular and plural item type names across versions
        if itype in ("command_execution", "mcp_tool_call", "mcp_tool_calls", "web_search",
                     "web_searches", "file_change", "file_changes"):
            summary = str(it.get("command") or it.get("query") or it.get("status") or itype)[:200]
            if t == "item.started":
                return [{"event": "begin", "tool": itype, "summary": summary}]
            return [{"event": "action", "tool": itype, "kind": "tool", "summary": summary}]
        if itype == "agent_message" and t == "item.completed":
            return [{"event": "result", "last_message": str(it.get("text") or "")[:2000]}]
    if t == "turn.completed" and isinstance(obj.get("usage"), dict):
        return [{"event": "usage", "usage": obj["usage"]}]
    if t == "error":
        return [{"event": "result", "last_message": f"[error] {obj.get('message') or 'codex error'}"}]
    return []


def parse_activity(backend: str, obj: dict) -> dict | None:
    """Legacy single-activity view (agent_runner.py): the first action/result/start in the object."""
    for ev in parse_events(backend, obj):
        if ev.get("event") in ("action", "result", "start"):
            return ev
    return None
