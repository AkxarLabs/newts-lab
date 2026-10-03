// A stand-in for `opencode run --format json` (1.18), for hermetic executor tests (no model, no network).
//
// It LOADS THE REAL tracer plugin (.opencode/plugins/newts-trace.js, found by walking up from --dir to
// the git root, like opencode) and drives it with opencode's plugin API — session.created (root, then a
// `task` child session with parentID + agent), tool.execute.before/after, message.part.updated,
// session.status idle, dispose — while printing the root session's JSON lines exactly as `run
// --format json` does: step_start / tool_use (completed only) / text / step_finish (cost + tokens).
// A subagent shows up in the stream ONCE, as the finished `task` tool with metadata.sessionId.
// Usage: node fake_opencode.mjs run <prompt> --format json --dir <d> [-s <session>]
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"

const argv = process.argv.slice(2)
if (argv[0] === "--version") { console.log("1.18.23"); process.exit(0) }
if (argv[0] === "providers" || argv[0] === "auth") { console.log("┌  Credentials\n│\n└  1 credentials"); process.exit(0) }
// `opencode serve` (the executor's live session): HTTP + an SSE event stream, basic auth from
// OPENCODE_SERVER_PASSWORD. POST /session · /session/:id/prompt_async · /session/:id/abort ·
// /question/:id/reply|reject · /permission/:id/reply; GET /event. The first prompt runs the scripted
// turn (bash, then FAKE_MODE: subagents · question · approval; FAKE_STEER=<s> waits for a second
// prompt or an abort), every later prompt is answered "got: <text>". The REAL tracer plugin is driven
// exactly as in `run`.
if (argv[0] === "serve") {
  const http = await import("node:http")
  const pw = process.env.OPENCODE_SERVER_PASSWORD || ""
  const auth = "Basic " + Buffer.from(`opencode:${pw}`).toString("base64")
  const clients = []
  const waiters = {}
  const pending = []
  let turns = 0, root = null, dir = process.cwd(), hooks = null, wake = null, busy = false
  const send = (type, properties) => {
    const d = `data: ${JSON.stringify({ id: `evt_${Date.now()}`, type, properties })}\n\n`
    for (const c of clients) c.write(d)
  }
  const loadHooks = async () => {
    if (hooks) return hooks
    hooks = []
    for (let d = path.resolve(dir); ; d = path.dirname(d)) {
      const f = path.join(d, ".opencode", "plugins", "newts-trace.js")
      if (fs.existsSync(f)) { const mod = await import(pathToFileURL(f).href); for (const fn of Object.values(mod)) hooks.push(await fn({ directory: dir, worktree: dir })); break }
      if (fs.existsSync(path.join(d, ".git")) || path.dirname(d) === d) break
    }
    return hooks
  }
  const pev = async (type, properties) => { for (const h of await loadHooks()) await h.event?.({ event: { id: "e", type, properties } }) }
  const part = (p) => send("message.part.updated", { sessionID: p.sessionID, part: p, time: Date.now() })
  const tool = async (s, name, callID, input, output, shown = true) => {
    for (const h of await loadHooks()) await h["tool.execute.before"]?.({ tool: name, sessionID: s, callID }, { args: input })
    for (const h of await loadHooks()) await h["tool.execute.after"]?.({ tool: name, sessionID: s, callID, args: input }, { title: name, output, metadata: {} })
    if (shown) part({ id: callID, sessionID: s, messageID: "m1", type: "tool", callID, tool: name,
      state: { status: "completed", input, output, title: `${name}: ${input.command || input.filePath || ""}`, metadata: {}, time: { start: 1, end: 2 } } })
  }
  const ask = (kind, id, props) => new Promise((resolve) => { waiters[id] = resolve; send(kind, { id, sessionID: root, ...props }) })
  const status = (type) => { send("session.status", { sessionID: root, status: { type } }); if (type === "idle") send("session.idle", { sessionID: root }) }
  const nextPrompt = (ms) => new Promise((resolve) => { if (pending.length) return resolve(pending.shift()); const t = setTimeout(() => { wake = null; resolve(null) }, ms); wake = (x) => { clearTimeout(t); wake = null; resolve(x) } })
  const turn = async (text) => {
    turns += 1
    busy = true
    status("busy")
    let final = "all done"
    if (turns > 1) final = `got: ${String(text).slice(0, 200)}`
    else {
      await tool(root, "bash", "call_1", { command: "python scripts/run.py", description: "run" }, "ok")
      const mode = process.env.FAKE_MODE || "complete"
      if (mode === "subagents") {
        const child = "ses_child1"
        const args = { description: "variant exp-004", prompt: "run exp-004", subagent_type: "experiment-runner" }
        for (const h of await loadHooks()) await h["tool.execute.before"]?.({ tool: "task", sessionID: root, callID: "call_task" }, { args })
        await pev("session.created", { sessionID: child, info: { id: child, parentID: root, agent: "experiment-runner", title: "variant exp-004 (@experiment-runner subagent)", directory: dir } })
        send("session.created", { sessionID: child, info: { id: child, parentID: root } })
        await tool(child, "bash", "call_c2", { command: "uv run scripts/run.py --variant exp-004" }, "run ok", false)
        await pev("session.status", { sessionID: child, status: { type: "idle" } })
        const output = `<task id="${child}" state="completed"><task_result>RESULT PACKET: status=ok metric=0.91</task_result></task>`
        const metadata = { parentSessionId: root, sessionId: child }
        for (const h of await loadHooks()) await h["tool.execute.after"]?.({ tool: "task", sessionID: root, callID: "call_task", args }, { title: "variant exp-004", output, metadata })
        part({ id: "call_task", sessionID: root, messageID: "m1", type: "tool", callID: "call_task", tool: "task",
          state: { status: "completed", input: args, output, title: "variant exp-004", metadata, time: { start: 1, end: 2 } } })
      }
      if (mode === "question") {
        const a = await ask("question.asked", "que_1", { questions: [{ question: "Which project type?", header: "Type",
          options: [{ label: "ml", description: "training" }, { label: "empirical", description: "regressions" }] }] })
        final = a === null ? "question rejected" : `answers=${JSON.stringify(a)}`
      }
      if (mode === "approval") {
        const r = await ask("permission.asked", "per_1", { permission: "bash", patterns: ["curl https://x"], metadata: { command: "curl https://x" }, always: [] })
        final = `decision=${r}`
      }
      const steer = Number(process.env.FAKE_STEER || 0)
      if (steer) { const x = await nextPrompt(steer * 1000); if (x && x.abort) final += " | interrupted"; else if (x) final += ` | steered: ${x.text.slice(0, 80)}` }
    }
    part({ id: `p${turns}`, sessionID: root, messageID: "m1", type: "text", text: final, time: { start: 1, end: 2 } })
    part({ id: `pf${turns}`, sessionID: root, messageID: "m1", type: "step-finish", reason: "stop", cost: 0.0042,
      tokens: { total: 180, input: 150, output: 30, reasoning: 0, cache: { read: 10, write: 0 } } })
    busy = false
    status("idle")
    if (pending.length) setTimeout(() => turn(pending.shift().text), 10)
  }
  const server = http.createServer((req, res) => {
    if (req.headers.authorization !== auth) { res.writeHead(401); return res.end() }
    if (req.headers["x-opencode-directory"]) dir = req.headers["x-opencode-directory"]
    let raw = ""
    req.on("data", (c) => { raw += c })
    req.on("end", async () => {
      const body = raw ? JSON.parse(raw) : {}
      const json = (o, code = 200) => { res.writeHead(code, { "Content-Type": "application/json" }); res.end(JSON.stringify(o)) }
      const u = req.url.split("?")[0]
      let m
      if (req.method === "GET" && u === "/event") {
        res.writeHead(200, { "Content-Type": "text/event-stream" })
        clients.push(res)
        return res.write(`data: ${JSON.stringify({ type: "server.connected", properties: {} })}\n\n`)
      }
      if (req.method === "POST" && u === "/session") {
        root = "ses_root1"
        await pev("session.created", { sessionID: root, info: { id: root, title: body.title, directory: dir } })
        return json({ id: root, directory: dir })
      }
      if ((m = u.match(/^\/session\/([^/]+)\/prompt_async$/))) {
        root = root || m[1]
        const text = (body.parts || [{}])[0].text || ""
        if (process.env.NEWTS_RUN_DIR) fs.appendFileSync(path.join(process.env.NEWTS_RUN_DIR, "fake_calls.jsonl"),
          JSON.stringify({ argv: ["serve", "prompt_async", m[1]], stdin: text, body, cwd: dir }) + "\n")
        res.writeHead(204); res.end()
        if (wake) wake({ text })
        else if (busy) pending.push({ text })
        else { busy = true; setTimeout(() => turn(text), 10) }
        return
      }
      if ((m = u.match(/^\/session\/([^/]+)\/abort$/))) { if (wake) wake({ abort: true }); return json(true) }
      if ((m = u.match(/^\/question\/([^/]+)\/(reply|reject)$/))) {
        const w = waiters[m[1]]; delete waiters[m[1]]
        send(m[2] === "reply" ? "question.replied" : "question.rejected", { sessionID: root, requestID: m[1], answers: body.answers })
        if (w) w(m[2] === "reply" ? body.answers : null)
        return json(true)
      }
      if ((m = u.match(/^\/permission\/([^/]+)\/reply$/))) {
        const w = waiters[m[1]]; delete waiters[m[1]]
        send("permission.replied", { sessionID: root, requestID: m[1], reply: body.reply })
        if (w) w(body.reply)
        return json(true)
      }
      json({ error: "not found" }, 404)
    })
  })
  server.listen(0, "127.0.0.1", () => console.log(`opencode server listening on http://127.0.0.1:${server.address().port}`))
  await new Promise(() => {})
}
if (argv[0] !== "run") process.exit(2)
const opt = (f) => { const i = argv.indexOf(f); return i >= 0 ? argv[i + 1] : undefined }
const prompt = argv[1]
const dir = opt("--dir") || process.cwd()
const resume = opt("-s")
const out = (o) => process.stdout.write(JSON.stringify({ timestamp: Date.now(), ...o }) + "\n")

