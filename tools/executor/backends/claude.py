"""claude — Claude Code (`claude -p`).

Live: `--input-format stream-json --permission-prompt-tool stdio` (the Agent SDK's channel). User turns
and control responses go in on stdin; stdout is stream-json plus `control_request`s (can_use_tool:
AskUserQuestion and permission prompts). One-shot: the prompt on stdin; questions end the turn.
The run's standing instructions ride `--append-system-prompt-file`; hooks come from `--settings`.
"""

from __future__ import annotations

import json

from .. import live
from . import (ANSI_RE, Attempt, Backend, RunCommand, TRACE_EVENTS, summarize_input)  # noqa: F401

# flags newer than some installs: only passed when the resolved CLI is at least this version
MIN_VERSION = {"--forward-subagent-text": (2, 1, 211)}
GUARD_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"


class Claude(Backend):
    name = "claude"
    ask_tool = "AskUserQuestion"
    native_slash = True
    probe_version = True
    preassign_session = True     # resumable even if it dies before its init line
    waits_for_background = True  # `claude -p` waits for background subagents (the ceiling is lifted below)
    env_auth = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
    auth_args = ["auth", "status"]
    sign_in_hint = "the claude CLI is not logged in — in a terminal run `claude`, then /login (your own account)"
    forbid = ("--permission-mode", "--dangerously-skip-permissions", "--settings", "--mcp-config",
              "--permission-prompt-tool", "--resume", "--input-format", "--replay-user-messages", "--session-id",
              "--add-dir", "--continue", "--fork-session", "--append-system-prompt", "--append-system-prompt-file",
              "--allow-dangerously-skip-permissions")

    def prepare(self, a: Attempt) -> None:
        # background subagents are waited for only up to a 10-minute ceiling by default; a lab runner in
        # a long PILOT must not be cut off — the executor's own watchdog bounds the run
        a.env.setdefault("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", "0")
        a.settings = _settings(a)
        if a.tracer:
            a.env["NEWTS_TRACE_FLAGS"] = "1"   # the repo's own trace hooks (--from-repo) stand down
        if a.preamble:
            a.system_prompt_file = a.rd / "preamble.md"
        if a.m.get("level") == "project":
            a.add_dirs = [a.lab.hub]           # the lifecycle skills live in the hub

    def command(self, a: Attempt) -> RunCommand:
        self.check_extra(a)
        bcfg, notes = a.bcfg, []
        argv, stdin_text = [*a.cli, "-p"], None
        if a.live:
            argv += ["--input-format", "stream-json", "--replay-user-messages", "--permission-prompt-tool", "stdio"]
        elif a.prompt:
            if str(bcfg.get("prompt_via") or "stdin").lower() == "argv":
                argv.append(a.prompt)   # MUST sit right after -p: --add-dir is variadic
            else:
                stdin_text = a.prompt
        argv += ["--output-format", "stream-json", "--verbose"]
        if a.resume_sid:
            argv += ["--resume", a.resume_sid]   # the permission mode is NOT restored on a -p resume
        elif a.m.get("session_id"):
            argv += ["--session-id", a.m["session_id"]]
        if a.model:
            argv += ["--model", str(a.model)]
        argv += ["--permission-mode", str(bcfg.get("permission_mode") or a.m.get("permission_mode")
                                          or a.prog.get("permission_mode") or "auto")]
        if a.m.get("effort") or bcfg.get("effort"):
            argv += ["--effort", str(a.m.get("effort") or bcfg.get("effort"))]
        if a.m.get("max_turns"):
            argv += ["--max-turns", str(int(a.m["max_turns"]))]
        if a.system_prompt_file:
            argv += ["--append-system-prompt-file", str(a.system_prompt_file)]
        if a.settings:
            argv += ["--settings", str(a.settings)]
        for d in a.add_dirs:
            argv += ["--add-dir", str(d)]
        for flag, minv in MIN_VERSION.items():
            if a.ver and a.ver >= minv:
                argv.append(flag)
            elif not a.ver:
                notes.append(f"{flag} skipped (CLI version unknown)")
        return RunCommand(argv + a.extra.split(), stdin_text, True, notes)

    def session(self, a: Attempt):
        return ClaudeSession(a.prompt, a.m.get("session_id"))

    def auth(self, out) -> dict | None:   # JSON: {"loggedIn": bool, "authMethod": ...}
        data = json.loads((out.stdout or "").strip() or "null")
        if isinstance(data, dict) and "loggedIn" in data:
            return {"logged_in": bool(data.get("loggedIn")), "method": data.get("authMethod")}
        return None

    def parse(self, obj: dict) -> list[dict]:
        t, parent = obj.get("type"), obj.get("parent_tool_use_id")
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
                    out.append(ev)
            return out
        if t == "user":
            content = (obj.get("message") or {}).get("content")
            return [{"event": "tool_result", "tool_use_id": b.get("tool_use_id"), "is_error": bool(b.get("is_error")),
                     "parent": parent, "text": _result_text(b.get("content"))[:2000]}
                    for b in (content if isinstance(content, list) else [])
                    if isinstance(b, dict) and b.get("type") == "tool_result"]
        if t == "result":
            return [{"event": "result", "last_message": obj.get("result"), "session_id": obj.get("session_id"),
                     "stop_reason": obj.get("stop_reason"), "cost_usd": obj.get("total_cost_usd"),
                     "usage": obj.get("usage"), "num_turns": obj.get("num_turns"), "is_error": obj.get("is_error"),
                     "subtype": obj.get("subtype"), "denials": len(obj.get("permission_denials") or [])}]
        return []


