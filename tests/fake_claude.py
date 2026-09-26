"""A stand-in for the `claude` CLI, for hermetic executor tests.

Speaks the flag surface tools/executor/backends.build_run_command emits and prints `claude -p
--output-format stream-json` shaped lines. Crucially it EXECUTES the real per-run hook from
`--settings` (tools/executor/ask_hook.py) and talks to the real MCP permission host from
`--mcp-config`, so the defer → answer → resume round-trip is tested end to end without a model.

Behaviour is picked by env FAKE_MODE:
  complete   init → Bash tool_use → tool_result → text → result(success)
  defer      first attempt: AskUserQuestion → hook → result(stop_reason=tool_deferred)
             on --resume: hook again → answers delivered → result(success, echoing the answers)
  slow       init, then sleep FAKE_SLEEP seconds (default 30)
  crash      init, then exit 3
  mcp        ask the permission host to approve a Bash call; report its decision
  subagents  spawn an Agent subagent, let it act (parent_tool_use_id), return a result packet
  prose      end with a question in prose (no AskUserQuestion) — answered via reply/resume
  auto       (demos) pick by procedure: /spawn-project|/discuss → defer, /experiment|/improve →
             subagents, else complete (/propose adds a gate1 footer); FAKE_PACE=<s> paces the lines
Optional env FAKE_REPORT='{"next": ..., "needs_pi": ..., "summary": ...}' makes the "agent" emit the
run_report footer on the run's bus, as the preamble instructs.
Every invocation appends {argv, stdin, cwd, env subset} to $NEWTS_RUN_DIR/fake_calls.jsonl.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path


def out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
    pace = float(os.environ.get("FAKE_PACE") or 0)
    if pace:
        time.sleep(pace)


def parse(argv: list[str]) -> tuple[dict, list[str]]:
    opts: dict = {}
    pos: list[str] = []
    takes = {"--output-format", "--session-id", "--resume", "--model", "--permission-mode", "--effort",
             "--max-turns", "--append-system-prompt-file", "--settings", "--mcp-config",
             "--permission-prompt-tool", "--add-dir"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in takes:
            opts.setdefault(a, []).append(argv[i + 1] if i + 1 < len(argv) else "")
            i += 2
        elif a.startswith("--") or a == "-p":
            opts[a] = [True]
            i += 1
        else:
            pos.append(a)
            i += 1
    return opts, pos


def run_hook(settings_path: str | None, payload: dict) -> dict | None:
    if not settings_path:
        return None
    s = json.loads(Path(settings_path).read_text(encoding="utf-8"))
    for entry in (s.get("hooks") or {}).get("PreToolUse") or []:
        if entry.get("matcher") and entry["matcher"] != payload.get("tool_name"):
            continue
        for h in entry.get("hooks") or []:
            cmd = h["command"]
            argv = shlex.split(cmd, posix=(os.name != "nt"))
            argv = [a.strip('"') for a in argv]
            r = subprocess.run(argv, input=json.dumps(payload), capture_output=True, text=True, timeout=30)
            if r.stdout.strip():
                return json.loads(r.stdout)
    return None


def ask_host(mcp_path: str, tool_name: str, tool_input: dict) -> dict:
    cfg = json.loads(Path(mcp_path).read_text(encoding="utf-8"))["mcpServers"]["newts"]
    env = {**os.environ, **(cfg.get("env") or {})}
    p = subprocess.Popen([cfg["command"], *cfg["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         env=env)

    def rpc(mid, method, params=None):
        p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n").encode())
        p.stdin.flush()
        return json.loads(p.stdout.readline())

    rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
    p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode())
    p.stdin.flush()
    tools = rpc(2, "tools/list")["result"]["tools"]
    assert tools and tools[0]["name"] == "permission"
    res = rpc(3, "tools/call", {"name": "permission", "arguments": {"tool_name": tool_name, "input": tool_input,
                                                                      "tool_use_id": "toolu_perm"}})
    p.stdin.close()
    p.wait(timeout=10)
    return json.loads(res["result"]["content"][0]["text"])


def main() -> int:
    argv = sys.argv[1:]
    if argv[:1] == ["--version"]:
        print("9.9.9 (Claude Code)")
        return 0
    if argv[:2] == ["auth", "status"]:
        print(json.dumps({"loggedIn": os.environ.get("FAKE_LOGGED_IN", "1") == "1", "authMethod": "fake"}))
        return 0
    opts, pos = parse(argv)
    stdin_text = ""
    if not sys.stdin.isatty():
        try:
            stdin_text = sys.stdin.read()
        except (OSError, ValueError):
            stdin_text = ""
    prompt = pos[0] if pos else stdin_text
    run_dir = os.environ.get("NEWTS_RUN_DIR")
    if run_dir:
        with Path(run_dir, "fake_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"argv": argv, "stdin": stdin_text, "cwd": os.getcwd(),
                                "env": {k: v for k, v in os.environ.items()
                                        if k.startswith(("AUTOSCIENTIST_", "NEWTS_", "CLAUDE_CODE_"))}}) + "\n")
    resume = (opts.get("--resume") or [None])[0]
    sid = resume or (opts.get("--session-id") or [None])[0] or str(uuid.uuid4())
    settings = (opts.get("--settings") or [None])[0]
    mode = os.environ.get("FAKE_MODE", "complete")
    if mode == "auto":
        low = prompt.lower()
        if "/spawn-project" in low or "/discuss" in low:
            mode = "defer"
        elif "/experiment" in low or "/improve" in low:
            mode = "subagents"
        else:
            mode = "complete"
        if "/propose" in low and not os.environ.get("FAKE_REPORT"):
            rest = low.split("/propose", 1)[1].split()
            slug = rest[0] if rest else "idea"
            os.environ["FAKE_REPORT"] = json.dumps({"next": f"/spawn-project {slug}", "needs_pi": "gate1",
                                                    "summary": f"proposal for {slug} written; staged plan + kill criteria ready for Gate 1"})
        elif not os.environ.get("FAKE_REPORT"):
            os.environ["FAKE_REPORT"] = json.dumps({"next": "", "needs_pi": "none", "summary": "done — see the notebook entry"})
    out({"type": "system", "subtype": "init", "session_id": sid, "model": "fake-model"})

    def report():
        rep = os.environ.get("FAKE_REPORT")
        if rep and os.environ.get("NEWTS_RUN_ID"):
            d = json.loads(rep)
            hub = Path(os.environ["NEWTS_HUB"])
            bus = hub / "lab" / ".bus" if Path(os.getcwd()).resolve() == hub.resolve() else Path(os.getcwd()) / ".bus"
            bus.mkdir(parents=True, exist_ok=True)
            with (bus / "events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": "x", "kind": "run_report",
                                    "run_id": os.environ["NEWTS_RUN_ID"], "data": d}) + "\n")

    def finish(text: str, rc: int = 0):
        report()
        out({"type": "result", "subtype": "success" if rc == 0 else "error", "is_error": rc != 0,
             "result": text, "session_id": sid, "stop_reason": "end_turn", "total_cost_usd": 0.0123,
             "num_turns": 3, "usage": {"input_tokens": 100, "output_tokens": 50}})
        return rc

    if mode == "complete":
        out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "text", "text": "working on it"},
            {"type": "tool_use", "id": "tu_b1", "name": "Bash", "input": {"command": "python scripts/run.py"}}]}})
        out({"type": "user", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_b1", "content": "ok"}]}})
        extra = f" | prompt={prompt.strip()[:80]}" if resume else ""
        return finish("all done; smoke green" + extra)
    if mode == "prose":
        if resume:
            return finish(f"thanks — continuing with: {prompt.strip()[:120]}")
        return finish("Which dataset should I use, A or B?")
    if mode == "defer":
        q = {"questions": [{"question": "Which project type?", "header": "Type", "multiSelect": False,
                            "options": [{"label": "ml", "description": "training"},
                                        {"label": "empirical", "description": "regressions"}]}]}
        tu = "toolu_q1"
        out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_use", "id": tu, "name": "AskUserQuestion", "input": q}]}})
        payload = {"session_id": sid, "hook_event_name": "PreToolUse", "tool_name": "AskUserQuestion",
                   "tool_input": q, "tool_use_id": tu, "cwd": os.getcwd()}
        decision = run_hook(settings, payload) or {}
        hs = decision.get("hookSpecificOutput") or {}
        if hs.get("permissionDecision") == "defer":
            out({"type": "result", "subtype": "success", "is_error": False, "result": "", "session_id": sid,
                 "stop_reason": "tool_deferred",
                 "deferred_tool_use": {"id": tu, "name": "AskUserQuestion", "input": q}})
            return 0
        if hs.get("permissionDecision") == "allow":
            ans = (hs.get("updatedInput") or {}).get("answers") or {}
            resp = (hs.get("updatedInput") or {}).get("response")
            out({"type": "user", "parent_tool_use_id": None, "message": {"content": [
                {"type": "tool_result", "tool_use_id": tu, "content": json.dumps(ans)}]}})
            return finish(f"answers={json.dumps(ans, sort_keys=True)} response={resp}")
        return finish("no hook decision", 1)
    if mode == "slow":
        time.sleep(float(os.environ.get("FAKE_SLEEP", "30")))
        return finish("slept")
    if mode == "crash":
        return 3
    if mode == "authfail":   # what an expired / missing login looks like from `claude -p`
        out({"type": "result", "subtype": "error", "is_error": True, "session_id": sid,
             "result": "Failed to authenticate: OAuth session expired and could not be refreshed"})
        return 1
    if mode == "mcp":
        mcp = (opts.get("--mcp-config") or [None])[0]
        tool = (opts.get("--permission-prompt-tool") or [None])[0]
        assert mcp and tool == "mcp__newts__permission", (mcp, tool)
        d = ask_host(mcp, "Bash", {"command": "rm -rf /tmp/x"})
        return finish(f"permission={d['behavior']}")
    if mode == "subagents":
        out({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_use", "id": "tu_agent", "name": "Agent",
             "input": {"subagent_type": "experiment-runner", "description": "variant exp-004", "prompt": "..."}}]}})
        out({"type": "assistant", "parent_tool_use_id": "tu_agent", "message": {"content": [
            {"type": "tool_use", "id": "tu_sub_bash", "name": "Bash", "input": {"command": "uv run scripts/run.py"}}]}})
        out({"type": "user", "parent_tool_use_id": "tu_agent", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_sub_bash", "content": "run ok"}]}})
        out({"type": "user", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_agent",
             "content": [{"type": "text", "text": "RESULT PACKET: status=ok metric=0.91"}]}]}})
        return finish("merged the variant")
    return finish(f"unknown mode {mode}", 1)


if __name__ == "__main__":
    sys.exit(main())
