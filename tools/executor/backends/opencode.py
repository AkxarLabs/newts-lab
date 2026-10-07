"""opencode — SST opencode (`opencode serve` live, `opencode run --format json` one-shot).

Live: a server on a random local port with a per-run password; the session is driven over HTTP
(prompt_async, question/permission replies, abort) and watched on its event stream (SSE). The
server's events are translated to `run --format json` lines (root session only: a subagent shows as
its finished `task` tool; live child activity comes from the lab's tracer plugin,
.opencode/plugins/newts-trace.js, which runs under both). The signature guard is a per-run plugin dir.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import urllib.request
import uuid
from pathlib import Path

from .. import live
from . import ANSI_RE, Attempt, Backend, RunCommand, summarize_input, with_preamble

GUARD_PLUGIN = Path(__file__).resolve().parents[1] / "opencode_guard.js"
_TASK_RESULT_RE = re.compile(r"<task_result>(.*?)</task_result>", re.S)


class Opencode(Backend):
    name = "opencode"
    ask_tool = "question"
    auth_args = ["providers", "list"]
    sign_in_hint = ("opencode has no working provider for this model — run `opencode auth login`, or set "
                    "agents.programmatic.backends.opencode.model to a provider/model you have")
    forbid = ("--dangerously-skip-permissions", "--dir", "--format")

    def prepare(self, a: Attempt) -> None:
        a.env.setdefault("OPENCODE_DISABLE_AUTOUPDATE", "1")
        if a.bcfg.get("permission"):   # the autonomy posture rides the env, not a flag
            a.env["OPENCODE_PERMISSION"] = json.dumps(a.bcfg["permission"])
        if a.guard and not a.env.get("OPENCODE_CONFIG_DIR"):
            d = guard_dir(a.rd, a.guard, a.python)
            if d:
                a.env["OPENCODE_CONFIG_DIR"] = str(d)
        a.traced = traced(a.workdir)

    def command(self, a: Attempt) -> RunCommand:
        if a.live:
            notes = ["extra_args ignored for a live opencode session"] if a.extra else []
            return RunCommand([*a.cli, "serve", "--port", "0", "--hostname", "127.0.0.1"], None, a.traced, notes)
        self.check_extra(a)
        # the prompt stays on argv: with a live stdin, `--format json` can block on the first readline
        argv = [*a.cli, "run", with_preamble(a), "--format", "json", "--dir", str(a.workdir)]
        if a.resume_sid:
            argv += ["-s", a.resume_sid]
        if a.model:
            argv += ["--model", str(a.model)]   # provider/model form
        for key, flag in (("variant", "--variant"), ("agent", "--agent")):
            if a.bcfg.get(key):
                argv += [flag, str(a.bcfg[key])]
        if a.bcfg.get("skip_permissions"):
            argv += ["--dangerously-skip-permissions"]
        return RunCommand(argv + a.extra.split(), None, a.traced)

    def session(self, a: Attempt):
        return OpencodeSession(a.prompt, a.resume_sid, workdir=a.workdir, model=a.model, agent=a.bcfg.get("agent"),
                               variant=a.bcfg.get("variant"), system=a.preamble or None, title=a.m.get("label"))

    def auth(self, out) -> dict | None:   # "N credentials" (auth.json) + "N environment variables" (provider keys)
        text = ANSI_RE.sub("", (out.stdout or "") + "\n" + (out.stderr or ""))
        nums = [int(n) for n in re.findall(r"(\d+)\s+(?:credentials?|environment variables?)", text)]
        return {"logged_in": sum(nums) > 0, "method": "providers" if sum(nums) else None} if nums else None

    def parse(self, obj: dict) -> list[dict]:
        """`run --format json` (1.18): {type, timestamp, sessionID, part}. step_finish carries cost +
        tokens; text is a finished text part; tool_use is emitted once the tool is completed|error; no
        result envelope — the final message is the LAST text part. A subagent (`task` tool) shows up
        once, when it returns, with its child session id and its answer inside <task_result>."""
        t, sid, part = obj.get("type"), obj.get("sessionID"), obj.get("part") or {}
        if t == "tool_use":
            state = part.get("state") or {}
            tool, inp = part.get("tool"), state.get("input") or {}
            err = state.get("status") == "error"
            if tool == "task" and isinstance(inp, dict):
                call = part.get("callID") or part.get("id")
                out = str(state.get("output") or state.get("error") or "")
                m = _TASK_RESULT_RE.search(out)
                desc = str(inp.get("description") or inp.get("prompt") or "")[:200]
                return [{"event": "action", "tool": "task", "kind": "tool", "tool_use_id": call,
                         "summary": f"{inp.get('subagent_type') or 'general'}: {desc}"[:200], "session_id": sid,
                         "spawn": {"subagent_type": inp.get("subagent_type") or "general", "description": desc,
                                   "child_session": (state.get("metadata") or {}).get("sessionId")}},
                        {"event": "tool_result", "tool_use_id": call, "is_error": err,
                         "text": (m.group(1) if m else out).strip()[:2000]}]
            summary = state.get("title") or summarize_input(tool, inp) or tool
            wrote = [str(inp.get("filePath") or inp.get("file_path"))] if tool in ("write", "edit", "patch", "multiedit") and                 isinstance(inp, dict) and (inp.get("filePath") or inp.get("file_path")) else []
            return [{"event": "action", "tool": tool, "kind": "tool", "summary": str(summary or "")[:200],
                     "session_id": sid, "tool_use_id": part.get("callID"), **({"files": wrote} if wrote else {})}] + \
                ([{"event": "tool_result", "tool_use_id": part.get("callID"), "is_error": True,
                   "text": str(state.get("error") or "")[:2000]}] if err else [])
        if t == "text" and part.get("text"):
            return [{"event": "result", "last_message": str(part["text"]), "session_id": sid},
                    {"event": "text", "text": str(part["text"]), "parent": None}]
        if t == "step_finish":
            tok = part.get("tokens") or {}
            usage = {k: tok[k] for k in ("input", "output", "reasoning") if isinstance(tok.get(k), (int, float))}
            if isinstance((tok.get("cache") or {}).get("read"), (int, float)):
                usage["cache_read"] = tok["cache"]["read"]
            return [{"event": "usage", "usage": usage, "cost_delta": part.get("cost"), "session_id": sid},
                    {"event": "start", "status": "working", "session_id": sid}]
        if t == "error":
            err = obj.get("error") or {}
            msg = (err.get("data") or {}).get("message") or err.get("name") or "opencode error"
            return [{"event": "result", "last_message": f"[error] {msg}", "session_id": sid, "is_error": True}]
        return [{"event": "start", "status": "working", "session_id": sid}] if sid else []


def guard_dir(run_dir, guard, python: str) -> Path | None:
    """A per-run OPENCODE_CONFIG_DIR holding only the signature-guard plugin (opencode searches it for
    plugins like a .opencode/ dir, in addition to the global and project config)."""
    if not GUARD_PLUGIN.is_file():
        return None
    d = Path(run_dir) / "opencode-config"
    (d / "plugins").mkdir(parents=True, exist_ok=True)
    src = GUARD_PLUGIN.read_text(encoding="utf-8")
    src = src.replace("__GUARD__", json.dumps(str(guard))).replace("__PYTHON__", json.dumps(str(python)))
    (d / "plugins" / "newts-guard.js").write_text(src, encoding="utf-8")
    return d


def traced(workdir) -> bool:
    """opencode loads plugins from every .opencode/ dir between the cwd and the git worktree root; the
    lab's tracer plugin there feeds the same worker logs as the claude/codex hooks."""
    w = Path(workdir).resolve()
    for d in [w, *w.parents]:
        if (d / ".opencode" / "plugins" / "newts-trace.js").is_file():
            return True
        if (d / ".git").exists():
            break
    return False


