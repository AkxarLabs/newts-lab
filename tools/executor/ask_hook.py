"""PreToolUse hook for AskUserQuestion — how a headless run asks the PI a question.

Registered per run by the executor (`claude -p --settings <run>.d/settings.json`), never in the repo's
own settings. STDLIB ONLY: it runs under a bare interpreter.

  no answer on file  → write <run>.d/question.json (the dashboard shows it instantly) and return
                       permissionDecision "defer": claude -p exits with stop_reason "tool_deferred"
                       and the pending call preserved in the session.
  answer on file     → (on `claude -p --resume`) return "allow" + updatedInput {questions, answers}:
                       the tool runs with the PI's answers and the model continues.

Fail-open: any error → exit 0 with no output (Claude Code's default, which in a headless run with a
permission host routes the call to the host — never a crash of the run).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.flush()


def main() -> int:
    run_dir = os.environ.get("NEWTS_RUN_DIR")
    if not run_dir:
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    if payload.get("tool_name") != "AskUserQuestion":
        return 0
    rd = Path(run_dir)
    tool_input = payload.get("tool_input") or {}
    tuid = payload.get("tool_use_id")
    answer_f = rd / "answer.json"
    if answer_f.exists():
        try:
            ans = json.loads(answer_f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            ans = None
        # an answer written for a DIFFERENT question (stale) is ignored — ask the new one
        if isinstance(ans, dict) and (not ans.get("tool_use_id") or not tuid or ans.get("tool_use_id") == tuid):
            try:
                os.replace(answer_f, rd / "answer.used.json")
            except OSError:
                pass
            updated = {"questions": tool_input.get("questions") or [],
                       "answers": ans.get("answers") or {}}
            if ans.get("response"):
                updated["response"] = str(ans["response"])
            _out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                         "permissionDecisionReason": "answered by the PI via the dashboard",
                                         "updatedInput": updated}})
            return 0
    try:
        rd.mkdir(parents=True, exist_ok=True)
        tmp = rd / "question.json.tmp"
        tmp.write_text(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool_use_id": tuid,
                                   "session_id": payload.get("session_id"), "input": tool_input}),
                       encoding="utf-8")
        os.replace(tmp, rd / "question.json")
    except OSError:
        pass
    _out({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "defer"}})
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 — a hook must never break the run
        sys.exit(0)
