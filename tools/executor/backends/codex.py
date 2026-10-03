"""codex — OpenAI Codex (`codex app-server` live, `codex exec --json` one-shot).

Live: JSON-RPC (without the "jsonrpc" field) over stdio. One thread; each user message is a turn (or
steers the running one). Approvals and `requestUserInput` arrive as server requests. The app-server's
lines are translated to `codex exec --json` ThreadEvents, so one parser and one transcript view serve
both modes. Tracing: the lab's hooks as `-c hooks.*` overrides (a headless run can't review hook trust in
the TUI), trusted per run.
"""

from __future__ import annotations

import re

from .. import live
from ..lab import profile
from . import ANSI_RE, TRACE_EVENTS, Attempt, Backend, RunCommand, toml_str, trace_script, with_preamble


class Codex(Backend):
    name = "codex"
    ask_tool = "request_user_input"
    probe_version = True
    env_auth = ("CODEX_API_KEY", "OPENAI_API_KEY")
    auth_args = ["login", "status"]
    sign_in_hint = "the codex CLI is not signed in — in a terminal run `codex login` (your own account)"
    forbid = ("--sandbox", "-s", "-a", "--ask-for-approval", "--dangerously-bypass-approvals-and-sandbox",
              "--yolo", "--full-auto", "--approve-for-me", "--not-so-yolo", "resume", "fork")

    def prepare(self, a: Attempt) -> None:
        a.hooks = hook_overrides(a.workdir, a.bcfg, a.python, guard=a.guard)
        a.traced = any(profile.TRACER.name in str(x) for x in (a.hooks or []))   # the guard alone logs nothing
        if a.traced:
            a.env["NEWTS_TRACE_FLAGS"] = "1"   # a trusted repo's own .codex/hooks.json then stands down

    def command(self, a: Attempt) -> RunCommand:
        if a.live:   # per-run settings (cwd, model, sandbox, approvals, instructions) ride thread/start
            hooks = [x for x in (a.hooks or []) if x != "--dangerously-bypass-hook-trust"]
            notes = ["extra_args ignored for a live codex session"] if a.extra else []
            return RunCommand([*a.cli, *hooks, "app-server"], None, a.traced, notes)
        # codex exec [opts] [resume <thread_id>] <prompt|->   (`-` = the prompt is on stdin)
        self.check_extra(a)
        text, via_argv = with_preamble(a), str(a.bcfg.get("prompt_via") or "").lower() == "argv"
        argv = [*a.cli, "exec", *_exec_opts(a), *(a.hooks or []), *a.extra.split()]
        if a.resume_sid:
            argv += ["resume", a.resume_sid]
        argv.append(text if via_argv else "-")
        return RunCommand(argv, None if via_argv else text, a.traced)

    def session(self, a: Attempt):
        return CodexSession(a.prompt, a.resume_sid, thread=thread_params(a))

    def auth(self, out) -> dict | None:   # exit 0 + "Logged in using …" on stderr; "Not logged in" otherwise
        text = ANSI_RE.sub("", (out.stdout or "") + "\n" + (out.stderr or ""))
        if "not logged in" in text.lower():
            return {"logged_in": False, "method": None}
        if out.returncode == 0:
            m = re.search(r"Logged in using ([^\n-]+)", text)
            return {"logged_in": True, "method": (m.group(1).strip() if m else None)}
        return None

    def parse(self, obj: dict) -> list[dict]:
        """`codex exec --json` ThreadEvents: thread.started{thread_id} · turn.completed{usage} ·
        turn.failed{error} · item.started / item.completed{item} · error. Only the PRIMARY thread's
        items stream; subagents appear as `collab_tool_call` items with receiver_thread_ids +
        agents_states — their own tool calls come from the codex hooks, not from this stream."""
        t = obj.get("type")
        if t == "thread.started":
            return [{"event": "start", "status": "working", "session_id": obj.get("thread_id") or obj.get("session_id")}]
        if t in ("item.started", "item.completed"):
            it = obj.get("item") or {}
            itype = it.get("type")
            if itype in ("collab_tool_call", "collab_agent_tool_call"):
                return _collab(t, it)
            # codex has emitted both singular and plural item type names across versions
            if itype in ("command_execution", "mcp_tool_call", "mcp_tool_calls", "web_search",
                         "web_searches", "file_change", "file_changes"):
                tool = f"mcp__{it.get('server') or 'mcp'}__{it['tool']}" \
                    if itype.startswith("mcp_tool_call") and it.get("tool") else itype
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
            return [{"event": "result", "last_message": f"[error] {(obj.get('error') or {}).get('message') or 'turn failed'}",
                     "is_error": True}]
        if t == "error":
            return [{"event": "result", "last_message": f"[error] {obj.get('message') or 'codex error'}"}]
        return []


