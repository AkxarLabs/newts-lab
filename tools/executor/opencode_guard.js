// Newts' Lab signature guard for opencode — the twin of the claude/codex PreToolUse guard hook.
//
// The executor copies this file into a per-run OPENCODE_CONFIG_DIR (plugins/newts-guard.js), filling in
// the guard script and interpreter. Before every tool call it pipes ONE Claude-shaped PreToolUse payload
// to tools/signature_guard.py and waits: exit 2 means "this would forge a PI signature", and throwing
// from tool.execute.before is how an opencode plugin refuses a tool call (the agent sees the message).
// Anything else — including a guard that fails to start — lets the call through.
import { spawn } from "node:child_process"

const GUARD = __GUARD__
const PYTHON = __PYTHON__

export const NewtsGuard = async ({ directory }) => {
  const check = (payload) => new Promise((resolve) => {
    let err = ""
    const timer = setTimeout(() => resolve(null), 15000)
    try {
      const child = spawn(PYTHON, [GUARD], { stdio: ["pipe", "ignore", "pipe"], windowsHide: true })
      child.stderr.on("data", (d) => { err += d })
      child.on("error", () => { clearTimeout(timer); resolve(null) })
      child.on("close", (code) => { clearTimeout(timer); resolve(code === 2 ? (err.trim() || "denied") : null) })
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify({ cwd: directory, ...payload }))
    } catch { clearTimeout(timer); resolve(null) }
  })
  return {
    "tool.execute.before": async (input, output) => {
      const why = await check({ hook_event_name: "PreToolUse", tool_name: input.tool,
                                tool_input: (output && output.args) || {}, tool_use_id: input.callID })
      if (why) throw new Error(why)
    },
  }
}