if (process.env.NEWTS_RUN_DIR) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("NEWTS_") || k.startsWith("AUTOSCIENTIST_") || k.startsWith("OPENCODE_")))
  fs.appendFileSync(path.join(process.env.NEWTS_RUN_DIR, "fake_calls.jsonl"), JSON.stringify({ argv, stdin: "", cwd: dir, env }) + "\n")
}

let pluginFile = null
for (let d = path.resolve(dir); ; d = path.dirname(d)) {
  const f = path.join(d, ".opencode", "plugins", "newts-trace.js")
  if (fs.existsSync(f)) { pluginFile = f; break }
  if (fs.existsSync(path.join(d, ".git")) || path.dirname(d) === d) break
}
const hooks = []
if (pluginFile) {
  const mod = await import(pathToFileURL(pluginFile).href)
  for (const fn of Object.values(mod)) hooks.push(await fn({ directory: dir, worktree: dir }))
}
const emit = async (type, properties) => { for (const h of hooks) await h.event?.({ event: { id: "e", type, properties } }) }
const before = async (sessionID, tool, callID, args) => { for (const h of hooks) await h["tool.execute.before"]?.({ tool, sessionID, callID }, { args }) }
const after = async (sessionID, tool, callID, args, o) => { for (const h of hooks) await h["tool.execute.after"]?.({ tool, sessionID, callID, args }, o) }

