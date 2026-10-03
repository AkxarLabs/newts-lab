"""A stand-in for `codex exec --json`, for hermetic executor tests (no model, no network).

Mirrors what the executor relies on, as read from codex-rs (rust-v0.157):
  * the exec flag surface — and REJECTS `-a/--ask-for-approval` like clap does (exec has no such flag);
  * `codex exec [opts] resume <thread_id> -` and the prompt on stdin (`-`);
  * `--json` ThreadEvents: thread.started{thread_id} · turn.* · item.started/completed{item} with
    command_execution / collab_tool_call (spawn_agent, wait) / agent_message items;
  * hooks from `-c hooks.<Event>=[…]` session flags, run ONLY with --dangerously-bypass-hook-trust
    (session-flag hooks are untrusted otherwise), each through the platform shell exactly as codex's
    command_runner does (Windows: `cmd.exe /C "<command>"`, POSIX: `$SHELL -lc <command>`), with a
    Claude-shaped payload: root session_id (= thread id); agent_id/agent_type inside a subagent;
    tool names Bash / spawn_agent.
FAKE_MODE: complete (default) | subagents.
Every invocation appends {argv, stdin, cwd, env subset} to $NEWTS_RUN_DIR/fake_calls.jsonl.

`codex [-c …] app-server` (the executor's live session) speaks the app-server protocol instead
(JSON-RPC without the "jsonrpc" field, one JSON object per line): initialize → thread/start|resume →
turn/start, notifications turn/started · item/started|completed (camelCase items) ·
thread/tokenUsage/updated · turn/completed, server requests item/tool/requestUserInput and
item/commandExecution/requestApproval, turn/steer and turn/interrupt. Hooks run when the thread's
config carries bypass_hook_trust. FAKE_MODE adds: question · approval · usage_limit; FAKE_STEER=<s>
keeps the first turn open for a steer.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid

try:
    import tomllib
except ModuleNotFoundError:   # Python < 3.11: hooks can't be parsed; those tests skip
    tomllib = None
from pathlib import Path

GLOBAL_FLAGS = {"--json", "--skip-git-repo-check", "--dangerously-bypass-hook-trust", "--ephemeral"}
VALUE_FLAGS = {"--sandbox", "-s", "-C", "--cd", "-m", "--model", "-c", "--config", "-o", "--add-dir"}


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def parse(argv: list[str]):
    opts: dict = {"-c": []}
    pos: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-a", "--ask-for-approval"):
            sys.stderr.write(f"error: unexpected argument '{a}' found\n")
            sys.exit(2)
        if a in VALUE_FLAGS:
            v = argv[i + 1] if i + 1 < len(argv) else ""
            if a in ("-c", "--config"):
                opts["-c"].append(v)
            else:
                opts[a] = v
            i += 2
        elif a in GLOBAL_FLAGS:
            opts[a] = True
            i += 1
        elif a.startswith("-") and a != "-":
            sys.stderr.write(f"error: unexpected argument '{a}' found\n")
            sys.exit(2)
        else:
            pos.append(a)
            i += 1
    return opts, pos


def hooks_from(overrides: list[str]) -> dict:
    hooks: dict = {}
    for ov in overrides:
        key, _, val = ov.partition("=")
        if key.startswith("hooks."):
            hooks[key.split(".", 1)[1]] = tomllib.loads("v = " + val)["v"]   # value is TOML, like codex
    return hooks


def run_hooks(hooks: dict, trusted: bool, cwd: str, event: str, payload: dict) -> None:
    if not trusted:
        return   # untrusted session-flag hooks never run
    for group in hooks.get(event) or []:
        m = group.get("matcher")
        if m not in (None, "", "*") and m != payload.get("tool_name"):
            continue
        for h in group.get("hooks") or []:
            body = json.dumps({"hook_event_name": event, "cwd": cwd, "transcript_path": None,
                               "model": "fake", "permission_mode": "never", **payload})
            if os.name == "nt":
                cmd = f'cmd.exe /C "{h["command"]}"'   # codex: raw_arg(format!(r#""{command_line}""#))
                subprocess.run(cmd, input=body, text=True, cwd=cwd, capture_output=True, timeout=30)
            else:
                subprocess.run([os.environ.get("SHELL") or "/bin/sh", "-lc", h["command"]], input=body,
                               text=True, cwd=cwd, capture_output=True, timeout=30)


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--version"]:
        print("codex-cli 0.157.1")
        return 0
    if argv[:2] == ["login", "status"]:
        sys.stderr.write("Logged in using ChatGPT\n")
        return 0
    if "app-server" in argv:
        return app_server(argv[:argv.index("app-server")])
    if argv[:1] != ["exec"]:
        return 2
    opts, pos = parse(argv[1:])
    resume = None
    if pos and pos[0] == "resume":
        resume = pos[1] if len(pos) > 1 else None
        pos = pos[2:]
    prompt = sys.stdin.read() if pos == ["-"] else (pos[0] if pos else "")
    cwd = opts.get("-C") or os.getcwd()
    run_dir = os.environ.get("NEWTS_RUN_DIR")
    if run_dir:
        with Path(run_dir, "fake_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": argv, "stdin": prompt, "cwd": cwd,
                                "env": {k: v for k, v in os.environ.items()
                                        if k.startswith(("AUTOSCIENTIST_", "NEWTS_"))}}) + "\n")
    hooks = hooks_from(opts["-c"])
    trusted = bool(opts.get("--dangerously-bypass-hook-trust"))
    tid = resume or str(uuid.uuid4())
    root = {"session_id": tid, "turn_id": "t1"}
    hook = lambda ev, **p: run_hooks(hooks, trusted, cwd, ev, {**root, **p})  # noqa: E731
    out({"type": "thread.started", "thread_id": tid})
    out({"type": "turn.started"})
    hook("SessionStart", source="resume" if resume else "startup")

    def bash(cmd, cid, agent=None):
        who = {"agent_id": agent[0], "agent_type": agent[1]} if agent else {}
        hook("PreToolUse", tool_name="Bash", tool_input={"command": cmd}, tool_use_id=cid, **who)
        if not agent:   # only the primary thread's items stream
            out({"type": "item.started", "item": {"id": cid, "type": "command_execution", "command": cmd,
                                                  "status": "in_progress"}})
            out({"type": "item.completed", "item": {"id": cid, "type": "command_execution", "command": cmd,
                                                    "aggregated_output": "ok", "exit_code": 0, "status": "completed"}})
        hook("PostToolUse", tool_name="Bash", tool_input={"command": cmd}, tool_use_id=cid,
             tool_response="ok", **who)

    mode = os.environ.get("FAKE_MODE", "complete")
    bash("python scripts/run.py", "call_1")
    if mode == "subagents":
        child, role = "thr-child-1", "experiment-runner"
        out({"type": "item.started", "item": {"id": "c1", "type": "collab_tool_call", "tool": "spawn_agent",
                                              "sender_thread_id": tid, "receiver_thread_ids": [],
                                              "prompt": "variant exp-004", "agents_states": {}, "status": "in_progress"}})
        hook("PreToolUse", tool_name="spawn_agent", tool_input={"message": "variant exp-004", "agent_type": role},
             tool_use_id="call_spawn")
        hook("SubagentStart", agent_id=child, agent_type=role)
        hook("PostToolUse", tool_name="spawn_agent", tool_input={"message": "variant exp-004", "agent_type": role},
             tool_use_id="call_spawn", tool_response={"agent_id": child, "nickname": "Ada"})
        out({"type": "item.completed", "item": {"id": "c1", "type": "collab_tool_call", "tool": "spawn_agent",
                                                "sender_thread_id": tid, "receiver_thread_ids": [child],
                                                "prompt": "variant exp-004",
                                                "agents_states": {child: {"status": "pending_init", "message": None}},
                                                "status": "completed"}})
        bash("uv run scripts/run.py --variant exp-004", "call_c1", agent=(child, role))
        hook("SubagentStop", agent_id=child, agent_type=role, stop_hook_active=False,
             last_assistant_message="RESULT PACKET: status=ok metric=0.91", agent_transcript_path=None)
        out({"type": "item.completed", "item": {"id": "c2", "type": "collab_tool_call", "tool": "wait",
                                                "sender_thread_id": tid, "receiver_thread_ids": [child], "prompt": None,
                                                "agents_states": {child: {"status": "completed",
                                                                          "message": "RESULT PACKET: status=ok metric=0.91"}},
                                                "status": "completed"}})
    text = f"done{' (resumed: ' + prompt.strip()[:60] + ')' if resume else ''}"
    out({"type": "item.completed", "item": {"id": "m1", "type": "agent_message", "text": text}})
    out({"type": "turn.completed", "usage": {"input_tokens": 120, "cached_input_tokens": 0, "output_tokens": 30}})
    hook("SessionEnd", reason="exit")
    return 0


class Server:
    """The client → server side of app-server: requests, notifications and responses on stdin."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.responses: dict = {}
        self.cv = threading.Condition()
        self.eof = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in sys.stdin:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if "id" in o and "method" not in o:
                with self.cv:
                    self.responses[o["id"]] = o
                    self.cv.notify_all()
            else:
                self.q.put(o)
        with self.cv:
            self.eof = True
            self.cv.notify_all()
        self.q.put(None)

    def ask(self, rid, method, params):
        out({"id": rid, "method": method, "params": params})
        with self.cv:
            while rid not in self.responses and not self.eof:
                self.cv.wait(0.5)
        out({"method": "serverRequest/resolved", "params": {"requestId": rid}})
        return (self.responses.get(rid) or {}).get("result") or {}