def _collab(t: str, it: dict) -> list[dict]:
    """A codex multi-agent call → the executor's subagent events, keyed by the child thread id."""
    tool = it.get("tool") or "collab"
    states = it.get("agents_states") if isinstance(it.get("agents_states"), dict) else {}
    receivers = [r for r in (it.get("receiver_thread_ids") or []) if r] or list(states)
    out: list[dict] = []
    if tool == "spawn_agent":
        if t != "item.completed":
            return [{"event": "begin", "tool": "spawn_agent", "summary": str(it.get("prompt") or "")[:200]}]
        desc = str(it.get("prompt") or "")[:200]
        out += [{"event": "action", "tool": "spawn_agent", "kind": "tool", "tool_use_id": tid,
                 "summary": f"subagent: {desc}"[:200],
                 "spawn": {"subagent_type": str(it.get("agent_type") or it.get("agent_name") or "subagent"),
                           "description": desc, "child_session": tid}} for tid in receivers]
    elif t == "item.completed":
        out.append({"event": "action", "tool": tool, "kind": "tool",
                    "summary": f"{tool} {', '.join(r[:8] for r in receivers)}"[:200]})
    for tid, stt in states.items():
        status = (stt or {}).get("status") if isinstance(stt, dict) else None
        if t == "item.completed" and status in ("completed", "errored", "interrupted", "shutdown", "not_found"):
            out.append({"event": "tool_result", "tool_use_id": tid, "is_error": status != "completed",
                        "text": str((stt or {}).get("message") or status)[:2000]})
    return out


def _exec_opts(a: Attempt) -> list[str]:
    """`codex exec` options (they go BEFORE the `resume` subcommand: -s / -C are exec-level flags the
    resume inherits). exec has no -a flag: it runs approval_policy=never, so a stricter `approval` is a
    config override under which such ops are rejected (exec can't ask)."""
    bcfg = a.bcfg
    opts = ["--json", "--sandbox", str(bcfg.get("sandbox") or "workspace-write"), "--skip-git-repo-check",
            "-C", str(a.workdir)]
    if str(bcfg.get("approval") or "never") != "never":
        opts += ["-c", f"approval_policy={toml_str(bcfg['approval'])}"]
    if bcfg.get("network_access"):   # workspace-write disables network by default; opt-in per genuine need
        opts += ["-c", "sandbox_workspace_write.network_access=true"]
    if bcfg.get("reasoning_effort"):   # codex has no --effort flag; it's a config override
        opts += ["-c", f"model_reasoning_effort={toml_str(bcfg['reasoning_effort'])}"]
    if a.model:
        opts += ["-m", str(a.model)]
    return opts


def thread_params(a: Attempt) -> dict:
    """thread/start params for a live session: the same posture as `codex exec` (sandbox, model,
    effort, network), plus approvals that reach the PI (`approval`, default on-request: a
    sandbox-blocked step asks instead of failing) and questions (request_user_input)."""
    bcfg = a.bcfg
    cfg = {"features.default_mode_request_user_input": True, "suppress_unstable_features_warning": True}
    if bcfg.get("network_access"):
        cfg["sandbox_workspace_write.network_access"] = True
    if a.m.get("effort") or bcfg.get("reasoning_effort"):
        cfg["model_reasoning_effort"] = str(a.m.get("effort") or bcfg["reasoning_effort"])
    if a.hooks:
        cfg["bypass_hook_trust"] = True   # this run's -c hooks (app-server reads it per thread)
    params = {"cwd": str(a.workdir), "sandbox": str(bcfg.get("sandbox") or "workspace-write"),
              "approvalPolicy": str(bcfg.get("approval") or "on-request"), "config": cfg}
    if a.model:
        params["model"] = str(a.model)
    if a.preamble:
        params["developerInstructions"] = a.preamble
    return params


