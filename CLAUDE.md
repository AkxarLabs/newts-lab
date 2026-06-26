@AGENTS.md

## Claude Code specifics

The manual imported above (`AGENTS.md`) is the lab protocol and binds you fully — it is the single source of truth, shared with every other agent that drives this lab. This section is the only Claude-Code-specific layer on top of it:

- **Procedures are native skills.** The `.claude/skills/<name>/SKILL.md` procedures are available to you as slash-command **skills** — invoke them with the Skill tool (`/ideate`, `/scope`, `/experiment`, …) rather than opening and hand-executing the file.
- **Subagents are native.** The roles in `.claude/agents/*.md` (`fresh-context-reviewer`, `experiment-runner`, `overseer`, …) are real **Task subagents** — spawn them as actual parallel subagents per the skill files. You do **not** use the "Multi-agent execution / how to approximate them" fallbacks in the manual; those are for agents that lack a subagent mechanism.

Everything else — lifecycle, the three PI gates, the 13 hard rules, subagent rules, write-back duties — applies to you exactly as written above.