const sid = resume || "ses_root1"
if (!resume) await emit("session.created", { sessionID: sid, info: { id: sid, title: "run", directory: dir } })
out({ type: "step_start", sessionID: sid, part: { id: "p0", sessionID: sid, messageID: "m1", type: "step-start" } })

const tool = async (s, name, callID, input, output, printed = true) => {
  await before(s, name, callID, input)
  await after(s, name, callID, input, { title: name, output, metadata: {} })
  if (printed) out({ type: "tool_use", sessionID: sid, part: { id: callID, sessionID: s, messageID: "m1", type: "tool", callID, tool: name,
    state: { status: "completed", input, output, title: `${name}: ${input.command || input.filePath || ""}`, metadata: {}, time: { start: 1, end: 2 } } } })
}
await tool(sid, "bash", "call_1", { command: "python scripts/run.py", description: "run" }, "ok")

if ((process.env.FAKE_MODE || "complete") === "subagents") {
  const child = "ses_child1"
  const args = { description: "variant exp-004", prompt: "run exp-004", subagent_type: "experiment-runner" }
  await before(sid, "task", "call_task", args)
  await emit("session.created", { sessionID: child, info: { id: child, parentID: sid, agent: "experiment-runner",
    title: "variant exp-004 (@experiment-runner subagent)", directory: dir } })
  await tool(child, "read", "call_c1", { filePath: path.join(dir, "configs", "exp-004.yaml") }, "cfg", false)
  await tool(child, "bash", "call_c2", { command: "uv run scripts/run.py --variant exp-004" }, "run ok", false)
  await emit("message.part.updated", { sessionID: child, part: { id: "t1", sessionID: child, type: "text", text: "RESULT PACKET: status=ok metric=0.91" } })
  await emit("session.status", { sessionID: child, status: { type: "idle" } })
  const output = `<task id="${child}" state="completed"><task_result>RESULT PACKET: status=ok metric=0.91</task_result></task>`
  const metadata = { parentSessionId: sid, sessionId: child, model: { modelID: "fake", providerID: "fake" } }
  await after(sid, "task", "call_task", args, { title: "variant exp-004", output, metadata })
  out({ type: "tool_use", sessionID: sid, part: { id: "call_task", sessionID: sid, messageID: "m1", type: "tool", callID: "call_task", tool: "task",
    state: { status: "completed", input: args, output, title: "variant exp-004", metadata, time: { start: 1, end: 2 } } } })
}

const text = resume ? `continuing: ${String(prompt).slice(0, 60)}` : "all done"
out({ type: "text", sessionID: sid, part: { id: "p9", sessionID: sid, messageID: "m1", type: "text", text, time: { start: 1, end: 2 } } })
out({ type: "step_finish", sessionID: sid, part: { id: "pf", sessionID: sid, messageID: "m1", type: "step-finish", reason: "stop",
  cost: 0.0042, tokens: { total: 180, input: 150, output: 30, reasoning: 0, cache: { read: 10, write: 0 } } } })
for (const h of hooks) await h.dispose?.()   // opencode awaits dispose on shutdown; the plugin drains its queue
