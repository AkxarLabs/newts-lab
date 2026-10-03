"""Research API keys and the phone-notification addresses, both in lab/.env.local (git-ignored): what is
set (never the values), saving one, and a test notification. Runs inherit the keys; the scheduler alone
reads the notification addresses (tools/executor/notify.py) — they are never given to an agent.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import ctx
import sources

executor = sources.executor   # tools/executor, or None


KNOWN_KEYS = {"S2_API_KEY": "Semantic Scholar", "OPENALEX_API_KEY": "OpenAlex"}


_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")


def _env_path() -> Path:
    return ctx.LAB / ".env.local"


def _env_read() -> dict:
    return ctx.labfiles.read_env(_env_path())


def keys_status() -> tuple[dict, int]:
    have = {k: v for k, v in _env_read().items() if not k.startswith("NEWTS_")}   # (notifications: their own form)
    keys = [{"key": k, "label": KNOWN_KEYS.get(k, k), "set": bool(have.get(k)) or bool(os.environ.get(k)),
             "where": ("lab" if have.get(k) else ("environment" if os.environ.get(k) else None))}
            for k in list(KNOWN_KEYS) + [k for k in have if k not in KNOWN_KEYS]]
    return {"ok": True, "keys": keys, "file": ".env.local (git-ignored)"}, 200


def keys_set(body: dict) -> tuple[dict, int]:
    key = str(body.get("key") or "").strip()
    if not _KEY_RE.match(key) or key.startswith(("NEWTS_", "AUTOSCIENTIST_", "CLAUDE_", "OPENCODE_", "CODEX_", "PATH")):
        return {"error": "a key name like S2_API_KEY"}, 400
    value = body.get("value")
    if value is not None and (not isinstance(value, str) or "\n" in value or len(value) > 500):
        return {"error": "the value must be one line"}, 400
    have = _env_read()
    if value:
        have[key] = value.strip()
    else:
        have.pop(key, None)
    _env_write(have)
    ctx.pi_log({"action": "keys.set", "key": key, "set": bool(value)})   # never the value
    return {"ok": True, "note": f"{key} {'saved' if value else 'removed'}"}, 200


def _env_write(have: dict) -> None:
    lines = ["# This lab's keys — written by the dashboard. Research keys are inherited by runs; NEWTS_* lines",
             "# (notifications) never are. Never commit."]
    lines += [f"{k}={v}" for k, v in have.items()]
    p = _env_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _ensure_gitignored()


_URL_RE = re.compile(r"^https?://[^\s\"'<>]{3,400}$")


def _mask(url: str) -> str:
    return (url[:url.find("/", 8) + 1] + "…" + url[-4:]) if url and url.count("/") > 2 else ("set" if url else "")


def notify_status() -> tuple[dict, int]:
    from executor import notify   # noqa: PLC0415
    cfg = notify.config(sources.executor.Lab(ctx.HUB))
    return {"ok": True, "ntfy": _mask(cfg.get("ntfy", "")), "webhook": _mask(cfg.get("webhook", "")),
            "link": cfg.get("link", "")}, 200


def notify_set(body: dict) -> tuple[dict, int]:
    """Set or clear (empty) the ntfy topic URL, the webhook URL and the dashboard link."""
    from executor import notify   # noqa: PLC0415
    if not body.get("confirm"):
        return {"error": "confirm first"}, 400
    have = _env_read()
    changed = []
    for k, env in notify.KEYS.items():
        if k not in body:
            continue
        v = str(body.get(k) or "").strip()
        if v and not _URL_RE.match(v):
            return {"error": f"{k}: a web address starting with https:// (or http://)"}, 400
        if v:
            have[env] = v
        else:
            have.pop(env, None)
        changed.append(k)
    if not changed:
        return {"error": "nothing to change"}, 400
    _env_write(have)
    ctx.pi_log({"action": "notify.set", "changed": changed})   # never the URLs
    return {"ok": True, "note": "saved — new items that need you are sent from now on"}, 200


def notify_test(body: dict) -> tuple[dict, int]:
    from executor import notify   # noqa: PLC0415
    cfg = notify.config(sources.executor.Lab(ctx.HUB))
    if not (cfg.get("ntfy") or cfg.get("webhook")):
        return {"error": "set an ntfy topic or a webhook first"}, 400
    failed = notify.send(cfg, {"title": "Newts' Lab: notifications work", "kind": "test",
                               "body": "Questions, approvals and gates that need you will arrive here."})
    if failed:
        return {"error": f"could not reach {', '.join(failed)} — check the address"}, 400
    return {"ok": True, "note": "sent — check your phone"}, 200


def _ensure_gitignored() -> None:
    gi = ctx.HUB / ".gitignore"
    text = ctx.read(gi) or ""
    if "lab/.env.local" not in text:
        with gi.open("a", encoding="utf-8") as f:
            f.write("\n# Research API keys (dashboard → Settings → Research keys)\nlab/.env.local\n")
