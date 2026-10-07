"""Phone notifications (tools/executor/notify.py): what needs the PI goes to ntfy / a webhook, once,
from the scheduler — tested against a local HTTP server standing in for both (the `inbox` fixture)."""

from __future__ import annotations

import json
import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "tools"))
import executor  # noqa: E402
from executor import manifest, notify  # noqa: E402
from executor.supervise import _env_local  # noqa: E402

from test_executor import _queue, setup  # noqa: E402


def test_what_needs_you_is_sent_once_with_a_link(hub, inbox):
    base, got = inbox
    lab = setup(hub)
    (hub.lab / ".env.local").write_text(f"S2_API_KEY=k\nNEWTS_NOTIFY_NTFY={base}/my-topic\n"
                                        f"NEWTS_NOTIFY_WEBHOOK={base}/hook\nNEWTS_NOTIFY_LINK=http://pc:8787\n",
                                        encoding="utf-8")
    assert notify.config(lab) == {"ntfy": f"{base}/my-topic", "webhook": f"{base}/hook", "link": "http://pc:8787"}
    assert "NEWTS_NOTIFY_NTFY" not in _env_local(lab) and _env_local(lab)["S2_API_KEY"] == "k"   # never to agents
    rid = _queue(lab, 1)[0]
    _t, _w, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, "waiting_input", by="test", transport="live", pending_question={
        "tool_use_id": "q1", "input": {"questions": [{"question": "Which dataset?", "options": []}]}, "live": True})
    sent = notify.check(lab, force=True)
    assert [it["kind"] for it in sent] == ["question"]
    ntfy = next(g for g in got if g["path"] == "/my-topic")
    assert ntfy["headers"]["Title"] == "Which dataset?" and ntfy["headers"]["Click"] == f"http://pc:8787/#/runs?run={rid}"
    hook = json.loads(next(g for g in got if g["path"] == "/hook")["body"])
    assert "Which dataset?" in hook["text"] and hook["content"] == hook["text"]
    assert notify.check(lab, force=True) == [] and len(got) == 2   # each item once


def test_nothing_is_sent_without_a_destination_or_for_info_items(hub, inbox):
    base, got = inbox
    lab = setup(hub)
    rid = _queue(lab, 1)[0]
    _t, _w, path, m = executor.find_run(lab, rid)
    manifest.transition(lab, path, m, "completed", by="test", finished=manifest.now())
    assert notify.check(lab, force=True) == []                      # not configured
    (hub.lab / ".env.local").write_text(f"NEWTS_NOTIFY_NTFY={base}/t\n", encoding="utf-8")
    assert notify.check(lab, force=True) == [] and not got         # a finished run is not "needs you"
