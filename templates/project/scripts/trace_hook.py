#!/usr/bin/env python3
"""Fail-safe activity tracer for a spawned Kartr Lab project (a Claude Code hook).

Registered in this project's `.claude/settings.json` on SessionStart,
PreToolUse(Task|Agent), PostToolUse(*), SubagentStop(*) and SessionEnd. It reads one
hook JSON object on stdin and appends ONE compact line to a per-worker log:

    <project>/.bus/workers/<worker_id>.jsonl

(a git worktree `<proj>-wt-*` maps back to the main project so its `experiment-runner`
workers land where the dashboard reads). One file per worker = clean, separated logs the
optional Vivarium dashboard renders as one sprite + one action history per agent/subagent.

Contract — this NEVER blocks a tool call: any error -> silent `exit 0`, nothing on
stdout; stdlib only; one append; no network. The log is best-effort and NON-canonical
(not a ledger): the harness writes it, not the subagent, so the parent-only-ledgers rule
is untouched. This is a verbatim copy of the hub's `tools/trace_hook.py`.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

MAX_SUMMARY = 200
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
IDEA_RE = re.compile(r"studies/([a-z0-9][a-z0-9._-]*)", re.I)
# a hub session touching a project's artifacts (analyze/write/finalize) → attribute it to
# that project, so its back-half work isn't blank on the project's trace.
PROJ_RE = re.compile(r"([a-z0-9][a-z0-9._-]*)/(?:runs/|PLAN\.md|EXPERIMENT_LOG\.md)", re.I)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _resolve_bus(cwd: str) -> Path:
    """Find the `.bus` dir to write to, from the hook's cwd."""
    start = Path(cwd) if cwd else Path.cwd()
    try:
        start = start.resolve()
    except OSError:
        pass
    for p in [start, *start.parents]:
        if (p / "lab" / "REGISTRY.md").exists():        # the hub
            return p / "lab" / ".bus"
        if (p / "control.yaml").exists():               # a spawned project (or worktree)
            root = p
            name = root.name
            if "-wt-" in name or name.endswith("-wt"):  # map a worktree to its project
                base = name.split("-wt", 1)[0]
                sib = root.parent / base
                if (sib / "control.yaml").exists():
                    root = sib
            return root / ".bus"
    return start / ".bus"


def _clean(s: str) -> str:
    return " ".join(str(s).split())[:MAX_SUMMARY]


def _summary(tool: str, ti: dict) -> str:
    if not isinstance(ti, dict):
        return tool or ""

    def g(*keys: str) -> str:
        for k in keys:
            v = ti.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    if tool in ("Bash", "PowerShell"):
        s = g("command")
    elif tool in ("Read", "Edit", "Write", "NotebookEdit"):
        fp = g("file_path", "notebook_path")
        s = Path(fp).name if fp else ""
    elif tool in ("Grep", "Glob"):
        s = g("pattern")
    elif tool in ("Task", "Agent"):
        s = (g("subagent_type") + ": " + g("description", "prompt")).strip(": ")
    elif tool == "Skill":
        s = g("skill", "command")
    elif tool.startswith("mcp__"):
        s = g("query", "name")
    else:
        s = g("description", "query", "prompt", "path", "url", "file_path")
    return _clean(f"{tool}: {s}" if s else (tool or ""))


def _kind(tool: str, ti: dict) -> str:
    t = tool or ""
    blob = ""
    if isinstance(ti, dict):
        blob = f"{ti.get('command', '')}{ti.get('file_path', '')}"
    if t in ("Task", "Agent"):
        return "spawn"
    if t in ("Edit", "Write", "NotebookEdit"):
        return "edit"
    if t in ("Read", "Grep", "Glob"):
        return "read"
    if t in ("Bash", "PowerShell"):
        if re.search(r"run\.py|sweep\.py", blob):
            return "run"
        if re.search(r"\bgit\b", blob):
            return "git"
        return "bash"
    if t == "Skill":
        return "skill"
    if t.startswith("mcp__"):
        return "mcp"
    return "tool"


def _idea_of(ti) -> str:
    if not isinstance(ti, dict):
        return ""
    cand = []
    for k in ("file_path", "notebook_path", "path", "prompt", "description", "command", "pattern"):
        v = ti.get(k)
        if isinstance(v, str):
            cand.append(v)
    blob = re.sub(r"[\\/]+", "/", " ".join(cand))
    m = IDEA_RE.search(blob) or PROJ_RE.search(blob)
    return m.group(1) if m else ""


def main() -> None:
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}

    event = data.get("hook_event_name") or ""
    session_id = data.get("session_id") or ""
    agent_id = data.get("agent_id") or ""
    agent_type = data.get("agent_type") or ""
    tool = data.get("tool_name") or ""
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or ""

    # worker identity: a subagent if agent_id is present, else the (orchestrator) session
    worker_id = agent_id or session_id or "unknown"
    role = agent_type or "orchestrator"

    rec = {"ts": _now(), "worker_id": worker_id, "role": role,
           "event": "action", "session_id": session_id}

    if event == "SessionStart":
        rec.update(event="start", status="working")
    elif event in ("SessionEnd", "SubagentStop"):
        rec.update(event="stop", status="done")
    elif event == "PreToolUse" and tool in ("Task", "Agent"):
        child = ti.get("subagent_type") if isinstance(ti, dict) else ""
        rec.update(event="spawn", tool=tool, kind="spawn", summary=_summary(tool, ti))
        if child:
            rec["spawns"] = child
    elif event == "PostToolUse":
        rec.update(event="action", tool=tool, kind=_kind(tool, ti), summary=_summary(tool, ti))
    else:
        return  # uninteresting event -> write nothing

    idea = _idea_of(ti)
    if idea:
        rec["idea"] = idea

    wdir = _resolve_bus(cwd) / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    safe = SAFE_RE.sub("-", worker_id)[:80] or "unknown"
    with open(wdir / f"{safe}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
