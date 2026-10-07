"""Artifacts — what agents made for the PI to look at (tools/artifact.py publishes them), and the PI's replies.

Each lives in lab/.bus/artifacts/<id>/: artifact.json, a copy of its file, and — written only here — `seen` and
reply.json. A reply reaches the run that published it (its next message, through the executor); when that run
can't take one any more it becomes a directive to the study (or the hub), which the next agent reads.
"""

from __future__ import annotations

import csv
import io
import json

import ctx  # noqa: E402
import sources  # noqa: E402

executor = sources.executor
CTYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".html": "text/html", ".htm": "text/html",
          ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
          ".svg": "image/svg+xml", ".pdf": "application/pdf", ".csv": "text/csv", ".tsv": "text/tab-separated-values",
          ".txt": "text/plain", ".log": "text/plain", ".json": "application/json"}
MAX_TEXT = 400_000
MAX_ROWS = 400


def _tool():
    return ctx.tool("artifact")


def _all() -> list[dict]:
    return _tool().all_artifacts(ctx.HUB)


def compact(m: dict) -> dict:
    """What the snapshot carries for one artifact (the rail, the world, the chimes)."""
    return {k: m.get(k) for k in ("id", "title", "kind", "study", "run_id", "skill", "created", "question", "seen")} \
        | {"answered": bool(m.get("reply")), "choices": len(m.get("choices") or [])}


def snapshot_view(limit: int = 40) -> list[dict]:
    try:
        return [compact(m) for m in _all()[:limit]]
    except Exception:  # noqa: BLE001 — a broken artifact folder must not break the snapshot
        return []


def attention_items() -> list[dict]:
    """An unanswered question an agent left with an artifact waits in Needs you, like a run's question."""
    out = []
    try:
        for m in _all()[:100]:
            if m.get("question") and not m.get("reply"):
                out.append({"id": f"artifact:{m['id']}", "kind": "artifact", "sev": "warn", "ts": m.get("created"),
                            "target": m.get("study") or "hub", "idea": m.get("study"), "run_id": m.get("run_id"),
                            "skill": m.get("skill"), "title": m["title"],
                            "body": f"asks you: {m.get('question') or m['title']}. The agent keeps working.",
                            "detail": {"artifact": m["id"]}, "actions": [{"id": "artifact", "label": "answer"}]})
    except Exception:  # noqa: BLE001
        pass
    return out


def list_artifacts(q: dict | None = None) -> tuple[dict, int]:
    q = q or {}
    rows = [compact(m) | {"note": m.get("note"), "size": m.get("size"), "file": m.get("file")} for m in _all()]
    if q.get("study"):
        rows = [r for r in rows if r.get("study") == q["study"]]
    if q.get("run"):
        rows = [r for r in rows if r.get("run_id") == q["run"]]
    return {"ok": True, "artifacts": rows}, 200


def get(q: dict) -> tuple[dict, int]:
    """One artifact: its record, the PI's reply, and — for text kinds — its content (a table already parsed)."""
    m = _tool().load(str(q.get("id") or ""), ctx.HUB)
    if not m:
        return {"error": "no such artifact"}, 404
    out = {"ok": True, "artifact": m}
    f = _file(m)
    if f and m["kind"] in ("md", "text", "table"):
        text = f.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT]
        if m["kind"] == "table":
            dialect = "excel-tab" if f.suffix == ".tsv" else "excel"
            rows = list(csv.reader(io.StringIO(text), dialect=dialect))
            out["table"] = {"rows": rows[:MAX_ROWS + 1], "more": max(0, len(rows) - MAX_ROWS - 1)}
        else:
            out["text"] = text
    return out, 200


def _file(m: dict):
    if not m.get("file"):
        return None
    f = _tool().root(ctx.HUB) / m["id"] / m["file"]
    return f if f.is_file() else None


def file_route(q: dict):
    """GET /api/artifact/file?id= → (path, content type). HTML and SVG are served sandboxed (serve.py adds a
    CSP sandbox for them), so a page an agent made can never act as the dashboard."""
    m = _tool().load(str(q.get("id") or ""), ctx.HUB)
    f = m and _file(m)
    if not f:
        return None
    ct = CTYPES.get(f.suffix.lower(), "application/octet-stream")
    return f, ct + ("; charset=utf-8" if ct.startswith("text/") or ct.endswith(("json", "svg+xml")) else "")


def seen(body: dict) -> tuple[dict, int]:
    t, n = _tool(), 0
    for aid in (body.get("ids") or [])[:200]:
        if t.load(str(aid), ctx.HUB):
            (t.root(ctx.HUB) / aid / "seen").touch()
            n += 1
    return {"ok": True, "seen": n}, 200


def reply(body: dict) -> tuple[dict, int]:
    """The PI's answer: {id, choice?, text?}. Recorded with the artifact, then delivered to its run."""
    t = _tool()
    m = t.load(str(body.get("id") or ""), ctx.HUB)
    if not m:
        return {"error": "no such artifact"}, 404
    choice = body.get("choice")
    if choice is not None and choice not in (m.get("choices") or []):
        return {"error": "pick one of its options"}, 400
    text = str(body.get("text") or "").strip()[:4000]
    if not choice and not text:
        return {"error": "pick an option or write a reply"}, 400
    rep = {"ts": ctx.ts(), "by": "PI", "choice": choice, "text": text or None, "delivered": None}
    msg = (f"[The PI replied to your artifact “{m['title']}” ({m['id']})] "
           + (f"Chosen: {choice}. " if choice else "") + (text or ""))
    if m.get("run_id") and executor is not None:
        try:
            executor.reply(executor.Lab(ctx.HUB), m["run_id"], msg.strip())
            rep["delivered"] = f"run {m['run_id']}"
        except Exception as e:  # noqa: BLE001 — the run has gone: leave it for the next agent instead
            rep["delivered_error"] = str(e)[:300]
    if not rep["delivered"]:
        import bus  # noqa: PLC0415 — bus imports sources too; keep module import order simple
        try:
            bus.append_directive(m.get("study") or "hub", msg.strip())
            rep["delivered"] = f"a note to {m.get('study') or 'the lab'}"
        except Exception as e:  # noqa: BLE001
            rep["delivered_error"] = str(e)[:300]
    d = t.root(ctx.HUB) / m["id"]
    (d / "reply.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    (d / "seen").touch()
    ctx.pi_log({"action": "artifact.reply", "artifact": m["id"], "choice": choice})
    try:
        with (ctx.LAB / ".bus" / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": ctx.ts(), "source": "hub", "kind": "artifact_reply", "run_id": m.get("run_id"),
                                "detail": f"the PI replied to “{m['title']}”", "data": {"id": m["id"]}}) + "\n")
    except OSError:
        pass
    ctx.KICK.set()
    return {"ok": True, "reply": rep}, 200
