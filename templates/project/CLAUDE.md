@AGENTS.md

## Claude Code specifics

The project protocol imported above (`AGENTS.md`) binds you fully — it is the single source of truth, shared with every other agent that works in this repo. This section is the only Claude-Code-specific layer:

- **Hub procedures are native skills.** Invoke the hub's `{{hub_path}}/.claude/skills/<name>/SKILL.md` procedures as slash-command **skills** via the Skill tool (`/experiment`, `/improve`, `/ideate --in-project`, `/analyze`, `/make-figures`, …) rather than hand-executing the file.
- **Subagents are native.** Run `experiment-runner` (and the hub's review/overseer roles) as real, parallel **Task subagents** per the skill files; the "an agent without a subagent mechanism" fallback in the manual is for agents that lack one.
- **Local engineering skills** in `.claude/skills/` (`grill-with-docs`, `grilling`, `domain-modeling`) are likewise native slash-command skills.

Everything else — orientation order, autonomy bounds, the extensibility rules, the session-end write-back — applies to you exactly as written above.