class OpencodeSession(live.Session):
    """ctx: workdir, model ("provider/model"), agent, variant, system (the standing instructions), title."""

    def __init__(self, prompt, session_id=None, **ctx):
        super().__init__(prompt, session_id, **ctx)
        self.url = None
        self.password = uuid.uuid4().hex
        self.busy = False
        self._seen: set = set()

    def env(self) -> dict:
        return {"OPENCODE_SERVER_PASSWORD": self.password, "OPENCODE_SERVER_USERNAME": "opencode"}

    def open(self, proc) -> None:
        self.proc = proc

    def _req(self, path: str, method: str = "GET", body=None) -> urllib.request.Request:
        return urllib.request.Request(
            self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Basic " + base64.b64encode(f"opencode:{self.password}".encode()).decode(),
                     "Content-Type": "application/json", "x-opencode-directory": str(self.ctx.get("workdir") or "")})

    def _http(self, method: str, path: str, body=None):
        with urllib.request.urlopen(self._req(path, method, body), timeout=30) as r:
            t = r.read().decode("utf-8", "replace")
        return json.loads(t) if t.strip() else None

    def stream(self, proc):
        for line in proc.stdout:        # wait for "opencode server listening on http://127.0.0.1:PORT"
            hit = re.search(r"listening on (http://\S+)", line)
            if hit:
                self.url = hit.group(1).rstrip("/")
                break
        if not self.url:
            return
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()   # keep the pipe drained
        try:
            events = urllib.request.urlopen(self._req("/event"), timeout=24 * 3600)
            if not self.session_id:
                self.session_id = (self._http("POST", "/session", {"title": self.ctx.get("title") or "newts run"}) or {})["id"]
            yield json.dumps({"type": "_session", "sessionID": self.session_id})
            self.send(self.prompt)
            for raw in events:
                if self.closed:
                    return
                s = raw.decode("utf-8", "replace").strip()
                if s.startswith("data:"):
                    yield s[5:].strip()
        except (OSError, ValueError, KeyError, TypeError) as e:
            if not self.closed:
                self.error = f"opencode server: {e}"

    def send(self, text: str) -> bool:
        body = {"parts": [{"type": "text", "text": text}]}
        model = str(self.ctx.get("model") or "")
        if "/" in model:
            prov, mid = model.split("/", 1)
            body["model"] = {"providerID": prov, "modelID": mid}
        for k in ("agent", "variant", "system"):
            if self.ctx.get(k):
                body[k] = self.ctx[k]
        try:
            self._http("POST", f"/session/{self.session_id}/prompt_async", body)
        except OSError:
            return False
        self.unread += 1
        return True

    def interrupt(self) -> bool:
        try:
            self._http("POST", f"/session/{self.session_id}/abort")
            return True
        except OSError:
            return False

    def respond(self, req: dict, item: dict) -> bool:
        try:
            if req["kind"] == "question":
                if item.get("allow") is False:
                    self._http("POST", f"/question/{req['id']}/reject")
                else:
                    self._http("POST", f"/question/{req['id']}/reply", {"answers": live.answer_labels(req, item)})
            else:
                body = {"reply": "once" if item.get("allow") else "reject"}
                if not item.get("allow") and item.get("message"):
                    body["message"] = item["message"]
                self._http("POST", f"/permission/{req['id']}/reply", body)
            return True
        except OSError:
            return False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = self.ended = True
        if self.proc and self.proc.poll() is None:   # the server goes; its event stream ends with it
            from ..procs import kill_tree             # (closing the response from this thread could block)
            kill_tree(self.proc.pid)

    def handle(self, obj: dict) -> tuple[list[dict], list[dict]]:
        t, p, root = obj.get("type"), obj.get("properties") or {}, self.session_id
        if t == "_session":
            return [{"type": "step_start", "sessionID": root, "part": {"type": "step-start"}}], []
        if t == "message.part.updated":
            part = p.get("part") or {}
            pt, key = part.get("type"), part.get("id")
            if part.get("sessionID") != root or key in self._seen:
                return [], []
            done = ((pt == "tool" and (part.get("state") or {}).get("status") in ("completed", "error"))
                    or (pt == "text" and (part.get("time") or {}).get("end")) or pt == "step-finish")
            if not done:
                return [], []
            self._seen.add(key)
            return [{"type": {"tool": "tool_use", "text": "text", "step-finish": "step_finish"}[pt],
                     "sessionID": root, "part": part}], []
        if t == "session.status" and p.get("sessionID") == root:
            kind = (p.get("status") or {}).get("type")
            if kind == "busy":
                self.busy, self.unread = True, 0
            elif kind == "idle" and self.busy:
                self.busy = False
                return [], [{"event": "turn_end"}]
            return [], []
        if t == "question.asked":
            qs = [{"question": q.get("question"), "header": q.get("header"), "multiSelect": bool(q.get("multiple")),
                   "options": q.get("options") or []} for q in p.get("questions") or []]
            return [], [{"event": "request", "id": p.get("id"), "kind": "question", "tool": "question",
                         "input": {"questions": qs}}]
        if t == "permission.asked":
            meta = p.get("metadata") or {}
            inp = {"command": meta["command"]} if meta.get("command") else {"file_path": ", ".join(p.get("patterns") or [])}
            return [], [{"event": "request", "id": p.get("id"), "kind": "permission", "tool": p.get("permission"),
                         "input": inp}]
        if t in ("question.replied", "question.rejected", "permission.replied"):
            return [], [{"event": "cancelled", "id": p.get("requestID")}]
        if t == "session.error" and p.get("sessionID") in (None, root):
            err = p.get("error") or {}
            self.error = (err.get("data") or {}).get("message") or err.get("name") or "opencode error"
            return [{"type": "error", "sessionID": root, "error": err}], []
        return [], []
