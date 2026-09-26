"""A stdio MCP server that answers Claude Code's permission prompts for a headless run.

`claude -p` only offers AskUserQuestion when a *permission host* exists, so every executor run passes
`--mcp-config <run>.d/mcp.json --permission-prompt-tool mcp__newts__permission`. This is that host.
STDLIB ONLY (newline-delimited JSON-RPC 2.0 over stdin/stdout).

Policy (never hangs an unattended run):
  - default: DENY, with a message telling the agent to escalate if the action is essential; every
    request is logged to <run>.d/permissions.jsonl (the dashboard turns denials into attention items).
  - AskUserQuestion reaching the host means the defer hook could not pause the turn (several tool
    calls at once): deny with an instruction to ask it again as the only call in the turn.
  - NEWTS_PERMISSION_WAIT=<seconds> > 0: write <run>.d/perm-<n>.json and wait that long for the PI's
    decision file <run>.d/perm-<n>.decision.json ({"allow": bool, "message": "..."}); then deny.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROTOCOL = "2025-06-18"
TOOL = {
    "name": "permission",
    "description": "Decide a Claude Code permission prompt for a headless Newts' Lab run.",
    "inputSchema": {
        "type": "object",
        "properties": {"tool_name": {"type": "string"}, "input": {"type": "object"},
                       "tool_use_id": {"type": "string"}},
        "required": ["tool_name", "input"],
    },
}


def _stdio():
    # binary + utf-8 + '\n' framing on every OS (Windows text mode would write \r\n)
    rin = sys.stdin.buffer if hasattr(sys.stdin, "buffer") else sys.stdin
    rout = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else sys.stdout
    return rin, rout


def _send(rout, obj: dict) -> None:
    data = (json.dumps(obj) + "\n").encode("utf-8")
    rout.write(data)
    rout.flush()


def _log(run_dir: Path | None, rec: dict) -> None:
    if not run_dir:
        return
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        with (run_dir / "permissions.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def decide(args: dict, run_dir: Path | None, wait_s: float) -> dict:
    tool = str(args.get("tool_name") or "?")
    inp = args.get("input") if isinstance(args.get("input"), dict) else {}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    if tool == "AskUserQuestion":
        res = {"behavior": "deny", "message": (
            "The PI can only answer a question asked as the ONLY tool call in a turn. Ask this "
            "AskUserQuestion again, alone, and stop — the run will pause for the PI's answer.")}
        _log(run_dir, {"ts": ts, "tool": tool, "decision": "deny", "why": "multi-call-turn"})
        return res
    if wait_s > 0 and run_dir:
        n = len(list(run_dir.glob("perm-*.json"))) + 1
        req = run_dir / f"perm-{n}.json"
        dec = run_dir / f"perm-{n}.decision.json"
        try:
            req.write_text(json.dumps({"ts": ts, "n": n, "tool": tool, "input": inp,
                                       "tool_use_id": args.get("tool_use_id")}), encoding="utf-8")
        except OSError:
            pass
        deadline = time.time() + wait_s
        while time.time() < deadline:
            if dec.exists():
                try:
                    d = json.loads(dec.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    d = {}
                if d.get("allow"):
                    _log(run_dir, {"ts": ts, "tool": tool, "decision": "allow", "by": "PI", "n": n})
                    return {"behavior": "allow", "updatedInput": inp}
                _log(run_dir, {"ts": ts, "tool": tool, "decision": "deny", "by": "PI", "n": n})
                return {"behavior": "deny", "message": str(d.get("message") or "Denied by the PI.")}
            time.sleep(0.5)
    summary = inp.get("command") or inp.get("file_path") or inp.get("url") or ""
    _log(run_dir, {"ts": ts, "tool": tool, "decision": "deny", "summary": str(summary)[:300]})
    return {"behavior": "deny", "message": (
        f"Headless run: '{tool}' is not auto-approvable under the executor's policy. If this action is "
        "essential to the procedure, escalate it (lab_bus.py escalate --detail \"...\") and continue "
        "with other in-bounds work; do not retry the same action.")}


def main() -> int:
    run_dir = Path(os.environ["NEWTS_RUN_DIR"]) if os.environ.get("NEWTS_RUN_DIR") else None
    try:
        wait_s = float(os.environ.get("NEWTS_PERMISSION_WAIT") or 0)
    except ValueError:
        wait_s = 0.0
    rin, rout = _stdio()
    for raw in rin:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue   # notifications (notifications/initialized, cancelled, …) need no reply
        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
            _send(rout, {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": ver, "capabilities": {"tools": {}},
                "serverInfo": {"name": "newts-permission", "version": "1.0"}}})
        elif method == "tools/list":
            _send(rout, {"jsonrpc": "2.0", "id": mid, "result": {"tools": [TOOL]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            if params.get("name") != TOOL["name"]:
                _send(rout, {"jsonrpc": "2.0", "id": mid,
                             "error": {"code": -32602, "message": f"unknown tool {params.get('name')!r}"}})
                continue
            res = decide(params.get("arguments") or {}, run_dir, wait_s)
            _send(rout, {"jsonrpc": "2.0", "id": mid,
                         "result": {"content": [{"type": "text", "text": json.dumps(res)}]}})
        elif method == "ping":
            _send(rout, {"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            _send(rout, {"jsonrpc": "2.0", "id": mid,
                         "error": {"code": -32601, "message": f"method not found: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
