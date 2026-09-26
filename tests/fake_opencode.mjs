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
