"""The live-session policy (tools/executor/live.py) without processes: a stub session records what the
supervisor would send the agent, a stub state records the manifest."""

from __future__ import annotations

import sys
import threading
import time

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
from executor import live  # noqa: E402

Q = {"questions": [{"question": "Which dataset?", "header": "Data", "multiSelect": False,
                    "options": [{"label": "B (recommended)", "description": ""}, {"label": "A", "description": ""}]}]}


class StubSession:
    def __init__(self):
        self.sent, self.responses, self.closed, self.unread, self.interrupted = [], [], False, 0, 0

    def send(self, text):
        self.sent.append(text)
        return True

    def respond(self, req, item):
        self.responses.append((req["id"], item))
        return True

    def interrupt(self):
        self.interrupted += 1
        return True

    def close(self):
        self.closed = True


class StubState:
    def __init__(self, m):
        self.m, self.lock, self.writes = m, threading.RLock(), 0

    def write(self, force=False):
        self.writes += 1

    def transition(self, to, *, by="supervisor", reason=None, **fields):
        self.m.update(fields, status=to)


def conv(tmp_path, campaign=None, **cfg):
    s, st = StubSession(), StubState({"run_id": "r1", "status": "running", "campaign": campaign})
    notes = []
    c = live.Conversation(s, st, tmp_path, {"live": cfg} if cfg else {}, note=lambda k, **d: notes.append((k, d)))
    return c, s, st, notes


def ask(c, rid="q1", kind="question", inp=Q, tool="AskUserQuestion"):
    with c.st.lock:
        c.on_event({"event": "request", "id": rid, "kind": kind, "tool": tool, "input": inp})


def test_inbox_post_and_take_in_order(tmp_path):
    live.post(tmp_path, {"kind": "message", "text": "one"})
    live.post(tmp_path, {"kind": "interrupt"})
    got = live.take(tmp_path)
    assert [g["kind"] for g in got] == ["message", "interrupt"] and got[0]["text"] == "one"
    assert live.take(tmp_path) == []
    try:
        live.post(tmp_path, {"kind": "shell", "cmd": "rm"})
        raise AssertionError("an unknown kind must be refused")
    except ValueError:
        pass


def test_a_question_waits_then_the_pi_answer_goes_to_the_session(tmp_path):
    c, s, st, notes = conv(tmp_path)
    ask(c)
    assert st.m["status"] == "waiting_input" and st.m["pending_question"]["live"] and c.waiting()
    assert notes[0][0] == "agent_waiting"
    live.post(tmp_path, {"kind": "answer", "request_id": "q1", "answers": {"Which dataset?": "A"}, "by": "PI"})
    assert c.tick() is False
    assert s.responses == [("q1", {"kind": "answer", "request_id": "q1", "answers": {"Which dataset?": "A"},
                                   "by": "PI", "ts": s.responses[0][1]["ts"]})]
    assert st.m["status"] == "running" and st.m["pending_question"] is None and not c.waiting()
    assert st.m["qa"][-1]["by"] == "PI"


def test_an_unanswered_question_parks(tmp_path):
    c, s, st, _ = conv(tmp_path, park_minutes=0.0001)
    ask(c)
    time.sleep(0.05)
    assert c.tick() is True            # park: the supervisor ends the process
    assert st.m["status"] == "waiting_input"


def test_a_campaign_takes_the_recommended_answer_and_says_so(tmp_path):
    c, s, st, notes = conv(tmp_path, campaign="c1", campaign_question_minutes=0.0001)
    ask(c)
    time.sleep(0.05)
    assert c.tick() is False
    assert s.responses[0][1]["answers"] == {"Which dataset?": "B (recommended)"}
    assert st.m["assumed"][0]["answers"] == {"Which dataset?": "B (recommended)"}
    assert st.m["status"] == "running" and any("assumed" in str(d) for _k, d in notes)


def test_a_campaign_question_without_options_parks_instead(tmp_path):
    c, s, st, _ = conv(tmp_path, campaign="c1", campaign_question_minutes=0.0001, park_minutes=0.0002)
    ask(c, inp={"questions": [{"question": "What next?", "options": []}]})
    time.sleep(0.05)
    assert c.tick() is True and not s.responses


def test_permissions_wait_for_the_pi_then_lapse_to_deny(tmp_path):
    c, s, st, _ = conv(tmp_path, permission_minutes=0.0001)
    ask(c, rid="p1", kind="permission", tool="Bash", inp={"command": "rm -rf x"})
    assert st.m["status"] == "running" and st.m["pending_permissions"][0]["id"] == "p1"
    time.sleep(0.05)
    c.tick()
    assert s.responses[0][0] == "p1" and s.responses[0][1]["allow"] is False
    assert "pending_permissions" not in st.m
    assert '"by": "deadline"' in (tmp_path / "permissions.jsonl").read_text(encoding="utf-8")


def test_a_campaign_denies_permissions_at_once(tmp_path):
    c, s, st, _ = conv(tmp_path, campaign="c1")
    ask(c, rid="p1", kind="permission", tool="Bash", inp={"command": "curl x"})
    assert s.responses[0][1]["allow"] is False and not c.waiting()


def test_a_cancelled_request_is_dropped(tmp_path):
    c, s, st, _ = conv(tmp_path)
    ask(c)
    with st.lock:
        c.on_event({"event": "cancelled", "id": "q1"})
    assert not c.waiting() and st.m["status"] == "running"


def test_the_session_closes_after_its_turn_unless_a_message_is_on_its_way(tmp_path):
    c, s, st, _ = conv(tmp_path)
    s.unread = 1
    with st.lock:
        c.on_event({"event": "turn_end"})
    c.tick()
    assert not s.closed                # the CLI hasn't read our message yet: a new turn will follow
    s.unread = 0
    c.tick()
    assert s.closed
    live.post(tmp_path, {"kind": "message", "text": "too late"})
    c.tick()
    assert c.leftover and c.leftover[0]["text"] == "too late"   # → the supervisor resumes with it


def test_claude_session_translates_the_protocol():
    sess = live.ClaudeSession("hi")
    evs = sess.handle({"type": "control_request", "request_id": "r9", "request": {
        "subtype": "can_use_tool", "tool_name": "AskUserQuestion", "input": Q, "tool_use_id": "tu"}})
    assert evs == [{"event": "request", "id": "r9", "tool": "AskUserQuestion", "kind": "question",
                    "input": Q, "tool_use_id": "tu", "why": None}]
    assert sess.handle({"type": "result"}) == [{"event": "turn_end"}]
    assert sess.handle({"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "resetsAt": 5,
                                                                         "rateLimitType": "five_hour"}}) == [
        {"event": "limits", "status": "allowed", "resets_at": 5, "type": "five_hour"}]
    sess.unread = 1
    sess.handle({"type": "user", "message": {"role": "user", "content": "hi"}})
    assert sess.unread == 0
    sess.unread = 1
    sess.handle({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "x"}]}})
    assert sess.unread == 1           # a tool result is not our message coming back


def test_the_codex_app_s_bundled_cli_is_found_newest_first(tmp_path, monkeypatch):
    from executor import backends
    if sys.platform != "win32":
        return
    for v in ("26.924.1866.0", "26.930.3748.0"):
        d = tmp_path / "WindowsApps" / f"OpenAI.Codex_{v}_x64__abc" / "app" / "resources"
        d.mkdir(parents=True)
        (d / "codex.exe").write_bytes(b"")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    hits = backends._app_bundled("codex")
    assert hits and "26.930" in str(hits[0]) and backends._app_bundled("claude") == []
