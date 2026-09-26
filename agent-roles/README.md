# Agent roles — canonical subagent specs

One source of truth for every lab subagent role, rendered to backend-native files by
`tools/role_sync.py` so a role means the same thing whether Claude or Codex runs it, and the
non-Claude scaffolding can't silently drift.

Each role is two files:

- `<name>.yaml` — metadata: `name`, `description`, `model_key` (which `lab/config.yaml`
  `agents.*` key sets the Claude model), `tools_claude` (the Claude frontmatter tools line), and a
  `codex:` block (`sandbox_mode`, `model_reasoning_effort`).
- `<name>.md` — the verbatim instruction body (identical text for every backend).

## Generated files — do NOT hand-edit; edit the source here, then re-render

- `.claude/agents/<name>.md` — Claude Code Task subagents (`model:` resolved from config).
- `.codex/agents/<name>.toml` — Codex GA subagents (hub).
- `templates/project/.codex/agents/<name>.toml` — the copy spawned projects ship.

```bash
uv run --with pyyaml python tools/role_sync.py render   # write/update the generated files
uv run --with pyyaml python tools/role_sync.py check    # CI drift guard — exit 1 if any is stale
```

## Backends

**Claude and Codex are rendered** (their role-file schemas are known and stable). **opencode,
Gemini CLI, and Cursor are compatibility-only** — their role-file schemas are unverified in this
repo, so until a CLI smoke proves them, use the sequential approximation or one headless process
per unit of work via `tools/agent_runner.py` (see `docs/autonomy.md`). Adding a backend = adding a
render target in `role_sync.py`, not editing the generated files.

## Roles

Five roles are rendered here — `fresh-context-reviewer`, `experiment-runner`, `overseer`,
`ideation-critic`, and `scoping-advocate` — the lab's named, isolated subagents. The last two share
`agents.critic_model`/`critic_effort` (their `model_key` is `critic_model`), so the per-role binding
is unchanged; being named roles means every critic and advocate appears in the hooks' traces — and
the dashboard's agent tree — by role, with its verdict as its result, instead of as an anonymous
`general-purpose` agent. `tools/role_sync.py resolve critic` still prints the resolved model/effort
for backends without role files (subagent rule 7).
