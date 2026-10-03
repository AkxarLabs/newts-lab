"""Tell the PI when something needs them — from the scheduler, so it works with the dashboard closed.

Configured in Settings → Lab → Notifications, stored in lab/.env.local (git-ignored; a topic or a
webhook URL is a secret — anyone holding it can read or post) and never passed to agents:

  NEWTS_NOTIFY_NTFY=https://ntfy.sh/<your-topic>     a phone push via ntfy (app or web); any ntfy server
  NEWTS_NOTIFY_WEBHOOK=https://hooks.slack.com/...   Slack / Discord / Teams / anything taking JSON {text}
  NEWTS_NOTIFY_LINK=http://my-pc.tailnet:8787        where the dashboard is reachable from your phone;
                                                     each notification links straight to the item

What is sent: the item's title and one line (e.g. "Which dataset?" · "/propose idea-a"), never files,
transcripts or keys. Only items that block the lab (questions, approvals, gates, a stalled campaign)
are sent, each once. Sending happens on a background thread; a failure is logged, never raised.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import attention, campaigns
from .lab import Lab, labfiles
from .manifest import now

CHECK_EVERY = 15.0
MAX_PER_CHECK = 5
_last: dict[str, float] = {}
_busy = threading.Lock()


KEYS = {"ntfy": "NEWTS_NOTIFY_NTFY", "webhook": "NEWTS_NOTIFY_WEBHOOK", "link": "NEWTS_NOTIFY_LINK"}


def config(lab: Lab) -> dict:
    env = labfiles.read_env(lab.lab / ".env.local")
    return {name: env[key] for name, key in KEYS.items() if env.get(key)}


def state_path(lab: Lab) -> Path:
    return lab.bus / "notified.json"


def items(lab: Lab) -> list[dict]:
    """What would be sent now: blocking, unseen items + stalled campaigns."""
    out = [it for it in attention.collect(lab) if it.get("sev") == "block" and not it.get("seen")]
    for st in campaigns.all_states(lab):
        if st.get("status") == "stalled":
            out.append({"id": f"campaign-stalled:{st['name']}:{st.get('paused_reason')}", "kind": "campaign",
                        "title": f"Campaign {st['name']} stalled", "body": st.get("paused_reason") or "",
                        "run_id": None, "detail": {"campaign": st["name"]}})
    return out


def link(cfg: dict, it: dict) -> str | None:
    base = cfg.get("link", "").rstrip("/")
    if not base:
        return None
    if it.get("run_id"):
        return f"{base}/#/runs?run={urllib.parse.quote(it['run_id'])}"
    if (it.get("detail") or {}).get("campaign"):
        return f"{base}/#/studies"
    return f"{base}/#/"


def send(cfg: dict, it: dict, timeout: float = 8.0) -> list[str]:
    """Send one item to every configured channel. Returns the channels that failed."""
    title = str(it.get("title") or "Newts' Lab needs you")[:200]
    body = str(it.get("body") or "")[:500]
    url = link(cfg, it)
    failed = []
    if cfg.get("ntfy"):
        headers = {"Title": title.encode("utf-8").decode("latin-1", "replace"), "Tags": "lizard",
                   "Priority": "high" if it.get("kind") in ("question", "permission") else "default"}
        if url:
            headers["Click"] = url
        try:
            req = urllib.request.Request(cfg["ntfy"], data=(body or title).encode("utf-8"), headers=headers,
                                         method="POST")
            urllib.request.urlopen(req, timeout=timeout).close()
        except (OSError, ValueError):
            failed.append("ntfy")
    if cfg.get("webhook"):
        text = f"*{title}*" + (f"\n{body}" if body else "") + (f"\n{url}" if url else "")
        try:
            req = urllib.request.Request(cfg["webhook"], data=json.dumps({"text": text, "content": text}).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=timeout).close()
        except (OSError, ValueError):
            failed.append("webhook")
    return failed


def check(lab: Lab, force: bool = False) -> list[dict]:
    """Send what's new (at most every CHECK_EVERY seconds per lab). Returns the items sent."""
    cfg = config(lab)
    key = str(lab.hub)
    if not (cfg.get("ntfy") or cfg.get("webhook")):
        return []
    if not force and time.time() - _last.get(key, 0) < CHECK_EVERY:
        return []
    _last[key] = time.time()
    try:
        sent = set(json.loads(state_path(lab).read_text(encoding="utf-8")).get("ids") or [])
    except (OSError, ValueError):
        sent = set()
    new = [it for it in items(lab) if it["id"] not in sent][:MAX_PER_CHECK]
    out = []
    for it in new:
        failed = send(cfg, it)
        if len(failed) < bool(cfg.get("ntfy")) + bool(cfg.get("webhook")):   # reached at least one channel
            sent.add(it["id"])
            out.append(it)
    if out:
        ids = list(sent)[-500:]
        tmp = state_path(lab).with_suffix(".tmp")
        tmp.write_text(json.dumps({"ids": ids, "ts": now()}), encoding="utf-8")
        tmp.replace(state_path(lab))
    return out


def check_in_background(lab: Lab) -> None:
    """The scheduler's call: never blocks a tick, never overlaps itself."""
    if not config(lab) or not _busy.acquire(blocking=False):
        return

    def run():
        try:
            check(lab)
        except Exception:  # noqa: BLE001 — a notification must never break scheduling
            pass
        finally:
            _busy.release()
    threading.Thread(target=run, daemon=True).start()