def app_server(pre: list[str]) -> int:
    opts, _ = parse(pre)
    hooks = hooks_from(opts["-c"])
    srv = Server()
    mode = os.environ.get("FAKE_MODE", "complete")
    tid = cwd = None
    trusted = False
    turns = 0
    reqs = iter(range(100))
    hook = lambda ev, **p: run_hooks(hooks, trusted, cwd, ev, {"session_id": tid, "turn_id": "t1", **p})  # noqa: E731

    def note(method, **params):
        out({"method": method, "params": {"threadId": tid, **params}})

    def item(kind, it, turn):
        note(f"item/{kind}", item=it, turnId=turn)

    def turn_body(turn, text):
        nonlocal turns
        turns += 1
        note("turn/started", turn={"id": turn, "status": "inProgress"})
        if turns > 1:   # every later turn: a reply to the PI's message
            item("completed", {"type": "agentMessage", "id": f"m{turns}", "text": f"got: {text[:200]}"}, turn)
            note("turn/completed", turn={"id": turn, "status": "completed"})
            return
        cmd = "python scripts/run.py"
        hook("PreToolUse", tool_name="Bash", tool_input={"command": cmd}, tool_use_id="call_1")
        item("started", {"type": "commandExecution", "id": "call_1", "command": cmd, "status": "inProgress"}, turn)
        item("completed", {"type": "commandExecution", "id": "call_1", "command": cmd, "status": "completed",
                           "aggregatedOutput": "ok", "exitCode": 0}, turn)
        hook("PostToolUse", tool_name="Bash", tool_input={"command": cmd}, tool_use_id="call_1", tool_response="ok")
        final = "done"
        if mode == "subagents":
            child = "thr-child-1"
            hook("SubagentStart", agent_id=child, agent_type="experiment-runner")
            item("completed", {"type": "collabAgentToolCall", "id": "c1", "tool": "spawnAgent", "status": "completed",
                               "senderThreadId": tid, "receiverThreadIds": [child], "prompt": "variant exp-004",
                               "agentsStates": {child: {"status": "pendingInit", "message": None}}}, turn)
            hook("SubagentStop", agent_id=child, agent_type="experiment-runner",
                 last_assistant_message="RESULT PACKET: status=ok metric=0.91")
            item("completed", {"type": "collabAgentToolCall", "id": "c2", "tool": "wait", "status": "completed",
                               "senderThreadId": tid, "receiverThreadIds": [child], "prompt": None,
                               "agentsStates": {child: {"status": "completed", "message": "RESULT PACKET: status=ok"}}}, turn)
        if mode == "question":
            r = srv.ask(next(reqs), "item/tool/requestUserInput", {
                "threadId": tid, "turnId": turn, "itemId": "q1", "isBlocking": False,
                "questions": [{"id": "ptype", "header": "Type", "question": "Which project type?", "isOther": True,
                               "isSecret": False, "options": [{"label": "ml", "description": "training"},
                                                              {"label": "empirical", "description": "regressions"}]}]})
            final = "answers=" + json.dumps(r.get("answers"), sort_keys=True)
        if mode == "approval":
            r = srv.ask(next(reqs), "item/commandExecution/requestApproval", {
                "threadId": tid, "turnId": turn, "itemId": "x1", "kind": "command", "command": "curl https://x",
                "cwd": cwd, "reason": "network access"})
            final = f"decision={r.get('decision')}"
        if mode == "usage_limit":
            note("error", error={"message": "You've hit your usage limit. Try again at 9:00 PM.",
                                 "codexErrorInfo": "usageLimitExceeded"}, willRetry=False, turnId=turn)
            note("turn/completed", turn={"id": turn, "status": "failed", "error": {"message": "usage limit"}})
            return
        steer = float(os.environ.get("FAKE_STEER") or 0)
        t_end = time.time() + steer
        while time.time() < t_end:   # a long turn: a steer or an interrupt arrives meanwhile
            try:
                o = srv.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if o is None:
                break
            if o.get("method") == "turn/steer":
                out({"id": o["id"], "result": {"turnId": turn}})
                final += " | steered: " + o["params"]["input"][0]["text"][:80]
                break
            if o.get("method") == "turn/interrupt":
                out({"id": o["id"], "result": {}})
                final += " | interrupted"
                break
        note("thread/tokenUsage/updated", turnId=turn, tokenUsage={"total": {"inputTokens": 120, "cachedInputTokens": 0,
                                                                              "outputTokens": 30}})
        item("completed", {"type": "agentMessage", "id": "m1", "text": final}, turn)
        note("turn/completed", turn={"id": turn, "status": "completed"})

    while True:
        o = srv.q.get()
        if o is None:
            hook("SessionEnd", reason="exit")
            return 0
        m, p = o.get("method"), o.get("params") or {}
        if m == "initialize":
            out({"id": o["id"], "result": {"userAgent": "fake/0.160.0", "codexHome": "", "platformFamily": "x"}})
        elif m in ("thread/start", "thread/resume"):
            tid = p.get("threadId") or str(uuid.uuid4())
            cwd = p.get("cwd") or os.getcwd()
            trusted = bool((p.get("config") or {}).get("bypass_hook_trust"))
            run_dir = os.environ.get("NEWTS_RUN_DIR")
            if run_dir:
                with Path(run_dir, "fake_calls.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"argv": ["app-server", *pre], "method": m, "params": p, "cwd": cwd,
                                        "env": {k: v for k, v in os.environ.items()
                                                if k.startswith(("AUTOSCIENTIST_", "NEWTS_"))}}) + "\n")
            out({"id": o["id"], "result": {"thread": {"id": tid}}})
            note("thread/started", thread={"id": tid})
            hook("SessionStart", source="resume" if m == "thread/resume" else "startup")
        elif m == "turn/start":
            turn = f"turn-{turns + 1}"
            out({"id": o["id"], "result": {"turn": {"id": turn, "status": "inProgress"}}})
            text = (p.get("input") or [{}])[0].get("text") or ""
            if turns == 0 and os.environ.get("NEWTS_RUN_DIR"):
                with Path(os.environ["NEWTS_RUN_DIR"], "fake_calls.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"argv": ["turn/start"], "stdin": text}) + "\n")
            turn_body(turn, text)
        elif m == "turn/steer":
            out({"id": o["id"], "error": {"code": 1, "message": "no active turn to steer"}})
        elif "id" in o:
            out({"id": o["id"], "result": {}})


if __name__ == "__main__":
    sys.exit(main())
