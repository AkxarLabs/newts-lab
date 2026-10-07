// Newts' Lab activity tracer for opencode — the twin of the Claude Code / Codex trace hooks.
//
// opencode loads every plugin in a .opencode/plugins/ dir between the session cwd and the git root.
// This one turns each session / tool event into ONE Claude-shaped hook payload and pipes it to the
// repo's trace_hook.py (tools/ in the hub, scripts/ in a project), which appends a line to the
// per-worker logs the Vivarium dashboard reads (<bus>/workers/<worker>.jsonl).
//
// Subagents: opencode's `task` tool runs a subagent as a CHILD SESSION (parentID = the caller,
// agent = the subagent's name). Its events are logged as a worker of the root session:
// session_id = root session, agent_id = child session id, agent_type = agent name — exactly the
// shape Claude Code and Codex hooks produce, so the dashboard draws the same run → subagent tree.
//
// Contract (same as trace_hook.py): never throws, never blocks a tool call (the hooks return at once;
// payloads go to ONE background queue that runs the tracer processes strictly in order, so a
// subagent's start always lands before its first action and its stop after its last), no network,
// and the log is best-effort and non-canonical. Delete this file and opencode runs exactly as
// before. Every export must be a plugin function (opencode calls each one).
import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

export const NewtsTrace = async ({ directory }) => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
  const script = [path.join(root, "tools", "trace_hook.py"), path.join(root, "scripts", "trace_hook.py")]
    .find((p) => existsSync(p))
  // one tracer per process even when a hub and a nested project both ship this file
  if (!script || globalThis.__newtsTraceLoaded) return {}
  globalThis.__newtsTraceLoaded = true
  // the executor passes its own interpreter; otherwise the usual name per platform
  const python = process.env.NEWTS_PYTHON || (process.platform === "win32" ? "python" : "python3")
  const sessions = new Map()   // id -> { root, parent, agent }
  const lastText = new Map()   // child session id -> its latest finished text part (its result)
  const roots = new Set()

  let queue = Promise.resolve()
  const runOne = (payload) => new Promise((done) => {
    const timer = setTimeout(done, 10000)   // a wedged tracer never stalls the queue for long
    const finish = () => { clearTimeout(timer); done() }
    try {
      const child = spawn(python, [script], { stdio: ["pipe", "ignore", "ignore"], windowsHide: true })
      child.on("error", finish)
      child.on("close", finish)
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify({ cwd: directory, ...payload }))
    } catch { finish() }
  })
  const send = (payload) => { queue = queue.then(() => runOne(payload)) }
  const rootOf = (id) => {
    let cur = id
    for (let i = 0; i < 16; i++) {
      const s = sessions.get(cur)
      if (!s || !s.parent) return cur
      cur = s.parent
    }
    return cur
  }
  const who = (id) => {
    const s = sessions.get(id)
    if (s && s.parent) return { session_id: rootOf(id), agent_id: id, agent_type: s.agent || "general" }
    return { session_id: id }
  }
  const onCreated = (info) => {
    if (!info || !info.id || sessions.has(info.id)) return
    const m = /\(@([\w.-]+) subagent\)/.exec(info.title || "")
    sessions.set(info.id, { parent: info.parentID || null, agent: info.agent || (m && m[1]) || null })
    if (info.parentID) {
      send({ hook_event_name: "SubagentStart", ...who(info.id) })
    } else {
      roots.add(info.id)
      send({ hook_event_name: "SessionStart", session_id: info.id, source: "startup" })
    }
  }
  const onIdle = (id) => {
    const s = sessions.get(id)
    if (!s || !s.parent || s.stopped) return
    s.stopped = true
    send({ hook_event_name: "SubagentStop", ...who(id), last_assistant_message: lastText.get(id) || "" })
  }

  return {
    event: async ({ event }) => {
      try {
        const p = event.properties || {}
        if (event.type === "session.created") onCreated(p.info)
        else if (event.type === "session.idle") onIdle(p.sessionID)
        else if (event.type === "session.status" && p.status && p.status.type === "idle") onIdle(p.sessionID)
        else if (event.type === "message.part.updated" && p.part && p.part.type === "text" && p.part.text) {
          const sid = p.part.sessionID || p.sessionID
          if (sessions.get(sid)?.parent) lastText.set(sid, p.part.text)
        }
      } catch {}
    },
    "tool.execute.before": async (input, output) => {
      try {
        send({ hook_event_name: "PreToolUse", ...who(input.sessionID), tool_name: input.tool,
               tool_input: (output && output.args) || {}, tool_use_id: input.callID })
      } catch {}
    },
    "tool.execute.after": async (input, output) => {
      try {
        const out = (output && output.output) || ""
        const resp = input.tool === "task"
          ? { output: out, child_session: output && output.metadata && output.metadata.sessionId }
          : out
        send({ hook_event_name: "PostToolUse", ...who(input.sessionID), tool_name: input.tool,
               tool_input: input.args || {}, tool_use_id: input.callID, tool_response: resp })
      } catch {}
    },
    dispose: async () => {
      try {
        for (const id of roots) send({ hook_event_name: "SessionEnd", session_id: id })
        // let the queue drain (bounded) so the last lines land before the process exits
        await Promise.race([queue, new Promise((r) => setTimeout(r, 5000))])
      } catch {}
    },
  }
}
