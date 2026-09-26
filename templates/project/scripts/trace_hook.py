#!/usr/bin/env python3
"""Fail-safe activity tracer for a spawned Newts' Lab project (a Claude Code hook).

Registered in this project's `.claude/settings.json` on SessionStart, SubagentStart,
PreToolUse(*), PostToolUse(*), SubagentStop(*) and SessionEnd. It reads one hook JSON
object on stdin and appends ONE compact line to a per-worker log:

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

MAX_SUMMARY = 400
MAX_RESULT = 2000                 # a subagent's result packet / final message, as returned
WORKER_RETENTION_S = 48 * 3600   # SessionStart prunes worker logs untouched longer than this
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
IDEA_RE = re.compile(r"studies/([a-z0-9][a-z0-9._-]*)", re.I)
# a hub session touching a project's artifacts (analyze/write/finalize) → attribute it to that
# project, so its back-half work isn't blank on the project's trace. NOTE: a config-free heuristic —
# it can't tell a real project name from any other `<word>/runs|PLAN.md|EXPERIMENT_LOG.md` path, so an
# unrelated path may yield a phantom 'idea'. Acceptable: attribution is best-effort dashboard colour,
# never a correctness signal (the canonical record is the project's ledgers, not this trace).
PROJ_RE = re.compile(r"([a-z0-9][a-z0-9._-]*)/(?:runs/|PLAN\.md|EXPERIMENT_LOG\.md)", re.I)
# an /improve variant runs in a git worktree `<project>-wt-<variant>` — even when the subagent's hook
# cwd is the HUB session's, its commands/paths name the worktree: attribute it to the project + variant.
WT_RE = re.compile(r"([A-Za-z0-9][A-Za-z0-9._]*(?:-[A-Za-z0-9._]+)*?)-wt-([A-Za-z0-9][A-Za-z0-9._-]*)")


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


def _prune_workers(wdir: Path) -> None:
    """Best-effort retention: drop worker logs untouched past WORKER_RETENTION_S. Bounds the
    directory so sessions that died WITHOUT a clean SessionEnd (crash, closed terminal, kill)
    don't accumulate forever — the dashboard's read-time filter hides them, this removes them.
    Runs once per session (SessionStart); never raises (we are on the never-block-a-tool path)."""
    cutoff = datetime.now().timestamp() - WORKER_RETENTION_S
    for f in wdir.glob("*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


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
    if t in ("Task", "Agent"):
        return "spawn"
    if t in ("Edit", "Write", "NotebookEdit"):
        return "edit"
    if t in ("Read", "Grep", "Glob"):
        return "read"
    if t in ("Bash", "PowerShell"):
        cmd = ti.get("command", "") if isinstance(ti, dict) else ""
        # an actual invocation, not `cat run.py` / a path mention / `overrun.py`
        if re.search(r"\b(?:python3?|uv|py)\b.*\b(?:run|sweep)\.py\b", cmd):
            return "run"
        if re.search(r"\bgit\b", cmd):
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


def _text(v) -> str:
    """A tool_response / last message as plain text (Agent results are content-block lists)."""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        for k in ("content", "result", "text", "output"):
            if k in v:
                return _text(v[k])
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "\n".join(_text(x.get("text") if isinstance(x, dict) and "text" in x else x) for x in v)
    return "" if v is None else str(v)


def _result(v) -> str:
    return _text(v).strip()[:MAX_RESULT]


def _worktree_of(ti, cwd: str) -> tuple:
    """(project, variant) if the call names an /improve worktree `<project>-wt-<variant>`."""
    blob = [cwd or ""]
    if isinstance(ti, dict):
        blob += [v for k, v in ti.items() if isinstance(v, str) and k in
                 ("file_path", "notebook_path", "path", "command", "cwd")]
    m = WT_RE.search(re.sub(r"[\\/]+", "/", " ".join(blob)))
    return (m.group(1).rsplit("/", 1)[-1], m.group(2).split("/", 1)[0]) if m else ("", "")


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
    tuid = data.get("tool_use_id") or ""

    # worker identity: a subagent if agent_id is present, else the (orchestrator) session. A
    # subagent's lines carry the PARENT session's id in `session_id` — that is the parent link the
    # dashboard uses to draw run → session → subagent trees.
    worker_id = agent_id or session_id or "unknown"
    role = agent_type or "orchestrator"

    rec = {"ts": _now(), "worker_id": worker_id, "role": role,
           "event": "action", "session_id": session_id}
    if tuid:
        rec["tool_use_id"] = tuid

    if event == "SessionStart":
        rec.update(event="start", status="working")
        if data.get("source"):
            rec["source"] = data["source"]          # startup | resume | clear | compact
    elif event == "SubagentStart":
        if not agent_id:
            return
        rec.update(event="start", status="working")  # born now — not at its first finished tool
    elif event == "SessionEnd":
        rec.update(event="stop", status="done")
    elif event == "SubagentStop":
        # SubagentStop can fire in the PARENT's context with no child id — writing 'done' to
        # worker_id (=session_id=orchestrator) would mark the still-running orchestrator finished.
        # Only record the stop when we can attribute it to the subagent itself.
        if not agent_id:
            return
        rec.update(event="stop", status="done")
        res = _result(data.get("last_assistant_message"))
        if res:
            rec["result"] = res
    elif event == "PreToolUse" and tool in ("Task", "Agent"):
        child = ti.get("subagent_type") if isinstance(ti, dict) else ""
        rec.update(event="spawn", tool=tool, kind="spawn", summary=_summary(tool, ti))
        if child:
            rec["spawns"] = child
    elif event == "PreToolUse":
        # "in <tool> since <ts>": a worker inside a 40-minute training call stays visibly busy
        rec.update(event="begin", tool=tool, kind=_kind(tool, ti), summary=_summary(tool, ti))
    elif event == "PostToolUse" and tool in ("Task", "Agent"):
        # the subagent handed back: its result packet is the return value of the Agent call
        rec.update(event="return", tool=tool, kind="spawn", summary=_summary(tool, ti))
        res = _result(data.get("tool_response"))
        if res:
            rec["result"] = res
    elif event == "PostToolUse":
        rec.update(event="action", tool=tool, kind=_kind(tool, ti), summary=_summary(tool, ti))
    else:
        return  # uninteresting event -> write nothing

    proj, variant = _worktree_of(ti, cwd)
    if proj:
        rec["project"], rec["variant"] = proj, variant
    idea = _idea_of(ti)
    if idea:
        rec["idea"] = idea

    wdir = _resolve_bus(cwd) / "workers"
    wdir.mkdir(parents=True, exist_ok=True)
    safe = SAFE_RE.sub("-", worker_id)[:80] or "unknown"
    with open(wdir / f"{safe}.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if event == "SessionStart":
        _prune_workers(wdir)   # once-per-session retention sweep (the fresh file above is kept)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