def _result_text(content) -> str:
    if isinstance(content, list):
        return "\n".join(str(c.get("text") or "") if isinstance(c, dict) else str(c) for c in content
                         if isinstance(c, str) or (isinstance(c, dict) and c.get("type") == "text"))
    return str(content or "")


def _settings(a: Attempt):
    """Per-run settings: the signature guard, the tracer, and ONE permission — the lab's own bus
    commands (`lab_bus.py emit|escalate`: the run footer, a campaign's dispatch). Those only append an
    event to the lab's record, and the run can't report back without them; claude's `auto` classifier
    was seen refusing the footer. Everything else stays with the PI's permission mode. The tracer runs
    with this interpreter's absolute path; the repo's own `.claude/settings.json` hooks (`--from-repo`)
    stand down for the run (NEWTS_TRACE_FLAGS=1), so a machine with only `python3` — or a repo whose
    tracing files are stale — is still traced, once."""
    py = a.python
    hooks = {"PreToolUse": [{"matcher": GUARD_MATCHER, "hooks": [
        {"type": "command", "command": f'"{py}" "{a.guard}"', "timeout": 15}]}] if a.guard else []}
    if a.tracer:
        trace = {"type": "command", "command": f'"{py}" "{a.tracer}"', "timeout": 10}
        for ev in TRACE_EVENTS:
            hooks.setdefault(ev, []).append(
                {"matcher": "*", "hooks": [trace]} if ev in ("PreToolUse", "PostToolUse") else {"hooks": [trace]})
    b = a.bus.as_posix()
    allow = [f"Bash({exe} {path} {sub}:*)" for exe in ("python", "python3", f'"{py}"', py)
             for path in (b, f'"{b}"') for sub in ("emit", "escalate")]
    sp = a.rd / "settings.json"
    sp.write_text(json.dumps({"hooks": hooks, "permissions": {"allow": allow}}, indent=2), encoding="utf-8")
    return sp


class ClaudeSession(live.Session):
    _n = 0

    def open(self, proc) -> None:
        self.proc = proc
        self._control({"subtype": "initialize", "hooks": None})
        self.send(self.prompt)

    def _control(self, request: dict) -> bool:
        self._n += 1
        return self._write({"type": "control_request", "request_id": f"newts_{self._n}", "request": request})

    def send(self, text: str) -> bool:
        ok = self._write({"type": "user", "message": {"role": "user", "content": text},
                          "parent_tool_use_id": None, "session_id": self.session_id})
        if ok:
            self.unread += 1   # until the CLI echoes it back (--replay-user-messages)
        return ok

    def interrupt(self) -> bool:
        return self._control({"subtype": "interrupt"})

    def respond(self, req: dict, item: dict) -> bool:
        """A question (item: answers/response) or a permission (item: allow/message)."""
        inp = req.get("input") or {}
        if req["kind"] == "question" and item.get("allow") is not False:
            upd = {**inp, "answers": {k: (", ".join(v) if isinstance(v, list) else v)
                                      for k, v in (item.get("answers") or {}).items()}}
            if item.get("response"):
                upd["response"] = str(item["response"])
            resp = {"behavior": "allow", "updatedInput": upd}
        elif req["kind"] == "permission" and item.get("allow"):
            resp = {"behavior": "allow", "updatedInput": inp}
        else:
            resp = {"behavior": "deny", "message": item.get("message") or "The PI declined."}
        return self._write({"type": "control_response", "response": {
            "subtype": "success", "request_id": req["id"], "response": resp}})

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        t = obj.get("type")
        if t == "control_request":
            r = obj.get("request") or {}
            if r.get("subtype") == "can_use_tool":
                tool = r.get("tool_name")
                return [obj], [{"event": "request", "id": obj.get("request_id"), "tool": tool,
                                "kind": "question" if tool == "AskUserQuestion" else "permission",
                                "input": r.get("input") or {}, "tool_use_id": r.get("tool_use_id"),
                                "why": r.get("decision_reason") or r.get("description")}]
            # anything else the CLI asks of the host (hook callbacks, MCP) — we register none
            self._write({"type": "control_response", "response": {
                "subtype": "error", "request_id": obj.get("request_id"), "error": "not supported"}})
            return [obj], []
        if t == "control_cancel_request":
            return [obj], [{"event": "cancelled", "id": obj.get("request_id")}]
        if t == "user" and _is_replay(obj):
            self.unread = max(0, self.unread - 1)
        elif t == "system" and obj.get("subtype") == "init" and obj.get("session_id"):
            self.session_id = obj["session_id"]
        elif t == "result":
            return [obj], [{"event": "turn_end"}]
        elif t == "rate_limit_event":
            info = obj.get("rate_limit_info") or {}
            return [obj], [{"event": "limits", "status": info.get("status"), "resets_at": info.get("resetsAt"),
                            "type": info.get("rateLimitType")}]
        return [obj], []


def _is_replay(obj: dict) -> bool:
    """A user line echoing a message we sent (not a tool result)."""
    c = (obj.get("message") or {}).get("content")
    return isinstance(c, str) or (isinstance(c, list) and bool(c)
                                  and all(isinstance(b, dict) and b.get("type") == "text" for b in c))