def hook_overrides(workdir, bcfg: dict | None = None, python: str = "python", guard=None) -> list[str] | None:
    """`-c hooks.<Event>=[…]` flags that register trace_hook.py on every hook event for THIS invocation,
    plus `--dangerously-bypass-hook-trust` (one-shot; a live thread gets bypass_hook_trust instead).

    Why flags and not the repo's .codex/hooks.json: codex loads a repo's .codex/ layer only when the
    project is marked trusted, and every non-managed hook runs only once its hash was reviewed in the
    TUI's /hooks — neither holds for a headless run in a fresh project. The payload matches Claude
    Code's: root `session_id` (= the thread id), `agent_id`/`agent_type` inside a subagent.
    `backends.codex.trace_hooks: false` turns tracing off. `guard` (tools/signature_guard.py) is added
    to PreToolUse either way: it denies a tool call that would forge a PI signature (exit 2)."""
    script = trace_script(workdir) if (bcfg or {}).get("trace_hooks") is not False else None
    if not script and not guard:
        return None
    trace = ("{type=\"command\",command=" + toml_str(f'"{python}" "{script}"') + ",timeout=10}") if script else None
    guard_h = ("{type=\"command\",command=" + toml_str(f'"{python}" "{guard}"') + ",timeout=15}") if guard else None
    out = ["--dangerously-bypass-hook-trust"]
    for ev in TRACE_EVENTS:
        handlers = [h for h in ([trace, guard_h] if ev == "PreToolUse" else [trace]) if h]
        if handlers:
            group = "{" + ('matcher="*",' if ev in ("PreToolUse", "PostToolUse") else "") + \
                f"hooks=[{','.join(handlers)}]" + "}"
            out += ["-c", f"hooks.{ev}=[{group}]"]
    return out


def _snake(s: str) -> str:
    return "".join("_" + ch.lower() if ch.isupper() else ch for ch in str(s))


class CodexSession(live.Session):
    """ctx: thread = the thread/start params."""

    def __init__(self, prompt, session_id=None, **ctx):
        super().__init__(prompt, session_id, **ctx)
        self._id = 0
        self._calls: dict = {}
        self.turn: str | None = None
        self.usage: dict | None = None

    def _rpc(self, method: str, params: dict) -> int:
        self._id += 1
        self._calls[self._id] = method
        self._write({"id": self._id, "method": method, "params": params})
        return self._id

    def open(self, proc) -> None:
        self.proc = proc
        self._rpc("initialize", {"clientInfo": {"name": "newts-lab", "title": "Newts' Lab", "version": "1"},
                                 "capabilities": {"experimentalApi": True}})

    def send(self, text: str) -> bool:
        inp = [{"type": "text", "text": text}]
        if self.turn:
            self._rpc("turn/steer", {"threadId": self.session_id, "input": inp, "expectedTurnId": self.turn})
            return True
        self.unread += 1
        self._rpc("turn/start", {"threadId": self.session_id, "input": inp})
        return True

    def interrupt(self) -> bool:
        if self.turn:
            self._rpc("turn/interrupt", {"threadId": self.session_id, "turnId": self.turn})
        return True

    def respond(self, req: dict, item: dict) -> bool:
        if req["kind"] == "question":
            qs = (req.get("input") or {}).get("questions") or []
            labels = live.answer_labels(req, item)
            result = {"answers": {q.get("id"): {"answers": [x for x in a if x]} for q, a in zip(qs, labels)}}
        else:
            result = {"decision": "accept" if item.get("allow") else "decline"}
        return self._write({"id": req["rpc_id"], "result": result})

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        m, p = obj.get("method"), obj.get("params") or {}
        if m and "id" in obj:                                      # a server → client request
            return self._request(obj["id"], m, p)
        if "id" in obj:                                            # a response to one of ours
            return self._response(self._calls.pop(obj["id"], None), obj)
        if m == "turn/started":
            self.turn, self.unread = (p.get("turn") or {}).get("id"), 0
            return [{"type": "turn.started"}], []
        if m in ("item/started", "item/completed"):
            it = p.get("item") or {}
            if it.get("type") in ("userMessage", "reasoning", "plan"):
                return [], []
            item = {_snake(k): (_snake(v) if k in ("type", "tool") and isinstance(v, str) else v) for k, v in it.items()}
            if item.get("type") == "collab_agent_tool_call":
                item["type"] = "collab_tool_call"
            return [{"type": m.replace("/", "."), "item": item}], []
        if m == "thread/tokenUsage/updated":
            self.usage = (p.get("tokenUsage") or {}).get("total")
            return [], []
        if m == "turn/completed":
            t, u = p.get("turn") or {}, self.usage or {}
            self.turn = None
            lines = [{"type": "turn.completed", "usage": {"input_tokens": u.get("inputTokens", 0),
                                                         "cached_input_tokens": u.get("cachedInputTokens", 0),
                                                         "output_tokens": u.get("outputTokens", 0)}}]
            if t.get("status") == "failed":
                self.error = self.error or ((t.get("error") or {}).get("message")) or "turn failed"
                lines.append({"type": "turn.failed", "error": {"message": self.error}})
            return lines, [{"event": "turn_end"}]
        if m == "error" and not p.get("willRetry"):
            e = p.get("error") or {}
            info = e.get("codexErrorInfo")
            self.error = f"{e.get('message') or 'codex error'}" + (f" ({info})" if info else "")
            return [{"type": "error", "message": self.error}], []
        if m == "account/rateLimits/updated":
            rl = p.get("rateLimits") or {}
            prim = rl.get("primary") or {}
            hit = rl.get("rateLimitReachedType") or (prim.get("usedPercent") or 0) >= 100
            return [], [{"event": "limits", "status": "rejected" if hit else "allowed",
                         "resets_at": prim.get("resetsAt"), "type": rl.get("limitId")}]
        if m == "serverRequest/resolved":
            return [], [{"event": "cancelled", "id": f"codex-{p.get('requestId')}"}]
        return [], []

    def _response(self, method, obj) -> tuple[list[dict], list[dict]]:
        if obj.get("error"):
            if method == "turn/steer":                  # the turn ended meanwhile: start a new one
                self.turn = None
                return [], []
            self.error = f"{method}: {(obj['error'] or {}).get('message')}"
            self.close()
            return [{"type": "error", "message": self.error}], []
        res = obj.get("result") or {}
        if method == "initialize":
            self._write({"method": "initialized"})
            params = dict(self.ctx.get("thread") or {})
            if self.session_id:
                self._rpc("thread/resume", {"threadId": self.session_id, **params})
            else:
                self._rpc("thread/start", params)
        elif method in ("thread/start", "thread/resume"):
            self.session_id = (res.get("thread") or {}).get("id") or self.session_id
            self.send(self.prompt)
            return [{"type": "thread.started", "thread_id": self.session_id}], []
        elif method == "turn/start":
            self.turn = (res.get("turn") or {}).get("id") or self.turn
        return [], []

    def _request(self, rid, method: str, p: dict) -> tuple[list[dict], list[dict]]:
        key = f"codex-{rid}"
        if method == "item/tool/requestUserInput":
            qs = [{"id": q.get("id"), "question": q.get("question"), "header": q.get("header"),
                   "multiSelect": False, "options": q.get("options") or []} for q in p.get("questions") or []]
            return [], [{"event": "request", "id": key, "rpc_id": rid, "kind": "question",
                         "tool": "request_user_input", "input": {"questions": qs}}]
        if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
            cmd = method.startswith("item/command")
            inp = {"command": p.get("command")} if cmd else {"file_path": p.get("grantRoot") or "file changes"}
            return [], [{"event": "request", "id": key, "rpc_id": rid, "kind": "permission",
                         "tool": "Bash" if cmd else "Edit", "input": inp, "why": p.get("reason")}]
        self._write({"id": rid, "error": {"code": -32601, "message": f"{method} is not supported here"}})
        return [], []
